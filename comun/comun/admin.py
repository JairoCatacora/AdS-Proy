"""Partes administrativas comunes a todos los servicios (solo las usan el
orquestador y el monitor por net_ctl).

- Contexto del ensayo en curso (lo fija /admin/reset).
- Buffer de eventos propios del servicio (GET /admin/eventos).
- Identificador de arranque para detectar reinicios (GET /admin/health).

Requiere FastAPI (solo está instalado en las imágenes de los servicios).
"""

import time
import uuid
from typing import Optional

from fastapi import APIRouter

from comun.logger import BufferEventos
from comun.modelos import ContextoEnsayo


class EstadoAdmin:
    def __init__(self, nombre: str, centro: Optional[str] = None):
        self.nombre = nombre                 # p. ej. "despacho-a"
        self.centro = centro                 # "A", "B" o None
        self.id_arranque = uuid.uuid4().hex  # cambia si el contenedor se reinicia
        self.t_arranque = time.time()
        self.contexto: Optional[ContextoEnsayo] = None
        self.eventos = BufferEventos()

    def nuevo_ensayo(self, contexto: Optional[ContextoEnsayo]) -> None:
        """Se llama en /admin/reset: fija el contexto y vacía los eventos."""
        self.contexto = contexto
        self.eventos.vaciar()

    def evento(self, evento: str, **campos) -> dict:
        """Registra un evento propio, con el contexto del ensayo en curso."""
        c = self.contexto
        return self.eventos.agregar(
            evento,
            ensayo=c.ensayo if c else None,
            arq=c.arq if c else None,
            escenario=c.escenario if c else None,
            tipo=c.tipo if c else None,
            centro=campos.pop("centro", self.centro),
            nodo=self.nombre,
            **campos,
        )


def crear_router(estado: EstadoAdmin) -> APIRouter:
    """Rutas /admin/health y /admin/eventos (cada servicio define su propio
    /admin/reset, porque reiniciar el estado depende de la arquitectura)."""
    router = APIRouter()

    @router.get("/admin/health")
    def health():
        return {
            "ok": True,
            "nodo": estado.nombre,
            "id_arranque": estado.id_arranque,
            "uptime": time.time() - estado.t_arranque,
        }

    @router.get("/admin/eventos")
    def eventos():
        # Se devuelven sin vaciar: así el orquestador puede volver a pedirlos.
        # El buffer se vacía en el siguiente /admin/reset.
        return estado.eventos.copiar()

    return router
