# Banco de pruebas — despacho de una ambulancia compartida

Proyecto final de Arquitectura de Software. Compara tres arquitecturas de
coordinación para reservar una ambulancia compartida entre dos centros de
despacho (A y B) cuando se corta la comunicación:

| | Arquitectura | Carpeta |
|---|---|---|
| A1 | Centralizada (PostgreSQL en el sitio C) | `arquitecturas/a1-centralizado/` |
| A2 | Replicada con quórum (etcd, 3 réplicas) | `arquitecturas/a2-quorum/` |
| A3 | Local con reconciliación (SQLite por centro) | `arquitecturas/a3-local/` |

El diseño está en [docs/](docs/): `ArquitecturaBase.md`, `ArquitecturaMejorada.md`,
`Metricas.md` y `DiseñoExperimento.md`.

## Estructura

```
comun/            librería compartida (logger JSONL, modelos, cliente HTTP con plazo)
arquitecturas/    docker compose de A1, A2 y A3
experimento/      orquestador, inyector de fallas, monitor y análisis
tests/            pruebas unitarias y fitness function
resultados/       logs, CSV y figuras (generados; no se versionan)
```

## Requisitos

- Docker Desktop (contenedores Linux).
- Python 3.12.

## Preparar el entorno local

En PowerShell (Windows):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

En Git Bash: `source .venv/Scripts/activate`.

## Estado por fases

| Fase | Contenido | Estado |
|---|---|---|
| F0 | Estructura, librería común, README | ✅ |
| F1 | A1 completa | ✅ |
| F2 | Inyector de fallas y latencia | ✅ |
| F3 | A2 completa | ✅ |
| F4 | A3 completa | ✅ |
| F5 | Orquestador y monitor | ✅ (piloto aprobado) |
| F6 | Análisis, figuras y fitness function | ✅ |
| F7 | Corrida completa | lista para ejecutar |

## F0 — Librería común

`comun/comun/`:

- `config.py`: constantes (T = 10 s, reintento cada 200 ms, AMB-01, lista de eventos).
- `logger.py`: eventos en JSONL con el formato
  `{"t", "ensayo", "arq", "escenario", "tipo", "centro", "incidente", "ambulancia", "evento", "extra"}`,
  escritos en `resultados/logs/<arq>/<escenario>/ensayo_<n>.jsonl`.
  `t` es `time.time()`. Solo el orquestador escribe archivos; los servicios
  guardan sus eventos en memoria (`BufferEventos`) y el orquestador los recoge.
- `modelos.py`: modelos Pydantic de la interfaz común (`/reservas`, `/liberar`,
  `/ambulancias`, `/admin/reset` con el contexto del ensayo).
- `cliente.py`: `pedir_con_plazo()`, que reintenta cada 200 ms ante errores de
  conexión y devuelve `None` si se agota T (el servicio responde `sin_confirmacion`).

### Ejecutar las pruebas

```powershell
pytest
```

## Levantar el banco de pruebas

```powershell
docker compose up -d --build     # orquestador + arquitecturas
docker ps                        # deben aparecer orquestador, a1-*
docker compose down              # apagar todo
```

Todo el experimento se ejecuta **dentro del contenedor `orquestador`**
(`docker exec orquestador python ...`). Ese contenedor está en `net_ctl`, tiene
montado el socket de Docker y monta `experimento/`, `tests/` y `resultados/`,
así que los cambios en el código no requieren reconstruir la imagen.

### Redes

- **Redes de enlace** (`<arq>_net_ab`, `_ac`, `_ad`, `_bc`, `_bd`): cada una contiene
  solo los contenedores de dos sitios. Se cortan para simular fallas.
- **Redes locales de sitio** (`<arq>_net_site_c`, …): comunicación dentro de un sitio
  (p. ej. `central-api` ↔ `postgres`). Nunca se cortan.
- **`net_ctl`**: control (orquestador y monitor). Nunca se corta; el sistema no la usa
  para coordinarse.
