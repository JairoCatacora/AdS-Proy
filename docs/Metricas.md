# Métricas y diseño experimental

**Proyecto:** Despacho de una ambulancia compartida durante un corte de comunicación entre dos centros
**Entregable II — Semana 14**

Este documento fija **qué se mide, con qué umbral, cómo se calcula y en qué condiciones** para comparar la arquitectura base (A1) con la mejorada (A2) y el contraste (A3).

---

## Métricas

| # | Métrica | Tipo | Definición | Umbral | Hipótesis |
|---|---|---|---|---|---|
| **M1** | Tasa de doble asignación | Principal | Ensayos con **dos confirmaciones vigentes** para la misma ambulancia ÷ ensayos con conflicto × 100 | **0 %** | H2, H3 |
| **M2** | Tasa de despacho válido a tiempo | Principal | Ensayos con **exactamente una** confirmación en ≤ T y sin doble asignación ÷ total de ensayos × 100 | Mayor es mejor; se compara A2 vs. A1 | H1 |
| **M3** | Tiempo hasta respuesta definitiva | Secundaria | Desde la solicitud hasta recibir confirmada, rechazada o sin_confirmacion (p50 y p95) | ≤ T = 10 s | — |
| **M4** | Latencia de confirmación sin falla | Secundaria | p95 del tiempo de confirmación con la red sana | ≤ 250 ms | H4 |
| **M5** | Tiempo de recuperación | Secundaria | Desde que vuelve la red hasta que todos los centros ven el mismo estado de la ambulancia | ≤ 30 s | — |
| **M6** | Tasa de reversión | Secundaria (A3) | Confirmaciones revertidas ÷ confirmaciones × 100 | 0 % | H3 |

**Reglas de conteo:**
- Se cuenta como **confirmación** solo lo que se comunicó al despachador. Si una escritura se completó pero la respuesta llegó después de T, cuenta como sin_confirmacion. Se registra aparte como *reserva sin aviso* (`reserva_sin_aviso`), porque deja la unidad bloqueada. Se revisa en las **tres** arquitecturas: en A2 por la escritura tardía, y en A1 porque el `UPDATE` puede ejecutarse aunque la respuesta se pierda al cortarse el enlace.
- Los tiempos de respuesta (`t_respuesta`, M3 y M4) los mide el **cliente simulado del despachador**, desde que registra `solicitud` hasta que recibe la respuesta. El cliente espera hasta T + 2 s, para recibir el `sin_confirmacion` del servicio en lugar de cortar él mismo.
- Una confirmación **revertida después** cuenta igual para M1: el despachador ya actuó sobre ella.
- M1 y M2 **se reportan siempre juntas**. Una arquitectura que nunca confirma tiene 0 % en M1, pero también 0 % en M2.

## Justificación de los umbrales

| Umbral | Valor | Justificación |
|---|---|---|
| Plazo de confirmación **T** | 10 s | La norma NFPA 1225 fija que el procesamiento de las emergencias de mayor prioridad se complete en 60 s para el 90 % de los eventos. Ese tiempo incluye atender, registrar y clasificar. La reserva de la unidad es un solo paso de ese proceso, así que se le asigna como máximo una sexta parte. Es una decisión del equipo, fijada antes de ejecutar los ensayos. |
| Doble asignación | 0 % | Es el invariante del sistema (RNF-01); cualquier valor mayor es una violación. |
| Latencia sin falla | 250 ms p95 | Un despachador percibe como inmediata una respuesta muy por debajo de 1 s. Se deja margen para la latencia entre sitios simulada (20 ms por sentido). |
| Recuperación | 30 s | Es menor que el tiempo de traslado de una ambulancia. El conflicto debe resolverse antes de que la unidad llegue a un incidente equivocado. |

## Escenarios de falla

Topología: sitios A, B, C y D (ver [ArquitecturaBase.md](ArquitecturaBase.md)).

