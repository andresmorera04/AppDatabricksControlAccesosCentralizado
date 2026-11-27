"""Prueba unitaria del servicio de solicitud de grants de la UI (design.md D2).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.1.

Contrato que fija esta prueba, sobre los modelos del dominio y la
`ConsultoraMatrizPrivilegios`:

- 1 a 1 con un único privilegio o varios -> `SolicitudGrant`;
- 1 a N (un principal, varios objetos) y N a 1 (varios principals, un objeto)
  -> `SolicitudLoteGrant`, con privilegios en forma canónica;
- N a M se rechaza **antes de pre-flight** con `ErrorSolicitudUi`;
- conjuntos vacíos se rechazan con mensaje específico por conjunto;
- un único tipo de objeto por solicitud (tipos mezclados -> error);
- identificadores inválidos se rechazan (principal/objeto sin identificación
  de dominio válida);
- una combinación privilegio x tipo fuera de la matriz se rechaza con el
  mensaje preciso de la consultora.

No hay pipeline ni ejecución: el servicio solo construye y valida.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.ui.servicio_solicitud import (
    ErrorSolicitudUi,
    ServicioSolicitudGrantsUi,
)

USUARIO_UNO = "usuario.uno@example.com"
USUARIO_DOS = "usuario.dos@example.com"
CATALOGO_A = "ventas"
CATALOGO_B = "finanzas"


def _Principal(identificador=USUARIO_UNO):
    return Principal(identificador=identificador, tipo=TipoPrincipal.USUARIO)


def _Catalogo(nombre):
    return ObjetoSecurable(identificador=nombre, tipo=TipoObjeto.CATALOGO)


def _Tabla(nombre):
    return ObjetoSecurable(identificador=nombre, tipo=TipoObjeto.TABLA_DELTA)


def TestSolicitud1A1ConVariosPrivilegios():
    """Un principal, un objeto y varios privilegios -> SolicitudGrant."""
    servicio = ServicioSolicitudGrantsUi()

    solicitud = servicio.Construir(
        [_Principal()], ["SELECT", "READ METADATA"], [_Catalogo(CATALOGO_A)]
    )

    assert isinstance(solicitud, SolicitudGrant)
    assert solicitud.principal.identificador == USUARIO_UNO
    assert solicitud.objeto.identificador == CATALOGO_A
    assert tuple(solicitud.privilegios) == ("SELECT", "READ METADATA")


def TestSolicitud1AN():
    """Un principal y varios objetos -> SolicitudLoteGrant."""
    servicio = ServicioSolicitudGrantsUi()

    solicitud = servicio.Construir(
        [_Principal()],
        ["SELECT"],
        [_Catalogo(CATALOGO_A), _Catalogo(CATALOGO_B)],
    )

    assert isinstance(solicitud, SolicitudLoteGrant)
    assert len(solicitud.objetos) == 2


def TestSolicitudNA1():
    """Varios principals y un objeto -> SolicitudLoteGrant."""
    servicio = ServicioSolicitudGrantsUi()

    solicitud = servicio.Construir(
        [_Principal(USUARIO_UNO), _Principal(USUARIO_DOS)],
        ["SELECT"],
        [_Catalogo(CATALOGO_A)],
    )

    assert isinstance(solicitud, SolicitudLoteGrant)
    assert len(solicitud.principales) == 2


def TestSolicitudNAmRechazadaAntesDePreFlight():
    """N a M se rechaza en la solicitud, antes de cualquier pre-flight."""
    servicio = ServicioSolicitudGrantsUi()

    with pytest.raises(ErrorSolicitudUi) as informacion:
        servicio.Construir(
            [_Principal(USUARIO_UNO), _Principal(USUARIO_DOS)],
            ["SELECT"],
            [_Catalogo(CATALOGO_A), _Catalogo(CATALOGO_B)],
        )

    assert "N a M" in str(informacion.value) or "fuera de alcance" in str(
        informacion.value
    )


def TestConjuntosVacios():
    """Cada conjunto vacío se rechaza con su mensaje específico."""
    servicio = ServicioSolicitudGrantsUi()

    with pytest.raises(ErrorSolicitudUi, match="principal"):
        servicio.Construir([], ["SELECT"], [_Catalogo(CATALOGO_A)])
    with pytest.raises(ErrorSolicitudUi, match="privilegio"):
        servicio.Construir([_Principal()], [], [_Catalogo(CATALOGO_A)])
    with pytest.raises(ErrorSolicitudUi, match="objeto"):
        servicio.Construir([_Principal()], ["SELECT"], [])


def TestUnicoTipoDeObjeto():
    """Múltiples objetos con tipos distintos se rechazan."""
    servicio = ServicioSolicitudGrantsUi()

    with pytest.raises(ErrorSolicitudUi, match="único tipo"):
        servicio.Construir(
            [_Principal()], ["SELECT"], [_Catalogo(CATALOGO_A), _Tabla("t_1")]
        )


def TestIdentificadoresInvalidos():
    """Principal u objeto sin identificación de dominio válida se rechazan."""
    servicio = ServicioSolicitudGrantsUi()

    with pytest.raises(ErrorSolicitudUi, match="[Pp]rincipal"):
        servicio.Construir(
            [USUARIO_UNO],  # cadena cruda, no Principal (libre-texto sin validar)
            ["SELECT"],
            [_Catalogo(CATALOGO_A)],
        )
    with pytest.raises(ErrorSolicitudUi, match="[Oo]bjeto"):
        servicio.Construir(
            [_Principal()], ["SELECT"], ["ventas"]  # cadena cruda, no objeto
        )


def TestCombinacionPrivilegioTipoInvalida():
    """Una combinación fuera de la matriz se rechaza con el mensaje preciso."""
    servicio = ServicioSolicitudGrantsUi()

    with pytest.raises(ErrorSolicitudUi, match="no es válido"):
        servicio.Construir(
            [_Principal()], ["CAN_USE"], [_Catalogo(CATALOGO_A)]
        )
