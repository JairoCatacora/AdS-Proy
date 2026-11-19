"""Prueba de aceptación específica de A3 (F4).

1. N ensayos con net_ab cortado y conflicto, alternando quién pide primero:
   - ambos centros confirman (cada uno con su base local);
   - al restaurar, EXACTAMENTE UNO registra `revertida` (el de la reserva más
     reciente), con el incidente afectado y el ganador en `extra`;
   - ambos terminan con el mismo estado y `pendientes == 0`.
2. Ensayos tipo P4 (enlace A–B intermitente cada 2 s): la reconciliación puede
   ocurrir durante la ventana del corte; se reporta en qué momento ocurrió.

Uso: python experimento/verificar_a3.py [--n 10] [--p4 2]
"""

import argparse
import asyncio
import random
import sys
import time

import httpx

import fallas
from clientes import solicitar
from comun.config import AMBULANCIA_ENSAYO, CON_CONFLICTO, DIR_LOGS
from comun.logger import LoggerEnsayo, leer_jsonl
from topologia import ARQUITECTURAS

ARQ = ARQUITECTURAS["A3"]
fallos: list[str] = []


def revisar(ok: bool, mensaje: str) -> bool:
    print(f"  [{'OK' if ok else 'FALLA'}] {mensaje}")
    if not ok:
        fallos.append(mensaje)
    return ok


async def estado_centros(http) -> tuple[dict, dict, int, int]:
    va, vb, pa, pb = await asyncio.gather(
        http.get(f"{ARQ.url_despacho('A')}/ambulancias"),
        http.get(f"{ARQ.url_despacho('B')}/ambulancias"),
        http.get(f"{ARQ.url_despacho('A')}/admin/pendientes"),
        http.get(f"{ARQ.url_despacho('B')}/admin/pendientes"))
    amb = lambda r: {a["id"]: a for a in r.json()}[AMBULANCIA_ENSAYO]
    return amb(va), amb(vb), pa.json()["pendientes"], pb.json()["pendientes"]


