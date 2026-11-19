"""Análisis: lee los logs y genera tablas, hipótesis y figuras.

    python experimento/analizar.py                                   # corrida completa
    python experimento/analizar.py --dir resultados/piloto/logs --salida resultados/piloto \\
        --dir-p0 resultados/logs                                     # piloto

Genera en --salida:
    resultados.csv            una fila por ensayo (sección 8)
    tabla_principal.csv       M1 y M2 por arquitectura × escenario, con IC de Wilson 95 %
    metricas_secundarias.csv  M3, M5, M6, reservas sin aviso y descartados por celda
    m4.csv                    M4 en P0, total y (en A2) por posición del líder
    hipotesis.md              H1–H4: valor medido y si se cumple
    figuras/F4..F7.png        300 dpi; se entienden sin color (etiquetas y tramas)

Solo los ensayos válidos entran en las métricas. Los ensayos inválidos quedan en
resultados.csv (columna `invalido`) y se cuentan en metricas_secundarias.csv.
"""

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import fisher_exact, mannwhitneyu  # noqa: E402

from clasificar import COLUMNAS, intentos_invalidos, leer_ensayos  # noqa: E402
from comun.config import DIR_LOGS  # noqa: E402
from comun.logger import leer_jsonl  # noqa: E402

ARQS = ["A1", "A2", "A3"]
ESCENARIOS = ["P0", "P1", "P2", "P3", "P4"]
NOMBRES = {"A1": "A1 centralizada", "A2": "A2 quórum", "A3": "A3 local"}

# Paleta categórica validada (slots 1–3, todos los pares) + trama por arquitectura,
# para que las figuras se entiendan sin color (y en impresión en blanco y negro).
COLOR = {"A1": "#2a78d6", "A2": "#eb6834", "A3": "#1baf7a"}
TRAMA = {"A1": "", "A2": "///", "A3": "..."}
LINEA = {"A1": "-", "A2": "--", "A3": ":"}
MARCADOR = {"A1": "o", "A2": "s", "A3": "^"}
TINTA, TINTA_2, REJILLA = "#0b0b0b", "#52514e", "#e4e3df"
SECUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


# ====================================================================== estadística

def wilson(k: int, n: int, z: float = 1.96):
    """Proporción e intervalo de confianza de Wilson al 95 %."""
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (p, max(0.0, centro - margen), min(1.0, centro + margen))


def pct(xs, q):
    return float(np.percentile(xs, q)) if len(xs) else math.nan


def fmt_pct(p, lo=None, hi=None):
    if p is None or math.isnan(p):
        return "sin datos"
    s = f"{p * 100:.1f} %"
    return s if lo is None else f"{s} [IC 95 %: {lo * 100:.1f}–{hi * 100:.1f} %]"


