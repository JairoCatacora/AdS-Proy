"""Pruebas unitarias del cliente HTTP con plazo (sin red real)."""

import asyncio
import time

import httpx

from comun.cliente import pedir_con_plazo


def _correr(transporte, **kw):
    async def main():
        async with httpx.AsyncClient(transport=transporte) as c:
            return await pedir_con_plazo(c, "POST", "http://x/reservas", json={}, **kw)
    return asyncio.run(main())


def test_responde_si_el_coordinador_contesta():
    t = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    assert _correr(t).json() == {"ok": True}


def test_reintenta_ante_error_de_conexion():
    intentos = []

    def manejador(req):
        intentos.append(time.monotonic())
        if len(intentos) < 3:
            raise httpx.ConnectError("red cortada")
        return httpx.Response(200, json={"ok": True})

    r = _correr(httpx.MockTransport(manejador), plazo=2.0, intervalo=0.2)
    assert r.status_code == 200
    assert len(intentos) == 3
    assert intentos[1] - intentos[0] >= 0.19  # espera ~200 ms entre intentos


def test_devuelve_none_al_agotar_el_plazo():
    def manejador(req):
        raise httpx.ConnectError("red cortada")

    inicio = time.monotonic()
    r = _correr(httpx.MockTransport(manejador), plazo=0.5, intervalo=0.1)
    duracion = time.monotonic() - inicio
    assert r is None
    assert 0.45 <= duracion < 0.8  # no se pasa del plazo


def test_reintentar_si_permite_reintentar_ante_respuestas():
    respuestas = iter([503, 503, 200])
    t = httpx.MockTransport(lambda req: httpx.Response(next(respuestas)))
    r = _correr(t, plazo=2.0, intervalo=0.05,
                reintentar_si=lambda resp: resp.status_code == 503)
    assert r.status_code == 200
