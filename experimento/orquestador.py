"""Orquestador del experimento.

Corre dentro del contenedor `orquestador` (en net_ctl, con el socket de Docker).

    python experimento/orquestador.py --arq A1,A2,A3 --escenarios P0,P1,P2,P3,P4 \\
        --rep 30 --sin-conflicto 10 --semilla 2026
    python experimento/orquestador.py --piloto          # 3 ensayos por celda
    python experimento/orquestador.py --p0              # prueba de latencia (M4)

Orden: para cada repetición y escenario, las tres arquitecturas seguidas, con
la misma semilla y en orden aleatorio (derivado de la semilla).
Reanudable: los ensayos cuyo log ya tiene `ensayo_fin` se saltan.

Línea de tiempo de un ensayo (t desde `ensayo_inicio`, tras la preparación):
    t=1   corte del escenario (`corte_inicio`)
    t=3   el centro "primero" pide AMB-01 para I-1
    t=3+δ si hay conflicto, el "segundo" pide AMB-01 para I-2
    t=21  restaurar + netem (`corte_fin`, registrado justo antes del connect)
    21–51 monitor cada 100 ms hasta estado consistente (`estado_consistente`/`no_recuperado`)
    luego: eventos de los servicios, reserva sin aviso, reinicios, `ensayo_fin`
"""

import argparse
import asyncio
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

import entorno
import etcd_admin
import fallas
import monitor
from clientes import liberar, solicitar
from comun.config import (AMBULANCIA_ENSAYO as AMB, CON_CONFLICTO, CONFIRMADA, DIR_LOGS,
                          RESERVADA, SIN_CONFLICTO)
from comun.logger import LoggerEnsayo, leer_jsonl, ruta_ensayo
from topologia import ARQUITECTURAS, ESCENARIOS, LIDER_LADO, Arquitectura

T_CORTE, T_SOLICITUD, T_RESTAURAR, T_FIN = 1.0, 3.0, 21.0, 51.0
PERIODO_P4 = 2.0
ESPERA_ESTABLE = 2.0           # paso 5 de la preparación
INTENTOS_PREPARACION = 3
INTENTOS_ENSAYO = 3            # un ensayo inválido se repite con la misma semilla
LIMITE_OPERACION_RED = 1.0     # s: un corte o una restauración (connect + netem) más lenta → inválido
ESPERA_ESTADO_FINAL = 5.0      # s: reintentos de la lectura del estado final; sin respuesta → inválido


# ====================================================================== plan

@dataclass
class Ensayo:
    arq: str
    escenario: str
    tipo: str
    rep: int
    n: int                     # número de archivo: rep (con conflicto) o 100 + rep (sin)
    semilla: int
    delta: float
    primero: str
    lado_lider: str | None     # solo A2-P1: "A" (etcd1) o "B" (etcd2)


