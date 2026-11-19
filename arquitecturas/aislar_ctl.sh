#!/bin/sh
# Punto de entrada de los contenedores del sistema bajo prueba.
#
# Aísla net_ctl: por esa red, este contenedor solo acepta tráfico del
# orquestador (IP fija 10.99.0.2). Así ningún servicio puede coordinarse
# con otro a través de net_ctl, aunque se equivoque de IP o de nombre.
set -e
ORQ="${IP_ORQUESTADOR:-10.99.0.2}"
IF_CTL=$(ip -o -4 addr show | awk '$4 ~ /^10\.99\./ {print $2}' | head -n 1)
if [ -n "$IF_CTL" ]; then
    iptables -A INPUT -i "$IF_CTL" -s "$ORQ" -j ACCEPT
    iptables -A INPUT -i "$IF_CTL" -j DROP
fi
exec "$@"
