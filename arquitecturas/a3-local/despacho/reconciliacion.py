"""A3 — Regla de reconciliación (función pura, sin estado ni red).

Cada centro guarda TODOS los eventos que conoce (los propios y los recibidos
del otro). El estado de la flota se calcula siempre igual a partir de ellos:

1. Se ordenan los eventos por (t, centro), con A antes que B en empate.
2. Se aplican en ese orden:
   - `reserva`: si la unidad está disponible, queda reservada para ese incidente.
     Si ya estaba reservada, esa reserva PIERDE (gana la más antigua).
   - `liberada`: si la unidad está reservada para ese mismo incidente, queda disponible.

Como la regla es determinista y simétrica, dos centros con el mismo conjunto
de eventos llegan exactamente al mismo estado, sin coordinador.
"""

from dataclasses import dataclass

DISPONIBLE, RESERVADA = "disponible", "reservada"


@dataclass(frozen=True)
class Evento:
    id: str            # único, p. ej. "A-3f9c..."
    tipo: str          # "reserva" o "liberada"
    centro: str        # centro que lo originó: "A" o "B"
    ambulancia: str
    incidente: str
    t: float           # time.time() en el centro de origen (reloj compartido del host)


def orden(e: Evento) -> tuple:
    """Gana el timestamp más antiguo; en empate gana A; luego el id (desempate total)."""
    return (e.t, 0 if e.centro == "A" else 1, e.id)


def reconciliar(eventos: list[Evento], ambulancias: list[str]):
    """Devuelve (estado, perdedoras).

    estado:      {ambulancia: {"estado", "incidente_asignado", "version"}}
    perdedoras:  [(reserva perdedora, reserva ganadora)]
    """
    estado = {a: {"estado": DISPONIBLE, "incidente_asignado": None, "version": 0}
              for a in ambulancias}
    titular: dict[str, Evento] = {}          # ambulancia -> reserva vigente
    perdedoras: list[tuple[Evento, Evento]] = []

    for e in sorted(eventos, key=orden):
        if e.ambulancia not in estado:
            continue
        s = estado[e.ambulancia]
        if e.tipo == "reserva":
            if s["estado"] == DISPONIBLE:
                s.update(estado=RESERVADA, incidente_asignado=e.incidente,
                         version=s["version"] + 1)
                titular[e.ambulancia] = e
            else:
                perdedoras.append((e, titular[e.ambulancia]))
        elif e.tipo == "liberada":
            if s["estado"] == RESERVADA and s["incidente_asignado"] == e.incidente:
                s.update(estado=DISPONIBLE, incidente_asignado=None,
                         version=s["version"] + 1)
                titular.pop(e.ambulancia, None)
    return estado, perdedoras
