"""Pruebas unitarias de la regla de reconciliación de A3 (sin Docker)."""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "arquitecturas" / "a3-local" / "despacho"))

from reconciliacion import Evento, reconciliar  # noqa: E402

AMB = ["AMB-01"]


def reserva(centro, incidente, t, id_=None):
    return Evento(id_ or f"{centro}-{incidente}", "reserva", centro, "AMB-01", incidente, t)


def test_gana_la_mas_antigua():
    a = reserva("A", "I-1", 10.0)
    b = reserva("B", "I-2", 10.1)
    estado, perdedoras = reconciliar([b, a], AMB)
    assert estado["AMB-01"]["incidente_asignado"] == "I-1"
    assert perdedoras == [(b, a)]


def test_empate_gana_a():
    a = reserva("A", "I-1", 10.0)
    b = reserva("B", "I-2", 10.0)
    estado, perdedoras = reconciliar([b, a], AMB)
    assert estado["AMB-01"]["incidente_asignado"] == "I-1"
    assert perdedoras[0][0] == b


def test_simetrica_mismo_resultado_en_cualquier_orden():
    """Ambos centros reciben los eventos en distinto orden y llegan a lo mismo."""
    rng = random.Random(2026)
    eventos = [reserva(rng.choice("AB"), f"I-{i}", rng.uniform(0, 5), f"e{i}") for i in range(6)]
    eventos.append(Evento("lib", "liberada", "A", "AMB-01", "I-0", 6.0))
    esperado = reconciliar(eventos, AMB)
    for perm in itertools.islice(itertools.permutations(eventos), 200):
        assert reconciliar(list(perm), AMB) == esperado


def test_liberada_solo_libera_al_titular():
    a = reserva("A", "I-1", 1.0)
    lib_ajena = Evento("l1", "liberada", "B", "AMB-01", "I-2", 2.0)
    estado, _ = reconciliar([a, lib_ajena], AMB)
    assert estado["AMB-01"]["estado"] == "reservada"
    lib = Evento("l2", "liberada", "A", "AMB-01", "I-1", 3.0)
    b = reserva("B", "I-2", 4.0)
    estado, perdedoras = reconciliar([a, lib, b], AMB)
    assert estado["AMB-01"]["incidente_asignado"] == "I-2" and perdedoras == []


def test_sin_eventos_todo_disponible():
    estado, perdedoras = reconciliar([], AMB)
    assert estado["AMB-01"] == {"estado": "disponible", "incidente_asignado": None, "version": 0}
    assert perdedoras == []
