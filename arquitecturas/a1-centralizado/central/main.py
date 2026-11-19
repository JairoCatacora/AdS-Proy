"""A1 — Servidor central (sitio C).

Única fuente de verdad: la tabla `ambulancias` en PostgreSQL. La reserva es
un UPDATE atómico condicionado, por eso A1 es linealizable.
"""

import asyncio
import os

import asyncpg
from fastapi import FastAPI
from pydantic import BaseModel

from comun.admin import EstadoAdmin, crear_router
from comun.config import CONFIRMADA, RECHAZADA, RESERVADA
from comun.modelos import SolicitudLiberar, SolicitudReset

DSN = os.environ.get("POSTGRES_DSN", "postgresql://despacho:despacho@postgres:5432/flota")

app = FastAPI(title="A1 central-api")
admin = EstadoAdmin("central-api")
app.include_router(crear_router(admin))
pool: asyncpg.Pool | None = None

SQL_TABLA = """
CREATE TABLE IF NOT EXISTS ambulancias (
    id                 TEXT PRIMARY KEY,
    estado             TEXT NOT NULL DEFAULT 'disponible',
    incidente_asignado TEXT,
    version            INTEGER NOT NULL DEFAULT 0
)"""

# La reserva: tal cual la especificación.
SQL_RESERVAR = """
UPDATE ambulancias
SET estado = 'reservada', incidente_asignado = $1, version = version + 1
WHERE id = $2 AND estado = 'disponible'
RETURNING id"""


class ReservaCentral(BaseModel):
    incidente: str
    ambulancia: str


@app.on_event("startup")
async def conectar():
    """Conecta con PostgreSQL (reintenta mientras la base arranca)."""
    global pool
    while True:
        try:
            pool = await asyncpg.create_pool(DSN, min_size=2, max_size=10)
            break
        except (OSError, asyncpg.PostgresError):
            await asyncio.sleep(0.5)
    async with pool.acquire() as con:
        await con.execute(SQL_TABLA)


@app.post("/reservas")
async def reservar(s: ReservaCentral):
    async with pool.acquire() as con:
        fila = await con.fetchrow(SQL_RESERVAR, s.incidente, s.ambulancia)
        if fila is not None:
            return {"estado": CONFIRMADA}
        # 0 filas. Idempotencia: si ya está reservada para ESTE incidente
        # (un reintento cuya primera respuesta se perdió), es una confirmación.
        actual = await con.fetchrow(
            "SELECT estado, incidente_asignado FROM ambulancias WHERE id = $1",
            s.ambulancia)
        if actual and actual["estado"] == RESERVADA and actual["incidente_asignado"] == s.incidente:
            return {"estado": CONFIRMADA, "reintento": True}
        return {"estado": RECHAZADA}


@app.post("/liberar")
async def liberar(s: SolicitudLiberar):
    async with pool.acquire() as con:
        r = await con.execute(
            "UPDATE ambulancias SET estado = 'disponible', incidente_asignado = NULL, "
            "version = version + 1 WHERE id = $1", s.ambulancia)
    return {"ok": r.endswith(" 1")}


@app.get("/ambulancias")
async def ambulancias():
    async with pool.acquire() as con:
        filas = await con.fetch(
            "SELECT id, estado, incidente_asignado, version FROM ambulancias ORDER BY id")
    return [dict(f) for f in filas]


@app.post("/admin/reset")
async def reset(s: SolicitudReset):
    """Deja solo las ambulancias indicadas, todas disponibles."""
    admin.nuevo_ensayo(s.contexto)
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute("DELETE FROM ambulancias")
            await con.executemany(
                "INSERT INTO ambulancias (id) VALUES ($1)", [(a,) for a in s.ambulancias])
    return {"ok": True}
