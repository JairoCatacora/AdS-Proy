"""Lectura del estado final (revisión de reserva sin aviso): reintenta mientras la
fuente de estado no responda 200; si no lo logra en ESPERA_ESTADO_FINAL → None
(el orquestador marca el ensayo inválido)."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / "experimento"))

import orquestador  # noqa: E402
from orquestador import leer_estado_final  # noqa: E402

AMBS = [{"id": "AMB-01", "estado": "disponible", "incidente_asignado": None}]


class ArqFalsa:
    fuente_estado = "a2-despacho-a"

    def url(self, c):
        return f"http://{c}:8000"


class LogFalso:
    def __init__(self):
        self.eventos = []

    def evento(self, nombre, **campos):
        self.eventos.append((nombre, campos))


def leer(respuestas):
    """Ejecuta leer_estado_final con un servidor falso que responde en orden."""
    pendientes = list(respuestas)

    def manejar(request):
        codigo = pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]
        return httpx.Response(codigo, json=AMBS if codigo == 200 else {"error": "sin quórum"})

    async def correr():
        async with httpx.AsyncClient(transport=httpx.MockTransport(manejar)) as http:
            return await leer_estado_final(http, ArqFalsa(), log)

    log = LogFalso()
    return asyncio.run(correr()), log.eventos


def test_200_a_la_primera_no_registra_nada():
    datos, eventos = leer([200])
    assert datos == AMBS and eventos == []


def test_503_transitorio_reintenta_y_lo_registra():
    # el caso de la F7: A2 sin quórum un instante tras el estado consistente
    datos, eventos = leer([503, 503, 200])
    assert datos == AMBS
    assert eventos == [("lectura_estado_final", {"intentos": 3, "codigos": [503, 503, 200],
                                                  "leido": True})]


def test_sin_respuesta_200_devuelve_none(monkeypatch):
    monkeypatch.setattr(orquestador, "ESPERA_ESTADO_FINAL", 0.5)
    datos, eventos = leer([503])
    assert datos is None
    nombre, campos = eventos[0]
    assert nombre == "lectura_estado_final" and campos["leido"] is False
    assert campos["intentos"] >= 2 and set(campos["codigos"]) == {503}