| Escenario | Enlaces cortados | Qué representa |
|---|---|---|
| **P1** (hipótesis principal) | C inalcanzable desde todos + A–B + B–D | Cae el centro de datos central y además se divide la red. A conserva acceso a D (mayoría en A2) |
| **P2** (prueba separada) | B aislado de todos | Solo un centro pierde conectividad |
| **P3** | Todos los enlaces | Nadie tiene mayoría |
| **P4** | Enlaces de B suben y bajan cada 2 s | Red intermitente |
| **P0** | Ninguno | Operación normal: línea base sin falla (16 ensayos con conflicto: M1, M2, M6) y prueba de latencia aparte (M4) |

En **P1**, en A2 se controla dónde está el líder al iniciar el corte: en la mitad de los ensayos está del lado de A (`etcd1`) y en la otra mitad del lado de B (`etcd2`). El líder real al iniciar el corte se registra en `extra.lider`.

## Definición de un ensayo

Cada ensayo sigue la misma línea de tiempo en las tres arquitecturas:

| Tiempo | Acción |
|---|---|
| t = 0 s | Reiniciar el estado: **una sola ambulancia disponible** |
| t = 1 s | Inyectar el corte del escenario |
| t = 3 s | El centro "primero" solicita AMB-01 para el incidente I-1 |
| t = 3 s + δ | El centro "segundo" solicita la misma ambulancia para I-2 (δ aleatorio entre 0 y 200 ms, según la semilla) |
| t = 13 s + δ | Vence el plazo T de ambas solicitudes |
| t = 21 s | Se restablece la red y se vuelve a aplicar netem (el corte dura 20 s, más que T) |
| t = 21–51 s | Se mide la recuperación (M5) y se registran reversiones (M6) |
| t = 51 s | El orquestador recoge los eventos propios de los servicios (`GET /admin/eventos`), incluidas las reversiones de A3, y revisa si hubo reserva sin aviso |

**Quién solicita primero:** se **alterna** entre A y B (`primero = A` si `rep` es par, `B` si es impar). Si A siempre fuera primero, A3 favorecería siempre a A al reconciliar, y en A2 el lado mayoritario siempre llegaría antes. En A2-P1 la posición del líder se cruza con ese factor: `lider = etcd1` si `(rep // 2)` es par, `etcd2` si es impar. Así cada valor de cada factor aparece en la mitad de los ensayos.

**Tipos de ensayo:**
- **Con conflicto:** dos solicitudes, una por centro (la línea de tiempo anterior).
- **Sin conflicto:** solo solicita el centro "primero", con la misma alternancia entre A y B. Evita favorecer a una arquitectura que simplemente bloquea todo.

## Tamaño del experimento

| | Por arquitectura | Total (3 arquitecturas) |
|---|---|---|
| P1–P4 con conflicto | 16 por escenario (64) | 192 |
| P1–P4 sin conflicto | 4 por escenario (16) | 48 |
| **P0 con conflicto** (línea base sin falla, sin corte) | 16 | 48 |
| **Total** | 96 | **288 ensayos** |

- **Reducción de 570 a 288 ensayos** (19-11-2026, decisión del usuario durante la F7, por falta de tiempo): el diseño original era 30 con conflicto y 10 sin conflicto por celda (570 ensayos, ~4 h en la máquina usada). Se eligió 16 y 4 porque mantiene **equilibrados** los factores alternados (quién pide primero: 8/8 con conflicto y 2/2 sin conflicto; líder de A2-P1 en el lado A o B: 8/8 y 2/2), que necesitan múltiplos de 4. Como la semilla de cada ensayo depende solo de (escenario, tipo, rep), el plan reducido es un **subconjunto idéntico** del de 570 (mismas semillas, δ y orden) y los ensayos ya ejecutados se conservaron. El costo es estadístico: ver "Estadística" y "Amenazas a la validez".