async def esperar_consistencia(http, limite: float = 30.0):
    """Devuelve (segundos, estado) cuando ambos centros coinciden en estado e
    incidente y no tienen pendientes, o (None, último estado)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limite:
        a, b, pa, pb = await estado_centros(http)
        if (a["estado"], a["incidente_asignado"]) == (b["estado"], b["incidente_asignado"]) \
                and pa == pb == 0:
            return time.monotonic() - t0, a
        await asyncio.sleep(0.1)
    return None, a


async def preparar(http, escenario, n):
    fallas.restaurar_todo(ARQ)
    for c in ARQ.reset:
        (await http.post(f"{ARQ.url(c)}/admin/reset",
                         json={"ambulancias": [AMBULANCIA_ENSAYO],
                               "contexto": {"arq": "A3", "escenario": escenario, "ensayo": n,
                                            "tipo": CON_CONFLICTO}})).raise_for_status()
    log = LoggerEnsayo(f"{DIR_LOGS}/../verificacion", "A3", escenario, n, tipo=CON_CONFLICTO)
    log.ruta.unlink(missing_ok=True)
    return log


async def pedir_ambos(http, log, primero, delta):
    segundo = "B" if primero == "A" else "A"

    async def segunda():
        await asyncio.sleep(delta)
        return await solicitar(http, ARQ.url_despacho(segundo), log, segundo, "I-2",
                               AMBULANCIA_ENSAYO)
    r1, r2 = await asyncio.gather(
        solicitar(http, ARQ.url_despacho(primero), log, primero, "I-1", AMBULANCIA_ENSAYO),
        segunda())
    return r1, r2, segundo


async def recoger_eventos(http, log):
    """Como hará el orquestador: GET /admin/eventos de cada servicio al final."""
    for c in ARQ.reset:
        for ev in (await http.get(f"{ARQ.url(c)}/admin/eventos")).json():
            log.escribir(ev)
    return [e for e in leer_jsonl(log.ruta) if e["evento"] == "revertida"]


async def ensayo_corte(http, n: int, rng: random.Random):
    primero = "A" if n % 2 == 0 else "B"
    delta = rng.uniform(0, 0.2)
    log = await preparar(http, "P1", n)
    fallas.cortar_enlace(ARQ, "ab")
    log.evento("corte_inicio")
    r1, r2, segundo = await pedir_ambos(http, log, primero, delta)
    t_rest = time.time()              # el enlace funciona desde el `connect`, antes de netem
    fallas.restaurar_enlace(ARQ, "ab")
    log.evento("corte_fin", t=t_rest)
    dur, final = await esperar_consistencia(http)
    rev = await recoger_eventos(http, log)
    ok = (r1["evento"] == r2["evento"] == "confirmada" and len(rev) == 1
          and rev[0]["centro"] == segundo and rev[0]["incidente"] == "I-2"
          and rev[0]["extra"]["incidente_ganador"] == "I-1"
          and dur is not None and final["incidente_asignado"] == "I-1")
    t_rev = f"{rev[0]['t'] - t_rest:.2f} s tras restaurar" if len(rev) == 1 else f"{len(rev)} revertidas"
    revisar(ok, f"ensayo {n}: primero={primero} δ={delta*1000:5.1f} ms → {primero}:{r1['evento']} "
                f"{segundo}:{r2['evento']}; revertida en {rev[0]['centro'] if rev else '-'} "
                f"({t_rev}); consistente en {dur if dur is None else round(dur, 2)} s, "
                f"ambos con {final['incidente_asignado']}, pendientes 0")


async def ensayo_p4(http, n: int):
    """Corte intermitente del enlace A–B: abajo 2 s, arriba 2 s, durante 20 s."""
    primero = "A" if n % 2 == 0 else "B"
    log = await preparar(http, "P4", n)
    t_corte = time.time()
    fallas.cortar_enlace(ARQ, "ab")
    log.evento("corte_inicio")
    tarea = asyncio.create_task(pedir_ambos(http, log, primero, 0.05))
    ventanas = []                       # (inicio, fin) de cada intervalo con el enlace ARRIBA
    abajo = True
    await asyncio.sleep(2)
    while time.time() - t_corte < 20:
        if abajo:
            ventanas.append([time.time(), None]); fallas.restaurar_enlace(ARQ, "ab")
        else:
            fallas.cortar_enlace(ARQ, "ab"); ventanas[-1][1] = time.time()
        abajo = not abajo
        await asyncio.sleep(2)
    r1, r2, segundo = await tarea
    fallas.restaurar_enlace(ARQ, "ab")
    if ventanas and ventanas[-1][1] is None:
        ventanas[-1][1] = time.time()
    log.evento("corte_fin")
    dur, final = await esperar_consistencia(http)
    rev = await recoger_eventos(http, log)
    if len(rev) == 1:
        t_rel = rev[0]["t"] - t_corte
        en_ventana = next((i for i, (a, b) in enumerate(ventanas) if a <= rev[0]["t"] <= b), None)
        cuando = (f"a los {t_rel:.2f} s del corte, durante la ventana arriba nº {en_ventana + 1}"
                  if en_ventana is not None else f"a los {t_rel:.2f} s del corte")
    else:
        cuando = f"{len(rev)} revertidas"
    revisar(len(rev) == 1 and r1["evento"] == r2["evento"] == "confirmada" and dur is not None,
            f"P4 {n}: ambos confirman; revertida en {rev[0]['centro'] if rev else '-'} {cuando}; "
            f"consistente al final ({final['incidente_asignado']})")


async def principal(n: int, n_p4: int):
    rng = random.Random("2026-verificar-a3")
    async with httpx.AsyncClient(timeout=15) as http:
        print(f"1) {n} ensayos con net_ab cortado y conflicto")
        for i in range(n):
            await ensayo_corte(http, i, rng)
        print(f"\n2) {n_p4} ensayos tipo P4 (A–B intermitente cada 2 s)")
        for i in range(n_p4):
            await ensayo_p4(http, i)
    fallas.restaurar_todo(ARQ)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--p4", type=int, default=2)
    a = p.parse_args()
    asyncio.run(principal(a.n, a.p4))
    print(f"\n{'APROBADA' if not fallos else 'REPROBADA'}: {len(fallos)} fallas")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
