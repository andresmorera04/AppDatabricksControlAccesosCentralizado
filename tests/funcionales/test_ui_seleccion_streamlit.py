"""Prueba funcional de la pantalla de selección (controlador, design.md D2/D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 6.1.

Ejercita `ControladorGrantsUi` con colaboradores simulados (sin red, sin
Streamlit): identidad visible, selección de principal/tipo/objeto, privilegios
exactos de la matriz, limpieza al cambiar el tipo, disponibilidad mixta y fallo
de descubrimiento que inhabilita la ejecución.
"""

import pytest

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.ui.controlador import ControladorGrantsUi
from control_accesos.ui.presentador import PresentadorGrantsUi
from control_accesos.ui.servicio_disponibilidad import (
    DisponibilidadObjeto,
    EstadoDisponibilidad,
)
from control_accesos.ui.servicio_solicitud import (
    ErrorSolicitudUi,
    ServicioSolicitudGrantsUi,
)

LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
PRINCIPAL_DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)
FINANZAS = ObjetoSecurable("finanzas", TipoObjeto.CATALOGO)


class DescubrimientoFalso:
    """Doble de `ServicioDescubrimientoUi` con listados fijos y fallo opcional."""

    def __init__(self, principales=(), catalogos=(), excepcion=None):
        self._principales = tuple(principales)
        self._catalogos = tuple(catalogos)
        self._excepcion = excepcion

    def _O(self, registros):
        if self._excepcion is not None:
            raise self._excepcion
        return registros

    def DescubrirPrincipales(self):
        return self._O(self._principales)

    def DescubrirCatalogos(self):
        return self._O(self._catalogos)

    def DescubrirClusters(self):
        return ()
    def DescubrirServerless(self):
        return ()
    def DescubrirWarehouses(self):
        return ()
    def DescubrirApps(self):
        return ()
    def DescubrirUsoTokens(self):
        return ()
    def DescubrirEsquemas(self, catalogo):
        return ()
    def DescubrirTablas(self, catalogo, esquema):
        return ()
    def DescubrirVolumenes(self, catalogo, esquema):
        return ()
    def DescubrirModelosMl(self, catalogo, esquema):
        return ()
    def DescubrirExternalLocations(self):
        return ()
    def DescubrirConexiones(self):
        return ()


class DisponibilidadFalso:
    """Doble de `ServicioDisponibilidadOpciones` que devuelve un resultado fijo."""

    def __init__(self, resultados):
        self._resultados = tuple(resultados)

    def Evaluar(self, objetos, privilegios, identidad):
        return self._resultados


class _PrevisualizacionFalsa:
    """Doble de previsualización (no se previsualiza en la pantalla de selección)."""

    def Previsualizar(self, solicitud, identidad):
        raise AssertionError("no se previsualiza en la pantalla de selección")


def _Controlador(descubrimiento, disponibilidad):
    return ControladorGrantsUi(
        servicio_descubrimiento=descubrimiento,
        servicio_solicitud=ServicioSolicitudGrantsUi(),
        servicio_disponibilidad=disponibilidad,
        servicio_previsualizacion=_PrevisualizacionFalsa(),
        servicio_ejecucion=_EjecucionFalsa(),
        presentador=PresentadorGrantsUi(),
        consultora=ConsultoraMatrizPrivilegios(),
    )


class _EjecucionFalsa:
    def __init__(self):
        self.llamadas = []

    def Ejecutar(self, solicitud, identidad_llamante=None):
        self.llamadas.append(solicitud)
        return solicitud


def _Identidad():
    return IdentidadLlamante(principal=LLAMANTE)


def TestIdentidadVisible():
    """El controlador expone la identidad OBO a mostrar (None sin identidad)."""
    controlador = _Controlador(DescubrimientoFalso(), DisponibilidadFalso(()))

    assert controlador.IdentidadVisible(_Identidad()) == LLAMANTE.identificador
    assert controlador.IdentidadVisible(None) is None