- Toda la coordinación entre sitios usa **IPs fijas de las redes de enlace**
  (plan `10.<arq>.<enlace>.0/24`, ver los `docker-compose.yml`). Todas las redes son
  `internal`: los contenedores no tienen ruta por defecto y un paquete hacia un sitio
  con el enlace cortado no puede salir por otra red.

## F1 — A1 centralizada

| Contenedor | Sitio | Redes |
|---|---|---|
| `a1-despacho-a` | A | `a1_net_ac` (10.1.13.10), `net_ctl` |
| `a1-despacho-b` | B | `a1_net_bc` (10.1.23.20), `net_ctl` |
| `a1-central-api` | C | `a1_net_ac` (.30), `a1_net_bc` (.30), `a1_net_site_c` (10.1.103.30), `net_ctl` |
| `a1-postgres` | C | `a1_net_site_c` (10.1.103.31) |

- Los despachos no guardan estado: reenvían a `central-api` por su enlace, con
  reintentos cada 200 ms hasta T = 10 s (después responden `sin_confirmacion`).
- `central-api` reserva con el `UPDATE ... WHERE estado='disponible' RETURNING id`.
  Si devuelve 0 filas pero la unidad ya está reservada **para el mismo incidente**
  (reintento cuya respuesta se perdió), responde `confirmada` (reserva idempotente).
- Endpoints de administración (solo por `net_ctl`): `/admin/reset` (recibe el contexto
  del ensayo y vacía los eventos), `/admin/health` (devuelve `id_arranque` para detectar
  reinicios) y `/admin/eventos` (eventos propios del servicio, p. ej. `liberada`).

### Verificación funcional (prueba de aceptación de F1)

```powershell
docker exec orquestador python experimento/verificacion.py --arq A1 --n 10 --semilla 2026
```

Corre 10 ensayos con conflicto y la red sana; cada uno debe dar exactamente
1 `confirmada` y 1 `rechazada`. Los logs quedan en `resultados/verificacion/A1/P0/`.

## F2 — Inyector de fallas y latencia

[experimento/fallas.py](experimento/fallas.py):

- **Cortar X–Y:** `docker network disconnect` de los contenedores del sitio X en `net_xy`.
- **Restaurar:** `docker network connect --ip <IP original>` (las IPs están en
  [topologia.py](experimento/topologia.py) y coinciden con los compose) y se vuelve
  a aplicar netem, porque la reconexión crea una interfaz nueva.
- **Latencia:** `tc qdisc replace dev <if> root netem delay 20ms` en las interfaces de
  las redes de enlace. La interfaz de cada red se identifica buscando con `ip -o addr`
  la IP que reporta `docker inspect`.
- **Aislamiento de `net_ctl`:** el orquestador tiene la IP fija `10.99.0.2` y cada
  contenedor del sistema arranca con [aislar_ctl.sh](arquitecturas/aislar_ctl.sh), que
  con `iptables` solo acepta tráfico de `net_ctl` desde esa IP.

Uso manual:

```powershell
docker exec orquestador python experimento/fallas.py estado    --arq A1
docker exec orquestador python experimento/fallas.py cortar    --arq A1 --escenario P3
docker exec orquestador python experimento/fallas.py restaurar --arq A1
```

### Prueba de aceptación de F2

```powershell
docker exec orquestador python experimento/verificar_fallas.py --arq A1
```

Comprueba: IPs iguales a la tabla (antes y después de cada corte); ping entre sitios
≈ 40 ms (mediana de 5 paquetes, porque el primero incluye ARP y pasa por netem dos
veces); el ping falla con el enlace cortado y vuelve a ≈ 40 ms tras restaurarlo;
5 ciclos seguidos de P4; y, con P3 aplicado, que ningún contenedor alcanza a otro sitio
por ninguna red ni a otro contenedor por `net_ctl`.

## F3 — A2 replicada con quórum (etcd)

