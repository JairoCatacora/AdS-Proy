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

## Estado del arte

El estado del arte revisa la **literatura existente** sobre el problema: qué se ha estudiado del despacho de ambulancias, de sus sistemas y fallas, y de cómo mantener un recurso compartido consistente cuando la red se divide. Se organiza en cinco líneas de investigación y termina con la brecha que justifica la propuesta.

**Búsqueda:** Google Scholar, USENIX, VLDB, ACM, BMJ Open, PubMed Central y repositorios peruanos. Palabras clave: *computer-aided dispatch*, *ambulance dispatch*, *ambulance relocation*, *network partition*, *linearizability*, *coordination avoidance*, *disaster response disconnected operation*, *atención prehospitalaria SAMU Lima*.

### Fallas de los sistemas de despacho de ambulancias

- **Page, Williams y Boyd (1993)**, informe de la investigación oficial sobre la caída del sistema CAD del **London Ambulance Service** en 1992, el caso de falla más estudiado en ingeniería de software. El sistema *"dependía de información casi perfecta sobre la ubicación y el estado de los vehículos"*; con reportes de estado incompletos y ubicaciones erróneas produjo *"asignaciones erróneas de vehículos"* e incidentes perdidos. El servicio volvió a operar en papel.
- **Furniss y Blandford (2005)** analizan el despacho médico de emergencia como un sistema de **cognición distribuida**: la información sobre qué unidad está libre se reparte entre personas, pantallas y radio, y el despacho depende de que esa visión compartida sea correcta.

**Aporte al problema:** muestran que el riesgo central del despacho es **actuar sobre un estado incorrecto de la flota**. Es la misma causa que produce una doble asignación cuando dos centros dejan de ver el mismo estado.

**Límite:** estudian un solo centro y fallas de proceso o de datos, no un corte de red entre centros activos.

### Despacho y atención prehospitalaria en Lima

- **Pronatel (2019)**, perfil del Proyecto 911: documenta el proceso de la Central 106 (recepción, regulación, despacho) y concluye que las centrales 105, 106 y 116 **no tienen integración tecnológica**. Plantea un esquema de atención centralizada y **despacho descentralizado**.
- **Chinchay, Franco y Rosas (2020)**, tesis de maestría en Gestión Pública sobre la cobertura de atención prehospitalaria en Lima Metropolitana (2013–2019). En 2019, **el 40 % de las emergencias prioridad I y II no recibió ambulancia por falta de unidades**; de 33 ambulancias, solo 19 estaban operativas. El 17 % de los despachos terminó frustrado o cancelado, muchas veces por demora.
- **Ríos et al. (2021)**, Universidad del Pacífico: proponen optimizar la ruta de las ambulancias del SAMU con grafos (Dijkstra), por el impacto del tráfico de Lima en el tiempo de llegada.

**Aporte al problema:** la literatura local confirma que la **unidad disponible es un recurso escaso** y que la arquitectura futura contempla varios centros despachando. Competir por la última ambulancia es un escenario realista.

**Límite:** los estudios locales abordan capacidad, cobertura y rutas. Ninguno estudia la coordinación entre centros ni su comportamiento ante fallas de comunicación.

### Interoperabilidad entre centros de despacho

- **NHTSA (2022)**, *Current Status of CAD Interoperability*: en EE. UU., la mayoría de centros de emergencia **puede transferir una llamada, pero no los datos del CAD** a otro centro. Las barreras son el costo, los estándares voluntarios (APCO, NENA), códigos de estado distintos y la gobernanza. Los participantes esperan que la interoperabilidad mejore la ayuda mutua entre jurisdicciones.
- **Brown et al. (2006)**, sistema **WIISARD** para respuesta médica en desastres: cada cliente mantiene una copia local, trabaja desconectado y resuelve conflictos al reconectar (*rollback/replay*). En un simulacro con 100 pacientes, los conflictos fueron raros (1.3 %), pero **una partición prolongada rompió la coordinación del equipo**, porque los datos de un proveedor quedaban en su cola local sin llegar a los demás.

**Aporte al problema:** WIISARD es el antecedente más cercano a la alternativa **A3** (operar local y reconciliar) en un contexto médico. Evidencia que funciona para registrar datos, pero que durante el corte cada parte decide sin ver a las otras.

**Límite:** WIISARD registra pacientes, no reserva recursos exclusivos. Con un registro, un conflicto se resuelve fusionando datos. Con una ambulancia, un conflicto implica que un paciente se queda sin la unidad prometida.

### Asignación y reubicación de ambulancias

