"""Prueba unitaria del estado de sesión de la UI (design.md D9).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.3.

Contrato que fija esta prueba:

- **huella canónica estable**: independiente del orden de selección de
  principals, objetos y privilegios (mismo contenido, misma huella);
- **invalidación por cambio de formulario**: una selección distinta produce una
  huella distinta y deja de ser vigente;
- **invalidación por cambio de identidad**: el estado se asocia a la identidad
  del llamante (no al token); otra identidad no ve la previsualización;
- **confirmación ausente sin ejecutables**: no se puede confirmar una
  previsualización sin ítems ejecutables;
- **confirmación consumida**: una confirmación válida se consume y no permite
  repetir la ejecución (rerender/doble clic).

El estado NO guarda tokens, clientes ni sesiones: solo selecciones y la
previsualización del dominio.
"""

import pytest

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.ui.estado_sesion import EstadoSesionGrantsUi

USUARIO_A = "usuario.a@example.com"
USUARIO_B = "usuario.b@example.com"
CATALOGO_A = "ventas"
CATALOGO_B = "finanzas"


def _Principal(identificador=USUARIO_A):
    return Principal(identificador, TipoPrincipal.USUARIO)


def _Catalogo(nombre):
    return ObjetoSecurable(nombre, TipoObjeto.CATALOGO)


def _Clasificacion(con_ejecutables=True):
    item = ItemGrant(
        principal=_Principal(), privilegio="SELECT", objeto=_Catalogo(CATALOGO_A)
    )
    return ClasificacionPreFlight(
        items_ejecutables=(item,) if con_ejecutables else (),
        items_bloqueados=() if con_ejecutables else (item,),
    )


def TestHuellaEstableIndependienteDelOrden():
    """El orden de selección no cambia la huella canónica."""
    huella_uno = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A), _Principal(USUARIO_B)],
        [_Catalogo(CATALOGO_A), _Catalogo(CATALOGO_B)],
        ["SELECT", "MODIFY"],
    )
    huella_dos = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_B), _Principal(USUARIO_A)],
        [_Catalogo(CATALOGO_B), _Catalogo(CATALOGO_A)],
        ["MODIFY", "SELECT"],
    )

    assert huella_uno == huella_dos
    assert isinstance(huella_uno, str) and huella_uno


def TestInvalidacionPorCambioDeFormulario():
    """Una selección distinta invalida la previsualización previa."""
    estado = EstadoSesionGrantsUi()
    clasificacion = _Clasificacion()
    huella = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A)], [_Catalogo(CATALOGO_A)], ["SELECT"]
    )
    estado.GuardarPrevisualizacion(huella, USUARIO_A, clasificacion)

    assert estado.PrevisualizacionVigente(huella, USUARIO_A) is clasificacion

    huella_distinta = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A)], [_Catalogo(CATALOGO_B)], ["SELECT"]
    )
    assert estado.PrevisualizacionVigente(huella_distinta, USUARIO_A) is None


def TestInvalidacionPorCambioDeIdentidad():
    """Otra identidad no ve la previsualización guardada."""
    estado = EstadoSesionGrantsUi()
    huella = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A)], [_Catalogo(CATALOGO_A)], ["SELECT"]
    )
    estado.GuardarPrevisualizacion(huella, USUARIO_A, _Clasificacion())

    assert (
        estado.PrevisualizacionVigente(huella, USUARIO_B) is None
    ), "La previsualización no es vigente para otra identidad."


def TestConfirmacionAusenteSinEjecutables():
    """Sin ítems ejecutables no se puede confirmar."""
    estado = EstadoSesionGrantsUi()
    huella = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A)], [_Catalogo(CATALOGO_A)], ["SELECT"]
    )
    estado.GuardarPrevisualizacion(huella, USUARIO_A, _Clasificacion(con_ejecutables=False))

    assert estado.Confirmar(huella, USUARIO_A) is False


def TestConfirmacionConsumidaImpideDuplicados():
    """Una confirmación válida se consume y no permite repetir."""
    estado = EstadoSesionGrantsUi()
    huella = EstadoSesionGrantsUi.Huella(
        [_Principal(USUARIO_A)], [_Catalogo(CATALOGO_A)], ["SELECT"]
    )
    estado.GuardarPrevisualizacion(huella, USUARIO_A, _Clasificacion())

    assert estado.Confirmar(huella, USUARIO_A) is True
    assert estado.Confirmar(huella, USUARIO_A) is False, (
        "La confirmación es de un solo uso: un rerender o doble clic no "
        "vuelve a ejecutar."
    )
    # Tras consumir, la previsualización deja de ser vigente.
    assert estado.PrevisualizacionVigente(huella, USUARIO_A) is None


def TestEstadoNoGuardaCredenciales():
    """El estado solo guarda selecciones y previsualización, sin tokens."""
    estado = EstadoSesionGrantsUi()
    atributos = {nombre for nombre in vars(estado)}
    assert "token" not in atributos
    assert "cliente" not in atributos
    assert "sesion" not in atributos
