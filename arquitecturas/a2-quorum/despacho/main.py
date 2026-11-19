"""A2 — Servicio de despacho (sitio A o B).

El estado vive en el clúster etcd (Raft, 3 réplicas). Este servicio habla
SOLO con su réplica local (etcd1 o etcd2), por la red de su sitio, usando la
API JSON de etcd (gRPC-gateway): las claves y valores van en base64.

Una escritura se confirma solo si la persiste la mayoría (2 de 3). Si la
réplica local no tiene mayoría, la petición falla o no responde: se reintenta
cada 200 ms hasta agotar T y luego se responde `sin_confirmacion`.
"""

import base64
import os
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from comun.admin import EstadoAdmin, crear_router
from comun.cliente import pedir_con_plazo
from comun.config import (CONFIRMADA, DISPONIBLE, MARGEN_RESPUESTA as MARGEN, PLAZO_T,
                          RECHAZADA, RESERVADA, SIN_CONFIRMACION)
from comun.modelos import (RespuestaReserva, SolicitudLiberar, SolicitudReserva,
                           SolicitudReset)

CENTRO = os.environ["CENTRO"]          # "A" o "B"
ETCD_URL = os.environ["ETCD_URL"]      # réplica local, p. ej. http://10.2.101.11:2379
PREFIJO = "/amb/"

app = FastAPI(title=f"A2 despacho-{CENTRO.lower()}")
admin = EstadoAdmin(f"despacho-{CENTRO.lower()}", CENTRO)
app.include_router(crear_router(admin))
http = httpx.AsyncClient()


# ------------------------------------------------------------ utilidades etcd

def b64(texto: str) -> str:
    return base64.b64encode(texto.encode()).decode()


def de_b64(texto: str) -> str:
    return base64.b64decode(texto).decode()


def fin_de_prefijo(prefijo: str) -> str:
    """range_end para leer todas las claves que empiezan con `prefijo`."""
    return prefijo[:-1] + chr(ord(prefijo[-1]) + 1)


def no_ok(r: httpx.Response) -> bool:
    # 5xx: sin líder, sin quórum, timeout interno de etcd... → reintentar
    return r.status_code != 200


async def etcd(ruta: str, cuerpo: dict, plazo: float):
    """POST a la API JSON de etcd. Devuelve el JSON o None si se agota el plazo."""
    r = await pedir_con_plazo(http, "POST", f"{ETCD_URL}{ruta}", json=cuerpo,
                              plazo=plazo, reintentar_si=no_ok)
    return None if r is None or r.status_code != 200 else r.json()


def interpretar(valor: str) -> tuple[str, str | None]:
    """"disponible" → (disponible, None); "reservada:I-1" → (reservada, I-1)."""
    if valor.startswith(RESERVADA + ":"):
        return RESERVADA, valor.split(":", 1)[1]
    return valor, None


# ------------------------------------------------------------ API común

@app.post("/reservas", response_model=RespuestaReserva)
async def reservar(s: SolicitudReserva):
    t0 = time.monotonic()
    clave = b64(PREFIJO + s.ambulancia)
    reservado = f"{RESERVADA}:{s.incidente}"
    # Transacción condicional: si /amb/<id> == "disponible" → put "reservada:<incidente>"
    txn = {
        "compare": [{"key": clave, "target": "VALUE", "result": "EQUAL",
                     "value": b64(DISPONIBLE)}],
        "success": [{"request_put": {"key": clave, "value": b64(reservado)}}],
        "failure": [{"request_range": {"key": clave}}],
    }
    res = await etcd("/v3/kv/txn", txn, plazo=PLAZO_T - MARGEN)
    if res is None:
        estado = SIN_CONFIRMACION
    elif res.get("succeeded"):          # proto3 omite los campos en false
        estado = CONFIRMADA
    else:
        # Falló la comparación. Reserva idempotente: si ya está reservada para
        # ESTE incidente (reintento cuya respuesta se perdió) → confirmada.
        kvs = res["responses"][0]["response_range"].get("kvs", [])
        actual = de_b64(kvs[0]["value"]) if kvs else None
        estado = CONFIRMADA if actual == reservado else RECHAZADA
    return RespuestaReserva(estado=estado, t_respuesta=time.monotonic() - t0)


@app.post("/liberar")
async def liberar(s: SolicitudLiberar):
    res = await etcd("/v3/kv/put", {"key": b64(PREFIJO + s.ambulancia),
                                    "value": b64(DISPONIBLE)}, plazo=PLAZO_T - MARGEN)
    if res is not None:
        admin.evento("liberada", ambulancia=s.ambulancia)
    return {"ok": res is not None}


@app.get("/ambulancias")
async def ambulancias():
    """Lectura linealizable a través de la réplica local: si esta no tiene
    mayoría, el centro no puede saber el estado (503)."""
    res = await etcd("/v3/kv/range", {"key": b64(PREFIJO), "range_end": b64(fin_de_prefijo(PREFIJO))},
                     plazo=1.0)
    if res is None:
        return JSONResponse({"error": "sin quórum"}, status_code=503)
    salida = []
    for kv in res.get("kvs", []):
        estado, incidente = interpretar(de_b64(kv["value"]))
        salida.append({"id": de_b64(kv["key"])[len(PREFIJO):], "estado": estado,
                       "incidente_asignado": incidente, "version": int(kv.get("version", 0))})
    return sorted(salida, key=lambda a: a["id"])


@app.post("/admin/reset")
async def reset(s: SolicitudReset):
    """Borra todas las /amb/* y pone cada ambulancia indicada en "disponible".
    Lo pueden llamar ambos centros: es idempotente.
    (Dos pasos: etcd no admite un delete_range y un put sobre la misma clave
    en una sola transacción.)"""
    admin.nuevo_ensayo(s.contexto)
    borrar = {"key": b64(PREFIJO), "range_end": b64(fin_de_prefijo(PREFIJO))}
    poner = {"compare": [],
             "success": [{"request_put": {"key": b64(PREFIJO + a), "value": b64(DISPONIBLE)}}
                         for a in s.ambulancias]}
    res = await etcd("/v3/kv/deleterange", borrar, plazo=5.0)
    if res is not None:
        res = await etcd("/v3/kv/txn", poner, plazo=5.0)
    if res is None:
        return JSONResponse({"ok": False, "error": "etcd sin quórum"}, status_code=503)
    return {"ok": True}
