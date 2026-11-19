"""Topología de cada arquitectura: qué contenedores hay en cada sitio, qué
redes existen y qué IP fija tiene cada contenedor en cada red.

- El orquestador solo habla por net_ctl, usando el nombre del contenedor
  (el DNS de Docker en net_ctl lo resuelve a su IP en esa red).
- Las IPs fijas de esta tabla deben coincidir con los docker-compose.yml.
  El inyector de fallas las usa para restaurar con `docker network connect --ip`,
  y la verificación de la F2 comprueba que coinciden con `docker inspect`.
"""

from dataclasses import dataclass

PUERTO = 8000
RED_CTL = "net_ctl"

# Escenarios: conjunto de enlaces cortados (idéntico para las tres arquitecturas).
ESCENARIOS = {
    "P0": (),
    "P1": ("ac", "bc", "ab", "bd"),
    "P2": ("ab", "bc", "bd"),
    "P3": ("ab", "ac", "ad", "bc", "bd"),
    "P4": ("ab", "bc", "bd"),          # intermitente: cortar/restaurar cada 2 s
}


@dataclass
class Arquitectura:
    nombre: str
    despachos: dict[str, str]                 # centro -> contenedor del servicio de despacho
    sitios: dict[str, list[str]]              # sitio -> todos sus contenedores
    redes_enlace: dict[str, str]              # enlace ("ab", ...) -> red Docker (solo las que existen)
    redes_sitio: dict[str, str]               # sitio -> red local del sitio (solo las que existen)
    ips: dict[str, dict[str, str]]            # contenedor -> {red: IP fija}
    reset: list[str]                          # contenedores a los que se llama /admin/reset
    fuente_estado: str                        # contenedor cuyo /ambulancias es el estado "real"

    def url(self, contenedor: str) -> str:
        return f"http://{contenedor}:{PUERTO}"

    def url_despacho(self, centro: str) -> str:
        return self.url(self.despachos[centro])

    def contenedores(self) -> list[str]:
        return [c for cs in self.sitios.values() for c in cs]

    def sitio_de(self, contenedor: str) -> str:
        return next(s for s, cs in self.sitios.items() if contenedor in cs)

    def en_red(self, red: str) -> list[str]:
        """Contenedores conectados (según la tabla) a una red."""
        return [c for c, redes in self.ips.items() if red in redes]

    def lado_a_cortar(self, enlace: str) -> list[str]:
        """Para cortar X–Y se desconectan de net_xy los contenedores del sitio X."""
        red = self.redes_enlace[enlace]
        sitio_x = enlace[0].upper()
        return [c for c in self.sitios[sitio_x] if red in self.ips.get(c, {})]


ARQUITECTURAS: dict[str, Arquitectura] = {
    "A1": Arquitectura(
        nombre="A1",
        despachos={"A": "a1-despacho-a", "B": "a1-despacho-b"},
        sitios={"A": ["a1-despacho-a"], "B": ["a1-despacho-b"],
                "C": ["a1-central-api", "a1-postgres"]},
        redes_enlace={"ac": "a1_net_ac", "bc": "a1_net_bc"},
        redes_sitio={"C": "a1_net_site_c"},
        ips={
            "a1-despacho-a": {"a1_net_ac": "10.1.13.10"},
            "a1-despacho-b": {"a1_net_bc": "10.1.23.20"},
            "a1-central-api": {"a1_net_ac": "10.1.13.30", "a1_net_bc": "10.1.23.30",
                               "a1_net_site_c": "10.1.103.30"},
            "a1-postgres": {"a1_net_site_c": "10.1.103.31"},
        },
        reset=["a1-central-api", "a1-despacho-a", "a1-despacho-b"],
        fuente_estado="a1-central-api",
    ),
    "A2": Arquitectura(
        nombre="A2",
        despachos={"A": "a2-despacho-a", "B": "a2-despacho-b"},
        sitios={"A": ["a2-despacho-a", "a2-etcd1"], "B": ["a2-despacho-b", "a2-etcd2"],
                "D": ["a2-etcd3"]},
        redes_enlace={"ab": "a2_net_ab", "ad": "a2_net_ad", "bd": "a2_net_bd"},
        redes_sitio={"A": "a2_net_site_a", "B": "a2_net_site_b"},
        ips={
            "a2-despacho-a": {"a2_net_site_a": "10.2.101.10"},
            "a2-despacho-b": {"a2_net_site_b": "10.2.102.20"},
            "a2-etcd1": {"a2_net_ab": "10.2.12.11", "a2_net_ad": "10.2.14.11",
                         "a2_net_site_a": "10.2.101.11"},
            "a2-etcd2": {"a2_net_ab": "10.2.12.21", "a2_net_bd": "10.2.24.21",
                         "a2_net_site_b": "10.2.102.21"},
            "a2-etcd3": {"a2_net_ad": "10.2.14.41", "a2_net_bd": "10.2.24.41"},
        },
        reset=["a2-despacho-a", "a2-despacho-b"],
        # Estado final: lectura linealizable a través de despacho-a (tras restaurar la red)
        fuente_estado="a2-despacho-a",
    ),
    "A3": Arquitectura(
        nombre="A3",
        despachos={"A": "a3-despacho-a", "B": "a3-despacho-b"},
        sitios={"A": ["a3-despacho-a"], "B": ["a3-despacho-b"]},
        redes_enlace={"ab": "a3_net_ab"},
        redes_sitio={},
        ips={
            "a3-despacho-a": {"a3_net_ab": "10.3.12.10"},
            "a3-despacho-b": {"a3_net_ab": "10.3.12.20"},
        },
        reset=["a3-despacho-a", "a3-despacho-b"],
        # No hay fuente única: tras reconciliar, ambos centros deben coincidir
        fuente_estado="a3-despacho-a",
    ),
}

# Miembros de etcd de A2: nombre del miembro -> contenedor (cliente en el puerto 2379)
ETCD_A2 = {"etcd1": "a2-etcd1", "etcd2": "a2-etcd2", "etcd3": "a2-etcd3"}
# "Lado" del líder en A2-P1
LIDER_LADO = {"A": "etcd1", "B": "etcd2"}
