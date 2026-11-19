"""Constantes compartidas por los servicios, el orquestador y el análisis."""

import os

# Plazo máximo de respuesta de toda solicitud (RF-03): T = 10 s.
PLAZO_T = 10.0

# El servicio deja de intentar coordinar MARGEN_RESPUESTA antes de T, para que el
# despachador reciba `sin_confirmacion` antes de T. Medido: entre que el manejador
# termina y la respuesta llega al cliente pasan 10–50 ms dentro del servicio
# (uvicorn); con 50 ms de margen, el cliente veía hasta 10,02 s.
MARGEN_RESPUESTA = 0.2

# Si falla la conexión con el coordinador, se reintenta cada 200 ms hasta agotar T.
INTERVALO_REINTENTO = 0.2

# Tiempo máximo para establecer una conexión en cada intento. Si se agota,
# se vuelve a intentar (mientras quede plazo).
TIMEOUT_CONEXION = 1.0

# Ambulancia que se disputan los dos centros en cada ensayo.
AMBULANCIA_ENSAYO = "AMB-01"

# Carpeta raíz de los logs (volumen compartido).
DIR_LOGS = os.environ.get("DIR_LOGS", "resultados/logs")

# Estados posibles de una respuesta a POST /reservas.
CONFIRMADA = "confirmada"
RECHAZADA = "rechazada"
SIN_CONFIRMACION = "sin_confirmacion"
ESTADOS_RESPUESTA = (CONFIRMADA, RECHAZADA, SIN_CONFIRMACION)

# Estados posibles de una ambulancia.
DISPONIBLE = "disponible"
RESERVADA = "reservada"

# Eventos válidos del log (sección 6 del prompt + `liberada`).
EVENTOS = frozenset({
    "ensayo_inicio",
    "corte_inicio",
    "solicitud",
    "confirmada",
    "rechazada",
    "sin_confirmacion",
    "revertida",
    "liberada",
    "reserva_sin_aviso",
    "corte_fin",
    "estado_consistente",
    "no_recuperado",
    "ensayo_invalido",
    "ensayo_fin",
})

# Tipos de ensayo.
CON_CONFLICTO = "con_conflicto"
SIN_CONFLICTO = "sin_conflicto"
