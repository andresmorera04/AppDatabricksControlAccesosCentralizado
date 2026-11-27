"""Prueba funcional de la pantalla de confirmación (controlador, design.md D8/D9).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 6.2.

Ejercita `ControladorGrantsUi` con dobles: previsualización mixta, todos
bloqueados (sin confirmación), cambio de formulario que invalida, doble
confirmación/rerender que ejecuta una sola vez y revalidación al confirmar
(la ejecución recibe la solicitud vigente construida de nuevo).
"""

import pytest

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
    SolicitudGrant,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.pipeline.reportador import (
    LineaReporte,
    ReporteGrant,
    TRAZABILIDAD_ITINERARIO_COMPLETO,
)
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.controlador import ControladorGrantsUi
from control_accesos.ui.presentador import PresentadorGrantsUi
from control_accesos.ui.servicio_solicitud import ServicioSolicitudGrantsUi

LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)


def _Item(privilegio="SELECT"):
    return ItemGrant(principal=DESTINO, privilegio=privilegio, objeto=VENTAS)


def _ClasificacionMixta():
    motivo = MensajePrivilegiosInsuficientes(
        objeto=VENTAS,
        plano=Plano.DATOS,
        privilegio_requerido="MODIFY",
        privilegio_faltante="MANAGE",
    )
    return ClasificacionPreFlight(
        items_ejecutables=(_Item("SELECT"),),
        items_bloqueados=(
            ResultadoItem.PrivilegiosInsuficientes(
                _Item("MODIFY"), causa=motivo.ComoTexto()
            ),
        ),
        mensajes_por_item={_Item("MODIFY"): motivo},
    )


class DescubrimientoVacio:
    def DescubrirPrincipales(self):
        return ()
    def DescubrirCatalogos(self):
        return ()


class DisponibilidadPassthrough:
    def Evaluar(self, objetos, privilegios, identidad):
        return ()

class PrevisualizacionFalsa:
    def __init__(self, clasificacion):
        self._clasificacion = clasificacion

    def Previsualizar(self, solicitud, identidad):
        return self._clasificacion


class EjecucionFalsa:
    def __init__(self, reporte):
        self._reporte = reporte
        self.llamadas = []

    def Ejecutar(self, solicitud, identidad_llamante=None):
        self.llamadas.append(solicitud)
        return self._reporte


def _Reporte():
    return ReporteGrant(
        lineas=(
            LineaReporte(
                item=_Item("SELECT"),
                estado=EstadoItem.OTORGADO,
                detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
        )
    )


def _Controlador(previsualizacion, ejecucion):
    return ControladorGrantsUi(
        servicio_descubrimiento=DescubrimientoVacio(),
        servicio_solicitud=ServicioSolicitudGrantsUi(),
        servicio_disponibilidad=DisponibilidadPassthrough(),
        servicio_previsualizacion=previsualizacion,
        servicio_ejecucion=ejecucion,
        presentador=PresentadorGrantsUi(),
        consultora=ConsultoraMatrizPrivilegios(),
    )


def _Identidad():
    return IdentidadLlamante(principal=LLAMANTE)


def _SeleccionValida(controlador):
    controlador.SeleccionarPrincipales([DESTINO])
    controlador.SeleccionarTipo(TipoObjeto.CATALOGO)
    controlador.SeleccionarObjetos([VENTAS])
    controlador.SeleccionarPrivilegios(["SELECT", "MODIFY"])


def TestPrevisualizacionMixta():
    """El split mixto (ejecutable y bloqueado) se presenta."""
    controlador = _Controlador(
        PrevisualizacionFalsa(_ClasificacionMixta()), EjecucionFalsa(_Reporte())
    )
    _SeleccionValida(controlador)

    filas = controlador.Previsualizar(_Identidad())

    assert [f.estado for f in filas] == [
        "ejecutable",
        EstadoItem.PRIVILEGIOS_INSUFICIENTES.value,
    ]


def TestTodosBloqueadosSinConfirmacion():
    """Sin ejecutables, no hay confirmación ni ejecución."""

    clasificacion = ClasificacionPreFlight(
        items_ejecutables=(),
        items_bloqueados=(
            ResultadoItem.PrivilegiosInsuficientes(
                _Item("MODIFY"), causa="sin autoridad para otorgar"
            ),
        ),
    )
    ejecucion = EjecucionFalsa(_Reporte())
    controlador = _Controlador(PrevisualizacionFalsa(clasificacion), ejecucion)
    _SeleccionValida(controlador)
    controlador.Previsualizar(_Identidad())

    assert controlador.ConfirmarYEejecutar(_Identidad()) is None
    assert ejecucion.llamadas == []


def TestCambioDeFormularioInvalida():
    """Cambiar la selección tras previsualizar invalida la confirmación."""
    ejecucion = EjecucionFalsa(_Reporte())
    controlador = _Controlador(
        PrevisualizacionFalsa(_ClasificacionMixta()), ejecucion
    )
    _SeleccionValida(controlador)
    controlador.Previsualizar(_Identidad())

    # El usuario cambia el privilegio seleccionado (nueva huella).
    controlador.SeleccionarPrivilegios(["READ METADATA"])

    assert controlador.ConfirmarYEejecutar(_Identidad()) is None
    assert ejecucion.llamadas == []


def TestDobleConfirmacionEjecutaUnaSolaVez():
    """Un rerender o doble clic no vuelve a ejecutar: confirmación única."""
    ejecucion = EjecucionFalsa(_Reporte())
    controlador = _Controlador(
        PrevisualizacionFalsa(_ClasificacionMixta()), ejecucion
    )
    _SeleccionValida(controlador)
    controlador.Previsualizar(_Identidad())

    primer = controlador.ConfirmarYEejecutar(_Identidad())
    segundo = controlador.ConfirmarYEejecutar(_Identidad())

    assert primer is not None
    assert segundo is None
    assert len(ejecucion.llamadas) == 1
    assert isinstance(ejecucion.llamadas[0], SolicitudGrant)
