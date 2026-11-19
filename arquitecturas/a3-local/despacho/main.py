"""A3 — Servicio de despacho local con reconciliación (sitio A o B).

- Cada centro tiene su propia base SQLite y confirma SOLO con ella: la reserva
  es el mismo UPDATE condicionado de A1, pero local, y responde de inmediato.
- Cada reserva o liberación confirmada genera un evento. El sincronizador (una
  tarea dentro de este mismo servicio) envía cada 500 ms al otro centro, por
  net_ab, los eventos propios que el otro aún no confirmó haber recibido.
- Al recibir eventos se recalcula el estado con `reconciliar()`. Si una
  reserva PROPIA pierde (otra más antigua ganó), este centro registra
  `revertida`, con el incidente afectado y el ganador.
"""

import asyncio
import os
import sqlite3
import time
import uuid

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from comun.admin import EstadoAdmin, crear_router
from comun.config import CONFIRMADA, RECHAZADA
from comun.modelos import (RespuestaReserva, SolicitudLiberar, SolicitudReserva,
                           SolicitudReset)
from reconciliacion import Evento, reconciliar

CENTRO = os.environ["CENTRO"]               # "A" o "B"
PAR_URL = os.environ["PAR_URL"]             # el otro centro, por su IP en net_ab
RUTA_DB = os.environ.get("RUTA_DB", "/var/lib/a3/flota.db")
INTERVALO_SYNC = 0.5
# Variante (desactivada por defecto): además del ciclo de 500 ms, enviar en cuanto
# se confirma un evento nuevo.
SYNC_INMEDIATO = os.environ.get("SYNC_INMEDIATO", "0") == "1"
hay_nuevos = asyncio.Event()

app = FastAPI(title=f"A3 despacho-{CENTRO.lower()}")
admin = EstadoAdmin(f"despacho-{CENTRO.lower()}", CENTRO)
app.include_router(crear_router(admin))
http = httpx.AsyncClient()
candado = asyncio.Lock()       # serializa todas las operaciones sobre la base

# ------------------------------------------------------------ base local (SQLite)

os.makedirs(os.path.dirname(RUTA_DB), exist_ok=True)
db = sqlite3.connect(RUTA_DB, check_same_thread=False, isolation_level=None)
db.executescript("""
CREATE TABLE IF NOT EXISTS ambulancias (
    id TEXT PRIMARY KEY, estado TEXT NOT NULL DEFAULT 'disponible',
    incidente_asignado TEXT, version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS eventos (
    id TEXT PRIMARY KEY, tipo TEXT, centro TEXT, ambulancia TEXT, incidente TEXT, t REAL,
    enviado INTEGER NOT NULL DEFAULT 0,      -- evento propio ya recibido por el otro centro
    revertida INTEGER NOT NULL DEFAULT 0);   -- reserva propia ya registrada como revertida
CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT);
""")


def epoca() -> str:
    """Identifica el ensayo en curso. Los eventos de otra época se descartan
    (p. ej. un envío de un ensayo anterior que llega tarde)."""
    fila = db.execute("SELECT valor FROM config WHERE clave = 'epoca'").fetchone()
    return fila[0] if fila else ""


def todos_los_eventos() -> list[Evento]:
    filas = db.execute("SELECT id, tipo, centro, ambulancia, incidente, t FROM eventos")
    return [Evento(*f) for f in filas]