- **Brotcorne, Laporte y Semet (2003)** revisan los modelos de ubicación y reubicación de ambulancias, desde modelos de cobertura estáticos hasta dinámicos.
- **Becker et al. (2023)**, revisión de alcance (*BMJ Open*) de 21 estudios sobre reubicación dinámica (2012–2022): todos usan **simulación**, la métrica principal es el **tiempo de respuesta** y ninguno mide resultados clínicos.

**Aporte al problema:** es la línea más amplia sobre despacho, y valida el uso de **simulación** y de métricas por ensayo para comparar estrategias.

**Límite:** estos modelos asumen un **despachador único con una visión consistente de la flota**. Optimizan qué unidad enviar, no qué pasa cuando dos decisores no comparten el mismo estado.

### Consistencia de un recurso compartido ante particiones de red

| Trabajo | Aporte |
|---|---|
| **Herlihy y Wing (1990)** | Definen la **linealizabilidad**: el sistema se comporta como una sola copia. Formaliza la regla "una ambulancia, una reserva confirmada". |
| **Gilbert y Lynch (2002)** | Demuestran el **teorema CAP**: ante una partición no se puede tener a la vez consistencia y disponibilidad. Es el dilema entre A2 y A3. |
| **Brewer (2012)** | Precisa CAP: las particiones son raras, pero el diseño debe decidir explícitamente qué hacer durante ellas y cómo recuperarse. Justifica medir el tiempo de recuperación. |
| **Abadi (2012)** | Propone **PACELC**: aun sin partición existe un trade-off entre latencia y consistencia. Justifica H4. |
| **Ongaro y Ousterhout (2014)** | Presentan **Raft**: un líder replica cada operación y solo se confirma con mayoría. Es la base de A2. |
| **O'Neil (1986)** | Método **escrow**: repartir cantidades de un recurso entre nodos para operar sin coordinar. Base de la opción de propiedad por centro. |
| **Shapiro et al. (2011)** y **Kleppmann et al. (2019)** | **CRDTs** y software *local-first*: operar sin conexión y converger después. Base de A3. |
| **Bailis et al. (2013, 2014)** | Muestran qué garantías son posibles sin coordinación (*highly available transactions*) y el criterio de **invariant confluence**: una operación puede ejecutarse sin coordinar solo si no puede violar el invariante. Restricciones de unicidad como la nuestra **no lo cumplen**, por lo que requieren coordinación. |
| **Alquraan et al. (2018)** | Estudio empírico de **136 fallas por particiones de red** en 25 sistemas distribuidos de uso amplio (OSDI). **La mayoría tuvo efectos catastróficos**, como pérdida de datos y locks rotos. |

**Aporte al problema:** la teoría **predice** el comportamiento de cada alternativa. Bailis et al. anticipan que A3 puede violar la regla de una sola reserva, porque esa regla requiere coordinación. Gilbert y Lynch anticipan que A1 y A2 deben dejar de confirmar en algún lado. Alquraan et al. muestran que **las particiones son una causa real de fallas graves** incluso en sistemas maduros, y que conviene probarlas explícitamente.

**Límite:** son resultados generales, evaluados en bases de datos y benchmarks como TPC-C. **No cuantifican el costo en servicio** (despachos no confirmados) frente al riesgo (dobles asignaciones) en un dominio de emergencias.

### Síntesis y brecha

| Línea | Qué resuelve | Qué no cubre |
|---|---|---|
| Fallas de CAD (4.1) | El riesgo de despachar con un estado incorrecto de la flota | Cortes de red entre centros |
| Lima (4.2) | Escasez de unidades y despacho descentralizado | Coordinación entre centros ante fallas |
| Interoperabilidad (4.3) | Intercambio de datos y operación desconectada | Reserva de un recurso exclusivo |
| Reubicación (4.4) | Qué unidad enviar, por simulación | Varios decisores sin estado común |
| Consistencia (4.5) | Qué es posible en teoría ante una partición | Costo medido en despachos de emergencia |

**Brecha:** la literatura revisada estudia el despacho asumiendo una visión única de la flota, y estudia la consistencia ante particiones en sistemas genéricos. **No se encontró un estudio que mida, para el despacho de ambulancias, cuántas dobles asignaciones y cuántos despachos perdidos produce cada estrategia de coordinación cuando dos centros activos quedan incomunicados.** La propuesta ocupa ese espacio: aplica la teoría de 4.5 a un caso del dominio de 4.1–4.4 y lo mide por simulación, como hace la literatura de 4.4.

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
- **Herramientas tentativas:** contenedores Docker; PostgreSQL para A1; etcd para A2; base local por centro para A3; inyección de fallas con `docker network disconnect`/`connect` y latencia con `tc netem`; simulador en Python.
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

