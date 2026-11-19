"""Criterio de invalidez: un corte o una restauración (connect + netem) que tarda
más de 1 s invalida el ensayo (se repite con la misma semilla)."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "experimento"))

from orquestador import (LIMITE_OPERACION_RED, operacion_red,  # noqa: E402
                         operaciones_lentas)


def test_limite_es_un_segundo():
    assert LIMITE_OPERACION_RED == 1.0


def test_operaciones_rapidas_no_invalidan():
    duraciones = [{"op": "corte", "t": 0, "s": 0.25},
                  {"op": "restauracion_p4", "t": 0, "s": 0.21},
                  {"op": "corte_p4", "t": 0, "s": 1.0},          # justo en el límite: válido
                  {"op": "restauracion", "t": 0, "s": 0.30}]
    assert operaciones_lentas(duraciones) == []


def test_corte_lento_invalida():
    motivos = operaciones_lentas([{"op": "corte", "t": 0, "s": 1.2}])
    assert len(motivos) == 1 and motivos[0].startswith("corte tardó 1.20 s")


def test_restauracion_lenta_invalida():
    # el caso visto en la PC nueva: restauración de P4 de 6,76 s
    duraciones = [{"op": "restauracion_p4", "t": 0, "s": 0.2},
                  {"op": "restauracion_p4", "t": 0, "s": 6.76},
                  {"op": "restauracion", "t": 0, "s": 1.01}]
    motivos = operaciones_lentas(duraciones)
    assert [m.split(" tardó")[0] for m in motivos] == ["restauracion_p4", "restauracion"]


def test_operacion_red_registra_la_duracion():
    duraciones = []
    resultado = asyncio.run(operacion_red(duraciones, "corte", lambda x: (time.sleep(0.05), x)[1], "ok"))
    assert resultado == "ok"
    assert len(duraciones) == 1 and duraciones[0]["op"] == "corte"
    assert 0.04 <= duraciones[0]["s"] < 0.5
