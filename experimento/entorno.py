"""Registro del entorno de ejecución (para la tabla del paper).

Se llama al inicio de cada corrida del orquestador y guarda <salida>/entorno.json:
CPU, RAM asignada a Docker, versiones de Docker, etcd, PostgreSQL y Python, y las
imágenes usadas. Cada arranque posterior (p. ej. la F7 después de la P0, o una
reanudación) se agrega en "entradas_posteriores" (así queda registrado si algo
cambió a mitad de la corrida).

Cada entrada lleva:
  tipo    "p0" (--p0), "corrida" (primer arranque de una corrida) o "reanudacion"
          (ya había una entrada "corrida" o "reanudacion" en el mismo archivo).
  commit  hash de git del código; el contenedor no ve .git, así que se pasa al
          lanzarlo: docker exec -e COMMIT=<git rev-parse HEAD> orquestador ...

Se ejecuta dentro del contenedor del orquestador: la CPU se lee de /proc/cpuinfo
(la VM de Docker Desktop ve el procesador del equipo) y la RAM es la que Docker
Desktop asigna a su VM, que es lo que realmente usan los contenedores.
"""

import json
import os
import platform
import subprocess
import time
from pathlib import Path

import httpx


def _cmd(*args: str) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip()
    except Exception as ex:
        return f"no disponible: {ex}"


def _cpu() -> dict:
    modelo, nucleos = "", 0
    try:
        for linea in Path("/proc/cpuinfo").read_text().splitlines():
            if linea.startswith("model name") and not modelo:
                modelo = linea.split(":", 1)[1].strip()
            if linea.startswith("processor"):
                nucleos += 1
    except OSError:
        pass
    return {"modelo": modelo, "cpus_visibles_en_docker": nucleos}


def recopilar() -> dict:
    info = json.loads(_cmd("docker", "info", "--format", "{{json .}}") or "{}")
    version = json.loads(_cmd("docker", "version", "--format", "{{json .}}") or "{}")
    try:
        etcd = httpx.post("http://a2-etcd1:2379/v3/maintenance/status", json={}, timeout=3).json()
        version_etcd = etcd.get("version")
    except Exception as ex:
        version_etcd = f"no disponible: {ex}"
    imagenes = {}
    for img in ("banco/servicio:latest", "banco/etcd:3.5.36", "banco/orquestador:latest",
                "postgres:16"):
        imagenes[img] = _cmd("docker", "image", "inspect", "-f", "{{.Id}}", img)
    return {
        "registrado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cpu": _cpu() | {"cpus_asignadas_a_docker": info.get("NCPU")},
        "ram_asignada_a_docker_gb": round(info.get("MemTotal", 0) / 2**30, 2),
        "docker": {
            "servidor": version.get("Server", {}).get("Version"),
            "cliente": version.get("Client", {}).get("Version"),
            "sistema": info.get("OperatingSystem"),
            "kernel": info.get("KernelVersion"),
        },
        "etcd": version_etcd,
        "postgresql": _cmd("docker", "exec", "a1-postgres", "postgres", "--version"),
        "python": {
            "orquestador": platform.python_version(),
            "servicios": _cmd("docker", "exec", "a1-despacho-a", "python", "--version"),
        },
        "imagenes": imagenes,
        "nota": "El sistema operativo y el modelo del equipo anfitrión (Windows) no son "
                "visibles desde Docker; agregarlos a mano en la tabla del paper.",
    }


def tipo_entrada(previos: dict | None, parametros: dict) -> str:
    """'p0', 'corrida' o 'reanudacion', según los parámetros y lo ya registrado."""
    if parametros.get("p0"):
        return "p0"
    entradas = [] if previos is None else [previos, *previos.get("entradas_posteriores", []),
                                           *previos.get("reanudaciones", [])]   # formato anterior
    hubo_corrida = any(x.get("tipo") in ("corrida", "reanudacion") for x in entradas)
    return "reanudacion" if hubo_corrida else "corrida"


def registrar(ruta: Path, parametros: dict) -> dict:
    """Escribe entorno.json; si ya existe, agrega la entrada en "entradas_posteriores"."""
    previos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
    actual = {"tipo": tipo_entrada(previos, parametros),
              "commit": os.environ.get("COMMIT") or "no indicado"} \
        | recopilar() | {"parametros": parametros}
    if previos is not None:
        datos = previos
        datos.setdefault("entradas_posteriores", []).append(actual)
    else:
        datos = actual
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return actual


if __name__ == "__main__":
    print(json.dumps(recopilar(), indent=2, ensure_ascii=False))
