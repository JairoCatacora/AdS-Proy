"""Cliente HTTP con plazo total y reintentos.

Lo usan los servicios de despacho para hablar con su coordinador
(central-api en A1, etcd en A2, el otro centro en A3).

Regla: se reintenta cada 200 ms ante errores de conexión hasta agotar el
plazo T. Si el plazo se agota sin respuesta, se devuelve `None` y el
servicio responde `sin_confirmacion`.
"""

import asyncio
import time
from typing import Any, Optional

import httpx

from comun.config import INTERVALO_REINTENTO, PLAZO_T, TIMEOUT_CONEXION


async def pedir_con_plazo(
    cliente: httpx.AsyncClient,
    metodo: str,
    url: str,
    *,
    json: Any = None,
    plazo: float = PLAZO_T,
    intervalo: float = INTERVALO_REINTENTO,
    timeout_conexion: float = TIMEOUT_CONEXION,
    reintentar_si: Optional[callable] = None,
) -> Optional[httpx.Response]:
    """Envía la petición y reintenta hasta tener respuesta o agotar `plazo`.

    - Error de conexión (red cortada, contenedor caído): espera `intervalo`
      y reintenta.
    - Si la petición se envió pero la respuesta no llega, se espera como
      máximo lo que queda del plazo (no se reintenta: el coordinador pudo
      haberla procesado).
    - `reintentar_si(respuesta)`: permite reintentar también ante ciertas
      respuestas (p. ej. un 503 de etcd sin líder).
    """
    limite = time.monotonic() + plazo
    while True:
        restante = limite - time.monotonic()
        if restante <= 0:
            return None
        timeout = httpx.Timeout(restante, connect=min(timeout_conexion, restante))
        try:
            respuesta = await cliente.request(metodo, url, json=json, timeout=timeout)
            if reintentar_si is None or not reintentar_si(respuesta):
                return respuesta
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pass  # no se llegó a enviar: se puede reintentar sin riesgo
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            return None  # se agotó el plazo esperando
        except httpx.TransportError:
            pass  # conexión reiniciada u otro error de red: reintentar
        # Esperar antes del siguiente intento, sin pasarse del plazo.
        espera = min(intervalo, limite - time.monotonic())
        if espera > 0:
            await asyncio.sleep(espera)
