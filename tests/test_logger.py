"""Pruebas unitarias del logger JSONL (aceptación de la F0)."""

import json
import threading
import time

import pytest

from comun.config import EVENTOS
from comun.logger import (BufferEventos, LoggerEnsayo, crear_evento, leer_jsonl,
                          ruta_ensayo)

CAMPOS = {"t", "ensayo", "arq", "escenario", "tipo", "centro", "incidente",
          "ambulancia", "evento", "extra"}


def test_evento_tiene_el_formato_de_la_seccion_6():
    antes = time.time()
    ev = crear_evento("confirmada", ensayo=17, arq="A2", escenario="P1",
                      tipo="con_conflicto", centro="A", incidente="I-1",
                      ambulancia="AMB-01", lider="etcd3")
    assert set(ev) == CAMPOS
    assert antes <= ev["t"] <= time.time()          # usa time.time()
    assert ev["extra"] == {"lider": "etcd3"}       # campos extra van en `extra`
    assert ev["evento"] == "confirmada"


def test_evento_desconocido_se_rechaza():
    with pytest.raises(ValueError):
        crear_evento("confirmado")  # error de tipeo


def test_lista_de_eventos_incluye_liberada():
    assert "liberada" in EVENTOS
    assert len(EVENTOS) == 14


def test_ruta_del_ensayo(tmp_path):
    assert ruta_ensayo(tmp_path, "A1", "P3", 5) == tmp_path / "A1" / "P3" / "ensayo_5.jsonl"


def test_logger_escribe_una_linea_json_por_evento(tmp_path):
    log = LoggerEnsayo(tmp_path, "A3", "P1", 2, tipo="sin_conflicto")
    log.evento("ensayo_inicio", semilla=2026)
    log.evento("solicitud", centro="B", incidente="I-1", ambulancia="AMB-01")
    lineas = log.ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    primero = json.loads(lineas[0])
    assert primero["arq"] == "A3" and primero["escenario"] == "P1"
    assert primero["ensayo"] == 2 and primero["tipo"] == "sin_conflicto"
    assert primero["extra"] == {"semilla": 2026}
    assert json.loads(lineas[1])["centro"] == "B"


def test_logger_agrega_sin_borrar_lo_anterior(tmp_path):
    LoggerEnsayo(tmp_path, "A1", "P1", 0).evento("ensayo_inicio")
    LoggerEnsayo(tmp_path, "A1", "P1", 0).evento("ensayo_fin")
    eventos = leer_jsonl(ruta_ensayo(tmp_path, "A1", "P1", 0))
    assert [e["evento"] for e in eventos] == ["ensayo_inicio", "ensayo_fin"]


def test_escritura_concurrente_no_mezcla_lineas(tmp_path):
    log = LoggerEnsayo(tmp_path, "A2", "P4", 1)

    def escribir(centro):
        for i in range(200):
            log.evento("solicitud", centro=centro, incidente=f"I-{i}")

    hilos = [threading.Thread(target=escribir, args=(c,)) for c in "AB"]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    eventos = leer_jsonl(log.ruta)
    assert len(eventos) == 400
    assert sum(e["centro"] == "A" for e in eventos) == 200


def test_escribir_evento_ya_construido_conserva_su_t(tmp_path):
    log = LoggerEnsayo(tmp_path, "A3", "P1", 3)
    ev = crear_evento("revertida", t=123.456, centro="B", ensayo=3)
    log.escribir(ev)
    assert leer_jsonl(log.ruta)[0]["t"] == 123.456


def test_leer_ignora_linea_final_incompleta(tmp_path):
    ruta = tmp_path / "ensayo_0.jsonl"
    ruta.write_text('{"evento": "ensayo_inicio"}\n\n{"evento": "solic', encoding="utf-8")
    assert leer_jsonl(ruta) == [{"evento": "ensayo_inicio"}]


def test_buffer_de_eventos_se_vacia_al_leer():
    buf = BufferEventos()
    buf.agregar("revertida", centro="B", incidente="I-2", ambulancia="AMB-01")
    buf.agregar("liberada", centro="A", ambulancia="AMB-01")
    eventos = buf.vaciar()
    assert [e["evento"] for e in eventos] == ["revertida", "liberada"]
    assert buf.vaciar() == []
