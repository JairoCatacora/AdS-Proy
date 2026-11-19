
## Definición del experimento

Esta sección describe **cómo se ejecuta** el experimento sobre las tres arquitecturas, de modo que cualquier integrante pueda repetirlo y obtener los mismos resultados.

### Objetivo y variables

**Objetivo:** medir, bajo fallas de red idénticas, cuántas dobles asignaciones (M1) y cuántos despachos válidos a tiempo (M2) produce cada arquitectura, además de su costo en latencia y recuperación.

| Tipo de variable | Variable | Valores |
|---|---|---|
| **Independiente** | Arquitectura | A1, A2, A3 |
| **Factores** | Escenario de falla | P0, P1, P2, P3, P4 |
| | Tipo de ensayo | Con conflicto, sin conflicto |
| | Centro que solicita primero | A, B (alternado) |
| | Posición del líder al iniciar el corte (solo A2) | Lado de A, lado de B (alternado) |
| **Controladas** | Semilla, plazo T, duración del corte, latencia entre sitios, máquina, versiones de software | Fijas en todos los ensayos |
| **Dependientes** | M1 a M6 | Ver 3.1 |

**Ajuste a la línea de tiempo de 3.4:** el centro que solicita primero se **alterna** entre A y B. Si A siempre fuera primero, A3 favorecería siempre a A al reconciliar, y en A2 el lado mayoritario siempre llegaría antes. Alternar evita ese sesgo.

### Entorno

| Elemento | Especificación |
|---|---|
| Máquina | Un solo equipo (se reportan CPU, RAM y sistema operativo en el paper) |
| Software | Docker Engine y Docker Compose; Python 3.12; PostgreSQL 16; etcd **3.5.36** (imagen oficial `gcr.io/etcd-development/etcd:v3.5.36`; se actualizó desde 3.5.17 antes de tomar datos) |
| Sitios | Cada sitio (A, B, C, D) es un grupo de contenedores |
| Enlaces | Cada enlace entre sitios es una **red Docker propia**: `net_ab`, `net_ac`, `net_ad`, `net_bc`, `net_bd` (con prefijo por arquitectura: `a1_net_ac`, `a2_net_ab`, …) |
| Redes locales de sitio | `net_site_a`, `net_site_b`, `net_site_c` (con prefijo por arquitectura): comunicación dentro de un mismo sitio. **Nunca se cortan** |
| Latencia entre sitios | 20 ms por sentido con `tc qdisc replace ... netem delay 20ms` en las interfaces de las redes de enlace (no en `net_ctl` ni en las redes locales). RTT entre sitios ≈ 40 ms |
| Corte de un enlace X–Y | `docker network disconnect net_xy <contenedores del sitio X>` |
| Restauración | `docker network connect --ip <IP original> net_xy <contenedores del sitio X>`; luego se **vuelve a aplicar netem**, porque la reconexión crea una interfaz nueva |
| Direcciones | IPs fijas en todas las redes de enlace y de sitio (plan `10.<arq>.<enlace>.0/24`). Toda la coordinación entre sitios usa esas IPs, nunca nombres de contenedor |

**Contenedores por arquitectura** (con prefijo por arquitectura, p. ej. `a1-despacho-a`; las tres se mantienen levantadas a la vez):

| Sitio | A1 | A2 | A3 |
|---|---|---|---|
| A | `despacho-a` | `despacho-a`, `etcd1` | `despacho-a` (con SQLite y sincronizador) |
| B | `despacho-b` | `despacho-b`, `etcd2` | `despacho-b` (con SQLite y sincronizador) |
| C | `central-api`, `postgres` | — | — |
| D | — | `etcd3` | — |

