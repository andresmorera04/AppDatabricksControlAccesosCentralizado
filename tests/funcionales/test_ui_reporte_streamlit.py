"""Prueba funcional de la pantalla de reporte (controlador, design.md D8).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 6.3.

Ejercita `ControladorGrantsUi` con dobles: reporte con los tres estados
(otorgado, fallido, privilegios insuficientes), bloqueados incluidos, totales
de lote con ceros y detalle en español.
"""

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
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.pipeline.reportador import (
    LineaReporte,
    ReporteGrant,
    TRAZABILIDAD_ITINERARIO_COMPLETO,
)
from control_accesos.pipeline.reporte_lote import ReporteLoteGrant
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.controlador import ControladorGrantsUi
from control_accesos.ui.presentador import PresentadorGrantsUi
from control_accesos.ui.servicio_solicitud import ServicioSolicitudGrantsUi

LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)


def _Item(privilegio):
    return ItemGrant(principal=DESTINO, privilegio=privilegio, objeto=VENTAS)


def _ReporteTresEstados():
    motivo = MensajePrivilegiosInsuficientes(
        objeto=VENTAS,
        plano=Plano.DATOS,
        privilegio_requerido="READ METADATA",
        privilegio_faltante="MANAGE",
    )
    return ReporteGrant(
        lineas=(
            LineaReporte(
                item=_Item("SELECT"), estado=EstadoItem.OTORGADO, detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
            LineaReporte(
                item=_Item("MODIFY"), estado=EstadoItem.FALLIDO,
                detalle="Error del canal en español", trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
            LineaReporte(
                item=_Item("READ METADATA"),
                estado=EstadoItem.PRIVILEGIOS_INSUFICIENTES,
                detalle=motivo.ComoTexto(),
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
                motivo_insuficiencia=motivo,
            ),
        )
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
    def Previsualizar(self, solicitud, identidad):
        return ClasificacionPreFlight(
            items_ejecutables=(_Item("SELECT"),), items_bloqueados=()
        )


class EjecucionFalsa:
    def __init__(self, reporte):
        self._reporte = reporte

    def Ejecutar(self, solicitud, identidad_llamante=None):
        return self._reporte


def _Controlador(ejecucion):
    return ControladorGrantsUi(
        servicio_descubrimiento=DescubrimientoVacio(),
        servicio_solicitud=ServicioSolicitudGrantsUi(),
        servicio_disponibilidad=DisponibilidadPassthrough(),
        servicio_previsualizacion=PrevisualizacionFalsa(),
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
    controlador.SeleccionarPrivilegios(["SELECT"])


def TestReporteConTresEstados():
    """El reporte presenta los tres estados, incluidos los bloqueados."""
    controlador = _Controlador(EjecucionFalsa(_ReporteTresEstados()))
    _SeleccionValida(controlador)
    controlador.Previsualizar(_Identidad())

    filas = controlador.ConfirmarYEejecutar(_Identidad())

    assert [f.estado for f in filas] == [
        EstadoItem.OTORGADO.value,
        EstadoItem.FALLIDO.value,
        EstadoItem.PRIVILEGIOS_INSUFICIENTES.value,
    ]
    # El detalle del error está en español.
    assert filas[1].detalle == "Error del canal en español"
    # El motivo de insuficiencia se expone por campo.
    assert filas[2].privilegio_requerido == "READ METADATA"
    assert filas[2].privilegio_faltante == "MANAGE"


def TestTotalesDelLoteIncluyenCeros():
    """El reporte de lote expone totales con los tres estados (ceros incluidos)."""
    reporte_base = _ReporteTresEstados()
    lote = ReporteLoteGrant(
        lineas=reporte_base.lineas,
        total_items=3,
        totales_por_estado={EstadoItem.OTORGADO: 1, EstadoItem.FALLIDO: 1},
    )
    controlador = _Controlador(EjecucionFalsa(lote))
    _SeleccionValida(controlador)
    controlador.Previsualizar(_Identidad())
    controlador.ConfirmarYEejecutar(_Identidad())

    totales = controlador.TotalesDelUltimoReporte()

    assert totales["total_items"] == 3
    assert totales["totales_por_estado"][EstadoItem.OTORGADO.value] == 1
    assert totales["totales_por_estado"][EstadoItem.FALLIDO.value] == 1
    assert totales["totales_por_estado"][
        EstadoItem.PRIVILEGIOS_INSUFICIENTES.value
    ] == 0
