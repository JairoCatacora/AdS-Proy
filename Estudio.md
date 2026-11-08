# Estudio

El estudio analiza las opciones de arquitectura para coordinar el despacho entre dos centros, antes de elegir qué probar. Parte de los pain points en [UsuarioModelo.md](UsuarioModelo.md) y de lo que existe en el mercado del estado de arte en [Propuesta.md](Propuesta.md)).

## Criterios de evaluación

Los criterios salen directamente de los pain points priorizados:

| Criterio | Pain point | Pregunta |
|---|---|---|
| **Consistencia** | Ambulancia confirmada a dos incidentes; confirmaciones revertidas | ¿Puede confirmar la misma unidad dos veces? |
| **Disponibilidad del despacho** | El despacho se bloquea durante el corte | ¿Puede seguir confirmando durante el corte? |
| **Respuesta definitiva** | Espera sin respuesta | ¿El despachador sabe rápido si tiene o no la unidad? |
| **Punto único de falla** | Bloqueo total | ¿Un solo componente detiene todo el despacho? |
| **Costo en operación normal** | Lentitud | ¿Cuánta latencia añade sin falla? |
| **Complejidad** | Tiempo limitado del proyecto | ¿Qué tan difícil es implementarla y operarla? |

## Opciones analizadas

### A1 — Despacho centralizado
Un servidor central (con su base de datos) confirma cada reserva. Es el modelo de la mayoría de CAD actuales, reforzado con failover o respaldo en la nube.

- **A favor:** simple, consistencia fuerte, baja latencia sin falla.
- **En contra:** el servidor es un **punto único de falla**; si un centro pierde acceso, no puede despachar. El failover reduce el tiempo de caída, pero no evita que un centro aislado espere.

### A2 — Despacho replicado con líder y quórum
Varias réplicas mantienen el estado de la flota. Una reserva se confirma solo si la acepta la mayoría (algoritmo de consenso tipo Raft).

- **A favor:** consistencia fuerte (linealizable) sin depender de un solo servidor; el lado que conserva la mayoría sigue despachando.
- **En contra:** el lado minoritario **no puede despachar**; añade latencia por la ronda de votación; más componentes que operar.

### A3 — Despacho local con reconciliación
Cada centro tiene su propia copia, confirma localmente y sincroniza cuando vuelve la red, resolviendo conflictos con una regla (por ejemplo, gana la primera confirmación).

- **A favor:** máxima disponibilidad; ningún centro se bloquea.
- **En contra:** puede **confirmar la misma unidad a dos incidentes**; la reconciliación revierte confirmaciones ya comunicadas al despachador.

## Comparación cualitativa

| Criterio | A1 Centralizado | A2 Quórum | A3 Local |
|---|---|---|---|
| Consistencia | Alta | Alta | Baja |
| Disponibilidad durante el corte | Baja | Media (solo lado mayoritario) | Alta |
| Respuesta definitiva | Baja (espera) | Media | Alta, pero puede revertirse |
| Punto único de falla | Sí | No (mientras haya mayoría) | No |
| Latencia sin falla | Baja | Media | Baja |
| Complejidad | Baja | Media-alta | Media |
| Lado del teorema CAP | CP | CP | AP |

## Conclusiones del estudio

1. **No hay una opción que gane en todo:** A1 y A2 protegen la consistencia; A3 protege la disponibilidad. Es el trade-off CAP aplicado al despacho.
2. **A2 es la candidata más prometedora** en teoría: elimina el punto único de falla de A1 sin aceptar el riesgo de doble asignación de A3. Su debilidad (el lado minoritario) debe medirse, no suponerse.
3. **La comparación cualitativa no basta:** "media" o "alta" no dice cuántos despachos se pierden ni cuántas dobles asignaciones ocurren. Hace falta un prototipo que lo cuantifique bajo la misma falla.
4. **Las tres opciones se mantienen en la comparación** porque cada una representa un enfoque real del mercado o la literatura.
