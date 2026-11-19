"""Diagnóstico de la recuperación lenta de A2 tras P1 (no forma parte del experimento).

Compara dos métodos de corte con la misma línea de tiempo que un ensayo:
- disconnect: `docker network disconnect/connect` (el método del experimento);
- iptables:   DROP de todo lo que ENTRA por la interfaz de la red de enlace, en los
              dos extremos (la interfaz no desaparece; netem sigue aplicado).

Durante el ensayo muestrea `ss -tino` en etcd2 (conexiones con los peers, puerto
2380: rto, backoff, timer de retransmisión, bytes sin confirmar) y al final
cruza los tiempos con los logs de etcd (rafthttp: streams perdidos/activos).

Uso: python experimento/investigar_a2.py --metodo disconnect|iptables [--n 2]
"""

import argparse
import asyncio
import json
import re
import subprocess
import threading
import time
from datetime import datetime

import httpx

import etcd_admin
import fallas
import monitor
from clientes import solicitar
from comun.config import AMBULANCIA_ENSAYO as AMB, DIR_LOGS
from comun.logger import LoggerEnsayo
from topologia import ARQUITECTURAS

ARQ = ARQUITECTURAS["A2"]
ENLACES_P1 = ["ab", "bd"]             # los enlaces de P1 que existen en A2


# ---------------------------------------------------------- corte con iptables

def interfaz(contenedor, red):
    ip = ARQ.ips[contenedor][red]
    return fallas.interfaces(contenedor)[ip]


def iptables(accion: str):
    """-I (cortar) o -D (restaurar) DROP en INPUT, en ambos extremos de cada enlace."""
    for e in ENLACES_P1:
        red = ARQ.redes_enlace[e]
        for c in ARQ.en_red(red):
            fallas.docker("exec", c, "iptables", accion, "INPUT", "-i", interfaz(c, red), "-j", "DROP")


def cortar(metodo):
    if metodo == "disconnect":
        fallas.aplicar_corte(ARQ, "P1")
    else:
        iptables("-I")


def restaurar(metodo):
    if metodo == "disconnect":
        fallas.restaurar_todo(ARQ)
    else:
        iptables("-D")


# ---------------------------------------------------------- muestreo de ss

def muestrear_ss(muestras, hasta, alto):
    """`ss -tino` en etcd2 para las conexiones con el puerto 2380 de los peers."""
    while time.time() < hasta and not alto.is_set():
        t = time.time()
        salida = fallas.docker("exec", "a2-etcd2", "ss", "-tino", "state", "established",
                               "( dport = :2380 or sport = :2380 )", check=False)
        conexiones = []
        lineas = salida.splitlines()[1:]
        for i in range(0, len(lineas) - 1, 2):
            cab, info = lineas[i].split(), lineas[i + 1]
            if len(cab) < 4:
                continue
            d = {"local": cab[2], "par": cab[3], "send_q": int(cab[1])}
            for clave in ("rto", "backoff", "unacked", "lastsnd", "lastrcv"):
                m = re.search(rf"\b{clave}:(\d+)", info + " " + lineas[i])
                if m:
                    d[clave] = int(m.group(1))
            m = re.search(r"timer:\((\w+),([\d.]+)(ms|sec|min),(\d+)\)", lineas[i] + info)
            if m:
                d["timer"] = f"{m.group(1)} {m.group(2)}{m.group(3)} reintentos={m.group(4)}"
            conexiones.append(d)
        muestras.append((t, conexiones))
        time.sleep(0.5)


# ---------------------------------------------------------- logs de etcd

PATRONES = ("lost TCP streaming", "established TCP streaming", "peer became active",
            "peer became inactive", "failed to dial", "failed to heartbeat",
            "read indexes queueing", "timed out waiting for read index", "leader changed")


