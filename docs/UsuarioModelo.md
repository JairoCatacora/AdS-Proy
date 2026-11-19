# Usuario modelo

## Mapa de usuarios

| Usuario | Relación con el sistema | Prioridad para el proyecto |
|---|---|---|
| **Despachador** | Reserva y confirma la ambulancia | **Usuario principal** |
| **Jefe de guardia** | Supervisa incidencias y resuelve conflictos | Usuario secundario |
| **Paciente / llamante** | Recibe (o no) la ambulancia | Usuario afectado (indirecto) |
| Operador de emergencia y médico regulador | Entregan el incidente ya registrado y priorizado | Fuera del alcance del prototipo |

---

## Persona 1: Despachadora (usuario principal)

**Rosa, 34 años, despachadora de la Central 106 (turno noche).**

- **Contexto:** recibe del médico regulador los casos prioridad I–II y debe enviar la unidad más cercana. En turno noche trabajan pocos despachadores para todo Lima.
- **Objetivo:** confirmar una ambulancia en el menor tiempo posible y saber con certeza que va en camino.
- **Herramientas:** sistema de despacho, mapa de ubicación de unidades, radio.

**Pain points**
1. **Incertidumbre sobre la confirmación:** si el sistema no responde, no sabe si la ambulancia quedó asignada o no.
2. **Esperas sin respuesta:** una pantalla "cargando" durante un corte es peor que un "no disponible", porque no le permite buscar otra unidad.
3. **Asignaciones que se revierten:** que una unidad confirmada se le quite después la obliga a reiniciar el despacho con el paciente ya esperando.
4. **Coordinación manual:** si el sistema falla, debe confirmar por radio o teléfono con otro centro, lo que consume minutos.

---

## Persona 2: Jefe de guardia (usuario secundario)

**Luis, 46 años, médico jefe de guardia.**

- **Contexto:** supervisa todas las incidencias abiertas del turno hasta su cierre.
- **Objetivo:** que ningún caso grave quede sin atender y que los recursos se usen bien.

**Pain points**
1. **Falta de visibilidad durante fallas:** no sabe qué centro asignó qué unidad mientras dura el corte.
2. **Conflictos descubiertos tarde:** se entera de una doble asignación cuando la ambulancia ya está en ruta hacia uno de los dos incidentes.
3. **Sin trazabilidad:** después de un incidente no puede reconstruir quién confirmó qué y cuándo.

---

## Persona 3: Familiar del paciente (usuario afectado)

**Carmen, 58 años, llama al 106 porque su esposo tiene dolor de pecho intenso.**

- **Objetivo:** que llegue una ambulancia lo antes posible.

**Pain points**
1. **Promesa incumplida:** le dicen que la ambulancia va en camino, pero nunca llega porque se asignó a otro caso.
2. **Demora:** cada minuto de espera aumenta la ansiedad y el riesgo para el paciente.
