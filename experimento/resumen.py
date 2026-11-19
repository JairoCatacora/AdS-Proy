"""Resumen de una corrida y revisión del piloto (aceptación de la F5).

Revisa, a partir de los logs:
- ningún ensayo inválido y ningún intento inválido apartado;
- cada `solicitud` tiene exactamente una respuesta y están los eventos obligatorios;
- los cortes se aplicaron de verdad (ping fallido durante el corte);
- A1 en P3 nunca confirma;
- A3 en P1 con conflicto siempre tiene doble asignación.

Uso: python experimento/resumen.py [--dir resultados/piloto/logs]
"""

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from clasificar import intentos_invalidos, leer_ensayos
from comun.logger import leer_jsonl


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="resultados/piloto/logs")
    a = p.parse_args()
    filas = leer_ensayos(a.dir)
    apartados = intentos_invalidos(a.dir)

    celdas = defaultdict(list)
    for f in filas:
        celdas[(f["arq"], f["escenario"], f["tipo"])].append(f)

    print(f"{'arq':3} {'esc':3} {'tipo':13} {'n':>2} {'inv':>3} {'conf/ens':>8} {'doble':>5} "
          f"{'válido':>6} {'rev':>3} {'s/aviso':>7} {'no rec':>6} {'t_rec p50':>9}  respuestas (A/B)")
    for (arq, esc, tipo), fs in sorted(celdas.items()):
        recs = [f["t_recuperacion"] for f in fs if f["t_recuperacion"] != ""]
        resp = ", ".join(f"{f['respuesta_a'][:4] or '-'}/{f['respuesta_b'][:4] or '-'}" for f in fs)
        print(f"{arq:3} {esc:3} {tipo:13} {len(fs):2d} {sum(f['invalido'] for f in fs):3d} "
              f"{statistics.mean(f['_confirmadas'] for f in fs):8.2f} "
              f"{sum(f['doble_asignacion'] for f in fs):5d} {sum(f['valido_a_tiempo'] for f in fs):6d} "
              f"{sum(f['reversiones'] for f in fs):3d} {sum(f['reserva_sin_aviso'] for f in fs):7d} "
              f"{sum(f['_no_recuperado'] for f in fs):6d} "
              f"{(f'{statistics.median(recs):.2f} s') if recs else '-':>9}  {resp}")

    # ---- revisiones del piloto
    fallos = []

    def revisar(ok, msg):
        print(f"  [{'OK' if ok else 'FALLA'}] {msg}")
        if not ok:
            fallos.append(msg)

    print("\nRevisión del piloto")
    invalidos = [f["_ruta"] for f in filas if f["invalido"]]
    revisar(not invalidos and not apartados,
            f"ensayos inválidos: {len(invalidos)}; intentos inválidos apartados: {len(apartados)}")
    revisar(all(f["_respuestas_ok"] for f in filas),
            "cada solicitud tiene exactamente una respuesta")
    revisar(all(not f["_faltan"] for f in filas), "están todos los eventos obligatorios")
    sin_verif = []
    for f in filas:
        cf = next(e for e in leer_jsonl(f["_ruta"]) if e["evento"] == "corte_fin")
        if f["escenario"] != "P0" and not cf["extra"].get("corte_verificado"):
            sin_verif.append(f["_ruta"])
    revisar(not sin_verif, f"cortes verificados por ping en P1–P4 ({len(sin_verif)} sin verificar)")
    a1p3 = [f for f in filas if f["arq"] == "A1" and f["escenario"] == "P3"]
    if not a1p3:
        print("  [--] A1 en P3: no aplica (no hay ensayos de esa celda)")
    else:
        revisar(all(f["_confirmadas"] == 0 for f in a1p3),
                f"A1 en P3 nunca confirma ({sum(f['_confirmadas'] for f in a1p3)} confirmaciones "
                f"en {len(a1p3)} ensayos)")
    a3p1 = [f for f in filas if f["arq"] == "A3" and f["escenario"] == "P1"
            and f["tipo"] == "con_conflicto"]
    if not a3p1:
        print("  [--] A3 en P1 con conflicto: no aplica (no hay ensayos de esa celda)")
    else:
        revisar(all(f["doble_asignacion"] for f in a3p1),
                f"A3 en P1 con conflicto siempre tiene doble asignación "
                f"({sum(f['doble_asignacion'] for f in a3p1)}/{len(a3p1)})")
    print(f"\n{'APROBADO' if not fallos else 'REPROBADO'}: {len(fallos)} fallas")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