def TestSeleccionDePrincipalTipoObjeto():
    """Se seleccionan principal, tipo y objetos descubiertos del tipo."""
    descubrimiento = DescubrimientoFalso(
        principales=[PRINCIPAL_DESTINO], catalogos=[VENTAS, FINANZAS]
    )
    controlador = _Controlador(descubrimiento, DisponibilidadFalso(()))

    assert controlador.ListarPrincipales() == (PRINCIPAL_DESTINO,)
    assert controlador.ListarObjetos(TipoObjeto.CATALOGO) == (VENTAS, FINANZAS)

    controlador.SeleccionarPrincipales([PRINCIPAL_DESTINO])
    controlador.SeleccionarTipo(TipoObjeto.CATALOGO)
    controlador.SeleccionarObjetos([VENTAS])
    controlador.SeleccionarPrivilegios(["SELECT"])

    solicitud = controlador.ConstruirSolicitud()
    assert solicitud.principal.identificador == PRINCIPAL_DESTINO.identificador
    assert solicitud.objeto.identificador == VENTAS.identificador


def TestPrivilegiosExactosDeLaMatriz():
    """Los privilegios ofrecidos son exactamente los de la matriz para el tipo."""
    controlador = _Controlador(DescubrimientoFalso(), DisponibilidadFalso(()))

    privilegios = controlador.ListarPrivilegios(TipoObjeto.CATALOGO)

    assert "SELECT" in privilegios
    assert "CAN_USE" not in privilegios
    assert privilegios == ConsultoraMatrizPrivilegios().ListarOpcionesParaUi(
        TipoObjeto.CATALOGO
    )


def TestLimpiezaAlCambiarTipo():
    """Al cambiar el tipo se descartan objetos y privilegios previos."""
    controlador = _Controlador(DescubrimientoFalso(), DisponibilidadFalso(()))
    controlador.SeleccionarPrincipales([PRINCIPAL_DESTINO])
    controlador.SeleccionarTipo(TipoObjeto.CATALOGO)
    controlador.SeleccionarObjetos([VENTAS])
    controlador.SeleccionarPrivilegios(["SELECT"])

    controlador.SeleccionarTipo(TipoObjeto.TABLA_DELTA)

    with pytest.raises(ErrorSolicitudUi):
        controlador.ConstruirSolicitud()


def TestDisponibilidadMixta():
    """La disponibilidad mixta (disponible/no disponible) se expone tal cual."""
    resultados = (
        DisponibilidadObjeto(VENTAS, EstadoDisponibilidad.DISPONIBLE),
        DisponibilidadObjeto(FINANZAS, EstadoDisponibilidad.NO_DISPONIBLE),
    )
    controlador = _Controlador(
        DescubrimientoFalso(), DisponibilidadFalso(resultados)
    )
    controlador.SeleccionarTipo(TipoObjeto.CATALOGO)
    controlador.SeleccionarObjetos([VENTAS, FINANZAS])
    controlador.SeleccionarPrivilegios(["SELECT"])

    disponibilidad = controlador.Disponibilidad(_Identidad())

    assert [d.estado for d in disponibilidad] == [
        EstadoDisponibilidad.DISPONIBLE,
        EstadoDisponibilidad.NO_DISPONIBLE,
    ]


def TestErrorDeDescubrimientoInhabilitaEjecucion():
    """Un fallo de descubrimiento inhabilita la ejecución."""
    from control_accesos.ui.servicio_descubrimiento import ErrorDescubrimientoOpciones

    descubrimiento = DescubrimientoFalso(
        excepcion=ErrorDescubrimientoOpciones("SCIM denegado")
    )
    ejecucion = _EjecucionFalsa()
    controlador = _Controlador(descubrimiento, DisponibilidadFalso(()))
    controlador._servicio_ejecucion = ejecucion  # para observar llamadas

    assert controlador.ListarPrincipales() == ()
    assert controlador.ErrorDescubrimiento() is not None
    assert controlador.PuedeEjecutar() is False
    assert controlador.ConfirmarYEejecutar(_Identidad()) is None
    assert ejecucion.llamadas == []
