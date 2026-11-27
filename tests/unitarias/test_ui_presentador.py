"""Prueba unitaria del presentador de grants de la UI (design.md D2).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.4.

Contrato que fija esta prueba: el presentador transforma previsualización y
reporte en filas inmutables con principal (identificador y tipo), privilegio,
objeto (identificador y tipo), estado, detalle y trazabilidad, y expone el
motivo de insuficiencia por campo (privilegio requerido/faltante) **sin parsear
textos**; conserva el orden de planificación del reporte y los totales del lote
**incluidos los ceros** por estado:

- previsualización: ejecutables y bloqueados (matriz y privilegios);
- reporte: líneas del `ReporteGrant` (otorgado/fallido);
- totales: `ReporteLoteGrant` con los tres estados presentes aunque queden en cero.
"""

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
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.pipeline.reportador import (
    LineaReporte,
    ReporteGrant,
    TRAZABILIDAD_ITINERARIO_COMPLETO,
)
from control_accesos.pipeline.reporte_lote import ReporteLoteGrant
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.presentador import PresentadorGrantsUi

PRINCIPAL = Principal("usuario.uno@example.com", TipoPrincipal.USUARIO)
CATALOGO = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)


def _Item(privilegio="SELECT"):
    return ItemGrant(principal=PRINCIPAL, privilegio=privilegio, objeto=CATALOGO)


def _ClasificacionMixta():
    item_ejecutable = _Item("SELECT")
    item_insuficiente = _Item("MODIFY")
    item_matriz = _Item("USE SCHEMA")  # inválido para catálogo: matriz

    motivo = MensajePrivilegiosInsuficientes(
        objeto=CATALOGO,
        plano=Plano.DATOS,
        privilegio_requerido="MODIFY",
        privilegio_faltante="MANAGE",
    )
    return ClasificacionPreFlight(
        items_ejecutables=(item_ejecutable,),
        items_bloqueados=(
            ResultadoItem.PrivilegiosInsuficientes(
                item_insuficiente, causa="(no se parsea este texto)"
            ),
            ResultadoItem.Fallido(item_matriz, detalle="motivo de matriz"),
        ),
        mensajes_por_item={item_insuficiente: motivo},
    )


def TestFilasDePrevisualizacion():
    """Ejecutables y bloqueados producen filas con los campos del dominio."""
    presentador = PresentadorGrantsUi()

    filas = presentador.PresentarPrevisualizacion(_ClasificacionMixta())

    assert [f.estado for f in filas] == [
        "ejecutable",
        EstadoItem.PRIVILEGIOS_INSUFICIENTES.value,
        EstadoItem.FALLIDO.value,
    ]
    assert [f.privilegio for f in filas] == ["SELECT", "MODIFY", "USE SCHEMA"]
    assert all(f.principal_identificador == PRINCIPAL.identificador for f in filas)
    assert all(f.objeto_identificador == CATALOGO.identificador for f in filas)
    assert all(f.objeto_tipo == CATALOGO.tipo.value for f in filas)


def TestMotivoDeInsuficienciaPorCampoSinParsearTexto():
    """El motivo de insuficiencia se expone por campo, no parseando el detalle."""
    presentador = PresentadorGrantsUi()

    filas = presentador.PresentarPrevisualizacion(_ClasificacionMixta())
    fila_insuficiente = filas[1]

    assert fila_insuficiente.estado == EstadoItem.PRIVILEGIOS_INSUFICIENTES.value
    assert fila_insuficiente.privilegio_requerido == "MODIFY"
    assert fila_insuficiente.privilegio_faltante == "MANAGE"
    # El motivo se lee del mensaje estructurado, no del texto del detalle.
    assert fila_insuficiente.detalle == "(no se parsea este texto)"
    # La fila de matriz (fallido) no tiene motivo de insuficiencia.
    assert filas[2].privilegio_requerido is None
    assert filas[2].privilegio_faltante is None


def TestFilasDeReporteYOrden():
    """El reporte produce filas en el orden de planificación con trazabilidad."""
    item_uno = _Item("SELECT")
    item_dos = _Item("MODIFY")
    reporte = ReporteGrant(
        lineas=(
            LineaReporte(
                item=item_uno,
                estado=EstadoItem.OTORGADO,
                detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
            LineaReporte(
                item=item_dos,
                estado=EstadoItem.FALLIDO,
                detalle="error del canal",
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
        )
    )
    presentador = PresentadorGrantsUi()

    filas = presentador.PresentarReporte(reporte)

    assert [f.privilegio for f in filas] == ["SELECT", "MODIFY"]
    assert [f.estado for f in filas] == [
        EstadoItem.OTORGADO.value,
        EstadoItem.FALLIDO.value,
    ]
    assert filas[0].detalle is None
    assert filas[1].detalle == "error del canal"
    assert filas[1].trazabilidad == TRAZABILIDAD_ITINERARIO_COMPLETO


def TestTotalesDelLoteIncluyenCeros():
    """Los totales del lote incluyen los tres estados aunque queden en cero."""
    reporte = ReporteGrant(
        lineas=(
            LineaReporte(
                item=_Item("SELECT"),
                estado=EstadoItem.OTORGADO,
                detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
            LineaReporte(
                item=_Item("MODIFY"),
                estado=EstadoItem.OTORGADO,
                detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
        )
    )
    lote = ReporteLoteGrant(
        lineas=reporte.lineas,
        total_items=2,
        totales_por_estado={EstadoItem.OTORGADO: 2},
    )
    presentador = PresentadorGrantsUi()

    totales = presentador.PresentarTotales(lote)

    assert totales["total_items"] == 2
    assert totales["totales_por_estado"][EstadoItem.OTORGADO.value] == 2
    assert totales["totales_por_estado"][EstadoItem.FALLIDO.value] == 0
    assert (
        totales["totales_por_estado"][
            EstadoItem.PRIVILEGIOS_INSUFICIENTES.value
        ]
        == 0
    )