- **P0 con conflicto** sigue la misma línea de tiempo, pero sin aplicar ningún corte. Mide el comportamiento sin falla: A1 y A2 deberían dar siempre 1 confirmada + 1 rechazada, y A3 puede dar doble asignación cuando δ es menor que el retardo de sincronización. M1, M2 y M6 se calculan también en P0.
- Cada ensayo dura unos 22–51 s: el monitor termina en cuanto detecta el estado consistente, y como máximo en t = 51 s. Con la preparación, la corrida completa toma unas 2 horas de ejecución desatendida (~25 s por ensayo en la máquina usada). Si falta tiempo, se prioriza P1 y P2.
- **P0 (latencia):** 1 000 reservas consecutivas por arquitectura con la red sana.
- **Misma semilla** para las tres arquitecturas: reciben exactamente las mismas solicitudes, desfases y momentos de falla.

## Fuente de los datos

**Datos de entrada (sintéticos):** ambulancias e incidentes generados por el simulador. No se usan datos de pacientes ni de centrales reales. Los parámetros de escala para el E3 se calibran con fuentes públicas:

| Parámetro | Valor | Fuente |
|---|---|---|
| Ambulancias SAMU en Lima | 33 (19 operativas) | Chinchay, Franco y Rosas (2020) |
| Emergencias prioridad I–II sin ambulancia | 40 % | Chinchay, Franco y Rosas (2020) |

**Datos de salida:** un **log de eventos** en JSONL (una línea JSON por evento) por ensayo, en `resultados/logs/<arq>/<escenario>/ensayo_<n>.jsonl`. `t` es `time.time()` (todos los contenedores comparten el reloj del host) y los datos adicionales van en `extra`:

```json
{"t": 1731972003.004, "ensayo": 17, "arq": "A2", "escenario": "P1", "tipo": "con_conflicto", "centro": "A", "incidente": "I-1", "ambulancia": "AMB-01", "evento": "solicitud", "extra": {}}
{"t": 1731972003.091, "ensayo": 17, "arq": "A2", "escenario": "P1", "tipo": "con_conflicto", "centro": "A", "incidente": "I-1", "ambulancia": "AMB-01", "evento": "confirmada", "extra": {"lider": "etcd3", "t_solicitud": 1731972003.004, "t_respuesta": 0.087}}
{"t": 1731972013.120, "ensayo": 17, "arq": "A2", "escenario": "P1", "tipo": "con_conflicto", "centro": "B", "incidente": "I-2", "ambulancia": "AMB-01", "evento": "sin_confirmacion", "extra": {"t_solicitud": 1731972003.110, "t_respuesta": 10.010}}
```

Solo el **orquestador** escribe los archivos. Los servicios guardan sus eventos propios (`liberada`, `revertida`) en memoria; el orquestador los recoge al final del ensayo con `GET /admin/eventos` y los agrega conservando su `t` original.

Eventos posibles: `ensayo_inicio`, `corte_inicio`, `solicitud`, `confirmada`, `rechazada`, `sin_confirmacion`, `revertida`, `liberada`, `reserva_sin_aviso`, `corte_fin`, `estado_consistente`, `no_recuperado`, `ensayo_invalido`, `ensayo_fin`.

## Cálculo de cada métrica

Un script (`analizar.py`) lee los logs y clasifica cada ensayo:

| Métrica | Cálculo a partir de los eventos |
|---|---|
| M1 | ¿Hay dos `confirmada` de la misma ambulancia sin `liberada` entre ellas? → ensayo con doble asignación |
| M2 | ¿Hay exactamente un `confirmada` con `t − t_solicitud ≤ 10 s` y el ensayo no tiene doble asignación? → válido |
| M3 | `t` de la primera respuesta − `t` de la `solicitud`, por solicitud |
| M4 | p95 de (`confirmada` − `solicitud`) en P0 |
| M5 | `estado_consistente` − `corte_fin` |
| M6 | número de `revertida` ÷ número de `confirmada` |