- En A2, cada servicio de despacho usa **solo su réplica local** como punto de acceso (`despacho-a` → `etcd1`), por la red local de su sitio. Si esa réplica no tiene mayoría, la escritura no se completa.
- En A3, el sincronizador va **dentro del servicio de despacho** (no hay contenedores `sync-a`/`sync-b`).
- Fuera de las redes de enlace hay una red de **control** (`net_ctl`) para el orquestador y el monitor. **Nunca se corta**, para que el experimento pueda observar el sistema durante la falla. El sistema bajo prueba no la usa para coordinarse, y eso se **impone**: el orquestador tiene la IP fija `10.99.0.2` y cada contenedor del sistema solo acepta tráfico de `net_ctl` desde esa IP (`iptables`).
- Todas las redes son `internal` de Docker: los contenedores no tienen ruta por defecto, así que un paquete hacia un sitio cortado no puede salir por otra red.
- `postgres` (A1) está solo en la red local del sitio C, no en `net_ctl`.

**Verificación del inyector de fallas** (`experimento/verificar_fallas.py`), antes del experimento:

- Las IPs de todos los contenedores coinciden con la tabla de la topología, también después de cortar y restaurar.
- Ping entre sitios conectados ≈ 40 ms (mediana de 5 paquetes, porque el primero incluye la resolución ARP); ping por `net_ctl` y por las redes locales ≈ 0 ms.
- Con un enlace cortado el ping falla; al restaurarlo vuelve a ≈ 40 ms y netem queda aplicado. Se repite en un ciclo de P4 con varios cortes y restauraciones seguidos.
- Con P3 aplicado, ningún contenedor alcanza a otro sitio por ninguna red, ni a otro contenedor por `net_ctl`. El orquestador sí los alcanza a todos, y las redes locales siguen arriba.

### Escenarios como conjuntos de enlaces cortados

Para garantizar fallas **equivalentes**, cada escenario se define como el **mismo conjunto de enlaces cortados** en las tres arquitecturas. Los enlaces que una arquitectura no usa simplemente no la afectan.

| Escenario | Enlaces cortados | Cómo se aplica |
|---|---|---|
| **P0** | Ninguno | — (línea base sin falla: misma línea de tiempo, sin corte) |
| **P1** | A–C, B–C, A–B, B–D | Todo el corte a la vez en t = 1 s |
| **P2** | A–B, B–C, B–D | Todo el corte a la vez en t = 1 s |
| **P3** | A–B, A–C, A–D, B–C, B–D | Todo el corte a la vez en t = 1 s |
| **P4** | A–B, B–C, B–D | Se cortan y restauran cada 2 s entre t = 1 s y t = 21 s |

**Efecto de cada escenario en cada arquitectura:**

| | A1 (usa A–C, B–C) | A2 (usa A–B, A–D, B–D) | A3 (usa A–B) |
|---|---|---|---|
| **P1** | A y B pierden al servidor central | A conserva a D (2 de 3); B queda sola | A y B incomunicados |
| **P2** | A conserva al servidor; B no | A conserva a D (2 de 3); B queda sola | A y B incomunicados |
| **P3** | Nadie llega al servidor | Ninguna réplica tiene mayoría | A y B incomunicados |
| **P4** | B pierde y recupera al servidor | B entra y sale de la mayoría | A y B se sincronizan a ratos |

### Preparación y reinicio entre ensayos

Antes de cada ensayo, el orquestador deja el sistema en un estado conocido:

| Paso | A1 | A2 | A3 |
|---|---|---|---|
| 1. Restaurar todos los enlaces | `docker network connect --ip` en las redes cortadas y netem en todas las interfaces de enlace | igual | igual |
| 2. Reiniciar la ambulancia (`POST /admin/reset` con el contexto del ensayo: `arq`, `escenario`, `ensayo`, `tipo`) | `central-api` deja AMB-01 `disponible` en PostgreSQL | `put /amb/AMB-01 disponible` en etcd | Vaciar ambas SQLite y las colas del sincronizador |
| 3. Verificar el estado inicial | `GET /ambulancias` en ambos centros = disponible | Igual, más `etcdctl endpoint status`: 3 miembros con la misma revisión | `GET /ambulancias` en ambos centros = disponible |
| 4. Preparar el factor (solo P1) | — | Consultar el líder actual, enviarle `move-leader` hacia etcd1 (lado A) o etcd2 (lado B) y verificar que los 3 miembros reportan al nuevo líder; si no, reintentar (cuenta para el criterio de invalidez) | — |
| 5. Estabilizar | Esperar 2 s | Esperar 2 s | Esperar 2 s |

