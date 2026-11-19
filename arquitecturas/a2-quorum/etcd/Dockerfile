# Réplica etcd v3.5 de A2.
# La imagen oficial de etcd no trae `tc`; esta parte de Debian slim, copia los
# binarios oficiales y agrega iproute2 (netem), iptables (aislar net_ctl) y ping.
FROM gcr.io/etcd-development/etcd:v3.5.36 AS etcd-oficial

# python:3.12-slim es Debian (trixie) slim y ya trae ca-certificates, necesario para
# usar los repositorios por HTTPS (en esta red el HTTP plano es interceptado).
# Además comparte capas con la imagen de los servicios.
FROM python:3.12-slim
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends iproute2 iptables iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY --from=etcd-oficial /usr/local/bin/etcd /usr/local/bin/etcdctl /usr/local/bin/

# Mismo punto de entrada que los demás servicios: aísla net_ctl y luego arranca etcd.
COPY arquitecturas/aislar_ctl.sh /usr/local/bin/aislar_ctl.sh
RUN sed -i 's/\r$//' /usr/local/bin/aislar_ctl.sh && chmod +x /usr/local/bin/aislar_ctl.sh
ENTRYPOINT ["/usr/local/bin/aislar_ctl.sh"]
CMD ["etcd"]
