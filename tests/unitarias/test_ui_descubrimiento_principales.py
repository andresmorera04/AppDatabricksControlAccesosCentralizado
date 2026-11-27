"""Prueba unitaria del descubrimiento de principals de la UI (design.md D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 3.1.

Contrato que fija esta prueba, sobre el adaptador SCIM con el service principal
(`DescubridorPrincipales`, change broker) y su traducción a `Principal` del
dominio:

- usuarios, grupos y service principals se traducen a `Principal` con su tipo e
  identificador correctos;
- el App Id del service principal se preserva como identificador;
- el agregado conserva un orden estable (usuarios, luego grupos, luego service
  principals) y el orden del servicio dentro de cada tipo;
- el límite configurable acota el listado (paginación acotada sin asumir una
  sola página);
- un fallo del listado se traduce a `ErrorDescubrimientoOpciones`, distinguible
  de una lista auténticamente vacía (que se devuelve como tupla vacía).

No hay red ni SDK real: el cliente SCIM del SP es un doble con `list()` por
servicio (usuarios, grupos y service principals).
"""

from types import SimpleNamespace

import pytest

from control_accesos.canales.reales.descubrimiento_principales import (
    DescubridorPrincipales,
)
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.dominio.modelos import Principal
from control_accesos.ui.servicio_descubrimiento import (
    ErrorDescubrimientoOpciones,
    ServicioDescubrimientoUi,
)

# Identificadores y nombres de prueba (sin valores reales de workspace).
USUARIO_UNO = "usuario.uno@example.com"
NOMBRE_USUARIO_UNO = "Usuario Uno"
GRUPO_UNO = "analistas"
APP_ID_UNO = "app-id-00000000-0000-0000-0000-000000000001"
NOMBRE_SP_UNO = "App Uno"


def _Registro(**campos):
    """Doble de un registro SCIM: los campos se exponen como atributos."""
    return SimpleNamespace(**campos)


class ServicioScimFalso:
    """Doble de un servicio SCIM (`users`/`groups`/`service_principals`)."""

    def __init__(self, registros=(), excepcion=None):
        self._registros = registros
        self._excepcion = excepcion

    def list(self):
        if self._excepcion is not None:
            raise self._excepcion
        return self._registros


class ClienteScimFalso:
    """Cliente SCIM falso con los tres servicios que consume el descubridor."""

    def __init__(self, usuarios=(), grupos=(), service_principals=()):
        self.users = usuarios
        self.groups = grupos
        self.service_principals = service_principals


def _CrearServicio(
    usuarios=(),
    grupos=(),
    service_principals=(),
    limite=None,
    excepcion=None,
):
    """Construye el servicio UI sobre un descubridor real y un cliente falso.

    Args:
        usuarios/grupos/service_principals: servicios SCIM falsos (registros o
            llamables).
        limite (int | None): tope del descubridor.
        excepcion: excepción que lanza `list()` de los tres servicios.

    Returns:
        ServicioDescubrimientoUi: servicio con dobles sin red.
    """
    usuario_svc = usuarios if isinstance(usuarios, ServicioScimFalso) else ServicioScimFalso(usuarios, excepcion)
    grupo_svc = grupos if isinstance(grupos, ServicioScimFalso) else ServicioScimFalso(grupos, excepcion)
    sp_svc = service_principals if isinstance(service_principals, ServicioScimFalso) else ServicioScimFalso(service_principals, excepcion)
    cliente = ClienteScimFalso(usuario_svc, grupo_svc, sp_svc)
    descubridor = DescubridorPrincipales(cliente=cliente, limite=limite)
    return ServicioDescubrimientoUi(descubridor_principales=descubridor)


def TestUsuariosSeTraducenAPrincipal():
    """Los usuarios SCIM se traducen a `Principal` con tipo e identificador."""
    servicio = _CrearServicio(
        usuarios=[_Registro(user_name=USUARIO_UNO, display_name=NOMBRE_USUARIO_UNO)],
    )

    principales = servicio.DescubrirUsuarios()

    assert len(principales) == 1
    principal = principales[0]
    assert isinstance(principal, Principal)
    assert principal.tipo == TipoPrincipal.USUARIO
    assert principal.identificador == USUARIO_UNO


def TestServicePrincipalPreservaAppId():
    """El App Id del service principal se preserva como identificador."""
    servicio = _CrearServicio(
        service_principals=[
            _Registro(application_id=APP_ID_UNO, display_name=NOMBRE_SP_UNO),
        ],
    )

    principales = servicio.DescubrirServicePrincipals()

    assert len(principales) == 1
    assert principales[0].tipo == TipoPrincipal.SERVICE_PRINCIPAL
    assert principales[0].identificador == APP_ID_UNO, (
        "El identificador del service principal debe ser su App Id (design D4)."
    )


def TestAgregadoConservaOrdenEstable():
    """El agregado ordena usuarios, luego grupos y luego service principals."""
    servicio = _CrearServicio(
        usuarios=[_Registro(user_name=USUARIO_UNO)],
        grupos=[_Registro(display_name=GRUPO_UNO)],
        service_principals=[_Registro(application_id=APP_ID_UNO)],
    )

    principales = servicio.DescubrirPrincipales()

    assert [p.tipo for p in principales] == [
        TipoPrincipal.USUARIO,
        TipoPrincipal.GRUPO,
        TipoPrincipal.SERVICE_PRINCIPAL,
    ]
    assert [p.identificador for p in principales] == [USUARIO_UNO, GRUPO_UNO, APP_ID_UNO]


def TestLimiteConfigurableAcotaElListado():
    """El límite configurable recorta el listado sin asumir una sola página."""
    usuarios = [
        _Registro(user_name=f"usuario.{indice}@example.com")
        for indice in range(5)
    ]
    servicio = _CrearServicio(usuarios=usuarios, limite=2)

    principales = servicio.DescubrirUsuarios()

    assert len(principales) == 2
    assert [p.identificador for p in principales] == [
        "usuario.0@example.com",
        "usuario.1@example.com",
    ]


def TestFalloDeListadoEsDistinguibleDeListaVacia():
    """Un fallo del listado eleva error; el vacío auténtico, tupla vacía."""
    servicio_con_fallo = _CrearServicio(
        excepcion=RuntimeError("SCIM sin scope"), usuarios=()
    )
    with pytest.raises(ErrorDescubrimientoOpciones):
        servicio_con_fallo.DescubrirUsuarios()

    servicio_vacio = _CrearServicio(usuarios=(), grupos=(), service_principals=())
    assert servicio_vacio.DescubrirUsuarios() == ()
    assert servicio_vacio.DescubrirGrupos() == ()
    assert servicio_vacio.DescubrirServicePrincipals() == ()
    assert servicio_vacio.DescubrirPrincipales() == ()
