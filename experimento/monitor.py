"""Monitor de consistencia (M5). Consulta por net_ctl cada 100 ms.

Estado consistente:
- A1: ambos centros reportan el mismo estado e incidente para AMB-01.
- A2: lo anterior, y además las 3 réplicas tienen la misma revisión.
- A3: lo anterior, y además `pendientes == 0` en ambos centros.
"""

import asyncio
import time

import httpx

import etcd_admin
from comun.config import AMBULANCIA_ENSAYO
from topologia import Arquitectura

INTERVALO = 0.1


async def _vista(http: httpx.AsyncClient, arq: Arquitectura, centro: str):
    """(estado, incidente) de AMB-01 según un centro, o None si no responde."""
    try:
        r = await http.get(f"{arq.url_despacho(centro)}/ambulancias", timeout=1.0)
        if r.status_code != 200:
            return None
        a = {x["id"]: x for x in r.json()}.get(AMBULANCIA_ENSAYO)
        return (a["estado"], a["incidente_asignado"]) if a else None
    except httpx.HTTPError:
        return None


async def _pendientes(http, arq, centro) -> int | None:
    try:
        r = await http.get(f"{arq.url_despacho(centro)}/admin/pendientes", timeout=1.0)
        return r.json()["pendientes"] if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


async def es_consistente(http: httpx.AsyncClient, arq: Arquitectura) -> tuple[bool, dict]:
    """¿El sistema está en estado consistente? Devuelve también lo observado."""
    va, vb = await asyncio.gather(_vista(http, arq, "A"), _vista(http, arq, "B"))
    obs = {"A": va, "B": vb}
    ok = va is not None and va == vb
    if ok and arq.nombre == "A2":
        obs["misma_revision"] = await asyncio.to_thread(etcd_admin.misma_revision)
        ok = obs["misma_revision"]
    if ok and arq.nombre == "A3":
        pa, pb = await asyncio.gather(_pendientes(http, arq, "A"), _pendientes(http, arq, "B"))
        obs["pendientes"] = (pa, pb)
        ok = pa == 0 and pb == 0
    return ok, obs


async def vigilar(http: httpx.AsyncClient, arq: Arquitectura, hasta: float):
    """Consulta cada 100 ms hasta el estado consistente o hasta `hasta`
    (time.time()). Devuelve (t de detección o None, última observación)."""
    obs = {}
    while time.time() < hasta:
        inicio = time.monotonic()
        ok, obs = await es_consistente(http, arq)
        if ok:
            return time.time(), obs
        await asyncio.sleep(max(0.0, INTERVALO - (time.monotonic() - inicio)))
    return None, obs
