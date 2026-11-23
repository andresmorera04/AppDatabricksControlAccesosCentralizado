"""Pruebas unitarias de la clase `Principal` del modelo de dominio.

Cubren el requirement "Representación de principals" del spec
`grant-domain-model`: principal válido de cada tipo, tipo no soportado
rechazado con mensaje explícito (tipo recibido + tipos válidos) e
identificador vacío o nulo rechazado.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import Principal


def TestPrincipalUsuarioValido():
    """Un principal de tipo usuario con identificador válido se acepta."""
    principal = Principal(identificador="usuario_demo", tipo=TipoPrincipal.USUARIO)
    assert principal.identificador == "usuario_demo"
    assert principal.tipo is TipoPrincipal.USUARIO


def TestPrincipalGrupoValido():
    """Un principal de tipo grupo con identificador válido se acepta."""
    principal = Principal(identificador="grupo_analistas", tipo=TipoPrincipal.GRUPO)
    assert principal.tipo is TipoPrincipal.GRUPO


def TestPrincipalServicePrincipalValido():
    """Un principal de tipo service principal con identificador válido se acepta."""
    principal = Principal(
        identificador="sp_pipelines", tipo=TipoPrincipal.SERVICE_PRINCIPAL
    )
    assert principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL


def TestPrincipalDesdeTextoDeTipoValido():
    """Se acepta el valor en texto de un tipo válido y se normaliza al enum."""
    principal = Principal(identificador="usuario_demo", tipo="usuario")
    assert principal.tipo is TipoPrincipal.USUARIO


def TestPrincipalTipoNoSoportadoSeRechaza():
    """Un tipo fuera de la enumeración se rechaza con mensaje explícito."""
    with pytest.raises(ErrorDominio) as error:
        Principal(identificador="robot_demo", tipo="robot")

    mensaje = str(error.value)
    # El mensaje debe indicar el tipo recibido y los tipos válidos (spec).
    assert "robot" in mensaje
    assert "usuario" in mensaje
    assert "grupo" in mensaje
    assert "service_principal" in mensaje


def TestPrincipalIdentificadorVacioSeRechaza():
    """Un identificador vacío se rechaza con error explícito."""
    with pytest.raises(ErrorDominio, match="identificador"):
        Principal(identificador="", tipo=TipoPrincipal.USUARIO)


def TestPrincipalIdentificadorSoloEspaciosSeRechaza():
    """Un identificador de solo espacios se rechaza (equivale a vacío)."""
    with pytest.raises(ErrorDominio, match="identificador"):
        Principal(identificador="   ", tipo=TipoPrincipal.USUARIO)


def TestPrincipalIdentificadorNuloSeRechaza():
    """Un identificador nulo se rechaza con error explícito."""
    with pytest.raises(ErrorDominio, match="identificador"):
        Principal(identificador=None, tipo=TipoPrincipal.USUARIO)


def TestPrincipalIgualdadPorIdentificadorYTipo():
    """Dos principals con el mismo identificador y tipo son iguales."""
    primero = Principal(identificador="usuario_demo", tipo=TipoPrincipal.USUARIO)
    segundo = Principal(identificador="usuario_demo", tipo=TipoPrincipal.USUARIO)
    distinto_tipo = Principal(identificador="usuario_demo", tipo=TipoPrincipal.GRUPO)
    assert primero == segundo
    assert primero != distinto_tipo
