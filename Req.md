# Requerimientos

## Requerimientos funcionales

### Sistema de despacho

| ID | Requerimiento |
|---|---|
| **RF-01** | El sistema debe recibir incidentes ya regulados con identificador, prioridad (I o II), ubicación y centro de origen. |
| **RF-02** | El despachador debe poder solicitar la reserva de una ambulancia específica para un incidente. |
| **RF-03** | El sistema debe responder cada solicitud con un estado definitivo: **confirmada**, **rechazada** (unidad no disponible) o **sin confirmación** (no se pudo coordinar). Una solicitud no puede quedar sin respuesta indefinidamente. |
| **RF-04** | Una ambulancia solo puede tener **una reserva confirmada a la vez**. |
| **RF-05** | Si la unidad ya está reservada, el sistema debe rechazar la segunda solicitud para que el despachador busque otra unidad. |
| **RF-06** | El despachador y el jefe de guardia deben poder consultar el estado de cada ambulancia (disponible, reservada, en servicio, fuera de servicio). |
| **RF-07** | El despachador debe poder liberar una ambulancia al cerrar el servicio. |
| **RF-08** | Durante un corte, cada alternativa debe aplicar su política: A1 espera al servidor central; A2 confirma solo en el lado con mayoría; A3 confirma localmente. |
| **RF-09** | Al restablecerse la comunicación, el sistema debe reconciliar el estado y resolver conflictos con una regla fija y documentada (en A3: prevalece la primera confirmación; la otra se revierte y se notifica). |
| **RF-10** | El sistema debe notificar al despachador y al jefe de guardia cuando una confirmación se revierte. |
| **RF-11** | El sistema debe registrar cada evento (solicitud, confirmación, rechazo, reversión, liberación) con marca de tiempo, centro y nodo. |

### Entorno experimental

| ID | Requerimiento |
|---|---|
| **RF-12** | El simulador debe generar ensayos reproducibles por semilla, con las mismas solicitudes, unidades y momentos de falla para A1, A2 y A3. |
| **RF-13** | Cada ensayo con conflicto debe tener **una ambulancia disponible y dos incidentes simultáneos** en centros distintos, con un desfase aleatorio controlado entre solicitudes. |
| **RF-14** | El simulador debe incluir también ensayos **sin conflicto** (una sola solicitud durante el corte), para no favorecer artificialmente a ninguna alternativa. |
| **RF-15** | El entorno debe inyectar los escenarios de corte: **P1** (ambos centros sin autoridad central, uno con mayoría), **P2** (solo un centro aislado), **P3** (sin mayoría en ningún lado) y **P4** (red intermitente). |
| **RF-16** | El entorno debe calcular las métricas de cada ensayo a partir del registro de eventos, sin intervención manual. |

## Requerimientos no funcionales

| ID | Atributo | Requerimiento | Cómo se verifica |
|---|---|---|---|
| **RNF-01** | Consistencia | Ninguna ambulancia puede tener dos reservas confirmadas simultáneamente. Una confirmación revertida después cuenta como violación. | Tasa de doble asignación |
| **RNF-02** | Disponibilidad del despacho | El sistema debe confirmar una reserva válida dentro de un plazo **[X s, fijado y justificado antes de ejecutar las pruebas]**. | Tasa de despacho válido a tiempo |
| **RNF-03** | Respuesta al despachador | El despachador que pierde el conflicto debe recibir una respuesta definitiva en menos de **[X s]**. | Tiempo hasta respuesta definitiva |
| **RNF-04** | Latencia sin falla | La latencia p95 de confirmación en operación normal no debe superar **[X ms]**. | p95 sin falla |
| **RNF-05** | Recuperación | Tras restablecerse la comunicación, el sistema debe volver a un estado consistente en menos de **[X s]**. | Tiempo de recuperación |
| **RNF-06** | Observabilidad | Cada ensayo debe poder reconstruirse a partir de los registros. | Revisión de logs |
| **RNF-07** | Reproducibilidad | Misma semilla y configuración deben producir los mismos resultados. | Repetición de ensayos |
| **RNF-08** | Equivalencia de la comparación | Las tres alternativas deben exponer la misma interfaz y someterse a fallas equivalentes. | Revisión del diseño experimental |
| **RNF-09** | Seguridad | Solo despachadores autenticados pueden reservar o liberar unidades (alcance básico). | Prueba funcional |
