# Propuesta

**Tema:** Despacho de una ambulancia compartida durante un corte de comunicación entre dos centros

---

## Contexto

En Lima Metropolitana y Callao, las emergencias médicas prehospitalarias las atiende la **Central 106 del SAMU** (MINSA). Tomamos como referencia su proceso, documentado por Pronatel en el perfil del Proyecto 911:

1. **Recepción:** el operador de emergencia atiende la llamada y registra una ficha.
2. **Regulación médica:** el médico regulador asigna la prioridad. Prioridad III–IV recibe orientación telefónica; **prioridad I–II requiere ambulancia**.
3. **Despacho:** el despachador elige la unidad más cercana y la envía.
4. **Atención y traslado:** la ambulancia atiende y, si corresponde, traslada al paciente.
5. **Seguimiento:** el jefe de guardia supervisa cada incidencia hasta su cierre.

La propuesta se concentra en la etapa **3 (Despacho)**, en el momento en que el sistema **reserva y confirma** una ambulancia.

Tres hechos del contexto hacen relevante el problema:

- **Centrales sin integración:** según el diagnóstico de Pronatel, las centrales 105, 106 y 116 no integran sus plataformas y coordinan por radio o teléfono.
- **Despacho descentralizado:** el Proyecto 911 evalúa un esquema de atención centralizada y despacho descentralizado, con varios centros despachando sobre recursos compartidos.
- **Flota reducida:** reportes de prensa hablan de alrededor de dos decenas de ambulancias SAMU para más de 10 millones de habitantes, por lo que competir por la última unidad disponible es plausible.

## Problema

Cuando dos centros pueden despachar sobre la misma flota y **se corta la comunicación** entre ellos justo cuando dos incidentes graves compiten por la **última ambulancia disponible**, el sistema debe elegir entre:

- **Seguir despachando**, con el riesgo de confirmar la misma ambulancia a dos incidentes; o
- **Bloquear el despacho**, con el riesgo de no enviar ninguna a tiempo.

**Caso único de estudio:** dos centros reciben casi al mismo tiempo un incidente prioridad I–II cada uno, queda una sola ambulancia disponible y en ese momento se corta la comunicación entre ellos.

## Pain points que aborda

| Pain point | Usuario | Atributo de calidad |
|---|---|---|
| Una ambulancia confirmada a dos incidentes | Despachador, paciente | Consistencia |
| El despacho se bloquea durante el corte | Despachador, paciente | Disponibilidad |
| Espera sin respuesta definitiva | Despachador | Confiabilidad |
| Confirmaciones que se revierten después | Despachador, jefe de guardia | Consistencia |
| Falta de trazabilidad tras la falla | Jefe de guardia | Observabilidad |

## Qué existe hoy

Los centros de emergencia usan sistemas **CAD** (despacho asistido por computadora). Los productos del mercado resuelven la resiliencia sobre todo con **redundancia del sistema central y conmutación a un respaldo**:

- **Motorola PremierOne CAD** ofrece un CAD completo en la nube como recuperación ante desastres y un cliente web de continuidad.
- **Hexagon HxGN OnCall Dispatch** ofrece diseño redundante en la nube y un cliente de despacho de contingencia.
- Existen enfoques de **operación local**: una patente de CAD (US8433763) donde las estaciones intercambian datos entre sí si cae el gestor central, y CAD con modo offline.

En la base técnica, la **linealizabilidad** define formalmente "una ambulancia, una reserva confirmada"; el **consenso Raft** permite que solo el lado con mayoría confirme; y la **replicación optimista** permite operar sin coordinación a costa de conflictos.

**Brecha:** la documentación pública revisada describe la continuidad del sistema completo, pero no mide qué ocurre con **reservas concurrentes de la misma unidad** cuando **dos centros activos** quedan incomunicados. Esa es la pregunta que aborda esta propuesta.

## Pregunta e hipótesis

**Pregunta:** ¿qué arquitectura de coordinación permite confirmar un despacho a tiempo durante un corte de comunicación entre dos centros sin asignar la misma ambulancia a dos incidentes?

**Escenario principal (P1):** ambos centros pierden acceso a la autoridad central y uno de ellos conserva acceso a un líder con mayoría.

- **H1:** A2 logra una tasa de despacho válido a tiempo **mayor** que A1.
- **H2:** A2 mantiene una tasa de doble asignación de **0 %**, menor que A3.

**Secundarias:**

- **H3:** A3 registra más confirmaciones durante el corte, pero parte de ellas se revierte al reconciliar.
- **H4:** sin falla, A2 añade latencia de confirmación respecto de A1 (costo del quórum).

**Prueba separada (P2):** si solo se aísla un centro, el otro aún puede confirmar con A1. Se reporta aparte.

