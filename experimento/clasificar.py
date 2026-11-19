"""Clasificación de un ensayo a partir de sus eventos (una fila de resultados.csv).

Definiciones (Metricas.md):
- M1 doble asignación: dos `confirmada` de la misma ambulancia sin `liberada`
  entre ellas. Una confirmación revertida después cuenta igual.
- M2 válido a tiempo: exactamente una `confirmada` con t − t_solicitud ≤ 10 s
  y sin doble asignación.
- M3: t_respuesta de cada solicitud (medido por el cliente).
- M5: `estado_consistente` − `corte_fin`.
- M6: reversiones ÷ confirmaciones.
"""

from pathlib import Path

from comun.config import PLAZO_T
from comun.logger import leer_jsonl

RESPUESTAS = ("confirmada", "rechazada", "sin_confirmacion")
OBLIGATORIOS = ("ensayo_inicio", "corte_inicio", "corte_fin", "ensayo_fin")

COLUMNAS = ["arq", "escenario", "tipo", "rep", "semilla", "primero", "lider_inicial",
            "respuesta_a", "t_respuesta_a", "respuesta_b", "t_respuesta_b",
            "doble_asignacion", "valido_a_tiempo", "reversiones", "reserva_sin_aviso",
            "t_recuperacion", "invalido"]


def primero_de(eventos, nombre):
    return next((e for e in eventos if e["evento"] == nombre), None)


def hay_doble_asignacion(eventos) -> bool:
    """Recorre en orden temporal: una `confirmada` mientras la unidad sigue
    asignada por otra confirmación (sin `liberada` entre ambas) → doble."""
    vigentes: dict[str, int] = {}
    for e in sorted(eventos, key=lambda e: e["t"]):
        amb = e.get("ambulancia")
        if e["evento"] == "confirmada":
            vigentes[amb] = vigentes.get(amb, 0) + 1
            if vigentes[amb] >= 2:
                return True
        elif e["evento"] == "liberada":
            vigentes[amb] = 0
    return False


def clasificar(eventos: list[dict]) -> dict:
    eventos = sorted(eventos, key=lambda e: e["t"])
    ini = primero_de(eventos, "ensayo_inicio") or {"extra": {}}
    corte_ini = primero_de(eventos, "corte_inicio") or {"extra": {}}
    corte_fin = primero_de(eventos, "corte_fin")
    consistente = primero_de(eventos, "estado_consistente")
    base = ini if ini.get("arq") else (eventos[0] if eventos else {})

    respuestas = {e["centro"]: e for e in eventos if e["evento"] in RESPUESTAS}
    solicitudes = [e for e in eventos if e["evento"] == "solicitud"]
    confirmadas = [e for e in eventos if e["evento"] == "confirmada"]
    doble = hay_doble_asignacion(eventos)
    a_tiempo = [e for e in confirmadas if e["extra"].get("t_respuesta", 1e9) <= PLAZO_T]

    faltan = [n for n in OBLIGATORIOS if primero_de(eventos, n) is None]
    # Cada solicitud debe tener exactamente una respuesta
    resp_por_centro = {}
    for e in eventos:
        if e["evento"] in RESPUESTAS:
            resp_por_centro[e["centro"]] = resp_por_centro.get(e["centro"], 0) + 1
    respuestas_ok = all(resp_por_centro.get(s["centro"], 0) == 1 for s in solicitudes) \
        and len(resp_por_centro) == len(solicitudes)

    def resp(centro):
        e = respuestas.get(centro)
        return (e["evento"], round(e["extra"]["t_respuesta"], 4)) if e else ("", "")

    ra, ta = resp("A")
    rb, tb = resp("B")
    return {
        "arq": base.get("arq"), "escenario": base.get("escenario"), "tipo": base.get("tipo"),
        "rep": ini["extra"].get("rep"), "semilla": ini["extra"].get("semilla"),
        "primero": ini["extra"].get("primero"),
        "lider_inicial": corte_ini["extra"].get("lider") or "",
        "respuesta_a": ra, "t_respuesta_a": ta, "respuesta_b": rb, "t_respuesta_b": tb,
        "doble_asignacion": int(doble),
        "valido_a_tiempo": int(len(confirmadas) == 1 and len(a_tiempo) == 1 and not doble),
        "reversiones": sum(e["evento"] == "revertida" for e in eventos),
        "reserva_sin_aviso": sum(e["evento"] == "reserva_sin_aviso" for e in eventos),
        "t_recuperacion": (round(consistente["t"] - corte_fin["t"], 3)
                           if consistente and corte_fin else ""),
        "invalido": int(any(e["evento"] == "ensayo_invalido" for e in eventos)
                        or bool(faltan) or not respuestas_ok),
        # Columnas auxiliares (no van en resultados.csv)
        "_confirmadas": len(confirmadas),
        "_no_recuperado": int(primero_de(eventos, "no_recuperado") is not None),
        "_faltan": faltan,
        "_respuestas_ok": respuestas_ok,
    }


def leer_ensayos(dir_logs: str | Path) -> list[dict]:
    """Clasifica todos los ensayo_<n>.jsonl (no los intentos inválidos apartados)."""
    filas = []
    for ruta in sorted(Path(dir_logs).glob("*/*/ensayo_*.jsonl")):
        if ".invalido_" in ruta.name or ruta.parent.name == "P0-latencia":
            continue
        fila = clasificar(leer_jsonl(ruta))
        fila["_ruta"] = str(ruta)
        filas.append(fila)
    return filas


def intentos_invalidos(dir_logs: str | Path) -> list[Path]:
    return sorted(Path(dir_logs).glob("*/*/ensayo_*.invalido_*.jsonl"))