def registrar_evento(e: Evento, enviado: int) -> bool:
    """Guarda un evento (idempotente por id). Devuelve True si era nuevo."""
    cur = db.execute(
        "INSERT OR IGNORE INTO eventos (id, tipo, centro, ambulancia, incidente, t, enviado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (e.id, e.tipo, e.centro, e.ambulancia, e.incidente, e.t, enviado))
    return cur.rowcount == 1


def recalcular() -> None:
    """Aplica la regla de reconciliación y actualiza la vista local.
    Registra `revertida` (una sola vez) por cada reserva PROPIA que perdió."""
    ambulancias = [f[0] for f in db.execute("SELECT id FROM ambulancias")]
    estado, perdedoras = reconciliar(todos_los_eventos(), ambulancias)
    for amb, s in estado.items():
        db.execute("UPDATE ambulancias SET estado = ?, incidente_asignado = ?, version = ? "
                   "WHERE id = ?", (s["estado"], s["incidente_asignado"], s["version"], amb))
    for perdida, ganadora in perdedoras:
        if perdida.centro != CENTRO:
            continue                            # la revierte (y la registra) el otro centro
        cur = db.execute("UPDATE eventos SET revertida = 1 WHERE id = ? AND revertida = 0",
                         (perdida.id,))
        if cur.rowcount == 1:
            admin.evento("revertida", incidente=perdida.incidente, ambulancia=perdida.ambulancia,
                         incidente_ganador=ganadora.incidente, centro_ganador=ganadora.centro,
                         t_reserva_revertida=perdida.t, t_reserva_ganadora=ganadora.t)


def nuevo_evento(tipo: str, ambulancia: str, incidente: str) -> Evento:
    e = Evento(f"{CENTRO}-{uuid.uuid4().hex[:12]}", tipo, CENTRO, ambulancia, incidente,
               time.time())
    registrar_evento(e, enviado=0)
    hay_nuevos.set()
    return e


# ------------------------------------------------------------ API común

@app.post("/reservas", response_model=RespuestaReserva)
async def reservar(s: SolicitudReserva):
    t0 = time.monotonic()
    async with candado:
        # Mismo UPDATE condicionado de A1, sobre la base LOCAL
        cur = db.execute(
            "UPDATE ambulancias SET estado = 'reservada', incidente_asignado = ?, "
            "version = version + 1 WHERE id = ? AND estado = 'disponible'",
            (s.incidente, s.ambulancia))
        if cur.rowcount == 1:
            nuevo_evento("reserva", s.ambulancia, s.incidente)
            estado = CONFIRMADA
        else:
            estado = RECHAZADA
    return RespuestaReserva(estado=estado, t_respuesta=time.monotonic() - t0)


@app.post("/liberar")
async def liberar(s: SolicitudLiberar):
    async with candado:
        fila = db.execute("SELECT estado, incidente_asignado FROM ambulancias WHERE id = ?",
                          (s.ambulancia,)).fetchone()
        if not fila or fila[0] != "reservada":
            return {"ok": False}
        nuevo_evento("liberada", s.ambulancia, fila[1])   # se propaga como cualquier evento
        recalcular()
    admin.evento("liberada", ambulancia=s.ambulancia, incidente=fila[1])
    return {"ok": True}


@app.get("/ambulancias")
async def ambulancias():
    """Estado según ESTE centro (puede diferir del otro mientras no sincronicen)."""
    async with candado:
        filas = db.execute(
            "SELECT id, estado, incidente_asignado, version FROM ambulancias ORDER BY id").fetchall()
    return [dict(zip(("id", "estado", "incidente_asignado", "version"), f)) for f in filas]


# ------------------------------------------------------------ sincronización

class Lote(BaseModel):
    epoca: str
    eventos: list[dict]


@app.post("/sync/eventos")
async def recibir(lote: Lote):
    """Recibe eventos del otro centro (por net_ab). Responde los id guardados,
    para que el emisor los marque como enviados."""
    async with candado:
        if lote.epoca != epoca():
            return {"recibidos": []}           # de otro ensayo: se descarta
        recibidos = []
        for d in lote.eventos:
            registrar_evento(Evento(**d), enviado=1)
            recibidos.append(d["id"])
        recalcular()
    return {"recibidos": recibidos}


async def sincronizador():
    """Cada 500 ms envía al otro centro los eventos propios aún no confirmados."""
    while True:
        if SYNC_INMEDIATO:
            try:
                await asyncio.wait_for(hay_nuevos.wait(), INTERVALO_SYNC)
            except asyncio.TimeoutError:
                pass
            hay_nuevos.clear()
        else:
            await asyncio.sleep(INTERVALO_SYNC)
        async with candado:
            ep = epoca()
            pendientes = [dict(zip(("id", "tipo", "centro", "ambulancia", "incidente", "t"), f))
                          for f in db.execute(
                              "SELECT id, tipo, centro, ambulancia, incidente, t FROM eventos "
                              "WHERE centro = ? AND enviado = 0", (CENTRO,))]
        if not pendientes:
            continue
        try:
            r = await http.post(f"{PAR_URL}/sync/eventos",
                                json={"epoca": ep, "eventos": pendientes},
                                timeout=httpx.Timeout(1.0, connect=0.5))
            ids = r.json()["recibidos"] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            continue                            # enlace cortado: se reintenta en 500 ms
        async with candado:
            if epoca() == ep:                   # no marcar si hubo un reset entretanto
                db.executemany("UPDATE eventos SET enviado = 1 WHERE id = ?",
                               [(i,) for i in ids])


@app.on_event("startup")
async def arrancar():
    asyncio.create_task(sincronizador())


# ------------------------------------------------------------ administración

@app.get("/admin/pendientes")
async def pendientes():
    async with candado:
        n = db.execute("SELECT COUNT(*) FROM eventos WHERE centro = ? AND enviado = 0",
                       (CENTRO,)).fetchone()[0]
    return {"pendientes": n}


@app.post("/admin/reset")
async def reset(s: SolicitudReset):
    """Vacía la base local y la cola del sincronizador, y fija la nueva época."""
    c = s.contexto
    ep = f"{c.arq}-{c.escenario}-{c.ensayo}-{c.tipo}" if c else ""
    async with candado:
        admin.nuevo_ensayo(c)
        db.execute("DELETE FROM eventos")
        db.execute("DELETE FROM ambulancias")
        db.executemany("INSERT INTO ambulancias (id) VALUES (?)", [(a,) for a in s.ambulancias])
        db.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('epoca', ?)", (ep,))
    return {"ok": True}