| Contenedor | Sitio | Redes |
|---|---|---|
| `a2-despacho-a` | A | `a2_net_site_a` (10.2.101.10), `net_ctl` |
| `a2-etcd1` | A | `a2_net_ab` (10.2.12.11), `a2_net_ad` (10.2.14.11), `a2_net_site_a` (.11), `net_ctl` |
| `a2-despacho-b` | B | `a2_net_site_b` (10.2.102.20), `net_ctl` |
| `a2-etcd2` | B | `a2_net_ab` (10.2.12.21), `a2_net_bd` (10.2.24.21), `a2_net_site_b` (.21), `net_ctl` |
| `a2-etcd3` | D | `a2_net_ad` (10.2.14.41), `a2_net_bd` (10.2.24.41), `net_ctl` |

- **etcd v3.5.36**, imagen propia ([etcd/Dockerfile](arquitecturas/a2-quorum/etcd/Dockerfile)):
  Debian slim + binarios oficiales + `iproute2`/`iptables`/`ping`. Timeouts por defecto
  (heartbeat 100 ms, elección 1000 ms) y `--pre-vote=true`.
- Cada despacho usa **solo su réplica local**, por la red de su sitio, con la API JSON de
  etcd (`POST /v3/kv/txn`, claves en base64): si `/amb/<id> == "disponible"` →
  `put "reservada:<incidente>"`. Si la comparación falla pero el valor ya es
  `reservada:<mismo incidente>`, responde `confirmada` (reserva idempotente).
- [experimento/etcd_admin.py](experimento/etcd_admin.py): estado de cada miembro (líder,
  revisión), `move-leader` enviado al líder actual con verificación, y detección del
  nuevo líder durante un corte.

### Pruebas de aceptación de F3

```powershell
docker exec orquestador python experimento/verificacion.py --arq A2 --n 10   # 1 confirmada + 1 rechazada
docker exec orquestador python experimento/verificar_a2.py                   # move-leader, matar líder, P1
docker exec orquestador python experimento/verificar_fallas.py --arq A2      # fallas, netem, aislamiento
```

## F4 — A3 local con reconciliación

| Contenedor | Sitio | Redes |
|---|---|---|
| `a3-despacho-a` | A | `a3_net_ab` (10.3.12.10), `net_ctl` |
| `a3-despacho-b` | B | `a3_net_ab` (10.3.12.20), `net_ctl` |

- SQLite local por centro; la reserva es el `UPDATE` condicionado de A1 sobre la base
  local (responde en milisegundos).
- El sincronizador va dentro del servicio: cada 500 ms envía por `net_ab` los eventos
  propios (`reserva`, `liberada`) aún no confirmados por el otro centro.
- [reconciliacion.py](arquitecturas/a3-local/despacho/reconciliacion.py): regla pura y
  simétrica (gana el `t` más antiguo; empate → A). El centro cuya reserva pierde registra
  `revertida` con el incidente ganador en `extra`. Pruebas en
  [tests/test_reconciliacion.py](tests/test_reconciliacion.py).
- `GET /admin/pendientes`: eventos propios sin confirmar (el monitor espera que sea 0).
- Variante opcional `A3_SYNC_INMEDIATO=1` (envío inmediato además del ciclo de 500 ms);
  por defecto está desactivada.

### Pruebas de aceptación de F4

```powershell
docker exec orquestador python experimento/verificar_a3.py              # net_ab cortado ×10 y P4 ×2
docker exec orquestador python experimento/verificar_fallas.py --arq A3
docker exec orquestador python experimento/verificacion.py --arq A3     # red sana (ver nota)
```

## F5 — Orquestador y monitor

[experimento/orquestador.py](experimento/orquestador.py) corre todo el plan dentro del
contenedor `orquestador`:

