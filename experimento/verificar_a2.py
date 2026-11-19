"""Prueba de aceptación específica de A2 (F3).

1. move-leader: mover el líder a etcd1, etcd2 y etcd3 (enviado al líder actual)
   y verificar que los tres miembros lo reportan.
2. Matar el líder (docker kill) y medir cuánto tarda el orquestador en ver
   un líder nuevo entre los miembros que quedan. Debe ser < 3 s.
3. P1 con el líder en cada lado: se mueve el líder, se aplica P1, se registra
   cuándo se detecta el nuevo líder del lado mayoritario (A + D), y A y B piden
   AMB-01 a los 2 s del corte (como en el ensayo, t = 3 s).

Uso: python experimento/verificar_a2.py [--muertes 3]
"""

import argparse
import asyncio
import subprocess
import sys
import time

import httpx

import etcd_admin as etcd
import fallas
from clientes import solicitar
from comun.config import AMBULANCIA_ENSAYO, CON_CONFLICTO, DIR_LOGS
from comun.logger import LoggerEnsayo
from topologia import ARQUITECTURAS, ETCD_A2, LIDER_LADO

ARQ = ARQUITECTURAS["A2"]
LIMITE_ELECCION = 3.0
fallos: list[str] = []


def revisar(ok: bool, mensaje: str) -> bool:
    print(f"  [{'OK' if ok else 'FALLA'}] {mensaje}")
    if not ok:
        fallos.append(mensaje)
    return ok


def esperar(condicion, limite: float, intervalo: float = 0.1) -> bool:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(intervalo)
    return False


def mover_con_reintentos(destino: str, intentos: int = 3) -> tuple[bool, int, float]:
    t0 = time.monotonic()
    for i in range(1, intentos + 1):
        if etcd.mover_lider(destino):
            return True, i, time.monotonic() - t0
        time.sleep(0.5)
    return False, intentos, time.monotonic() - t0


def prueba_move_leader():
    print("\n1) move-leader (al líder actual) y verificación")
    for destino in ("etcd1", "etcd2", "etcd3", "etcd1"):
        antes = etcd.lider_actual()
        ok, intentos, dur = mover_con_reintentos(destino)
        revisar(ok, f"{antes} → {destino}: {'aplicado' if ok else 'NO aplicado'} "
                    f"en {dur:.2f} s ({intentos} intento/s); los 3 reportan {etcd.lider_actual()}")


def prueba_matar_lider(n: int):
    print(f"\n2) Matar el líder ({n} veces): nuevo líder en < {LIMITE_ELECCION:.0f} s")
    for i in range(1, n + 1):
        lider = etcd.lider_actual()
        resto = [m for m in ETCD_A2 if m != lider]
        t_kill = time.time()
        subprocess.run(["docker", "kill", ETCD_A2[lider]], capture_output=True, check=True)
        det = etcd.esperar_nuevo_lider(resto, anterior=lider, hasta=t_kill + 10)
        if det:
            t_det, nuevo = det
            revisar(t_det - t_kill < LIMITE_ELECCION,
                    f"muerte {i}: líder {lider} muerto → nuevo líder {nuevo} detectado "
                    f"a los {t_det - t_kill:.2f} s")
        else:
            revisar(False, f"muerte {i}: sin nuevo líder en 10 s tras matar a {lider}")
        # Revivir el nodo: vuelve con las mismas IPs; netem se reaplica (interfaces nuevas)
        subprocess.run(["docker", "start", ETCD_A2[lider]], capture_output=True, check=True)
        fallas.restaurar_todo(ARQ)
        ok = esperar(etcd.misma_revision, 15)
        revisar(ok, f"muerte {i}: {lider} reincorporado, 3 miembros con la misma revisión "
                    f"(líder {etcd.lider_actual()})")


async def ensayo_p1(lado: str, n: int):
    """Un ensayo P1 reducido con el líder en el lado indicado."""
    destino = LIDER_LADO[lado]
    fallas.restaurar_todo(ARQ)
    ok, _, _ = mover_con_reintentos(destino)
    revisar(ok, f"P1 lado {lado}: líder movido a {destino}")
    log = LoggerEnsayo(f"{DIR_LOGS}/../verificacion", "A2", "P1", n, tipo=CON_CONFLICTO)
    log.ruta.unlink(missing_ok=True)
    async with httpx.AsyncClient(timeout=15) as http:
        for c in ARQ.reset:
            (await http.post(f"{ARQ.url(c)}/admin/reset",
                             json={"ambulancias": [AMBULANCIA_ENSAYO],
                                   "contexto": {"arq": "A2", "escenario": "P1", "ensayo": n,
                                                "tipo": CON_CONFLICTO}})).raise_for_status()
        esperar(etcd.misma_revision, 5)
        lider_inicial = etcd.lider_actual()
        t_corte = time.time()
        fallas.aplicar_corte(ARQ, "P1")
        log.evento("corte_inicio", lider=lider_inicial)
        # Vigilar al nuevo líder del lado mayoritario (etcd1 + etcd3) en paralelo
        vigilancia = asyncio.get_running_loop().run_in_executor(
            None, etcd.esperar_nuevo_lider, ["etcd1", "etcd3"],
            None if lider_inicial == "etcd1" else lider_inicial, t_corte + 15)
        await asyncio.sleep(max(0, t_corte + 2 - time.time()))      # t = 3 s del ensayo
        ra, rb = await asyncio.gather(
            solicitar(http, ARQ.url_despacho("A"), log, "A", "I-1", AMBULANCIA_ENSAYO),
            solicitar(http, ARQ.url_despacho("B"), log, "B", "I-2", AMBULANCIA_ENSAYO))
        det = await vigilancia
    fallas.restaurar_todo(ARQ)
    log.evento("corte_fin", lider_inicial=lider_inicial,
               lider_mayoria=det[1] if det else None,
               t_lider_mayoria=det[0] if det else None)
    t_lider = f"{det[0] - t_corte:.2f} s tras el corte ({det[1]})" if det else "no detectado"
    print(f"  líder inicial {lider_inicial}; líder del lado A+D detectado a {t_lider}")
    print(f"  A: {ra['evento']} en {ra['extra']['t_respuesta']:.3f} s   "
          f"B: {rb['evento']} en {rb['extra']['t_respuesta']:.3f} s")
    revisar(ra["evento"] == "confirmada" and rb["evento"] == "sin_confirmacion",
            f"P1 lado {lado}: A confirma (mayoría A+D) y B responde sin_confirmacion")
    esperar(etcd.misma_revision, 15)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--muertes", type=int, default=3)
    a = p.parse_args()
    fallas.restaurar_todo(ARQ)
    revisar(esperar(etcd.misma_revision, 10), f"clúster sano, líder {etcd.lider_actual()}")
    prueba_move_leader()
    prueba_matar_lider(a.muertes)
    print("\n3) P1 con el líder en cada lado")
    asyncio.run(ensayo_p1("A", 0))
    asyncio.run(ensayo_p1("B", 1))
    print(f"\n{'APROBADA' if not fallos else 'REPROBADA'}: {len(fallos)} fallas")
    for f in fallos:
        print("  -", f)
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
