"""Prueba unitaria del transporte de permisos mixto (design.md D10, tarea 6.4).

El transporte despacha por recurso: `apps` -> OBO; el resto del plano de control
(`clusters`, `serverless-compute`, `sql/warehouses`, `authorization/tokens`) ->
SP.
"""

from control_accesos.canales.reales.transporte_permisos_mixto import (
    TransportePermisosMixto,
)


class TransporteEspia:
    """Doble de transporte que registra el recurso de cada operación."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.llamadas = []

    def LeerAcl(self, recurso, identificador):
        self.llamadas.append(("leer", recurso, identificador))
        return ()

    def EscribirAcl(self, recurso, identificador, entradas):
        self.llamadas.append(("escribir", recurso, identificador))
        return None


def TestAppsUsaTransporteObo():
    """El recurso apps se atiende con el transporte OBO del llamante."""
    obo = TransporteEspia("obo")
    sp = TransporteEspia("sp")
    transporte = TransportePermisosMixto(obo, sp)

    transporte.LeerAcl("apps", "nombre-app")
    transporte.EscribirAcl("apps", "nombre-app", [])

    assert obo.llamadas == [
        ("leer", "apps", "nombre-app"),
        ("escribir", "apps", "nombre-app"),
    ]
    assert sp.llamadas == []


def TestRestoDelPlanoDeControlUsaTransporteSp():
    """Warehouses, clusters, serverless y tokens se atienden con el SP."""
    obo = TransporteEspia("obo")
    sp = TransporteEspia("sp")
    transporte = TransportePermisosMixto(obo, sp)

    for recurso, identificador in (
        ("sql/warehouses", "wh-1"),
        ("clusters", "cl-1"),
        ("serverless-compute", "sc-1"),
        ("authorization/tokens", ""),
    ):
        transporte.LeerAcl(recurso, identificador)
        transporte.EscribirAcl(recurso, identificador, [])

    assert obo.llamadas == []
    assert [l[1] for l in sp.llamadas] == [
        "sql/warehouses",
        "sql/warehouses",
        "clusters",
        "clusters",
        "serverless-compute",
        "serverless-compute",
        "authorization/tokens",
        "authorization/tokens",
    ]
