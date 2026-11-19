"""Verificación funcional con la red sana (DiseñoExperimento: "Verificación
funcional en P0").

N ensayos con conflicto, sin fallas: los dos centros piden AMB-01 casi a la
vez (la segunda solicitud δ ∈ [0, 200] ms después, o `--separacion` s fija).

Criterio:
- A1 y A2: exactamente 1 `confirmada` y 1 `rechazada`.
- A3 (consistencia eventual): 1 `confirmada` + 1 `rechazada`, **o** 2 `confirmada`
  + exactamente una `revertida` + estado consistente. Con la red sana A3 también
  puede dar doble asignación si δ es menor que el retardo de sincronización.
  Con `--separacion 1` (mayor que el ciclo de 500 ms) debe dar 1 + 1.

El conteo se hace leyendo los logs JSONL escritos (no la memoria), para
probar también el registro de eventos.

Uso (dentro del contenedor del orquestador):
    python experimento/verificacion.py --arq A1 --n 10 --semilla 2026
    python experimento/verificacion.py --arq A3 --n 10 --separacion 1
"""

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

import httpx

import monitor
from clientes import solicitar
from comun.config import AMBULANCIA_ENSAYO, CON_CONFLICTO, DIR_LOGS
from comun.logger import LoggerEnsayo, leer_jsonl
from topologia import ARQUITECTURAS

DIR_VERIFICACION = Path(DIR_LOGS).parent / "verificacion"


async def preparar(http: httpx.AsyncClient, arq, contexto: dict) -> None:
    """Reinicia el estado y verifica que ambos centros ven AMB-01 disponible."""
    for c in arq.reset:
        r = await http.post(f"{arq.url(c)}/admin/reset",
                            json={"ambulancias": [AMBULANCIA_ENSAYO], "contexto": contexto})
        r.raise_for_status()
    for centro in ("A", "B"):
        r = await http.get(f"{arq.url_despacho(centro)}/ambulancias")
        amb = {a["id"]: a for a in r.json()}[AMBULANCIA_ENSAYO]
        assert amb["estado"] == "disponible", f"{centro} ve {amb}"


async def ensayo(http, arq, n: int, semilla: int, separacion=None) -> tuple[bool, str]:
    rng = random.Random(f"{semilla}-verificacion-{arq.nombre}-{n}")
    primero = "A" if n % 2 == 0 else "B"          # se alterna quién pide primero
    segundo = "B" if primero == "A" else "A"
    delta = rng.uniform(0, 0.200) if separacion is None else separacion   # δ ∈ [0, 200] ms

    log = LoggerEnsayo(DIR_VERIFICACION, arq.nombre, "P0", n, tipo=CON_CONFLICTO)
    log.ruta.unlink(missing_ok=True)               # cada verificación empieza limpia
    await preparar(http, arq, {"arq": arq.nombre, "escenario": "P0",
                               "ensayo": n, "tipo": CON_CONFLICTO})
    log.evento("ensayo_inicio", semilla=semilla, primero=primero, delta=delta)

    async def segunda():
        await asyncio.sleep(delta)
        return await solicitar(http, arq.url_despacho(segundo), log, segundo,
                               "I-2", AMBULANCIA_ENSAYO)

    await asyncio.gather(
        solicitar(http, arq.url_despacho(primero), log, primero, "I-1", AMBULANCIA_ENSAYO),
        segunda())
    consistente = True
    if arq.nombre == "A3":
        # Esperar a que ambos centros se sincronicen y recoger sus eventos (revertida)
        t_cons, _ = await monitor.vigilar(http, arq, hasta=time.time() + 30)
        consistente = t_cons is not None
        for c in arq.reset:
            for ev in (await http.get(f"{arq.url(c)}/admin/eventos")).json():
                log.escribir(ev)
    log.evento("ensayo_fin")

    # Conteo a partir del archivo
    eventos = leer_jsonl(log.ruta)
    resp = {e["centro"]: (e["evento"], e["extra"]["t_respuesta"])
            for e in eventos if e["evento"] in ("confirmada", "rechazada", "sin_confirmacion")}
    n_conf = sum(1 for ev, _ in resp.values() if ev == "confirmada")
    n_rech = sum(1 for ev, _ in resp.values() if ev == "rechazada")
    n_rev = sum(1 for e in eventos if e["evento"] == "revertida")
    simple = n_conf == 1 and n_rech == 1 and n_rev == 0
    doble_revertida = n_conf == 2 and n_rev == 1 and consistente
    ok = simple or (arq.nombre == "A3" and doble_revertida)
    tipo = "1+1" if simple else ("doble+revertida" if doble_revertida else "otro")
    detalle = (f"primero={primero} δ={delta*1000:6.1f} ms  "
               f"A={resp['A'][0]:<10} ({resp['A'][1]*1000:6.1f} ms)  "
               f"B={resp['B'][0]:<10} ({resp['B'][1]*1000:6.1f} ms)  "
               f"revertidas={n_rev}  [{tipo}]")
    return ok, detalle


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arq", required=True, choices=sorted(ARQUITECTURAS))
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--separacion", type=float, default=None,
                   help="segundos fijos entre las dos solicitudes (por defecto δ aleatorio)")
    a = p.parse_args()
    arq = ARQUITECTURAS[a.arq]

    aprobados = 0
    async with httpx.AsyncClient(timeout=15) as http:
        for n in range(a.n):
            ok, detalle = await ensayo(http, arq, n, a.semilla, a.separacion)
            aprobados += ok
            print(f"{a.arq} ensayo {n:2d}: {'OK   ' if ok else 'FALLA'} {detalle}")
    criterio = ("1 confirmada + 1 rechazada, o doble + exactamente 1 revertida + consistente"
                if a.arq == "A3" and a.separacion is None
                else "exactamente 1 confirmada y 1 rechazada")
    print(f"\n{aprobados}/{a.n} ensayos con {criterio}")
    print(f"Logs en {DIR_VERIFICACION / a.arq / 'P0'}")
    return 0 if aprobados == a.n else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
