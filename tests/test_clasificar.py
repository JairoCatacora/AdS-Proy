"""Pruebas unitarias de la clasificación de ensayos (M1, M2, M5, M6)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "experimento"))

from clasificar import clasificar  # noqa: E402
from comun.logger import crear_evento  # noqa: E402

BASE = dict(ensayo=1, arq="A3", escenario="P1", tipo="con_conflicto")


def ev(nombre, t, **kw):
    return crear_evento(nombre, t=t, **BASE, **kw)


def resp(nombre, t, centro, inc, t_resp):
    return ev(nombre, t, centro=centro, incidente=inc, ambulancia="AMB-01", t_respuesta=t_resp)


def esqueleto(*respuestas, extra=()):
    return [ev("ensayo_inicio", 0, rep=0, semilla=7, primero="A"),
            ev("corte_inicio", 1, lider="etcd1"),
            ev("solicitud", 3, centro="A", incidente="I-1", ambulancia="AMB-01"),
            ev("solicitud", 3.1, centro="B", incidente="I-2", ambulancia="AMB-01"),
            *respuestas, ev("corte_fin", 21), ev("estado_consistente", 22.5), *extra,
            ev("ensayo_fin", 23)]


def test_doble_asignacion_aunque_se_revierta():
    f = clasificar(esqueleto(resp("confirmada", 3.02, "A", "I-1", 0.02),
                             resp("confirmada", 3.12, "B", "I-2", 0.02),
                             extra=[ev("revertida", 21.4, centro="B", incidente="I-2")]))
    assert f["doble_asignacion"] == 1
    assert f["valido_a_tiempo"] == 0          # dos confirmaciones: no es válido
    assert f["reversiones"] == 1
    assert f["t_recuperacion"] == 1.5
    assert f["lider_inicial"] == "etcd1" and f["invalido"] == 0


def test_una_confirmada_a_tiempo_es_valido():
    f = clasificar(esqueleto(resp("confirmada", 3.07, "A", "I-1", 0.07),
                             resp("sin_confirmacion", 13.1, "B", "I-2", 10.0)))
    assert f["doble_asignacion"] == 0 and f["valido_a_tiempo"] == 1
    assert (f["respuesta_a"], f["respuesta_b"]) == ("confirmada", "sin_confirmacion")


def test_confirmacion_tardia_no_es_valida():
    f = clasificar(esqueleto(resp("confirmada", 13.5, "A", "I-1", 10.5),
                             resp("rechazada", 13.6, "B", "I-2", 10.5)))
    assert f["valido_a_tiempo"] == 0


def test_liberada_entre_confirmaciones_no_es_doble():
    f = clasificar(esqueleto(resp("confirmada", 3.02, "A", "I-1", 0.02),
                             ev("liberada", 3.05, centro="A", ambulancia="AMB-01"),
                             resp("confirmada", 3.12, "B", "I-2", 0.02)))
    assert f["doble_asignacion"] == 0


def test_falta_evento_obligatorio_es_invalido():
    eventos = [e for e in esqueleto(resp("confirmada", 3.02, "A", "I-1", 0.02),
                                    resp("rechazada", 3.12, "B", "I-2", 0.02))
               if e["evento"] != "corte_fin"]
    f = clasificar(eventos)
    assert f["invalido"] == 1 and f["_faltan"] == ["corte_fin"]


def test_solicitud_sin_respuesta_es_invalido():
    f = clasificar(esqueleto(resp("confirmada", 3.02, "A", "I-1", 0.02)))
    assert f["invalido"] == 1