def fmt_s(x, ms=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "sin datos"
    return f"{x * 1000:.1f} ms" if ms else f"{x:.2f} s"


# ====================================================================== cálculo

def calcular(filas):
    """Métricas por (arq, escenario) con los ensayos válidos."""
    celdas = defaultdict(list)
    for f in filas:
        if not f["invalido"]:
            celdas[(f["arq"], f["escenario"])].append(f)

    res = {}
    for clave, fs in celdas.items():
        con = [f for f in fs if f["tipo"] == "con_conflicto"]
        dobles = sum(f["doble_asignacion"] for f in con)
        validos = sum(f["valido_a_tiempo"] for f in fs)
        m3 = [float(f[c]) for f in fs for c in ("t_respuesta_a", "t_respuesta_b") if f[c] != ""]
        m5 = [float(f["t_recuperacion"]) for f in fs if f["t_recuperacion"] != ""]
        confirmaciones = sum(f["_confirmadas"] for f in fs)
        reversiones = sum(f["reversiones"] for f in fs)
        res[clave] = {
            "n_conflicto": len(con), "dobles": dobles, "M1": wilson(dobles, len(con)),
            "n_total": len(fs), "validos": validos, "M2": wilson(validos, len(fs)),
            "M3": m3, "M5": m5, "no_recuperados": sum(f["_no_recuperado"] for f in fs),
            "confirmaciones": confirmaciones, "reversiones": reversiones,
            "M6": wilson(reversiones, confirmaciones),
            "sin_aviso": sum(f["reserva_sin_aviso"] for f in fs),
        }
    return res


def leer_m4(dir_p0: Path):
    """Latencias de confirmación de la prueba P0 (sin calentamiento)."""
    datos = {}
    for arq in ARQS:
        ruta = Path(dir_p0) / arq / "P0-latencia" / "ensayo_0.jsonl"
        if not ruta.exists():
            continue
        filas = []
        for e in leer_jsonl(ruta):
            if e["evento"] == "confirmada" and not e["extra"].get("calentamiento"):
                lider = e["extra"].get("lider")
                local = None
                if lider:
                    local = (e["centro"], lider) in (("A", "etcd1"), ("B", "etcd2"))
                filas.append({"t": e["extra"]["t_respuesta"], "centro": e["centro"],
                              "lider": lider, "local": local})
        datos[arq] = filas
    return datos


# ====================================================================== tablas

def escribir_csv(ruta, columnas, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def r4(x):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 4)


def tablas(salida: Path, filas, res, m4, dir_logs):
    escribir_csv(salida / "resultados.csv", COLUMNAS, filas)

    principal = []
    for arq in ARQS:
        for esc in ESCENARIOS:
            c = res.get((arq, esc))
            if not c:
                continue
            principal.append({
                "arq": arq, "escenario": esc,
                "n_con_conflicto": c["n_conflicto"], "dobles_asignaciones": c["dobles"],
                "M1": r4(c["M1"][0]), "M1_ic_inf": r4(c["M1"][1]), "M1_ic_sup": r4(c["M1"][2]),
                "n_total": c["n_total"], "validos_a_tiempo": c["validos"],
                "M2": r4(c["M2"][0]), "M2_ic_inf": r4(c["M2"][1]), "M2_ic_sup": r4(c["M2"][2])})
    escribir_csv(salida / "tabla_principal.csv", list(principal[0]) if principal else ["arq"],
                 principal)

    apartados = defaultdict(int)
    for ruta in intentos_invalidos(dir_logs):
        apartados[(ruta.parent.parent.name, ruta.parent.name)] += 1
    invalidos = defaultdict(int)
    for f in filas:
        invalidos[(f["arq"], f["escenario"])] += f["invalido"]
    secundarias = []
    for arq in ARQS:
        for esc in ESCENARIOS:
            c = res.get((arq, esc))
            if not c:
                continue
            secundarias.append({
                "arq": arq, "escenario": esc, "n_solicitudes": len(c["M3"]),
                "M3_p50_s": r4(pct(c["M3"], 50)), "M3_p95_s": r4(pct(c["M3"], 95)),
                "M5_p50_s": r4(pct(c["M5"], 50)), "M5_p95_s": r4(pct(c["M5"], 95)),
                "no_recuperados": c["no_recuperados"],
                "confirmaciones": c["confirmaciones"], "reversiones": c["reversiones"],
                "M6": r4(c["M6"][0]), "M6_ic_inf": r4(c["M6"][1]), "M6_ic_sup": r4(c["M6"][2]),
                "reservas_sin_aviso": c["sin_aviso"],
                "ensayos_invalidos": invalidos[(arq, esc)],
                "intentos_descartados": apartados[(arq, esc)]})
    escribir_csv(salida / "metricas_secundarias.csv",
                 list(secundarias[0]) if secundarias else ["arq"], secundarias)

    filas_m4 = []
    for arq, ds in m4.items():
        grupos = [("total", ds)]
        if arq == "A2":
            grupos += [(f"lider={l}", [d for d in ds if d["lider"] == l])
                       for l in ("etcd1", "etcd2", "etcd3")]
            grupos += [("lider local", [d for d in ds if d["local"]]),
                       ("lider remoto", [d for d in ds if d["local"] is False])]
        for nombre, g in grupos:
            ts = [d["t"] for d in g]
            filas_m4.append({"arq": arq, "grupo": nombre, "n": len(ts),
                             "p50_ms": r4(pct(ts, 50) * 1000) if ts else "",
                             "p95_ms": r4(pct(ts, 95) * 1000) if ts else ""})
    escribir_csv(salida / "m4.csv", ["arq", "grupo", "n", "p50_ms", "p95_ms"], filas_m4)
    return filas_m4


# ====================================================================== hipótesis

def hipotesis(salida: Path, res, m4, es_piloto: bool):
    lineas = ["# Contraste de hipótesis", ""]
    if es_piloto:
        lineas += ["> **Piloto:** 2–3 ensayos por celda. Estos valores solo prueban el "
                   "análisis; no deben interpretarse.", ""]
    lineas += ["Nivel de significancia: 0,05. Proporciones con IC de Wilson al 95 %.", ""]

    def celda(a, e):
        return res.get((a, e))

    # H1: M2 de A2 > A1 en P1 (Fisher exacta, una cola)
    a1, a2 = celda("A1", "P1"), celda("A2", "P1")
    lineas.append("## H1 — M2 en P1: A2 > A1")
    if a1 and a2:
        tabla = [[a2["validos"], a2["n_total"] - a2["validos"]],
                 [a1["validos"], a1["n_total"] - a1["validos"]]]
        _, p = fisher_exact(tabla, alternative="greater")
        cumple = a2["M2"][0] > a1["M2"][0] and p < 0.05
        lineas += [f"- A2: {a2['validos']}/{a2['n_total']} = {fmt_pct(*a2['M2'])}",
                   f"- A1: {a1['validos']}/{a1['n_total']} = {fmt_pct(*a1['M2'])}",
                   f"- Prueba exacta de Fisher (una cola, A2 > A1): p = {p:.3g}",
                   f"- **{'Se cumple' if cumple else 'No se cumple'}**", ""]
    else:
        lineas += ["- Sin datos suficientes.", ""]

    # H2: M1 de A2 = 0 % y menor que A3 en P1
    a3 = celda("A3", "P1")
    lineas.append("## H2 — M1 en P1: A2 = 0 % y A2 < A3")
    if a2 and a3:
        tabla = [[a2["dobles"], a2["n_conflicto"] - a2["dobles"]],
                 [a3["dobles"], a3["n_conflicto"] - a3["dobles"]]]
        _, p = fisher_exact(tabla, alternative="less")
        cumple = a2["dobles"] == 0 and p < 0.05
        lineas += [f"- A2: {a2['dobles']}/{a2['n_conflicto']} = {fmt_pct(*a2['M1'])}",
                   f"- A3: {a3['dobles']}/{a3['n_conflicto']} = {fmt_pct(*a3['M1'])}",
                   f"- Prueba exacta de Fisher (una cola, A2 < A3): p = {p:.3g}",
                   f"- **{'Se cumple' if cumple else 'No se cumple'}**"
                   + ("" if a2["dobles"] == 0 else " (A2 tuvo dobles asignaciones)"), ""]
    else:
        lineas += ["- Sin datos suficientes.", ""]

    # H3: M6 de A3 > 0
    lineas.append("## H3 — M6 de A3 > 0")
    c3 = [res[k] for k in res if k[0] == "A3"]
    if c3:
        rev, conf = sum(c["reversiones"] for c in c3), sum(c["confirmaciones"] for c in c3)
        p, lo, hi = wilson(rev, conf)
        lineas += [f"- A3, todos los escenarios: {rev}/{conf} confirmaciones revertidas = "
                   f"{fmt_pct(p, lo, hi)}"]
        for e in ESCENARIOS:
            c = celda("A3", e)
            if c:
                lineas.append(f"  - {e}: {c['reversiones']}/{c['confirmaciones']} = {fmt_pct(*c['M6'])}")
        lineas += [f"- **{'Se cumple' if lo > 0 else 'No se cumple'}** "
                   f"(límite inferior del IC {'> 0' if lo > 0 else '= 0'})", ""]
    else:
        lineas += ["- Sin datos suficientes.", ""]

    # H4: M4 (p95) de A2 > A1
    lineas.append("## H4 — M4 (p95 de latencia sin falla): A2 > A1")
    if "A1" in m4 and "A2" in m4 and m4["A1"] and m4["A2"]:
        t1, t2 = [d["t"] for d in m4["A1"]], [d["t"] for d in m4["A2"]]
        _, p = mannwhitneyu(t2, t1, alternative="greater")
        cumple = pct(t2, 95) > pct(t1, 95) and p < 0.05
        lineas += [f"- A1: p50 {fmt_s(pct(t1, 50), True)}, p95 {fmt_s(pct(t1, 95), True)} (n = {len(t1)})",
                   f"- A2: p50 {fmt_s(pct(t2, 50), True)}, p95 {fmt_s(pct(t2, 95), True)} (n = {len(t2)})"]
        for grupo in ("etcd1", "etcd2", "etcd3"):
            g = [d["t"] for d in m4["A2"] if d["lider"] == grupo]
            if g:
                lineas.append(f"  - líder {grupo}: p95 {fmt_s(pct(g, 95), True)} (n = {len(g)})")
        for nombre, val in (("local", True), ("remoto", False)):
            g = [d["t"] for d in m4["A2"] if d["local"] is val]
            if g:
                lineas.append(f"  - líder {nombre} al centro que pide: p95 {fmt_s(pct(g, 95), True)} (n = {len(g)})")
        if "A3" in m4 and m4["A3"]:
            t3 = [d["t"] for d in m4["A3"]]
            lineas.append(f"- A3 (solo reserva local): p95 {fmt_s(pct(t3, 95), True)} (n = {len(t3)})")
        lineas += [f"- Mann-Whitney (una cola, A2 > A1): p = {p:.3g}",
                   f"- **{'Se cumple' if cumple else 'No se cumple'}**", ""]
    else:
        lineas += ["- Sin datos de la prueba P0 (`orquestador.py --p0`).", ""]
    (salida / "hipotesis.md").write_text("\n".join(lineas), encoding="utf-8")


# ====================================================================== figuras

def estilo(ax, ylabel=None):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(TINTA_2)
    ax.tick_params(colors=TINTA_2, labelsize=9)
    ax.grid(axis="y", color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    if ylabel:
        ax.set_ylabel(ylabel, color=TINTA_2, fontsize=9)


def barras_con_ic(ax, valores, titulo):
    """Una barra por arquitectura, con IC de Wilson y etiqueta directa."""
    xs = np.arange(len(ARQS))
    for x, arq in zip(xs, ARQS):
        p, lo, hi = valores.get(arq, (math.nan,) * 3)
        if math.isnan(p):
            ax.text(x, 2, "sin datos", ha="center", fontsize=8, color=TINTA_2)
            continue
        ax.bar(x, p * 100, width=0.6, color=COLOR[arq], hatch=TRAMA[arq],
               edgecolor="white", linewidth=2)
        ax.errorbar(x, p * 100, yerr=[[p * 100 - lo * 100], [hi * 100 - p * 100]],
                    color=TINTA, capsize=5, linewidth=1.2)
        ax.text(x, hi * 100 + 3, f"{p * 100:.0f} %\n[{lo * 100:.0f}–{hi * 100:.0f}]",
                ha="center", va="bottom", fontsize=8, color=TINTA)
    ax.set_xticks(xs, [NOMBRES[a] for a in ARQS], fontsize=9, color=TINTA)
    ax.set_ylim(0, 125)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_title(titulo, fontsize=10, color=TINTA, loc="left")
    estilo(ax, "% de ensayos")


def figuras(salida: Path, res, m4):
    dir_fig = salida / "figuras"
    dir_fig.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "hatch.color": "white",
                         "hatch.linewidth": 1.0})

    # F4: M1 y M2 en P1 (dos paneles: dos medidas → dos ejes, nunca doble eje)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.8))
    barras_con_ic(a, {k[0]: v["M1"] for k, v in res.items() if k[1] == "P1"},
                  "M1 · Doble asignación en P1 (↓ mejor)")
    barras_con_ic(b, {k[0]: v["M2"] for k, v in res.items() if k[1] == "P1"},
                  "M2 · Despacho válido a tiempo en P1 (↑ mejor)")
    fig.text(0.01, 0.01, "Barras: proporción; bigotes: IC de Wilson al 95 %. "
             "Trama: A1 lisa, A2 rayada, A3 punteada.", fontsize=7.5, color=TINTA_2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(dir_fig / "F4_M1_M2_P1.png", dpi=300)
    plt.close(fig)

    # F5: mapa de calor de M2 (arquitectura × escenario), con el valor escrito en cada celda
    matriz = np.full((len(ARQS), len(ESCENARIOS)), np.nan)
    for i, arq in enumerate(ARQS):
        for j, esc in enumerate(ESCENARIOS):
            if (arq, esc) in res:
                matriz[i, j] = res[(arq, esc)]["M2"][0] * 100
    fig, ax = plt.subplots(figsize=(7, 3.2))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("azul", SECUENCIAL)
    im = ax.imshow(matriz, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i in range(len(ARQS)):
        for j in range(len(ESCENARIOS)):
            v = matriz[i, j]
            texto = "sin datos" if np.isnan(v) else f"{v:.0f} %"
            ax.text(j, i, texto, ha="center", va="center", fontsize=10,
                    color="white" if (not np.isnan(v) and v >= 55) else TINTA)
    ax.set_xticks(range(len(ESCENARIOS)), ESCENARIOS, color=TINTA)
    ax.set_yticks(range(len(ARQS)), [NOMBRES[a] for a in ARQS], color=TINTA)
    ax.set_xticks(np.arange(-0.5, len(ESCENARIOS)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(ARQS)), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("M2 · Despacho válido a tiempo por arquitectura y escenario",
                 fontsize=10, color=TINTA, loc="left")
    barra = fig.colorbar(im, ax=ax, fraction=0.04)
    barra.set_label("% de ensayos", color=TINTA_2, fontsize=8)
    barra.outline.set_visible(False)
    fig.tight_layout()
    fig.savefig(dir_fig / "F5_M2_mapa_calor.png", dpi=300)
    plt.close(fig)

    # F6: CDF de M3, un panel por escenario; arquitecturas por estilo de línea y marcador
    escenarios = [e for e in ESCENARIOS if any((a, e) in res for a in ARQS)]
    fig, axes = plt.subplots(1, len(escenarios), figsize=(2.6 * len(escenarios), 3.4),
                             sharey=True, squeeze=False)
    for ax, esc in zip(axes[0], escenarios):
        for arq in ARQS:
            ts = sorted(res.get((arq, esc), {}).get("M3", []))
            if not ts:
                continue
            ys = np.concatenate([[0], np.arange(1, len(ts) + 1) / len(ts)])
            ax.step([ts[0]] + ts, ys, where="post", color=COLOR[arq], linestyle=LINEA[arq],
                    linewidth=2, label=NOMBRES[arq])
            ax.plot(ts[-1], 1, MARCADOR[arq], color=COLOR[arq], markersize=7,
                    markeredgecolor="white", markeredgewidth=1.5)
        ax.axvline(10, color=TINTA_2, linewidth=1, linestyle=(0, (2, 2)))
        ax.text(10, 1.06, "T", fontsize=8, color=TINTA_2, ha="center", va="bottom")
        ax.set_xscale("log")
        ax.set_xlim(0.005, 15)
        ax.set_ylim(0, 1.05)
        ax.set_title(esc, fontsize=10, color=TINTA, loc="left")
        estilo(ax)
        ax.set_xlabel("tiempo hasta la respuesta (s)", fontsize=8, color=TINTA_2)
    axes[0][0].set_ylabel("fracción de solicitudes", fontsize=9, color=TINTA_2)
    manejadores, etiquetas = axes[0][0].get_legend_handles_labels()
    fig.legend(manejadores, etiquetas, fontsize=8, frameon=False, loc="lower center", ncol=3)
    fig.suptitle("M3 · Distribución acumulada del tiempo hasta la respuesta definitiva "
                 "(línea punteada vertical: T = 10 s)", fontsize=10, color=TINTA, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(dir_fig / "F6_M3_cdf.png", dpi=300)
    plt.close(fig)

    # F7: diagrama de caja de M4 (P0); A2 también separado por posición del líder
    grupos = []
    for arq in ARQS:
        ds = m4.get(arq, [])
        if not ds:
            continue
        grupos.append((NOMBRES[arq], arq, [d["t"] * 1000 for d in ds]))
        if arq == "A2":
            for nombre, val in (("A2 · líder local", True), ("A2 · líder remoto", False)):
                g = [d["t"] * 1000 for d in ds if d["local"] is val]
                if g:
                    grupos.append((nombre, arq, g))
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    if grupos:
        cajas = ax.boxplot([g for _, _, g in grupos], patch_artist=True, widths=0.55,
                           showfliers=True, whis=(5, 95),
                           flierprops={"marker": ".", "markersize": 3, "alpha": 0.5},
                           medianprops={"color": TINTA, "linewidth": 1.5})
        for caja, (_, arq, _) in zip(cajas["boxes"], grupos):
            caja.set(facecolor=COLOR[arq], hatch=TRAMA[arq], edgecolor="white", linewidth=1.5)
        for i, (_, _, g) in enumerate(grupos, 1):
            ax.text(i + 0.32, pct(g, 95), f"p95 {pct(g, 95):.0f} ms", fontsize=8,
                    color=TINTA, va="center")
        ax.set_xticks(range(1, len(grupos) + 1), [n for n, _, _ in grupos], fontsize=9, color=TINTA)
    else:
        ax.text(0.5, 0.5, "sin datos de P0", ha="center", transform=ax.transAxes)
    ax.set_title("M4 · Latencia de confirmación sin falla (P0); bigotes p5–p95",
                 fontsize=10, color=TINTA, loc="left")
    estilo(ax, "ms")
    fig.tight_layout()
    fig.savefig(dir_fig / "F7_M4_cajas.png", dpi=300)
    plt.close(fig)


# ====================================================================== main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=DIR_LOGS, help="logs de los ensayos")
    p.add_argument("--dir-p0", help="logs de la prueba P0 (por defecto, --dir)")
    p.add_argument("--salida", default=str(Path(DIR_LOGS).parent))
    a = p.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)

    filas = leer_ensayos(a.dir)
    res = calcular(filas)
    m4 = leer_m4(Path(a.dir_p0 or a.dir))
    tablas(salida, filas, res, m4, a.dir)
    hipotesis(salida, res, m4, es_piloto="piloto" in str(a.dir))
    figuras(salida, res, m4)
    print(f"{len(filas)} ensayos ({sum(f['invalido'] for f in filas)} inválidos); "
          f"P0-latencia: {', '.join(f'{k}={len(v)}' for k, v in m4.items()) or 'sin datos'}")
    for nombre in ("resultados.csv", "tabla_principal.csv", "metricas_secundarias.csv",
                   "m4.csv", "hipotesis.md", "figuras/F4_M1_M2_P1.png",
                   "figuras/F5_M2_mapa_calor.png", "figuras/F6_M3_cdf.png",
                   "figuras/F7_M4_cajas.png"):
        print(f"  {'OK  ' if (salida / nombre).exists() else 'FALTA'} {salida / nombre}")


if __name__ == "__main__":
    main()
