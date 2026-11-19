"""Prueba de aceptación de la F2: inyector de fallas y latencia.

1. Con todo restaurado: IPs = tabla de topologia.py y netem en todas las
   interfaces de enlace.
2. Ping entre sitios conectados ≈ 40 ms; net_ctl y redes locales de sitio sin netem.
3. Cada enlace: cortado → el ping falla; restaurado → ≈ 40 ms, misma IP, netem aplicado.
4. Ciclo P4: varios cortes y restauraciones seguidos (cada 2 s); tras cada
   restauración, RTT ≈ 40 ms.
5. Aislamiento con P3: ningún contenedor alcanza a otro sitio por ninguna red,
   y ningún contenedor del sistema alcanza a otro por net_ctl (solo el orquestador).

Uso: python experimento/verificar_fallas.py --arq A1 [--ciclos-p4 5]
"""

import argparse
import sys
import time

import fallas
from fallas import en_paralelo, ping, redes_conectadas
from topologia import ARQUITECTURAS, ESCENARIOS, RED_CTL, Arquitectura

RTT_MIN, RTT_MAX = 38.0, 45.0      # "unos 40 ms" (2 × 20 ms de netem)
RTT_SIN_NETEM = 10.0               # net_ctl y redes de sitio: casi 0 ms

fallos: list[str] = []


def revisar(ok: bool, mensaje: str) -> bool:
    print(f"  [{'OK' if ok else 'FALLA'}] {mensaje}")
    if not ok:
        fallos.append(mensaje)
    return ok


def rtt_txt(rtt):
    return "sin respuesta" if rtt is None else f"{rtt:.1f} ms"


def pares_enlace(arq: Arquitectura, enlace: str) -> list[tuple[str, str, str]]:
    """(origen, destino, IP del destino en la red) para un enlace:
    del lado X que se corta hacia cada contenedor del sitio Y en esa red."""
    red = arq.redes_enlace[enlace]
    sitio_y = enlace[1].upper()
    return [(o, d, arq.ips[d][red]) for o in arq.lado_a_cortar(enlace)
            for d in arq.sitios[sitio_y] if red in arq.ips.get(d, {})]


def revisar_ips(arq: Arquitectura, momento: str) -> None:
    distintas = []
    for c in arq.contenedores():
        actuales = redes_conectadas(c)
        for red, ip in arq.ips[c].items():
            if actuales.get(red) != ip:
                distintas.append(f"{c}/{red}: esperada {ip}, actual {actuales.get(red)}")
    revisar(not distintas, f"IPs iguales a la tabla ({momento})" +
            ("" if not distintas else f": {distintas}"))


def revisar_netem(arq: Arquitectura, momento: str) -> None:
    problemas = fallas.verificar_netem(arq)
    revisar(not problemas, f"netem en todas las interfaces de enlace ({momento})" +
            ("" if not problemas else f": {problemas}"))


def revisar_enlace_arriba(arq, enlace, momento):
    for o, d, ip in pares_enlace(arq, enlace):
        rtt = ping(o, ip)
        revisar(rtt is not None and RTT_MIN <= rtt <= RTT_MAX,
                f"{enlace.upper()} {momento}: ping {o} → {d} ({ip}) = {rtt_txt(rtt)}")


def revisar_enlace_abajo(arq, enlace, momento):
    for o, d, ip in pares_enlace(arq, enlace):
        rtt = ping(o, ip, n=2)
        revisar(rtt is None, f"{enlace.upper()} {momento}: ping {o} → {d} ({ip}) falla "
                f"[{rtt_txt(rtt)}]")