Si alguna verificación falla, el ensayo **no se ejecuta**: se repite la preparación hasta tres veces y luego se marca como inválido.

`/admin/reset` también vacía la lista de eventos propios de cada servicio y le indica a qué ensayo pertenecen los que genere desde ese momento. El orquestador guarda el `id_arranque` de cada servicio (`GET /admin/health`) al preparar el ensayo, para compararlo al final.

### Detección del estado consistente (M5)

Desde que se restaura la red (`corte_fin`), un **monitor** consulta `GET /ambulancias` en ambos centros cada 100 ms por la red de control.

| Arquitectura | Condición de "estado consistente" |
|---|---|
| A1 | Ambos centros responden con el mismo estado e incidente para la ambulancia |
| A2 | Lo anterior, y además las 3 réplicas tienen la misma revisión |
| A3 | Lo anterior, y además no quedan eventos pendientes en las colas de sincronización |

Cuando se cumple, el monitor registra `estado_consistente`. Si no ocurre en 30 s, el ensayo se registra como **no recuperado**.

`corte_fin` se registra justo **antes** del `docker network connect`, porque el enlace funciona desde ese instante. El momento en que netem quedó aplicado de nuevo se guarda en `extra.t_netem` (unos 0,3 s después; ver amenazas a la validez). M5 se mide desde `corte_fin`. El monitor termina en cuanto detecta el estado consistente, sin esperar a t = 51 s. En A3, el estado consistente exige `pendientes == 0` en ambos centros, así que la reconciliación ya ocurrió cuando el orquestador recoge los eventos.

### Orquestador

Un script en Python (`orquestador.py`) ejecuta todo el plan sin intervención manual:

```python
for rep in range(N_REPETICIONES):
    for escenario in ["P1", "P2", "P3", "P4"]:
        for tipo in plan_de_tipos(escenario, rep):        # con / sin conflicto
            semilla = hash(escenario, tipo, rep)           # misma para las 3 arquitecturas
            for arq in orden_aleatorio(["A1", "A2", "A3"], semilla):
                levantar(arq)                              # docker compose up (si no está arriba)
                preparar(arq, semilla)                     # 3.8.4
                log("ensayo_inicio", arq, escenario, semilla)
                t0 = ahora()
                en(t0 + 1, aplicar_corte, escenario)       # 3.8.3
                primero, segundo = centros_en_orden(semilla)
                en(t0 + 3, solicitar, primero, "I-1")
                if tipo == "con_conflicto":
                    en(t0 + 3 + delta(semilla), solicitar, segundo, "I-2")
                en(t0 + 21, restaurar, escenario)          # corte_fin justo ANTES del connect; extra.t_netem
                monitor_consistencia(arq, hasta=t0 + 51)   # 3.8.5
                recoger_eventos(arq)                       # GET /admin/eventos (incluye revertida)
                revisar_reserva_sin_aviso(arq)             # en las tres arquitecturas
                revisar_reinicios(arq)                     # id_arranque distinto → ensayo inválido
                log("ensayo_fin", arq, escenario, semilla)
```

- Cada solicitud la envía un **cliente simulado del despachador** por `net_ctl`. El cliente espera hasta **T + 2 s**, para recibir el `sin_confirmacion` del propio servicio en lugar de cortar él mismo, y registra `t_respuesta` tal como lo mide él.
- Los eventos se escriben en `resultados/logs/<arq>/<escenario>/ensayo_<n>.jsonl`. **Solo el orquestador escribe** esos archivos: los eventos propios de los servicios se recogen con `GET /admin/eventos` al final del ensayo (después del monitor, en t = 51 s, para incluir las reversiones de A3) y se agregan con su `t` original.
- Al final, `analizar.py` (ver 3.7) genera `resultados.csv` y las tablas del paper.