**Estadística:**
- M1, M2 y M6 son proporciones: se reportan con **intervalo de confianza del 95 % (Wilson)**. Con 16 ensayos, un resultado de 0/16 tiene un límite superior de alrededor del 19 % (con los 30 del diseño original habría sido 11 %); en los ensayos sin conflicto (4 por celda), 0/4 deja un límite superior de alrededor del 49 %, por lo que esas celdas son solo descriptivas.
- M3, M4 y M5 se reportan con p50 y p95.
- Comparación A2 vs. A1 en M2: prueba exacta de Fisher sobre los conteos (se usa esta prueba porque las muestras son pequeñas).

## Resultados esperados (a contrastar en E3)

| Hipótesis | Métrica | Predicción | Si se cumple |
|---|---|---|---|
| **H1** | M2 en P1 | A2 > A1 (A1 ≈ 0 %) | A2 sigue despachando donde A1 se detiene |
| **H2** | M1 en P1 | A2 = 0 %, A3 cerca del 100 % en ensayos con conflicto | A2 mantiene la consistencia que A3 pierde |
| **H3** | M6 en A3 | > 0 % | El "despacho siempre disponible" de A3 tiene un costo oculto |
| **H4** | M4 en P0 | A2 > A1 | Costo del quórum en operación normal |

Si los resultados no coinciden con la predicción, también se reportan: el objetivo es medir el trade-off, no confirmar a A2.

## Fitness function

El invariante se convierte en una prueba automática de la arquitectura, que se ejecuta en cada cambio del prototipo:

> **FF-01:** ejecutar 10 ensayos de P1 con conflicto sobre A2. **Falla si M1 > 0 %** o si M3 p95 > 10 s.

Así, la propiedad principal de la arquitectura mejorada queda protegida contra regresiones.

## Amenazas a la validez

- **Una sola máquina:** las latencias reales entre sedes serían mayores y variables. Se mitiga con la latencia simulada de 20 ms.
- **Datos sintéticos:** los resultados describen el mecanismo de coordinación, no la operación real del SAMU.
- **A1 sin respaldo:** el respaldo comercial activo-pasivo no se modela porque su activación supera T.
- **Reloj compartido:** facilita la reconciliación de A3 frente a un despliegue real.
- **Instrumentación y tiempos medidos por el cliente:** M3 y M4 los mide el orquestador. Una primera versión del logger abría el archivo y hacía `fsync` en cada evento sobre el volumen montado desde Windows, lo que bloqueaba ~8 ms (hasta 50 ms) el bucle que mide los tiempos. Se corrigió antes de la corrida completa (archivo abierto durante el ensayo, sin `fsync`: ~0,1 ms por evento), y la prueba P0 se repitió con el logger corregido. Las mediciones con el logger anterior se apartaron en `resultados/descartados/`.
- **Margen de respuesta de 200 ms:** los servicios dejan de reintentar a los 9,8 s para que el despachador reciba `sin_confirmacion` antes de T. Una coordinación que solo se completara entre 9,8 s y 10 s cuenta como `sin_confirmacion`.
- **Tamaño de muestra reducido:** 16 ensayos con conflicto y 4 sin conflicto por celda, en lugar de 30 y 10 (ver "Tamaño del experimento"). Los intervalos de Wilson son más anchos y una proporción baja pero no nula (p. ej. una `reserva_sin_aviso` ocasional en A2-P3) se estima con poca precisión. Las diferencias principales esperadas (doble asignación de A3 frente a A1/A2, recuperación de A2 de ~12 s) son grandes, así que siguen siendo detectables con Fisher y Mann-Whitney con 16 por grupo.
- **Unos 0,3 s sin latencia al restaurar:** `docker network connect` restablece el enlace en cuanto se ejecuta, pero netem solo puede aplicarse después, sobre la interfaz nueva (unos 0,3 s más tarde). En ese intervalo el enlace funciona sin los 20 ms de retardo, lo que puede adelantar levemente la sincronización de A3 o la reconexión de Raft. `corte_fin` se registra justo **antes** del `connect` y el instante en que netem quedó aplicado va en `extra.t_netem`. Así el intervalo queda medido en cada ensayo.
