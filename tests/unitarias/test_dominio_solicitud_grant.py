"""Pruebas unitarias de `SolicitudGrant` e `ItemGrant` del modelo de dominio.

Cubren el requirement "Solicitud de grant cardinalidad 1 a 1" del spec
`grant-domain-model`: solicitud válida con varios privilegios, rechazo de
lista de privilegios vacía, y rechazo explícito de la cardinalidad N a M
(fuera de alcance) antes de cualquier ejecución.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)


def CrearSolicitudDePrueba(privilegios=None):
    """Construye una solicitud 1 a 1 de prueba con datos válidos.

    Args:
        privilegios (list[str] | None): privilegios a usar; por defecto dos.

    Returns:
        SolicitudGrant: solicitud válida lista para procesar.
    """
    if privilegios is None:
        privilegios = ["SELECT", "USE CATALOG"]
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=privilegios,
        objeto=ObjetoSecurable(
            identificador="control", tipo=TipoObjeto.CATALOGO
        ),
    )


def TestSolicitudValidaConVariosPrivilegios():
    """Una solicitud con un principal, dos privilegios y un objeto se acepta."""
    solicitud = CrearSolicitudDePrueba()
    assert len(solicitud.privilegios) == 2
    assert solicitud.principal.identificador == "usuario_demo"
    assert solicitud.objeto.tipo is TipoObjeto.CATALOGO


def TestSolicitudSinPrivilegiosSeRechaza():
    """Una solicitud con lista de privilegios vacía se rechaza (spec)."""
    with pytest.raises(ErrorDominio, match="privilegios"):
        CrearSolicitudDePrueba(privilegios=[])


def TestPrivilegioVacioSeRechaza():
    """Un privilegio vacío o de solo espacios dentro de la lista se rechaza."""
    with pytest.raises(ErrorDominio, match="privilegio"):
        CrearSolicitudDePrueba(privilegios=["SELECT", "  "])


def TestPrivilegiosSeNormalizanAMayusculas():
    """Los privilegios se recortan y se normalizan a mayúsculas.

    Los privilegios de Databricks se escriben en mayúsculas (SELECT,
    USE CATALOG, CAN_USE); la normalización evita que una misma solicitud se
    trate como distinta por la escritura.
    """
    solicitud = CrearSolicitudDePrueba(privilegios=[" select ", "use catalog"])
    assert solicitud.privilegios == ("SELECT", "USE CATALOG")


def TestSolicitudConPrincipalInvalidoSeRechaza():
    """El principal debe ser una instancia de `Principal`, no un texto."""
    with pytest.raises(ErrorDominio, match="Principal"):
        SolicitudGrant.Crear(
            principal="usuario_demo",
            privilegios=["SELECT"],
            objeto=ObjetoSecurable(
                identificador="control", tipo=TipoObjeto.CATALOGO
            ),
        )


def TestSolicitudConObjetoInvalidoSeRechaza():
    """El objeto debe ser una instancia de `ObjetoSecurable`, no un texto."""
    with pytest.raises(ErrorDominio, match="ObjetoSecurable"):
        SolicitudGrant.Crear(
            principal=Principal(
                identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto="control",
        )


def TestSolicitudConCardinalidadNMSeRechaza():
    """Varios principals y varios objetos a la vez: N a M fuera de alcance."""
    principales = [
        Principal(identificador="usuario_a", tipo=TipoPrincipal.USUARIO),
        Principal(identificador="usuario_b", tipo=TipoPrincipal.USUARIO),
    ]
    objetos = [
        ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO),
        ObjetoSecurable(identificador="produccion", tipo=TipoObjeto.CATALOGO),
    ]
    with pytest.raises(ErrorDominio) as error:
        SolicitudGrant.CrearDesdeConjuntos(
            principales=principales,
            privilegios=["SELECT"],
            objetos=objetos,
        )

    mensaje = str(error.value)
    assert "N a M" in mensaje
    assert "fuera de alcance" in mensaje


def TestSolicitudConCardinalidadUnoANSeRechazaEnEstaVersion():
    """Un principal con varios objetos no es una solicitud 1 a 1 (es C5)."""
    with pytest.raises(ErrorDominio, match="1 a 1"):
        SolicitudGrant.CrearDesdeConjuntos(
            principales=[
                Principal(
                    identificador="usuario_a", tipo=TipoPrincipal.USUARIO
                )
            ],
            privilegios=["SELECT"],
            objetos=[
                ObjetoSecurable(
                    identificador="control", tipo=TipoObjeto.CATALOGO
                ),
                ObjetoSecurable(
                    identificador="produccion", tipo=TipoObjeto.CATALOGO
                ),
            ],
        )


def TestSolicitudConCardinalidadNUnoSeRechazaEnEstaVersion():
    """Varios principals con un objeto no es una solicitud 1 a 1 (es C5)."""
    with pytest.raises(ErrorDominio, match="1 a 1"):
        SolicitudGrant.CrearDesdeConjuntos(
            principales=[
                Principal(
                    identificador="usuario_a", tipo=TipoPrincipal.USUARIO
                ),
                Principal(
                    identificador="usuario_b", tipo=TipoPrincipal.USUARIO
                ),
            ],
            privilegios=["SELECT"],
            objetos=[
                ObjetoSecurable(
                    identificador="control", tipo=TipoObjeto.CATALOGO
                )
            ],
        )


def TestSolicitudDesdeConjuntosUnoAUnoSeAcepta():
    """Un principal y un objeto con varios privilegios sí es una solicitud 1 a 1."""
    solicitud = SolicitudGrant.CrearDesdeConjuntos(
        principales=[
            Principal(identificador="usuario_a", tipo=TipoPrincipal.USUARIO)
        ],
        privilegios=["SELECT", "USE CATALOG"],
        objetos=[
            ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
        ],
    )
    assert isinstance(solicitud, SolicitudGrant)
    assert len(solicitud.privilegios) == 2


def TestItemGrantEsLaUnidadAtomica():
    """`ItemGrant` representa un par principal-privilegio-objeto (unidad atómica)."""
    principal = Principal(
        identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
    )
    objeto = ObjetoSecurable(
        identificador="control", tipo=TipoObjeto.CATALOGO
    )
    item = ItemGrant(
        principal=principal, privilegio="SELECT", objeto=objeto
    )
    assert item.principal == principal
    assert item.privilegio == "SELECT"
    assert item.objeto == objeto


def TestItemGrantValidaSusCampos():
    """`ItemGrant` rechaza un privilegio vacío y tipos incorrectos."""
    principal = Principal(
        identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
    )
    objeto = ObjetoSecurable(
        identificador="control", tipo=TipoObjeto.CATALOGO
    )
    with pytest.raises(ErrorDominio, match="privilegio"):
        ItemGrant(principal=principal, privilegio="  ", objeto=objeto)
    with pytest.raises(ErrorDominio, match="Principal"):
        ItemGrant(principal="usuario_demo", privilegio="SELECT", objeto=objeto)
    with pytest.raises(ErrorDominio, match="ObjetoSecurable"):
        ItemGrant(principal=principal, privilegio="SELECT", objeto="control")
