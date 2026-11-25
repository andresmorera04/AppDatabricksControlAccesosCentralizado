"""Pruebas unitarias del reporte consolidado del lote con agregación PySpark.

Trazabilidad:
- spec `batch-grant-operations` - "Reporte consolidado del lote"
- design.md D3 - agregación con funciones masivas de PySpark

Convención del proyecto (README.md): clases, funciones y métodos en PascalCase
(pytest.ini registra `python_functions = Test*`); la sesión Spark se inyecta
(local en pruebas, del entorno en la Databricks App).
"""

import pytest

from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.pipeline.reportador import LineaReporte, ReporteGrant
from control_accesos.pipeline.reporte_lote import (
    AgregadorReporteLote,
    ReporteLoteGrant,
)


def _CrearItem(principal_id="user@example.com", privilegio="SELECT", objeto_id="catalogo1.schema1.tabla1"):
    """Construye un ítem de prueba."""
    principal = Principal(identificador=principal_id, tipo="usuario")
    objeto = ObjetoSecurable(identificador=objeto_id, tipo=TipoObjeto.TABLA_DELTA)
    return ItemGrant(principal=principal, privilegio=privilegio, objeto=objeto)


def _CrearLinea(item, estado, detalle=None):
    """Construye una línea de reporte de prueba."""
    return LineaReporte(
        item=item,
        estado=estado,
        detalle=detalle,
        trazabilidad=("planificado", "pre-flight: ejecutable", "ejecutado", "verificado"),
    )


class TestReporteLoteGrant:
    """Verifica que ReporteLoteGrant expone los totales agregados correctamente."""

    def TestLoteMixtoExponeTotalesPorEstado(self, sesion_spark):
        """Scenario: Totales por estado de un lote mixto.

        WHEN un lote termina con tres ítems otorgados, dos fallidos y uno con
        privilegios insuficientes THEN el reporte consolidado expone un total
        de seis ítems, los totales por estado tres otorgados, dos fallidos y
        uno con privilegios insuficientes, y el detalle de cada ítem.
        """
        # Crear 6 líneas: 3 otorgadas, 2 fallidas, 1 privilegios insuficientes.
        lineas = [
            _CrearLinea(_CrearItem(objeto_id="tabla1"), EstadoItem.OTORGADO),
            _CrearLinea(_CrearItem(objeto_id="tabla2"), EstadoItem.OTORGADO),
            _CrearLinea(_CrearItem(objeto_id="tabla3"), EstadoItem.OTORGADO),
            _CrearLinea(_CrearItem(objeto_id="tabla4"), EstadoItem.FALLIDO, detalle="objeto no existe"),
            _CrearLinea(_CrearItem(objeto_id="tabla5"), EstadoItem.FALLIDO, detalle="error de ejecución"),
            _CrearLinea(_CrearItem(objeto_id="tabla6"), EstadoItem.PRIVILEGIOS_INSUFICIENTES, detalle="sin MANAGE"),
        ]
        reporte = ReporteGrant(lineas=tuple(lineas))

        agregador = AgregadorReporteLote(sesion=sesion_spark)
        reporte_lote = agregador.Agregar(reporte)

        assert reporte_lote.total_items == 6
        assert reporte_lote.totales_por_estado[EstadoItem.OTORGADO] == 3
        assert reporte_lote.totales_por_estado[EstadoItem.FALLIDO] == 2
        assert reporte_lote.totales_por_estado[EstadoItem.PRIVILEGIOS_INSUFICIENTES] == 1
        # Los tres estados están presentes en el mapa.
        assert len(reporte_lote.totales_por_estado) == 3

    def TestLoteTotalmenteOtorgadoExponeCeroEnLosDemasEstados(self, sesion_spark):
        """Scenario: Lote totalmente otorgado.

        WHEN todos los ítems del lote quedan otorgados THEN el reporte
        consolidado expone el total de otorgados igual al total de ítems y
        cero en los demás estados.
        """
        lineas = [
            _CrearLinea(_CrearItem(objeto_id="tabla1"), EstadoItem.OTORGADO),
            _CrearLinea(_CrearItem(objeto_id="tabla2"), EstadoItem.OTORGADO),
        ]
        reporte = ReporteGrant(lineas=tuple(lineas))

        agregador = AgregadorReporteLote(sesion=sesion_spark)
        reporte_lote = agregador.Agregar(reporte)

        assert reporte_lote.total_items == 2
        assert reporte_lote.totales_por_estado[EstadoItem.OTORGADO] == 2
        assert reporte_lote.totales_por_estado[EstadoItem.FALLIDO] == 0
        assert reporte_lote.totales_por_estado[EstadoItem.PRIVILEGIOS_INSUFICIENTES] == 0

    def TestDetallePorItemConservaElOrdenDeLaPlanificacion(self, sesion_spark):
        """El detalle por ítem conserva el orden de la planificación.

        WHEN se agrega un reporte con líneas en un orden específico THEN el
        reporte de lote conserva ese orden en su campo `lineas`.
        """
        item1 = _CrearItem(objeto_id="tabla1")
        item2 = _CrearItem(objeto_id="tabla2")
        item3 = _CrearItem(objeto_id="tabla3")
        lineas = [
            _CrearLinea(item1, EstadoItem.OTORGADO),
            _CrearLinea(item2, EstadoItem.FALLIDO, detalle="error"),
            _CrearLinea(item3, EstadoItem.OTORGADO),
        ]
        reporte = ReporteGrant(lineas=tuple(lineas))

        agregador = AgregadorReporteLote(sesion=sesion_spark)
        reporte_lote = agregador.Agregar(reporte)

        # Las líneas conservan el orden original.
        assert len(reporte_lote.lineas) == 3
        assert reporte_lote.lineas[0].item == item1
        assert reporte_lote.lineas[1].item == item2
        assert reporte_lote.lineas[2].item == item3
