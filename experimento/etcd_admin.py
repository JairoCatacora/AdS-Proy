"""Administración del clúster etcd de A2 desde el orquestador (por net_ctl).

Usa la API JSON de etcd, que expone los mismos RPC que `etcdctl`:
- `endpoint status`  → POST /v3/maintenance/status  (líder, revisión, término)
- `member list`      → POST /v3/cluster/member/list
- `move-leader`      → POST /v3/maintenance/transfer-leadership (al líder ACTUAL)
"""

import time

import httpx

from topologia import ETCD_A2

PUERTO_ETCD = 2379


def _url(miembro: str) -> str:
    return f"http://{ETCD_A2[miembro]}:{PUERTO_ETCD}"


def _post(miembro: str, ruta: str, cuerpo: dict | None = None, timeout: float = 1.0):
    r = httpx.post(f"{_url(miembro)}{ruta}", json=cuerpo or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ids_miembros() -> dict[str, str]:
    """{id del miembro: nombre} (los id de etcd son uint64; en JSON llegan como texto)."""
    for m in ETCD_A2:
        try:
            datos = _post(m, "/v3/cluster/member/list")
            return {str(x["ID"]): x["name"] for x in datos["members"]}
        except httpx.HTTPError:
            continue
    raise RuntimeError("ningún miembro de etcd responde")


def estado(miembro: str, timeout: float = 1.0) -> dict | None:
    """Estado de un miembro según él mismo, o None si no responde.
    {'lider': nombre o None, 'revision': int, 'termino': int, 'raft_index': int}"""
    try:
        d = _post(miembro, "/v3/maintenance/status", timeout=timeout)
    except httpx.HTTPError:
        return None
    nombres = ids_miembros_cache()
    lider = str(d.get("leader", "0"))
    return {
        "lider": nombres.get(lider),       # None si el miembro no conoce líder
        "revision": int(d["header"].get("revision", 0)),
        "termino": int(d.get("raftTerm", d["header"].get("raft_term", 0))),
        "raft_index": int(d.get("raftIndex", 0)),
    }


_cache_ids: dict[str, str] = {}


def ids_miembros_cache() -> dict[str, str]:
    """Los id de los miembros no cambian mientras el clúster vive: se guardan."""
    global _cache_ids
    if not _cache_ids:
        _cache_ids = ids_miembros()
    return _cache_ids


def estados() -> dict[str, dict | None]:
    return {m: estado(m) for m in ETCD_A2}


def lider_actual() -> str | None:
    """Líder en el que coinciden los miembros que responden (None si no hay acuerdo)."""
    vistos = {e["lider"] for e in estados().values() if e}
    return vistos.pop() if len(vistos) == 1 else None


def misma_revision() -> bool:
    """¿Los 3 miembros responden y tienen la misma revisión?"""
    es = estados().values()
    return all(es) and len({e["revision"] for e in es}) == 1


def mover_lider(destino: str, espera: float = 3.0) -> bool:
    """Transfiere el liderazgo a `destino` y verifica que se aplicó.

    `move-leader` debe enviarse al líder actual, así que primero se consulta
    quién es. Devuelve True si al final los 3 miembros reportan a `destino`."""
    actual = lider_actual()
    if actual is None:
        return False
    if actual != destino:
        id_destino = next(i for i, n in ids_miembros_cache().items() if n == destino)
        try:
            _post(actual, "/v3/maintenance/transfer-leadership",
                  {"targetID": id_destino}, timeout=espera)
        except httpx.HTTPError:
            return False
    # Verificar que los tres lo ven como líder
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if lider_actual() == destino and all(estados().values()):
            return True
        time.sleep(0.05)
    return False


def esperar_nuevo_lider(miembros: list[str], anterior: str | None, hasta: float,
                        intervalo: float = 0.05) -> tuple[float, str] | None:
    """Consulta `miembros` hasta que alguno reporte un líder distinto de
    `anterior` (y que esté entre `miembros`). Devuelve (time.time(), líder)
    del momento de la detección, o None si no ocurre antes de `hasta`."""
    while time.time() < hasta:
        for m in miembros:
            e = estado(m, timeout=0.3)
            if e and e["lider"] and e["lider"] != anterior and e["lider"] in miembros:
                return time.time(), e["lider"]
        time.sleep(intervalo)
    return None
