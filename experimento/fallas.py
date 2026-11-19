"""Inyector de fallas y latencia.

- Cortar el enlace X–Y: desconectar de net_xy los contenedores del sitio X
  (la red solo contiene X e Y, así que con eso basta).
- Restaurar: `docker network connect --ip <IP original>`, para que cada
  contenedor recupere exactamente la misma IP (A1 y etcd dependen de ellas).
- Latencia: 20 ms por sentido con `tc qdisc replace ... netem delay 20ms` en
  las interfaces de las redes de ENLACE (nunca en net_ctl ni en las redes
  locales de sitio). Al reconectar se crea una interfaz nueva, así que netem
  se vuelve a aplicar después de cada restauración.

Uso desde el orquestador:
    python experimento/fallas.py estado    --arq A1
    python experimento/fallas.py cortar    --arq A1 --escenario P3
    python experimento/fallas.py restaurar --arq A1
"""

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from topologia import ARQUITECTURAS, ESCENARIOS, Arquitectura

RETARDO = "20ms"


class ErrorFallas(RuntimeError):
    pass


def docker(*args: str, check: bool = True) -> str:
    """Ejecuta un comando del CLI de Docker y devuelve su salida."""
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise ErrorFallas(f"docker {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def en_paralelo(funcion, elementos) -> list:
    elementos = list(elementos)
    if not elementos:
        return []
    with ThreadPoolExecutor(max_workers=len(elementos)) as ex:
        return list(ex.map(funcion, elementos))


# ---------------------------------------------------------------- consulta

def redes_conectadas(contenedor: str) -> dict[str, str]:
    """{red: IP} de las redes a las que el contenedor está conectado ahora."""
    salida = docker("inspect", "-f", "{{json .NetworkSettings.Networks}}", contenedor)
    return {red: datos["IPAddress"] for red, datos in json.loads(salida).items()}


def interfaces(contenedor: str) -> dict[str, str]:
    """{IP: interfaz} dentro del contenedor, leído con `ip -o addr`."""
    salida = docker("exec", contenedor, "ip", "-o", "-4", "addr", "show")
    res = {}
    for linea in salida.splitlines():
        # p. ej. "52: eth1@if53    inet 10.1.13.10/24 brd ..."
        m = re.match(r"\d+:\s+([\w.-]+?)(?:@\S+)?\s+inet\s+([\d.]+)/", linea)
        if m:
            res[m.group(2)] = m.group(1)
    return res


def interfaces_de_enlace(arq: Arquitectura, contenedor: str) -> dict[str, str]:
    """{red de enlace: interfaz} de las redes de enlace conectadas ahora."""
    enlaces = set(arq.redes_enlace.values())
    conectadas = {red: ip for red, ip in redes_conectadas(contenedor).items() if red in enlaces}
    if not conectadas:
        return {}      # p. ej. postgres: solo está en la red local de su sitio
    ip_a_if = interfaces(contenedor)
    return {red: ip_a_if[ip] for red, ip in conectadas.items() if ip in ip_a_if}


# ---------------------------------------------------------------- latencia

def aplicar_netem(arq: Arquitectura, contenedor: str) -> list[str]:
    """Aplica netem en todas las interfaces de enlace del contenedor."""
    ifs = sorted(interfaces_de_enlace(arq, contenedor).values())
    if ifs:
        cmd = "; ".join(f"tc qdisc replace dev {i} root netem delay {RETARDO}" for i in ifs)
        docker("exec", contenedor, "sh", "-c", cmd)
    return ifs


def problemas_netem(arq: Arquitectura, contenedor: str) -> list[str]:
    """Lista de interfaces de enlace SIN netem (vacía = todo bien)."""
    problemas = []
    for red, iface in interfaces_de_enlace(arq, contenedor).items():
        q = docker("exec", contenedor, "tc", "qdisc", "show", "dev", iface)
        if f"netem" not in q or f"delay {RETARDO}" not in q:
            problemas.append(f"{contenedor}:{iface} ({red}) sin netem: {q.strip()}")
    return problemas


def verificar_netem(arq: Arquitectura) -> list[str]:
    return [p for ps in en_paralelo(lambda c: problemas_netem(arq, c), arq.contenedores())
            for p in ps]


# ---------------------------------------------------------------- cortes

def cortar_enlace(arq: Arquitectura, enlace: str) -> list[str]:
    """Corta X–Y. Devuelve los contenedores desconectados."""
    if enlace not in arq.redes_enlace:
        return []                      # el enlace no existe en esta arquitectura: se ignora
    red = arq.redes_enlace[enlace]

    def desconectar(c):
        if red in redes_conectadas(c):
            docker("network", "disconnect", red, c)
            return c
    return [c for c in en_paralelo(desconectar, arq.lado_a_cortar(enlace)) if c]


def restaurar_enlace(arq: Arquitectura, enlace: str) -> list[str]:
    """Reconecta con la IP original y vuelve a aplicar netem.
    Devuelve los contenedores reconectados."""
    if enlace not in arq.redes_enlace:
        return []
    red = arq.redes_enlace[enlace]

    def reconectar(c):
        if red not in redes_conectadas(c):
            docker("network", "connect", "--ip", arq.ips[c][red], red, c)
            aplicar_netem(arq, c)      # la interfaz es nueva: netem otra vez
            return c
    return [c for c in en_paralelo(reconectar, arq.lado_a_cortar(enlace)) if c]


def aplicar_corte(arq: Arquitectura, escenario: str) -> list[str]:
    """Corta a la vez todos los enlaces del escenario que existen en `arq`."""
    enlaces = [e for e in ESCENARIOS[escenario] if e in arq.redes_enlace]
    en_paralelo(lambda e: cortar_enlace(arq, e), enlaces)
    return enlaces


def restaurar_corte(arq: Arquitectura, escenario: str) -> list[str]:
    enlaces = [e for e in ESCENARIOS[escenario] if e in arq.redes_enlace]
    en_paralelo(lambda e: restaurar_enlace(arq, e), enlaces)
    return enlaces


def restaurar_todo(arq: Arquitectura) -> None:
    """Preparación del ensayo: todos los enlaces arriba y netem en todas las
    interfaces de enlace (también las que no se cortaron)."""
    en_paralelo(lambda e: restaurar_enlace(arq, e), list(arq.redes_enlace))
    en_paralelo(lambda c: aplicar_netem(arq, c), arq.contenedores())


# ---------------------------------------------------------------- pruebas

def ping(origen: str | None, ip: str, n: int = 5, espera: float = 1.0) -> float | None:
    """RTT en ms (mediana de las respuestas) desde `origen` hacia `ip`, o None
    si no hay respuesta. Con origen=None el ping sale del propio orquestador.

    Se usa la mediana y no el promedio: el primer paquete hacia una interfaz
    recién conectada incluye la resolución ARP, que también pasa por netem
    (≈ 80 ms), y sesgaría el promedio."""
    cmd = ["ping", "-n", "-c", str(n), "-i", "0.2", "-W", str(espera), ip]
    if origen is None:
        salida = subprocess.run(cmd, capture_output=True, text=True).stdout
    else:
        salida = docker("exec", origen, *cmd, check=False)
    tiempos = sorted(float(t) for t in re.findall(r"time=([\d.]+) ms", salida))
    return tiempos[len(tiempos) // 2] if tiempos else None


def estado(arq: Arquitectura) -> dict:
    """Para cada contenedor: redes conectadas con su IP."""
    return {c: redes_conectadas(c) for c in arq.contenedores()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("accion", choices=["estado", "cortar", "restaurar"])
    p.add_argument("--arq", required=True, choices=sorted(ARQUITECTURAS))
    p.add_argument("--escenario", choices=sorted(ESCENARIOS))
    a = p.parse_args()
    arq = ARQUITECTURAS[a.arq]
    if a.accion == "cortar":
        print("Enlaces cortados:", aplicar_corte(arq, a.escenario))
    elif a.accion == "restaurar":
        restaurar_todo(arq)
        print("Todo restaurado. Problemas de netem:", verificar_netem(arq) or "ninguno")
    for c, redes in estado(arq).items():
        print(f"  {c:18s} {redes}")


if __name__ == "__main__":
    main()
