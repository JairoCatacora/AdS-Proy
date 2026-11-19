"""Cliente simulado del despachador.

Envía POST /reservas al servicio de despacho de su centro (por net_ctl),
registra `solicitud` y luego la respuesta (`confirmada`, `rechazada` o
`sin_confirmacion`). Ninguna solicitud queda sin respuesta: si el servicio
no contesta, el cliente registra `sin_confirmacion` al vencer su espera.
"""

import time
from typing import Optional

import httpx

from comun.config import ESTADOS_RESPUESTA, PLAZO_T, SIN_CONFIRMACION
from comun.logger import LoggerEnsayo

# El servicio responde a más tardar en T; el cliente espera un poco más
# por si la respuesta HTTP tarda en llegar.
ESPERA_CLIENTE = PLAZO_T + 2.0


async def solicitar(http: httpx.AsyncClient, url_despacho: str, log: LoggerEnsayo,
                    centro: str, incidente: str, ambulancia: str,
                    extra: Optional[dict] = None) -> dict:
    """Pide la ambulancia y devuelve el evento de respuesta registrado."""
    extra = extra or {}
    sol = log.evento("solicitud", centro=centro, incidente=incidente,
                     ambulancia=ambulancia, **extra)
    cuerpo = {"incidente": incidente, "ambulancia": ambulancia,
              "prioridad": 1, "ensayo": log.ensayo}
    try:
        r = await http.post(f"{url_despacho}/reservas", json=cuerpo, timeout=ESPERA_CLIENTE)
        datos = r.json()
        estado = datos["estado"]
        if estado not in ESTADOS_RESPUESTA:
            raise ValueError(f"estado inesperado {estado!r}")
        detalle = {"t_servicio": datos.get("t_respuesta")}
    except Exception as e:  # sin respuesta del servicio: no puede quedar colgada
        estado = SIN_CONFIRMACION
        detalle = {"motivo": f"{type(e).__name__}: {e}"}
    # t_respuesta: medido por el cliente (desde su `solicitud` hasta recibir la respuesta).
    # t_servicio: lo que reporta el propio servicio (solo informativo).
    t_resp = time.time()
    return log.evento(estado, t=t_resp, centro=centro, incidente=incidente,
                      ambulancia=ambulancia, t_solicitud=sol["t"],
                      t_respuesta=t_resp - sol["t"], **extra, **detalle)


async def liberar(http: httpx.AsyncClient, url_despacho: str, ambulancia: str) -> bool:
    r = await http.post(f"{url_despacho}/liberar", json={"ambulancia": ambulancia},
                        timeout=ESPERA_CLIENTE)
    return r.status_code == 200 and r.json().get("ok", False)
