# Orquestador del experimento: Python 3.12 + cliente de Docker (para cortar redes).
FROM docker:27-cli AS docker-cli

FROM python:3.12-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# ping: verificación de cortes; procps: pgrep/pkill para ver o detener la corrida
# (repositorios de Debian por HTTPS, ver Dockerfile.servicio)
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY experimento/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt

COPY comun /app/comun
RUN pip install --no-cache-dir /app/comun

# El código de experimento/ y tests/ se monta como volumen (ver docker-compose.yml),
# así los cambios no requieren reconstruir la imagen.
ENV PYTHONPATH=/app/experimento \
    DIR_LOGS=/app/resultados/logs