## Alternativas a comparar

Seleccionadas en [Estudio.md](Estudio.md); cada una representa un enfoque real del mercado o la literatura.

| ID | Alternativa | Ante el corte | Referente |
|---|---|---|---|
| **A1** | Centralizado | El centro sin acceso al servidor espera | CAD con failover / respaldo en nube |
| **A2** | Replicado con quórum | Solo el lado con mayoría confirma | Raft (etcd) |
| **A3** | Local con reconciliación | Ambos confirman y se resuelve al volver la red | Modo offline, patente entre pares |

## Alcance

**Incluido**
- La etapa de despacho: solicitud, reserva y confirmación de una ambulancia ya regulada como prioridad I–II.
- Dos centros de despacho y una flota simulada compartida.
- Cortes de comunicación entre centros, autoridad central y réplicas.
- Prototipo con datos sintéticos y medición automática.

**Fuera de alcance**
- Recepción de llamadas y regulación médica (el incidente llega ya registrado y priorizado).
- Política de prioridad clínica y elección de la unidad más cercana (idénticas en las tres alternativas).
- Rutas, tráfico y tiempos de traslado.
- Integración con sistemas reales (Aplicativo SAMU, DISAMU).

**Actores del prototipo:** el **despachador** solicita la reserva; el **jefe de guardia** consulta estados y conflictos; el **sistema de coordinación** confirma según A1, A2 o A3; el **evaluador** configura ensayos e inyecta cortes.

## Métricas

| Métrica | Tipo | Cálculo |
|---|---|---|
| **Tasa de doble asignación** | Principal | Ensayos con dos confirmaciones simultáneas para la misma ambulancia ÷ total × 100 |
| **Tasa de despacho válido a tiempo** | Principal | Ensayos con exactamente una confirmación dentro del plazo y sin doble asignación ÷ total × 100 |
| Tiempo hasta respuesta definitiva | Secundaria | Desde la solicitud del segundo despachador hasta recibir rechazo o "sin confirmación" |
| Latencia p95 sin falla | Secundaria | Confirmación en operación normal |
| Tiempo de recuperación | Secundaria | Desde que vuelve la red hasta un estado consistente |

## Plan de evaluación

- **Ensayo:** una ambulancia disponible, dos incidentes en centros distintos con un desfase aleatorio controlado, y un corte que empieza en un momento fijado.
- **Ensayos sin conflicto:** una sola solicitud durante el corte, para no favorecer a ninguna alternativa.
- **Escenarios de corte:** P1 (hipótesis principal), P2 (un solo centro aislado), P3 (sin mayoría), P4 (red intermitente).
- **Equivalencia:** mismas solicitudes, unidades, semilla y momento de falla para A1, A2 y A3.
- **Repeticiones:** varias decenas de ensayos por alternativa y escenario, con intervalos de confianza.
- **Herramientas tentativas:** contenedores Docker; PostgreSQL para A1; etcd para A2; base local por centro para A3; inyección de fallas con Docker network o Toxiproxy; simulador en Python.
- **Plazo de despacho y umbrales:** se fijan y justifican antes de ejecutar las pruebas.

## Temas del curso que se aplican

| Tema | Dónde aparece |
|---|---|
| Modelado de usuarios y pain points | Usuario modelo y sección 3 |
| Requerimientos funcionales y no funcionales | Documento de requerimientos |
| Pruebas de concepto | Prototipo comparativo de A1, A2 y A3 |
| Confiabilidad | Comportamiento ante cortes de red |
| Bottlenecks y single points of failure | El servidor central de A1 |
| Consistencia, linealizabilidad y CAP | Regla de "una ambulancia, una reserva confirmada"; CP vs. AP |
| Monitoreo / logging | Registro de eventos para calcular métricas |
| Fitness functions | Las métricas principales pueden automatizarse como pruebas de la arquitectura |

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Que el experimento parezca armado a favor de A2 | Incluir ensayos sin conflicto y escenarios donde A2 pierde (P3, lado minoritario) |
| Configuración compleja de A2 | Usar etcd en lugar de implementar consenso a mano |
| Resultados no generalizables al SAMU real | Presentarlos como comportamiento del prototipo con datos sintéticos |
| Tiempo limitado (12 h) | Acotar a un solo flujo y dos centros |

## Aporte esperado y siguientes pasos

**Aporte:** evidencia medida de qué gana y qué sacrifica cada arquitectura cuando dos centros quedan incomunicados, y una recomendación de cuándo conviene cada una para el despacho de emergencias.

- **E2 (Semana 14):** arquitectura básica de las tres alternativas, métricas y umbrales finales, y línea base con A1.
- **E3 (Semana 15):** resultados de todos los escenarios, arquitectura recomendada y paper final.
