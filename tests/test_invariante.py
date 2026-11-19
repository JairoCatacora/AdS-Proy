"""FF-01 — Fitness function de la arquitectura mejorada.

Ejecuta 10 ensayos de A2-P1 con conflicto (los mismos que el orquestador:
misma preparación, línea de tiempo, alternancia de quién pide primero y de la
posición del líder) y FALLA si:
- M1 > 0 (alguna doble asignación), o
- el p95 de M3 supera T = 10 s.

Necesita el banco de pruebas levantado; se corre dentro del contenedor:
    docker exec orquestador pytest tests/test_invariante.py -v
(Fuera del contenedor se salta: no hay acceso a net_ctl.)
"""

import asyncio
import random
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experimento"))

from comun.config import CON_CONFLICTO, PLAZO_T  # noqa: E402

N_ENSAYOS = 10
SEMILLA = 2026


def banco_disponible() -> bool:
    try:
        socket.gethostbyname("a2-despacho-a")
        return shutil.which("docker") is not None
    except OSError:
        return False


@pytest.mark.skipif(not banco_disponible(),
                    reason="requiere el banco de pruebas (correr dentro del contenedor orquestador)")
def test_ff01_a2_p1_sin_doble_asignacion_y_m3_p95_bajo_T():
    import httpx
    from clasificar import leer_ensayos
    from orquestador import Ensayo, correr_ensayo

    dir_logs = Path(tempfile.mkdtemp(prefix="ff01_"))
    ensayos = []
    for rep in range(N_ENSAYOS):
        s = random.Random(f"{SEMILLA}-FF01-{rep}").randrange(2**31)
        ensayos.append(Ensayo(arq="A2", escenario="P1", tipo=CON_CONFLICTO, rep=rep, n=rep,
                              semilla=s, delta=random.Random(s).uniform(0, 0.2),
                              primero="A" if rep % 2 == 0 else "B",
                              lado_lider="A" if (rep // 2) % 2 == 0 else "B"))

    async def correr():
        async with httpx.AsyncClient() as http:
            for e in ensayos:
                await correr_ensayo(http, e, dir_logs)
    asyncio.run(correr())

    filas = [f for f in leer_ensayos(dir_logs) if not f["invalido"]]
    assert len(filas) == N_ENSAYOS, f"solo {len(filas)} ensayos válidos (logs en {dir_logs})"

    dobles = sum(f["doble_asignacion"] for f in filas)
    m3 = [float(f[c]) for f in filas for c in ("t_respuesta_a", "t_respuesta_b") if f[c] != ""]
    p95 = float(np.percentile(m3, 95))
    print(f"\nFF-01: M1 = {dobles}/{len(filas)}; M3 p95 = {p95:.3f} s "
          f"({len(m3)} solicitudes); logs en {dir_logs}")
    assert dobles == 0, f"M1 > 0: {dobles} ensayos con doble asignación"
    assert p95 <= PLAZO_T, f"M3 p95 = {p95:.3f} s supera T = {PLAZO_T} s"