```powershell
# Corrida completa (P0 con conflicto como línea base + P1–P4); -e COMMIT queda en entorno.json
docker exec -e "COMMIT=$(git rev-parse HEAD)" orquestador python experimento/orquestador.py --arq A1,A2,A3 --escenarios P0,P1,P2,P3,P4 --rep 16 --sin-conflicto 4 --semilla 2026
# Piloto: 3 ensayos por celda, en resultados/piloto/logs (no entra en el análisis final)
docker exec -e "COMMIT=$(git rev-parse HEAD)" orquestador python experimento/orquestador.py --piloto
# Prueba de latencia sin falla (M4)
docker exec -e "COMMIT=$(git rev-parse HEAD)" orquestador python experimento/orquestador.py --p0
# Resumen y revisión del piloto
docker exec orquestador python experimento/resumen.py --dir resultados/piloto/logs
```

- **Orden:** para cada repetición y escenario, las tres arquitecturas seguidas, con la
  misma semilla (misma δ) y en orden aleatorio derivado de la semilla.
  `primero = A` si `rep` es par; en A2-P1, el líder en etcd1 si `(rep // 2)` es par y en
  etcd2 si no.
- **Ensayo:** preparación (restaurar + netem, `/admin/reset` con el contexto, verificar
  AMB-01 disponible y, en A2, la misma revisión y el líder movido; esperar 2 s) →
  `t=1` corte (verificado por ping) → `t=3 (+δ)` solicitudes → `t=21` `corte_fin`
  (justo antes del `connect`; `extra.t_netem`) → monitor cada 100 ms
  ([monitor.py](experimento/monitor.py)) → eventos de los servicios → reserva sin aviso →
  reinicios → `ensayo_fin`.
- **P4:** el corte se restaura y se vuelve a aplicar cada 2 s; las ventanas con el enlace
  arriba quedan en `extra.ventanas_arriba_p4` de `corte_fin`.
- **A2:** `extra.lider` (líder al iniciar el corte) y `lider_mayoria`/`t_lider_mayoria`
  (cuándo tuvo líder el lado A + D).
- **Inválidos:** si la preparación falla 3 veces, si el corte no se aplicó o si algún
  contenedor se reinició (cambió `id_arranque` o `StartedAt`), o si algún corte o
  restauración (connect + netem) tardó más de 1 s (duraciones en `extra.duraciones_red`
  de `corte_fin`). Se repite con la misma
  semilla hasta 3 veces; los intentos inválidos quedan como `ensayo_<n>.invalido_<k>.jsonl`.
- **Reanudación:** al relanzar, se saltan los ensayos cuyo log tiene `ensayo_fin`; un
  ensayo interrumpido se borra y se repite.
- [clasificar.py](experimento/clasificar.py): una fila por ensayo con las definiciones de
  M1–M6 (lo usarán `resumen.py` y `analizar.py`).

## F6 — Análisis, figuras y fitness function

```powershell
# Corrida completa (logs en resultados/logs → salida en resultados/)
docker exec orquestador python experimento/analizar.py
# Piloto (logs del piloto; M4 desde la prueba P0 en resultados/logs)
docker exec orquestador python experimento/analizar.py --dir resultados/piloto/logs --salida resultados/piloto --dir-p0 resultados/logs
# Fitness function FF-01 (10 ensayos reales de A2-P1; ~7 min)
docker exec orquestador pytest tests/test_invariante.py -v -s
```

[experimento/analizar.py](experimento/analizar.py) genera:

| Archivo | Contenido |
|---|---|
| `resultados.csv` | Una fila por ensayo (columnas de la sección 8 del diseño) |
| `tabla_principal.csv` | M1 y M2 por arquitectura × escenario (P0–P4), con IC de Wilson 95 % |
| `metricas_secundarias.csv` | M3 y M5 (p50, p95), no recuperados, M6 con IC, reservas sin aviso, inválidos y descartados |
| `m4.csv` | M4 (p50, p95) por arquitectura; en A2 también por líder (etcd1/2/3) y líder local/remoto |
| `hipotesis.md` | H1 (Fisher), H2 (Fisher), H3 (IC de M6), H4 (p95 y Mann-Whitney): valor y si se cumple |
| `figuras/F4…F7.png` | 300 dpi; cada arquitectura tiene color, trama y etiqueta propios (se lee sin color) |

