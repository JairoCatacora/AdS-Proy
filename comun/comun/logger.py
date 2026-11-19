"""Logger de eventos en formato JSONL (una línea JSON por evento).

Ruta de cada ensayo: <DIR_LOGS>/<arq>/<escenario>/ensayo_<n>.jsonl

Decisión: solo el orquestador escribe archivos. Los servicios guardan sus
eventos propios (p. ej. `revertida`, `liberada`) en un `BufferEventos` en
memoria y el orquestador los recoge por net_ctl. Así ningún archivo tiene
dos procesos escribiendo a la vez a través del volumen de Docker Desktop.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from comun.config import EVENTOS


def crear_evento(
    evento: str,
    *,
    ensayo: Optional[int] = None,
    arq: Optional[str] = None,
    escenario: Optional[str] = None,
    tipo: Optional[str] = None,
    centro: Optional[str] = None,
    incidente: Optional[str] = None,
    ambulancia: Optional[str] = None,
    t: Optional[float] = None,
    **extra: Any,
) -> dict:
    """Construye un evento con el formato de la sección 6.

    `t` es `time.time()` (todos los contenedores comparten el reloj del host).
    Los campos adicionales van dentro de `extra`.
    """
    if evento not in EVENTOS:
        raise ValueError(f"Evento desconocido: {evento!r}")
    return {
        "t": time.time() if t is None else t,
        "ensayo": ensayo,
        "arq": arq,
        "escenario": escenario,
        "tipo": tipo,
        "centro": centro,
        "incidente": incidente,
        "ambulancia": ambulancia,
        "evento": evento,
        "extra": extra,
    }


def ruta_ensayo(dir_logs: str | Path, arq: str, escenario: str, ensayo: int) -> Path:
    """Ruta del archivo de un ensayo."""
    return Path(dir_logs) / arq / escenario / f"ensayo_{ensayo}.jsonl"


class LoggerEnsayo:
    """Escribe los eventos de un ensayo en su archivo JSONL.

    Rellena automáticamente ensayo, arq, escenario y tipo. Es seguro usarlo
    desde varios hilos (los clientes simulados corren en paralelo).
    """

    def __init__(self, dir_logs: str | Path, arq: str, escenario: str,
                 ensayo: int, tipo: Optional[str] = None):
        self.arq, self.escenario, self.ensayo, self.tipo = arq, escenario, ensayo, tipo
        self.ruta = ruta_ensayo(dir_logs, arq, escenario, ensayo)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        self._archivo = None     # se abre en la primera escritura y queda abierto

    def evento(self, evento: str, **campos: Any) -> dict:
        """Registra un evento nuevo y lo devuelve."""
        datos = crear_evento(evento, ensayo=self.ensayo, arq=self.arq,
                             escenario=self.escenario, tipo=self.tipo, **campos)
        self.escribir(datos)
        return datos

    def escribir(self, datos: dict) -> None:
        """Agrega un evento ya construido (p. ej. uno recogido de un servicio)."""
        linea = json.dumps(datos, ensure_ascii=False) + "\n"
        # El archivo queda abierto durante el ensayo y no se hace fsync: en el volumen
        # montado desde Windows, abrir + fsync bloqueaba ~8 ms (hasta 50 ms) el bucle
        # del orquestador por evento, y ese tiempo se sumaba a M3 medido por el cliente.
        # Con el archivo abierto, escribir + flush cuesta ~0,1 ms. El fsync no hace
        # falta para reanudar: un ensayo sin `ensayo_fin` se borra y se repite.
        with self._candado:
            if self._archivo is None:
                self._archivo = open(self.ruta, "a", encoding="utf-8")
            self._archivo.write(linea)
            self._archivo.flush()

    def cerrar(self) -> None:
        with self._candado:
            if self._archivo is not None:
                self._archivo.close()
                self._archivo = None

    def __del__(self):
        try:
            self.cerrar()
        except Exception:
            pass


class BufferEventos:
    """Eventos en memoria de un servicio, a la espera de que el orquestador
    los recoja (GET /admin/eventos)."""

    def __init__(self):
        self._eventos: list[dict] = []
        self._candado = threading.Lock()

    def agregar(self, evento: str, **campos: Any) -> dict:
        datos = crear_evento(evento, **campos)
        with self._candado:
            self._eventos.append(datos)
        return datos

    def copiar(self) -> list[dict]:
        """Devuelve una copia de los eventos sin vaciar el buffer."""
        with self._candado:
            return list(self._eventos)

    def vaciar(self) -> list[dict]:
        """Devuelve los eventos acumulados y deja el buffer vacío."""
        with self._candado:
            eventos, self._eventos = self._eventos, []
        return eventos


def leer_jsonl(ruta: str | Path) -> list[dict]:
    """Lee un archivo JSONL. Ignora líneas vacías y una última línea
    incompleta (puede quedar así si el orquestador se interrumpe)."""
    eventos = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                eventos.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
    return eventos