### Orden de ejecución

- **Bloques intercalados:** dentro de cada repetición y escenario se corren las tres arquitecturas seguidas, con la **misma semilla** y en **orden aleatorio**. Así, un problema de la máquina en un momento dado (calor, otra carga) afecta por igual a las tres, y no a una sola.
- **Factores alternados:** el centro que solicita primero (`primero = A` si `rep % 2 == 0`, si no `B`; igual en los ensayos sin conflicto) y, en A2-P1, la posición del líder (`etcd1` si `(rep // 2) % 2 == 0`, si no `etcd2`) se alternan para que cada valor aparezca en la mitad de los ensayos.
- **Sin reinicios innecesarios:** cada arquitectura se mantiene levantada mientras dura el experimento. Solo se reinicia el estado (3.8.4).

### Prueba de latencia sin falla (P0)

Se ejecuta aparte, con la red sana y la latencia de 20 ms:

1. 50 reservas de calentamiento (se descartan).
2. 1 000 reservas secuenciales, alternando centro A y B; cada una seguida de `liberar`.
3. Se registra el tiempo de cada confirmación y se calcula el p50 y p95 (M4).

**Posición del líder en A2.** La latencia de A2 depende de dónde esté el líder. Si el líder es la réplica local del centro que pide, basta con replicar a un seguidor (≈ 1 RTT). Si no, la réplica local reenvía al líder y este replica (≈ 2 RTT). Para no medir una sola posición por azar, en A2 las 1 000 reservas se dividen en **tres bloques consecutivos** con el líder en `etcd1` (334 reservas), `etcd2` (333) y `etcd3` (333):

- Antes de cada bloque, el líder se mueve con `move-leader` (enviado al líder actual) y se verifica que los 3 miembros lo reportan. Luego se hacen 10 reservas de calentamiento, que se descartan.
- Dentro de cada bloque se sigue alternando el centro A y B, así que cada combinación (centro, líder) aparece en la mitad de las reservas del bloque.
- Cada `confirmada` registra en `extra.lider` el líder verificado del bloque. En A1 y A3, `extra.lider` queda vacío.
- `analizar.py` reporta M4 (p50 y p95) de A2 **en total y por posición del líder** (`etcd1`, `etcd2`, `etcd3`). Como complemento, lo reporta también según si el líder es local al centro que pide (A con `etcd1`, B con `etcd2`) o remoto.

**Verificación funcional en P0:** antes del experimento principal, se corren 10 ensayos con conflicto y sin falla en cada arquitectura (`experimento/verificacion.py`). Si no salen como se espera, hay un error de implementación y no se continúa:

- **A1 y A2:** exactamente **una confirmada y una rechazada** en cada ensayo.
- **A3:** una confirmada y una rechazada, **o** dos confirmadas seguidas de **exactamente una `revertida`** y estado consistente (`pendientes == 0`). La doble asignación sin falla es una propiedad de A3, no un error: ocurre cuando δ es menor que el retardo de sincronización (hasta 500 ms de ciclo + 20 ms). Con δ ∈ [0, 200] ms ocurrió en 37 de 40 ensayos. Además, con las dos solicitudes **separadas 1 s** (más que el ciclo de 500 ms), A3 debe dar exactamente una confirmada y una rechazada (`--separacion 1`).

**P0 de A3:** como la `liberada` de un centro tarda hasta unos 500 ms en llegar al otro, en la prueba de latencia de A3 el orquestador espera `pendientes == 0` en ambos centros antes de la siguiente reserva. Así, **M4 de A3 mide solo la reserva local** (el `UPDATE` sobre su SQLite), sin el tiempo de sincronización. No es comparable con un "tiempo hasta que ambos centros lo saben", y así se reporta.

### Corrida piloto

Antes de la corrida completa, se ejecutan **3 ensayos por arquitectura y escenario** (36 ensayos, alrededor de 30 minutos) y se revisa:

