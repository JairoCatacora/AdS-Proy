"""A1 — Servicio de despacho (sitio A o B).

No guarda estado: reenvía cada operación a central-api por su red de enlace
(net_ac desde A, net_bc desde B), usando la IP fija de central-api en esa red.
"""

import os
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from comun.admin import EstadoAdmin, crear_router
from comun.cliente import pedir_con_plazo
from comun.config import (CONFIRMADA, MARGEN_RESPUESTA as MARGEN, PLAZO_T, RECHAZADA,
                          SIN_CONFIRMACION)
from comun.modelos import (RespuestaReserva, SolicitudLiberar, SolicitudReserva,
                           SolicitudReset)

CENTRO = os.environ["CENTRO"]              # "A" o "B"
CENTRAL_URL = os.environ["CENTRAL_URL"]    # p. ej. http://10.1.13.30:8000 (IP en net_ac)

app = FastAPI(title=f"A1 despacho-{CENTRO.lower()}")
admin = EstadoAdmin(f"despacho-{CENTRO.lower()}", CENTRO)
app.include_router(crear_router(admin))
http = httpx.AsyncClient()


def _error_servidor(r: httpx.Response) -> bool:
    return r.status_code >= 500  # central-api arrancando o sin base: reintentar


@app.post("/reservas", response_model=RespuestaReserva)
async def reservar(s: SolicitudReserva):
    t0 = time.monotonic()
    r = await pedir_con_plazo(
        http, "POST", f"{CENTRAL_URL}/reservas",
        json={"incidente": s.incidente, "ambulancia": s.ambulancia},
        plazo=PLAZO_T - MARGEN, reintentar_si=_error_servidor)
    if r is None or r.status_code != 200:
        estado = SIN_CONFIRMACION
    else:
        estado = CONFIRMADA if r.json()["estado"] == CONFIRMADA else RECHAZADA
    return RespuestaReserva(estado=estado, t_respuesta=time.monotonic() - t0)


@app.post("/liberar")
async def liberar(s: SolicitudLiberar):
    r = await pedir_con_plazo(http, "POST", f"{CENTRAL_URL}/liberar",
                              json=s.model_dump(), plazo=PLAZO_T - MARGEN)
    ok = r is not None and r.status_code == 200 and r.json()["ok"]
    if ok:
        admin.evento("liberada", ambulancia=s.ambulancia)
    return {"ok": ok}


@app.get("/ambulancias")
async def ambulancias():
    """Estado según este centro = lo que le responde central-api. Si no la
    alcanza, el centro no conoce el estado (503)."""
    r = await pedir_con_plazo(http, "GET", f"{CENTRAL_URL}/ambulancias", plazo=1.0)
    if r is None or r.status_code != 200:
        return JSONResponse({"error": "central-api inalcanzable"}, status_code=503)
    return r.json()


@app.post("/admin/reset")
async def reset(s: SolicitudReset):
    # El estado vive en central-api; el orquestador la reinicia directamente.
    # Aquí solo se fija el contexto del ensayo y se vacían los eventos.
    admin.nuevo_ensayo(s.contexto)
    return {"ok": True}