def generar_plan(arqs, escenarios, n_rep, n_sin, piloto, semilla) -> list[Ensayo]:
    def cantidades(esc):
        if piloto:
            return (3, 0) if esc == "P0" else (2, 1)
        return (n_rep, 0) if esc == "P0" else (n_rep, n_sin)   # P0: solo con conflicto

    max_rep = max(max(cantidades(e)) for e in escenarios)
    plan = []
    for rep in range(max_rep):
        for esc in escenarios:
            n_con, n_sin_e = cantidades(esc)
            for tipo, limite in ((CON_CONFLICTO, n_con), (SIN_CONFLICTO, n_sin_e)):
                if rep >= limite:
                    continue
                s = random.Random(f"{semilla}-{esc}-{tipo}-{rep}").randrange(2**31)
                rng = random.Random(s)
                delta = rng.uniform(0, 0.200)               # misma δ para las 3 arquitecturas
                orden = list(arqs)
                rng.shuffle(orden)                          # orden aleatorio, según la semilla
                primero = "A" if rep % 2 == 0 else "B"
                lado = ("A" if (rep // 2) % 2 == 0 else "B") if esc == "P1" else None
                n = rep if tipo == CON_CONFLICTO else 100 + rep
                plan += [Ensayo(a, esc, tipo, rep, n, s, delta, primero, lado) for a in orden]
    return plan


def completo(ruta: Path) -> bool:
    return ruta.exists() and any(e["evento"] == "ensayo_fin" for e in leer_jsonl(ruta))


# ====================================================================== utilidades

async def dormir_hasta(t: float) -> None:
    await asyncio.sleep(max(0.0, t - time.time()))


def arranques(arq: Arquitectura) -> dict[str, str]:
    """Hora de arranque de cada contenedor (cambia si se reinicia)."""
    salida = fallas.docker("inspect", "-f", "{{.Name}} {{.State.StartedAt}} {{.RestartCount}}",
                           *arq.contenedores())
    return {l.split()[0].lstrip("/"): " ".join(l.split()[1:]) for l in salida.splitlines()}


async def ids_arranque(http, arq) -> dict[str, str]:
    """id_arranque de cada servicio (GET /admin/health)."""
    ids = {}
    for c in arq.reset:
        r = await http.get(f"{arq.url(c)}/admin/health", timeout=2)
        ids[c] = r.json()["id_arranque"]
    return ids


async def operacion_red(duraciones: list, op: str, funcion, *args):
    """Ejecuta un corte o una restauración y anota cuánto tardó en `duraciones`."""
    inicio = time.time()
    resultado = await asyncio.to_thread(funcion, *args)
    duraciones.append({"op": op, "t": inicio, "s": round(time.time() - inicio, 3)})
    return resultado


async def leer_estado_final(http, arq: Arquitectura, log) -> list | None:
    """GET /ambulancias de la fuente de estado para revisar la reserva sin aviso.
    Reintenta cada 200 ms (hasta ESPERA_ESTADO_FINAL) mientras no responda 200: en A2
    la réplica puede quedar sin quórum un instante después del estado consistente (503).
    Si hubo que reintentar, lo registra (`lectura_estado_final`). None si no se pudo."""
    codigos, datos = [], None
    fin = time.monotonic() + ESPERA_ESTADO_FINAL
    while True:
        try:
            r = await http.get(f"{arq.url(arq.fuente_estado)}/ambulancias", timeout=5)
            codigos.append(r.status_code)
            if r.status_code == 200:
                datos = r.json()
                break
        except (httpx.HTTPError, ValueError) as ex:
            codigos.append(type(ex).__name__)
        if time.monotonic() >= fin:
            break
        await asyncio.sleep(0.2)
    if len(codigos) > 1:
        log.evento("lectura_estado_final", intentos=len(codigos), codigos=codigos,
                   leido=datos is not None)
    return datos


def operaciones_lentas(duraciones: list, limite: float = LIMITE_OPERACION_RED) -> list[str]:
    """Motivos de invalidez: cada corte o restauración que tardó más de `limite` s."""
    return [f"{d['op']} tardó {d['s']:.2f} s (límite {limite:g} s)"
            for d in duraciones if d["s"] > limite]


def verificar_corte(arq: Arquitectura, enlaces: list[str]) -> tuple[bool, list[str]]:
    """Durante el corte, un ping entre los sitios cortados debe fallar."""
    pares = []
    for e in enlaces:
        red = arq.redes_enlace[e]
        for o in arq.lado_a_cortar(e):
            for d in arq.sitios[e[1].upper()]:
                if red in arq.ips.get(d, {}):
                    pares.append((o, arq.ips[d][red]))
    alcanzados = [f"{o}→{ip}" for (o, ip), rtt in
                  zip(pares, fallas.en_paralelo(lambda p: fallas.ping(p[0], p[1], n=1), pares))
                  if rtt is not None]
    return not alcanzados, alcanzados


# ====================================================================== preparación

async def preparar(http, arq: Arquitectura, e: Ensayo, contexto: dict):
    """Pasos 1–5. Devuelve (ok, info o motivo)."""
    motivo = ""
    for intento in range(1, INTENTOS_PREPARACION + 1):
        try:
            await asyncio.to_thread(fallas.restaurar_todo, arq)                  # 1
            for c in arq.reset:                                                  # 2
                r = await http.post(f"{arq.url(c)}/admin/reset", timeout=10,
                                    json={"ambulancias": [AMB], "contexto": contexto})
                r.raise_for_status()
            for centro in ("A", "B"):                                            # 3
                r = await http.get(f"{arq.url_despacho(centro)}/ambulancias", timeout=5)
                r.raise_for_status()
                amb = {a["id"]: a for a in r.json()}[AMB]
                if amb["estado"] != "disponible":
                    raise RuntimeError(f"{centro} ve {amb}")
            lider = None
            if arq.nombre == "A2":
                fin = time.monotonic() + 5
                while not await asyncio.to_thread(etcd_admin.misma_revision):
                    if time.monotonic() > fin:
                        raise RuntimeError("las 3 réplicas no tienen la misma revisión")
                    await asyncio.sleep(0.1)
                if e.lado_lider:                                                 # 4
                    destino = LIDER_LADO[e.lado_lider]
                    if not await asyncio.to_thread(etcd_admin.mover_lider, destino):
                        raise RuntimeError(f"no se pudo mover el líder a {destino}")
                lider = await asyncio.to_thread(etcd_admin.lider_actual)
            info = {"lider_preparado": lider, "intentos_preparacion": intento,
                    "ids": await ids_arranque(http, arq),
                    "arranques": await asyncio.to_thread(arranques, arq)}
            await asyncio.sleep(ESPERA_ESTABLE)                                  # 5
            return True, info
        except Exception as ex:                 # cualquier fallo: reintentar la preparación
            motivo = f"{type(ex).__name__}: {ex}"
            await asyncio.sleep(1)
    return False, motivo


# ====================================================================== ensayo

async def intermitente(arq, escenario, t0, ventanas, duraciones):
    """P4: el corte se restaura y se vuelve a aplicar cada 2 s hasta t = 21.
    Registra las ventanas con el enlace arriba: [inicio (antes del connect), fin]
    y la duración de cada operación en `duraciones`."""
    abajo, t = True, t0 + T_CORTE + PERIODO_P4
    while t < t0 + T_RESTAURAR - 0.01:
        await dormir_hasta(t)
        if abajo:
            ventanas.append([time.time(), None])
            await operacion_red(duraciones, "restauracion_p4", fallas.restaurar_corte, arq, escenario)
        else:
            await operacion_red(duraciones, "corte_p4", fallas.aplicar_corte, arq, escenario)
            ventanas[-1][1] = time.time()
        abajo, t = not abajo, t + PERIODO_P4


async def ejecutar(http, e: Ensayo, dir_logs: Path, intento: int) -> tuple[bool, str]:
    """Ejecuta un ensayo completo. Devuelve (válido, motivo)."""
    arq = ARQUITECTURAS[e.arq]
    log = LoggerEnsayo(dir_logs, e.arq, e.escenario, e.n, tipo=e.tipo)
    contexto = {"arq": e.arq, "escenario": e.escenario, "ensayo": e.n, "tipo": e.tipo}
    base = {"semilla": e.semilla, "rep": e.rep, "primero": e.primero, "delta": e.delta,
            "lado_lider": e.lado_lider, "intento": intento}

    ok, info = await preparar(http, arq, e, contexto)
    if not ok:
        log.evento("ensayo_inicio", **base)
        log.evento("ensayo_invalido", motivo=f"preparación: {info}")
        log.evento("ensayo_fin")
        log.cerrar()
        return False, f"preparación: {info}"

    t0 = time.time()
    log.evento("ensayo_inicio", t=t0, **base, lider_preparado=info["lider_preparado"],
               intentos_preparacion=info["intentos_preparacion"])
    es_a2 = arq.nombre == "A2"

    # ---- t = 1: corte
    await dormir_hasta(t0 + T_CORTE)
    lider = await asyncio.to_thread(etcd_admin.lider_actual) if es_a2 else None
    t_corte = time.time()
    duraciones: list = []                       # cada corte/restauración: {op, t, s}
    enlaces = await operacion_red(duraciones, "corte", fallas.aplicar_corte, arq, e.escenario)
    log.evento("corte_inicio", t=t_corte, enlaces=enlaces, lider=lider)
    verif = asyncio.create_task(asyncio.to_thread(verificar_corte, arq, enlaces))
    vig_lider = None
    if es_a2 and enlaces:
        # Momento en que el lado mayoritario (etcd1 + etcd3) tiene líder (para explicar M3)
        anterior = None if lider in ("etcd1", "etcd3") else lider
        vig_lider = asyncio.create_task(asyncio.to_thread(
            etcd_admin.esperar_nuevo_lider, ["etcd1", "etcd3"], anterior, t0 + T_RESTAURAR))
    ventanas: list = []
    flapeo = (asyncio.create_task(intermitente(arq, e.escenario, t0, ventanas, duraciones))
              if e.escenario == "P4" else None)

    # ---- t = 3 (+δ): solicitudes
    segundo = "B" if e.primero == "A" else "A"
    extra = {"lider": lider} if es_a2 else {}
    await dormir_hasta(t0 + T_SOLICITUD)
    tareas = [asyncio.create_task(solicitar(http, arq.url_despacho(e.primero), log,
                                            e.primero, "I-1", AMB, extra))]
    if e.tipo == CON_CONFLICTO:
        async def segunda():
            await asyncio.sleep(e.delta)
            return await solicitar(http, arq.url_despacho(segundo), log, segundo, "I-2", AMB, extra)
        tareas.append(asyncio.create_task(segunda()))
    respuestas = await asyncio.gather(*tareas)

    # ---- t = 21: restaurar
    await dormir_hasta(t0 + T_RESTAURAR)
    if flapeo:
        await flapeo
    corte_ok, alcanzados = await verif
    det = await vig_lider if vig_lider else None
    t_fin = time.time()                         # justo antes del connect
    await operacion_red(duraciones, "restauracion", fallas.restaurar_todo, arq)
    log.evento("corte_fin", t=t_fin, t_netem=time.time(), corte_verificado=corte_ok,
               alcanzados_durante_corte=alcanzados, ventanas_arriba_p4=ventanas,
               duraciones_red=duraciones,
               lider_mayoria=det[1] if det else None, t_lider_mayoria=det[0] if det else None)

    # ---- 21–51: monitor
    t_cons, obs = await monitor.vigilar(http, arq, hasta=t0 + T_FIN)
    if t_cons:
        log.evento("estado_consistente", t=t_cons, observado=obs)
    else:
        log.evento("no_recuperado", observado=obs)

    # ---- eventos propios de los servicios (liberada, revertida), con su t original
    for c in arq.reset:
        r = await http.get(f"{arq.url(c)}/admin/eventos", timeout=5)
        for ev in r.json():
            log.escribir(ev)

    # ---- reserva sin aviso: la unidad quedó reservada para un incidente cuyo
    #      cliente no recibió `confirmada` (se revisa en las 3 arquitecturas)
    estado_final = await leer_estado_final(http, arq, log)
    if estado_final is not None:
        final = {a["id"]: a for a in estado_final}.get(AMB, {})
        if final.get("estado") == RESERVADA:
            inc = final["incidente_asignado"]
            resp = next((x for x in respuestas if x["incidente"] == inc), None)
            if resp is None or resp["evento"] != CONFIRMADA:
                log.evento("reserva_sin_aviso", centro=resp["centro"] if resp else None,
                           incidente=inc, ambulancia=AMB,
                           respuesta_recibida=resp["evento"] if resp else None)

    # ---- validez
    motivos = []
    if estado_final is None:
        motivos.append(f"no se pudo leer el estado final en {ESPERA_ESTADO_FINAL:g} s "
                       "(revisión de reserva sin aviso)")
    if not corte_ok:
        motivos.append(f"el corte no se aplicó (alcanzados: {alcanzados})")
    motivos += operaciones_lentas(duraciones)
    try:
        if await ids_arranque(http, arq) != info["ids"] or \
                await asyncio.to_thread(arranques, arq) != info["arranques"]:
            motivos.append("algún contenedor se reinició durante el ensayo")
    except Exception as ex:
        motivos.append(f"no se pudo verificar reinicios: {ex}")
    if motivos:
        log.evento("ensayo_invalido", motivo="; ".join(motivos))
    log.evento("ensayo_fin")
    log.cerrar()
    return not motivos, "; ".join(motivos)


async def correr_ensayo(http, e: Ensayo, dir_logs: Path) -> str:
    """Salta si ya está completo; si sale inválido, lo repite con la misma semilla
    (hasta 3 veces). Los intentos inválidos se apartan como ensayo_<n>.invalido_<k>.jsonl."""
    ruta = ruta_ensayo(dir_logs, e.arq, e.escenario, e.n)
    if completo(ruta):
        return "saltado"
    ruta.unlink(missing_ok=True)                # intento interrumpido: se descarta
    previos = len(list(ruta.parent.glob(f"ensayo_{e.n}.invalido_*.jsonl")))
    for intento in range(previos + 1, INTENTOS_ENSAYO + 1):
        valido, motivo = await ejecutar(http, e, dir_logs, intento)
        if valido:
            return "ok"
        if intento < INTENTOS_ENSAYO:           # el último intento inválido se queda como resultado
            ruta.rename(ruta.with_name(f"ensayo_{e.n}.invalido_{intento}.jsonl"))
        print(f"      intento {intento} inválido: {motivo}", flush=True)
    return "INVÁLIDO"


def resumen_linea(ruta: Path) -> str:
    ev = leer_jsonl(ruta)
    resp = {x["centro"]: f"{x['evento']}({x['extra']['t_respuesta']:.2f}s)" for x in ev
            if x["evento"] in ("confirmada", "rechazada", "sin_confirmacion")}
    rev = sum(x["evento"] == "revertida" for x in ev)
    cf = next((x["t"] for x in ev if x["evento"] == "corte_fin"), None)
    ec = next((x["t"] for x in ev if x["evento"] == "estado_consistente"), None)
    rec = f"{ec - cf:.2f}s" if cf and ec else "no recuperado"
    return (f"A={resp.get('A', '-')} B={resp.get('B', '-')} rev={rev} "
            f"recuperación={rec}")


# ====================================================================== P0: latencia

async def prueba_latencia(http, nombre: str, dir_logs: Path, semilla: int) -> None:
    """50 reservas de calentamiento + 1 000 secuenciales alternando A y B,
    cada una seguida de `liberar`. En A2, tres bloques con el líder en etcd1,
    etcd2 y etcd3 (334/333/333), con 10 de calentamiento tras mover el líder.
    En A3 se espera `pendientes == 0` antes de cada reserva (M4 = reserva local)."""
    arq = ARQUITECTURAS[nombre]
    ruta = ruta_ensayo(dir_logs, nombre, "P0-latencia", 0)
    if completo(ruta):
        print(f"{nombre} P0-latencia: ya completo, se salta")
        return
    ruta.unlink(missing_ok=True)
    log = LoggerEnsayo(dir_logs, nombre, "P0-latencia", 0, tipo=None)
    contexto = {"arq": nombre, "escenario": "P0-latencia", "ensayo": 0, "tipo": None}
    await asyncio.to_thread(fallas.restaurar_todo, arq)
    for c in arq.reset:
        (await http.post(f"{arq.url(c)}/admin/reset", timeout=10,
                         json={"ambulancias": [AMB], "contexto": contexto})).raise_for_status()
    log.evento("ensayo_inicio", semilla=semilla)
    bloques = ([("etcd1", 334), ("etcd2", 333), ("etcd3", 333)] if nombre == "A2"
               else [(None, 1000)])
    k = 0

    async def una(calentamiento: bool, lider, bloque):
        nonlocal k
        centro = "A" if k % 2 == 0 else "B"
        await solicitar(http, arq.url_despacho(centro), log, centro, f"L-{k}", AMB,
                        {"lider": lider, "calentamiento": calentamiento, "bloque": bloque,
                         "indice": k})
        await liberar(http, arq.url_despacho(centro), AMB)
        if nombre == "A3":                      # esperar a que el otro centro sepa la liberación
            fin = time.monotonic() + 5
            while time.monotonic() < fin:
                pa, pb = await asyncio.gather(
                    http.get(f"{arq.url_despacho('A')}/admin/pendientes"),
                    http.get(f"{arq.url_despacho('B')}/admin/pendientes"))
                if pa.json()["pendientes"] == pb.json()["pendientes"] == 0:
                    break
                await asyncio.sleep(0.02)
        k += 1

    for _ in range(50):
        await una(True, None, None)
    for i, (lider, cantidad) in enumerate(bloques):
        if lider:
            if not await asyncio.to_thread(etcd_admin.mover_lider, lider):
                log.evento("ensayo_invalido", motivo=f"no se pudo mover el líder a {lider}")
                log.evento("ensayo_fin")
                return
            for _ in range(10):
                await una(True, lider, i)
        for j in range(cantidad):
            await una(False, lider, i)
            if (j + 1) % 100 == 0:
                print(f"  {nombre} bloque {i} ({lider or '-'}): {j + 1}/{cantidad}", flush=True)
    for c in arq.reset:
        for ev in (await http.get(f"{arq.url(c)}/admin/eventos", timeout=10)).json():
            log.escribir(ev)
    log.evento("ensayo_fin")
    conf = [x for x in leer_jsonl(ruta)
            if x["evento"] == "confirmada" and not x["extra"].get("calentamiento")]
    lat = sorted(x["extra"]["t_respuesta"] for x in conf)
    if lat:
        print(f"{nombre} P0-latencia: {len(conf)} confirmadas medidas; "
              f"p50={lat[len(lat) // 2] * 1000:.1f} ms  p95={lat[int(len(lat) * 0.95)] * 1000:.1f} ms")


# ====================================================================== main

async def principal(a) -> int:
    arqs = a.arq.split(",")
    dir_logs = Path(a.dir or (Path(DIR_LOGS).parent / "piloto" / "logs" if a.piloto else DIR_LOGS))
    # Registro del entorno (CPU, RAM de Docker, versiones) junto a los resultados
    ruta_entorno = dir_logs.parent / "entorno.json"
    e = await asyncio.to_thread(entorno.registrar, ruta_entorno, vars(a))
    print(f"Entorno → {ruta_entorno}: {e['cpu']['modelo']}, {e['cpu']['cpus_asignadas_a_docker']} CPU "
          f"y {e['ram_asignada_a_docker_gb']} GB para Docker; Docker {e['docker']['servidor']}, "
          f"etcd {e['etcd']}, {e['postgresql']}, Python {e['python']['orquestador']}; "
          f"tipo={e['tipo']}, commit={e['commit']}", flush=True)
    async with httpx.AsyncClient() as http:
        if a.p0:
            for nombre in arqs:
                await prueba_latencia(http, nombre, dir_logs, a.semilla)
            return 0
        plan = generar_plan(arqs, a.escenarios.split(","), a.rep, a.sin_conflicto,
                            a.piloto, a.semilla)
        hechos = sum(completo(ruta_ensayo(dir_logs, e.arq, e.escenario, e.n)) for e in plan)
        print(f"Plan: {len(plan)} ensayos ({hechos} ya completos) → {dir_logs}", flush=True)
        invalidos, t_inicio, ejecutados = 0, time.time(), 0
        for i, e in enumerate(plan, 1):
            t = time.time()
            estado = await correr_ensayo(http, e, dir_logs)
            if estado == "saltado":
                continue
            ejecutados += 1
            invalidos += estado == "INVÁLIDO"
            restantes = len(plan) - i
            eta = (time.time() - t_inicio) / ejecutados * restantes / 60
            ruta = ruta_ensayo(dir_logs, e.arq, e.escenario, e.n)
            print(f"[{i}/{len(plan)}] {e.arq} {e.escenario} {e.tipo:13s} rep={e.rep:2d} "
                  f"primero={e.primero} {estado:8s} {resumen_linea(ruta)}  "
                  f"({time.time() - t:.1f} s, faltan ~{eta:.0f} min)", flush=True)
        print(f"\nTerminado: {ejecutados} ensayos ejecutados, {invalidos} inválidos.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arq", default="A1,A2,A3")
    p.add_argument("--escenarios", default="P0,P1,P2,P3,P4")
    p.add_argument("--rep", type=int, default=30, help="ensayos con conflicto por celda")
    p.add_argument("--sin-conflicto", type=int, default=10, help="ensayos sin conflicto por celda")
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--piloto", action="store_true", help="3 ensayos por celda (en resultados/piloto)")
    p.add_argument("--p0", action="store_true", help="prueba de latencia sin falla (M4)")
    p.add_argument("--dir", help="carpeta de logs (por defecto resultados/logs)")
    sys.exit(asyncio.run(principal(p.parse_args())))


if __name__ == "__main__":
    main()