def eventos_etcd(desde: float):
    res = []
    for c in ("a2-etcd1", "a2-etcd2", "a2-etcd3"):
        # docker logs entrega la salida de etcd por stderr
        r = subprocess.run(["docker", "logs", "--since", str(int(desde)), c],
                                         capture_output=True, text=True)
        for linea in (r.stdout + r.stderr).splitlines():
            try:
                d = json.loads(linea)
            except ValueError:
                continue
            if any(p in d.get("msg", "") for p in PATRONES):
                t = datetime.fromisoformat(d["ts"].replace("Z", "+00:00")).timestamp()
                quien = d.get("remote-peer-id") or d.get("stream-type") or ""
                res.append((t, c, d["msg"], quien))
    return sorted(res)


# ---------------------------------------------------------- ensayo

async def ensayo(http, metodo: str, n: int):
    nombres = etcd_admin.ids_miembros_cache()
    fallas.restaurar_todo(ARQ)
    assert etcd_admin.mover_lider("etcd1"), "no se pudo mover el líder a etcd1"
    for c in ARQ.reset:
        (await http.post(f"{ARQ.url(c)}/admin/reset", timeout=10,
                         json={"ambulancias": [AMB], "contexto": {"arq": "A2", "escenario": "P1",
                                                                  "ensayo": n, "tipo": "con_conflicto"}})).raise_for_status()
    await asyncio.sleep(2)
    log = LoggerEnsayo(f"{DIR_LOGS}/../investigacion", "A2", f"P1-{metodo}", n, tipo="con_conflicto")
    log.ruta.unlink(missing_ok=True)

    t0 = time.time()
    await asyncio.sleep(1)
    await asyncio.to_thread(cortar, metodo)
    await asyncio.sleep(2)
    await asyncio.gather(solicitar(http, ARQ.url_despacho("A"), log, "A", "I-1", AMB),
                         solicitar(http, ARQ.url_despacho("B"), log, "B", "I-2", AMB))
    muestras, alto = [], threading.Event()
    hilo = threading.Thread(target=muestrear_ss, args=(muestras, t0 + 51, alto))
    await asyncio.sleep(max(0, t0 + 19 - time.time()))
    hilo.start()
    await asyncio.sleep(max(0, t0 + 21 - time.time()))
    t_rest = time.time()
    await asyncio.to_thread(restaurar, metodo)
    t_listo = time.time()
    t_cons, _ = await monitor.vigilar(http, ARQ, hasta=t0 + 51)
    await asyncio.sleep(1)
    alto.set()
    hilo.join()
    m5 = t_cons - t_rest if t_cons else None

    print(f"\n=== {metodo} ensayo {n}: M5 = {m5 if m5 is None else round(m5, 2)} s "
          f"(restauración {t_listo - t_rest:.2f} s)")
    print("  ss -tino en etcd2 (conexiones con peers :2380), t relativo a la restauración:")
    for t, cs in muestras:
        if t < t_rest - 1.5 or t > t_rest + 14:
            continue
        resumen = "; ".join(
            f"{c['local'].split(':')[0][-5:]}→{c['par']} sendq={c['send_q']} rto={c.get('rto')} "
            f"backoff={c.get('backoff', 0)} {c.get('timer', '')}"
            for c in cs if c["send_q"] or c.get("backoff"))
        print(f"   {t - t_rest:+6.2f} s  {resumen or 'sin datos pendientes ni backoff'}")
    print("  logs de etcd (rafthttp), t relativo a la restauración:")
    for t, c, msg, quien in eventos_etcd(t0):
        if t >= t0 + 0.5:
            nombre = nombres.get(str(int(quien, 16))) if re.fullmatch(r"[0-9a-f]+", quien or "") else quien
            print(f"   {t - t_rest:+6.2f} s  {c:9s} {msg} {nombre or quien}")
    return m5


async def principal(metodo, n):
    async with httpx.AsyncClient() as http:
        return [await ensayo(http, metodo, i) for i in range(n)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--metodo", choices=["disconnect", "iptables"], required=True)
    p.add_argument("--n", type=int, default=2)
    a = p.parse_args()
    m5 = asyncio.run(principal(a.metodo, a.n))
    print(f"\nM5 con {a.metodo}: {[round(x, 2) if x else None for x in m5]}")


if __name__ == "__main__":
    main()
