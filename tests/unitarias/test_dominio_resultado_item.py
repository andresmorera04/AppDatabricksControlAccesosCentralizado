"""Pruebas unitarias de la clase `ResultadoItem` del modelo de dominio.

Cubren el requirement "Resultado por ítem" del spec `grant-domain-model`:
construcción del resultado por cada estado (otorgado, fallido, privilegios
insuficientes), con el detalle del error presente en FALLIDO y la causa en
PRIVILEGIOS_INSUFICIENTES.
"""

import pytest

from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
)


def CrearItemDePrueba(privilegio="SELECT"):
    """Construye un ítem atómico de prueba con datos válidos.

    Args:
        privilegio (str): privilegio del ítem.

    Returns:
        ItemGrant: ítem listo para usar en las pruebas de resultado.
    """
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(
            identificador="control", tipo=TipoObjeto.CATALOGO
        ),
    )


def TestResultadoOtorgadoSeConstruye():
    """Un resultado otorgado conserva el ítem y su estado."""
    item = CrearItemDePrueba()
    resultado = ResultadoItem.Otorgado(item)
    assert resultado.estado is EstadoItem.OTORGADO
    assert resultado.item == item
    assert resultado.detalle is None


def TestResultadoFallidoConDetalle():
    """Un resultado fallido registra el detalle del error ocurrido (spec)."""
    item = CrearItemDePrueba()
    resultado = ResultadoItem.Fallido(
        item, detalle="El objeto no existe en el workspace."
    )
    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle


def TestResultadoFallidoRequiereDetalle():
    """Un resultado fallido sin detalle se rechaza: el detalle es obligatorio."""
    item = CrearItemDePrueba()
    with pytest.raises(ErrorDominio, match="detalle"):
        ResultadoItem.Fallido(item, detalle="")


def TestResultadoPrivilegiosInsuficientesConCausa():
    """Un resultado por privilegios insuficientes registra la causa (spec)."""
    item = CrearItemDePrueba()
    resultado = ResultadoItem.PrivilegiosInsuficientes(
        item, causa="PERMISSION_DENIED: el llamante no puede otorgar SELECT."
    )
    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "PERMISSION_DENIED" in resultado.detalle


def TestResultadoPrivilegiosInsuficientesRequiereCausa():
    """La causa es obligatoria en un resultado de privilegios insuficientes."""
    item = CrearItemDePrueba()
    with pytest.raises(ErrorDominio, match="causa"):
        ResultadoItem.PrivilegiosInsuficientes(item, causa="  ")


def TestResultadoConEstadoInvalidoSeRechaza():
    """El estado debe ser un miembro de `EstadoItem`, no un texto cualquiera."""
    item = CrearItemDePrueba()
    with pytest.raises(ErrorDominio, match="EstadoItem"):
        ResultadoItem(item=item, estado="otorgado_maybe", detalle=None)


def TestResultadoConItemInvalidoSeRechaza():
    """El resultado debe referenciar un `ItemGrant`, no un texto."""
    with pytest.raises(ErrorDominio, match="ItemGrant"):
        ResultadoItem(item="usuario_demo", estado=EstadoItem.OTORGADO, detalle=None)


def TestResultadoEsInmutable():
    """El resultado por ítem es inmutable (frozen dataclass)."""
    resultado = ResultadoItem.Otorgado(CrearItemDePrueba())
    with pytest.raises(Exception):
        resultado.estado = EstadoItem.FALLIDO