def alcanzables(origen: str, ips: list[str]) -> list[str]:
    """IPs que `origen` logra alcanzar por ping (en paralelo dentro del contenedor).
    Para contenedores sin `ping` (postgres) se usa un contenedor auxiliar que
    comparte su espacio de red."""
    script = ("for ip in " + " ".join(ips) + "; do "
              "(ping -n -c 1 -W 1 $ip >/dev/null 2>&1 && echo $ip) & done; wait")
    if fallas.docker("exec", origen, "sh", "-c", "command -v ping", check=False).strip():
        salida = fallas.docker("exec", origen, "sh", "-c", script, check=False)
    else:
        salida = fallas.docker("run", "--rm", "--network", f"container:{origen}",
                               "--entrypoint", "sh", "banco/servicio:latest", "-c", script,
                               check=False)
    return salida.split()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arq", required=True, choices=sorted(ARQUITECTURAS))
    p.add_argument("--ciclos-p4", type=int, default=5)
    a = p.parse_args()
    arq = ARQUITECTURAS[a.arq]
    enlaces = list(arq.redes_enlace)

    print(f"== {arq.nombre}: enlaces existentes {[e.upper() for e in enlaces]}")
    print("\n1) Estado inicial (restaurar todo)")
    fallas.restaurar_todo(arq)
    revisar_ips(arq, "inicio")
    revisar_netem(arq, "inicio")

    print("\n2) Latencias con la red sana")
    for e in enlaces:
        revisar_enlace_arriba(arq, e, "sano")
    for c in arq.despachos.values():   # net_ctl: orquestador → despacho, sin netem
        ip = redes_conectadas(c)[RED_CTL]
        rtt = ping(None, ip)
        revisar(rtt is not None and rtt < RTT_SIN_NETEM,
                f"net_ctl sin netem: orquestador → {c} ({ip}) = {rtt_txt(rtt)}")
    for sitio, red in arq.redes_sitio.items():   # red local del sitio, sin netem
        miembros = [c for c in arq.sitios[sitio] if red in arq.ips[c]]
        o, d = miembros[0], miembros[1]
        rtt = ping(o, arq.ips[d][red])
        revisar(rtt is not None and rtt < RTT_SIN_NETEM,
                f"red local {red} sin netem: {o} → {d} = {rtt_txt(rtt)}")

    print("\n3) Cortar y restaurar cada enlace")
    for e in enlaces:
        fallas.cortar_enlace(arq, e)
        revisar_enlace_abajo(arq, e, "cortado")
        fallas.restaurar_enlace(arq, e)
        revisar_enlace_arriba(arq, e, "restaurado")
    revisar_ips(arq, "tras cortar/restaurar cada enlace")
    revisar_netem(arq, "tras cortar/restaurar cada enlace")

    print(f"\n4) Ciclo P4: {a.ciclos_p4} cortes y restauraciones seguidos (cada 2 s)")
    enlaces_p4 = [e for e in ESCENARIOS["P4"] if e in arq.redes_enlace]
    for i in range(1, a.ciclos_p4 + 1):
        t0 = time.monotonic()
        fallas.aplicar_corte(arq, "P4")
        print(f"  ciclo {i}: corte aplicado en {time.monotonic() - t0:.2f} s")
        for e in enlaces_p4:
            revisar_enlace_abajo(arq, e, f"P4 ciclo {i} cortado")
        time.sleep(max(0.0, 2.0 - (time.monotonic() - t0)))
        t1 = time.monotonic()
        fallas.restaurar_corte(arq, "P4")
        print(f"  ciclo {i}: restauración + netem en {time.monotonic() - t1:.2f} s")
        for e in enlaces_p4:
            revisar_enlace_arriba(arq, e, f"P4 ciclo {i} restaurado")
        time.sleep(max(0.0, 2.0 - (time.monotonic() - t1)))
    revisar_ips(arq, "tras el ciclo P4")
    revisar_netem(arq, "tras el ciclo P4")

    print("\n5) Aislamiento con P3 aplicado")
    fallas.aplicar_corte(arq, "P3")
    ip_ctl = {c: redes_conectadas(c).get(RED_CTL) for c in arq.contenedores()}

    def revisar_origen(origen):
        sitio = arq.sitio_de(origen)
        # (a) todas las IPs (en cualquier red, salvo net_ctl) de los otros sitios
        otros = [(d, red, ip) for d in arq.contenedores() if arq.sitio_de(d) != sitio
                 for red, ip in arq.ips[d].items()]
        # (b) las IPs en net_ctl de los demás contenedores del sistema
        ctl = [(d, RED_CTL, ip_ctl[d]) for d in arq.contenedores()
               if d != origen and ip_ctl[d]]
        objetivos = otros + ctl
        alcanzadas = set(alcanzables(origen, [ip for _, _, ip in objetivos]))
        return origen, len(otros), len(ctl), [x for x in objetivos if x[2] in alcanzadas]

    for origen, n_otros, n_ctl, fugas in en_paralelo(revisar_origen, arq.contenedores()):
        revisar(not fugas, f"{origen}: 0 de {n_otros} IPs de otros sitios y 0 de {n_ctl} "
                f"IPs de net_ctl alcanzables" + ("" if not fugas else f" — FUGAS: {fugas}"))
    # Controles positivos: el orquestador sigue viendo todo por net_ctl y las
    # redes locales de sitio no se cortan.
    for c, ip in ip_ctl.items():
        if ip:
            rtt = ping(None, ip)
            revisar(rtt is not None, f"orquestador → {c} por net_ctl durante P3 = {rtt_txt(rtt)}")
    for sitio, red in arq.redes_sitio.items():
        miembros = [c for c in arq.sitios[sitio] if red in arq.ips[c]]
        rtt = ping(miembros[0], arq.ips[miembros[1]][red])
        revisar(rtt is not None, f"red local {red} sigue arriba durante P3 = {rtt_txt(rtt)}")

    fallas.restaurar_todo(arq)
    print("\n6) Restauración final")
    for e in enlaces:
        revisar_enlace_arriba(arq, e, "final")
    revisar_ips(arq, "final")
    revisar_netem(arq, "final")

    print(f"\n{'APROBADA' if not fallos else 'REPROBADA'}: {len(fallos)} fallas")
    for f in fallos:
        print("  -", f)
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
