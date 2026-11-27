"""Prueba unitaria del servicio de disponibilidad de opciones (design.md D7).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 3.5.

Contrato que fija esta prueba, sobre `ResolutorPrivilegiosEfectivos` inyectado:

- **una resolución por objeto** dentro de la acción: objetos desduplicados y
  consultados una sola vez;
- **combinación no disponible con mensaje estructurado** (`MensajePrivilegios-
  Insuficientes`) cuando el privilegio no figura entre los efectivos;
- **disponibilidad mixta**: algunos objetos disponibles y otros no;
- **error de resolución** distinguido del bloqueo (`ERROR_RESOLUCION`), sin
  afirmar ni negar el privilegio;
- **sin reglas alternativas** por `admins`/`CAN_MANAGE`: tener `MANAGE` no
  habilita `SELECT` (coincidencia exacta de C3, sin expansión de jerarquías).

El resolutor es un doble con `ResolverPrivilegiosEfectivos(identidad, objeto)`.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import NormalizarPrivilegio, ObjetoSecurable
from control_accesos.resolucion.errores import ErrorObjetivoInaccesible
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.servicio_disponibilidad import (
    DisponibilidadObjeto,
    EstadoDisponibilidad,
    ServicioDisponibilidadOpciones,
)

CATALOGO_A = "ventas"
CATALOGO_B = "finanzas"
CLUSTER_ID = "cl-0808"


class VistaFalsa:
    """Doble de `PrivilegiosEfectivosVista` con `TieneElPrivilegio`."""

    def __init__(self, privilegios):
        self._privilegios = {NormalizarPrivilegio(p) for p in privilegios}

    def TieneElPrivilegio(self, privilegio):
        return NormalizarPrivilegio(privilegio) in self._privilegios


class ResolutorFalso:
    """Doble del resolutor que registra los objetos consultados."""

    def __init__(self, privilegios_por_objeto, excepcion=None):
        self._privilegios_por_objeto = privilegios_por_objeto
        self._excepcion = excepcion
        self.llamadas = []

    def ResolverPrivilegiosEfectivos(self, identidad_llamante, objeto):
        self.llamadas.append(objeto)
        if self._excepcion is not None:
            raise self._excepcion
        return VistaFalsa(self._privilegios_por_objeto.get(objeto.identificador, ()))


def _Catalogo(nombre):
    return ObjetoSecurable(identificador=nombre, tipo=TipoObjeto.CATALOGO)


def TestUnaResolucionPorObjetoDentroDeLaAccion():
    """Los objetos se desduplican y se consultan una sola vez por acción."""
    resolutor = ResolutorFalso(
        {CATALOGO_A: {"SELECT"}, CATALOGO_B: {"SELECT"}}
    )
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A), _Catalogo(CATALOGO_A), _Catalogo(CATALOGO_B)],
        ["SELECT"],
        identidad_llamante=object(),
    )

    assert [r.objeto.identificador for r in resultados] == [CATALOGO_A, CATALOGO_B]
    assert len(resolutor.llamadas) == 2, (
        "Cada objeto se resuelve una sola vez aunque se repita en la entrada."
    )
    assert all(r.estado == EstadoDisponibilidad.DISPONIBLE for r in resultados)


def TestCombinacionNoDisponibleConMensajeEstructurado():
    """Un privilegio no efectivo produce no disponible con el mensaje de C3."""
    resolutor = ResolutorFalso({CATALOGO_A: ()})
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A)], ["SELECT"], identidad_llamante=object()
    )

    resultado = resultados[0]
    assert resultado.estado == EstadoDisponibilidad.NO_DISPONIBLE
    assert isinstance(resultado.mensaje, MensajePrivilegiosInsuficientes)
    assert resultado.mensaje.privilegio_requerido == "SELECT"
    assert resultado.mensaje.privilegio_faltante == "MANAGE"
    assert resultado.mensaje.objeto.identificador == CATALOGO_A
    assert "MANAGE" in resultado.mensaje.ComoTexto()


def TestDisponibilidadMixta():
    """Algunos objetos disponibles y otros no, con sus motivos conservados."""
    resolutor = ResolutorFalso({CATALOGO_A: {"SELECT"}, CATALOGO_B: ()})
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A), _Catalogo(CATALOGO_B)],
        ["SELECT"],
        identidad_llamante=object(),
    )

    assert [r.estado for r in resultados] == [
        EstadoDisponibilidad.DISPONIBLE,
        EstadoDisponibilidad.NO_DISPONIBLE,
    ]
    assert resultados[1].mensaje is not None


def TestErrorDeResolucionSeDistingueDelBloqueo():
    """Un fallo de resolución produce ERROR_RESOLUCION, no privilegios insuficientes."""
    resolutor = ResolutorFalso({}, excepcion=ErrorObjetivoInaccesible("objeto inaccesible"))
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A)], ["SELECT"], identidad_llamante=object()
    )

    resultado = resultados[0]
    assert resultado.estado == EstadoDisponibilidad.ERROR_RESOLUCION
    assert resultado.mensaje is None
    assert "objeto inaccesible" in resultado.detalle_error


def TestSinReglasAlternativasPorAdminsOCanManage():
    """Tener MANAGE no habilita SELECT: coincidencia exacta de C3, sin atajos."""
    # El llamante tiene MANAGE (autoridad de administración) pero NO SELECT.
    resolutor = ResolutorFalso({CATALOGO_A: {"MANAGE"}})
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A)], ["SELECT"], identidad_llamante=object()
    )

    assert resultados[0].estado == EstadoDisponibilidad.NO_DISPONIBLE, (
        "El servicio no debe habilitar SELECT por tener MANAGE: no hay reglas "
        "alternativas por administradores (coincidencia exacta de C3)."
    )


def TestPlanoDeControlUsaCanManageComoAutoridad():
    """En el plano de control el privilegio faltante se reporta como CAN_MANAGE."""
    objeto = ObjetoSecurable(identificador=CLUSTER_ID, tipo=TipoObjeto.COMPUTO_CLASICO)
    resolutor = ResolutorFalso({CLUSTER_ID: ()})
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar([objeto], ["CAN_ATTACH_TO"], identidad_llamante=object())

    assert resultados[0].estado == EstadoDisponibilidad.NO_DISPONIBLE
    assert resultados[0].mensaje.privilegio_faltante == "CAN_MANAGE"


def TestSinPrivilegiosEsDisponible():
    """Sin privilegios que comprobar, el objeto queda disponible (vacío)."""
    resolutor = ResolutorFalso({CATALOGO_A: ()})
    servicio = ServicioDisponibilidadOpciones(resolutor)

    resultados = servicio.Evaluar(
        [_Catalogo(CATALOGO_A)], [], identidad_llamante=object()
    )

    assert resultados[0].estado == EstadoDisponibilidad.DISPONIBLE
    assert isinstance(resultados[0], DisponibilidadObjeto)
