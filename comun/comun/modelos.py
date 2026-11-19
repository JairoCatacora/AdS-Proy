"""Modelos de datos de la interfaz común (idéntica en A1, A2 y A3)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

EstadoRespuesta = Literal["confirmada", "rechazada", "sin_confirmacion"]
TipoEnsayo = Literal["con_conflicto", "sin_conflicto"]


class ContextoEnsayo(BaseModel):
    """Identifica el ensayo en curso. Lo envía el orquestador en /admin/reset
    para que el servicio sepa a qué ensayo pertenecen los eventos que genera."""
    arq: str
    escenario: str
    ensayo: int
    tipo: Optional[TipoEnsayo] = None


class SolicitudReserva(BaseModel):
    """Entrada de POST /reservas."""
    incidente: str
    ambulancia: str
    prioridad: int = Field(default=1, ge=1, le=2)  # incidentes de prioridad I–II
    ensayo: Optional[int] = None


class RespuestaReserva(BaseModel):
    """Salida de POST /reservas. `t_respuesta` es el tiempo que tardó el
    servicio en responder, en segundos."""
    estado: EstadoRespuesta
    t_respuesta: float


class SolicitudLiberar(BaseModel):
    """Entrada de POST /liberar."""
    ambulancia: str


class SolicitudReset(BaseModel):
    """Entrada de POST /admin/reset: deja estas ambulancias disponibles."""
    ambulancias: list[str]
    contexto: Optional[ContextoEnsayo] = None