- Que cada `solicitud` tenga exactamente una respuesta (`confirmada`, `rechazada` o `sin_confirmacion`).
- Que los cortes se apliquen de verdad: durante el corte, un ping entre los sitios cortados debe fallar.
- Que `analizar.py` produzca las seis métricas sin valores vacíos.
- Que los resultados tengan sentido frente a 3.8.3. Por ejemplo, A1 en P3 nunca debe confirmar.

Los resultados del piloto **no se incluyen** en el análisis final.

### Criterios de invalidez

Un ensayo se descarta y se repite con la misma semilla si:

- Algún contenedor se reinició durante el ensayo (su `id_arranque` en `GET /admin/health` cambió entre la preparación y el final).
- El corte no se aplicó (falló la verificación por ping).
- En A2-P1, el líder no pudo moverse al lado que tocaba tras 3 intentos (se registra `ensayo_invalido`).
- Falta algún evento obligatorio (`ensayo_inicio`, `corte_inicio`, `corte_fin`, `ensayo_fin`).
- **Alguna operación de red tardó más de 1 s** (`LIMITE_OPERACION_RED` en `orquestador.py`): el corte de t = 1, cada corte y cada restauración de P4, o la restauración final de t = 21 (`docker network connect --ip` + netem). La duración de cada operación queda en `extra.duraciones_red` del evento `corte_fin` (lista de `{op, t, s}`, con `op` ∈ `corte`, `corte_p4`, `restauracion_p4`, `restauracion`).
  *Motivo (agregado el 19-11-2026, antes de la F7):* en la PC donde se corre el experimento, una restauración de P4 tardó una vez 6,76 s en lugar de los 0,2 s habituales (no se repitió en 20 ciclos más). Una operación así de lenta corre la línea de tiempo del ensayo (el corte dura más de lo previsto o la ventana de P4 se acorta) y el ensayo deja de ser comparable. Con la red sana, cortar o restaurar tarda 0,12–0,30 s, así que 1 s deja un margen amplio. No se aplica a la restauración de la preparación, que ocurre antes de `ensayo_inicio`.
- **No se pudo leer el estado final** para revisar la reserva sin aviso: `GET /ambulancias` de la fuente de estado se reintenta cada 200 ms mientras no responda 200, hasta 5 s (`ESPERA_ESTADO_FINAL`); si no lo logra, el ensayo es inválido. Si hubo que reintentar, se registra el evento `lectura_estado_final` (`intentos`, `codigos`, `leido`).
  *Motivo (agregado el 19-11-2026, durante la F7):* en un ensayo A2-P3, justo después de que el monitor detectara el estado consistente (+13,3 s), la réplica de A respondió 503 ("sin quórum": la lectura linealizable no se completó en 1 s; etcd registraba *"waiting for ReadIndex response took too long"*). El orquestador suponía que esa lectura siempre devolvía la lista y se detuvo con un error. Antes, un fallo de esta lectura se registraba como `reserva_sin_aviso` con un campo `error`, lo que habría contado una reserva sin aviso inexistente.

El número de ensayos descartados por arquitectura se reporta en el paper.

### Resultados que produce el experimento

**`resultados.csv`**: una fila por ensayo.

| Columna | Ejemplo |
|---|---|
| `arq`, `escenario`, `tipo`, `rep`, `semilla` | A2, P1, con_conflicto, 12, 83127 |
| `primero`, `lider_inicial` | B, etcd2 |
| `respuesta_a`, `t_respuesta_a` | confirmada, 0.091 |
| `respuesta_b`, `t_respuesta_b` | sin_confirmacion, 10.000 |
| `doble_asignacion`, `valido_a_tiempo` | 0, 1 |
| `reversiones`, `t_recuperacion` | 0, 1.3 |

A partir de este archivo se generan las tablas y gráficos del E3: la tabla 3 × 4 con M1 y M2 por arquitectura y escenario, y los gráficos de barras con sus intervalos de confianza.
