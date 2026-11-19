"""Etiqueta de cada entrada de entorno.json: 'p0', 'corrida' o 'reanudacion'."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "experimento"))

from entorno import tipo_entrada  # noqa: E402

CORRIDA = {"p0": False, "piloto": False}
P0 = {"p0": True, "piloto": False}


def test_p0():
    assert tipo_entrada(None, P0) == "p0"
    assert tipo_entrada({"tipo": "corrida"}, P0) == "p0"


def test_primer_arranque_es_corrida():
    assert tipo_entrada(None, CORRIDA) == "corrida"


def test_f7_despues_de_la_p0_es_corrida():
    # el caso de esta PC: la P0 creó entorno.json antes de la F7
    assert tipo_entrada({"tipo": "p0"}, CORRIDA) == "corrida"
    assert tipo_entrada({"parametros": P0}, CORRIDA) == "corrida"        # entrada sin tipo


def test_reanudacion():
    assert tipo_entrada({"tipo": "corrida"}, CORRIDA) == "reanudacion"
    previos = {"tipo": "p0", "entradas_posteriores": [{"tipo": "corrida"}]}
    assert tipo_entrada(previos, CORRIDA) == "reanudacion"
    previos["entradas_posteriores"].append({"tipo": "reanudacion"})
    assert tipo_entrada(previos, CORRIDA) == "reanudacion"