- Solo los ensayos válidos entran en las métricas; los inválidos se cuentan aparte.
- La paleta (azul, naranja, aguamarina) se validó para daltonismo con el validador de la
  guía de visualización; la identidad nunca depende solo del color (tramas, estilos de
  línea, marcadores y etiquetas directas).
- **FF-01** ([tests/test_invariante.py](tests/test_invariante.py)): falla si M1 > 0 o si el
  p95 de M3 supera 10 s. Fuera del contenedor se salta.

## F7 — Corrida completa

La corrida dura unas **2 horas** (288 ensayos de 24–36 s, más la preparación; el diseño
original era de 570 y se redujo por tiempo, ver `docs/Metricas.md`). Antes de
empezar: Docker Desktop abierto, el equipo enchufado y **sin suspensión** (Windows:
Configuración → Sistema → Energía → "Nunca"), y sin otras cargas pesadas.

### 0. Verificaciones previas (≈ 3 min)

```powershell
docker compose up -d --build
docker exec orquestador python experimento/verificacion.py --arq A1 --n 10
docker exec orquestador python experimento/verificacion.py --arq A2 --n 10
docker exec orquestador python experimento/verificacion.py --arq A3 --n 10
```

### 1. Lanzar la corrida (en segundo plano, dentro del contenedor)

```powershell
docker exec -d -e "COMMIT=$(git rev-parse HEAD)" orquestador sh -c "mkdir -p resultados/logs && python experimento/orquestador.py --arq A1,A2,A3 --escenarios P0,P1,P2,P3,P4 --rep 16 --sin-conflicto 4 --semilla 2026 >> resultados/logs/corrida.log 2>&1"
```

Con `-d` la corrida sigue aunque cierres la terminal o VS Code. Al empezar registra el
entorno en `resultados/entorno.json`. Cada entrada tiene `tipo` (`p0`, `corrida` o
`reanudacion`) y `commit` (el hash que se pasa con `-e COMMIT=...`, porque el contenedor
no ve `.git`; sin él queda `"no indicado"`). La primera entrada es la de la P0 y las
siguientes van en `entradas_posteriores`. La prueba de latencia P0 (`--p0`) ya está hecha
(`resultados/logs/*/P0-latencia/`); si hubiera que repetirla, se borra esa carpeta y se
corre `python experimento/orquestador.py --p0`.

### 2. Ver el progreso

```powershell
Get-Content resultados\logs\corrida.log -Wait -Tail 20          # una línea por ensayo, con ETA
docker exec orquestador pgrep -af orquestador.py                 # ¿sigue corriendo?
docker exec orquestador python experimento/resumen.py --dir resultados/logs   # tabla por celda
```

### 3. Si se interrumpe (corte de luz, reinicio, Docker se cerró…)

Se relanza **exactamente el mismo comando del paso 1** (después de
`docker compose up -d` si los contenedores se detuvieron). Los ensayos con `ensayo_fin`
se saltan; el que quedó a medias se borra y se repite con la misma semilla; la
reanudación queda anotada en `entorno.json` (`tipo: "reanudacion"`). Para detenerla a propósito:
`docker exec orquestador pkill -f orquestador.py`.

### 4. Al terminar

```powershell
docker exec orquestador python experimento/resumen.py --dir resultados/logs   # inválidos y revisiones
docker exec orquestador python experimento/analizar.py                        # tablas, hipótesis y figuras
docker exec orquestador pytest tests/test_invariante.py -v -s                 # FF-01 (opcional, ~7 min)
```

Los resultados quedan en `resultados/` (`resultados.csv`, `tabla_principal.csv`,
`metricas_secundarias.csv`, `m4.csv`, `hipotesis.md`, `figuras/`, `entorno.json`).
Los logs crudos (`resultados/logs/`) no se versionan.