## Cambios respecto a la versión entregada (E1)

La versión entregada en E1 corresponde al tag `e1-entregado` (commit `66e9c35`, 7 de noviembre de 2026). Se puede comparar con `git diff e1-entregado -- docs/Propuesta.md`.

### Cambios en esta propuesta

| Sección | En E1 | Ahora | Motivo |
|---|---|---|---|
| **Estado del arte** | Revisión de **soluciones**: el CAD como sistema de referencia, la situación de las centrales en Lima, una tabla de productos del mercado (Motorola PremierOne, Hexagon OnCall, Stratus, la patente US8433763, CAD con modo offline), una tabla de base técnica (linealizabilidad, CAP, PACELC, Raft, CRDT) y la brecha | Revisión de **literatura** organizada en cinco líneas: fallas de los sistemas de despacho (London Ambulance Service 1992; Furniss y Blandford), despacho prehospitalario en Lima (Pronatel 2019; Chinchay, Franco y Rosas 2020; Ríos et al. 2021), interoperabilidad entre centros (NHTSA 2022; WIISARD), asignación y reubicación de ambulancias (Brotcorne et al.; Becker et al. 2023) y consistencia ante particiones (Herlihy y Wing; Gilbert y Lynch; Brewer; Abadi; Ongaro y Ousterhout; O'Neil; Shapiro et al.; Kleppmann et al.; Bailis et al.; Alquraan et al.). Cada línea indica su aporte y su límite, y termina en una tabla de síntesis y la brecha | El estado del arte debía revisar la literatura existente sobre el problema, no solo productos. La nueva versión justifica cada alternativa con trabajos publicados (p. ej. Bailis et al. predicen que A3 puede violar la unicidad) y sitúa la brecha frente a la literatura |
| **Plan de evaluación** (herramientas) | "inyección de fallas con Docker network o Toxiproxy" | "inyección de fallas con `docker network disconnect`/`connect` y latencia con `tc netem`" | Se descartó Toxiproxy: la latencia se aplica con `tc netem` en las interfaces de las redes de enlace (ver [DiseñoExperimento.md](DiseñoExperimento.md)) |

El resto de secciones (contexto, problema, pain points, pregunta e hipótesis, alternativas, alcance, métricas, temas del curso, riesgos y siguientes pasos) no cambió.

### Documentos nuevos desde E1

En E1 solo existían `Propuesta.md`, `Estudio.md`, `Req.md` y `UsuarioModelo.md` (los tres últimos no cambiaron; ahora están en `docs/`). Se agregaron:

| Documento | Contenido |
|---|---|
| [ArquitecturaBase.md](ArquitecturaBase.md) | A1 y los elementos comunes: topología, redes del banco de pruebas, interfaz, modelo de datos e invariante |
| [ArquitecturaMejorada.md](ArquitecturaMejorada.md) | A2 (quórum con etcd) y A3 (local con reconciliación), ADR y los hallazgos de la implementación |
| [Metricas.md](Metricas.md) | M1–M6, umbrales, escenarios, línea de tiempo del ensayo, tamaño del experimento, hipótesis y amenazas a la validez |
| [DiseñoExperimento.md](DiseñoExperimento.md) | Cómo se ejecuta el experimento: entorno, preparación, monitor, orquestador, criterios de invalidez y resultados |

### Decisiones tomadas al implementar el banco de pruebas

Están detalladas en los documentos anteriores. Las que cambian lo que se mide respecto de lo planteado en E1:

- **P0 con conflicto** como línea base sin falla; el diseño pasó de 480 a 570 ensayos (30 con conflicto y 10 sin conflicto por celda) y, por tiempo, la corrida final se hizo con **288 ensayos** (16 con conflicto y 4 sin conflicto por celda; ver `Metricas.md`, "Tamaño del experimento").
- **Quién pide primero se alterna** entre A y B, y en A2-P1 también la posición del líder (etcd1 o etcd2).
- **M4 de A2** se reporta por posición del líder (local o remota al centro que pide); **M4 de A3** mide solo la reserva local.
- **Reserva sin aviso** se revisa en las tres arquitecturas.
- **Hallazgos ya documentados:** A3 asigna dos veces incluso sin falla cuando δ es menor que el retardo de sincronización; en A2 el nodo aislado tarda ~12 s en recuperarse por el retroceso de retransmisión de TCP; y en A2-P3 puede quedar una reserva sin aviso.
