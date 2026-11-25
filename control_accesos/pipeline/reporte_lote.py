"""Reporte consolidado del lote con agregación masiva PySpark.

Change `grants-batch` (C5), capability `batch-grant-operations` (design.md
D3): el reporte de lote expone el total de ítems, los totales por estado final
(otorgado, fallido, privilegios_insuficientes) y el detalle por ítem en el
orden de la planificación (spec - "Reporte consolidado del lote").

La agregación de totales usa funciones masivas de PySpark (`groupBy`/`agg`,
sin ciclos por fila) sobre una sesión inyectada, cumpliendo el estándar del
proyecto ("PySpark al máximo") y el mandato explícito del `proposal.md`.

El camino 1 a 1 no requiere sesión: la agregación solo se invoca en el camino
de lote, que es donde el estándar exige el cálculo masivo.
"""

from dataclasses import dataclass
from typing import Optional

from pyspark.sql import functions as F

from control_accesos.dominio.enumeraciones import EstadoItem
from control_accesos.pipeline.reportador import ReporteGrant


@dataclass(frozen=True)
class ReporteLoteGrant:
    """Reporte consolidado de un lote de grants.

    Attributes:
        lineas (tuple[LineaReporte, ...]): las líneas del `ReporteGrant`, en el
            orden de la planificación.
        total_items (int): cantidad total de ítems del lote.
        totales_por_estado (dict[EstadoItem, int]): mapa estado → cantidad, con
            los tres estados presentes (otorgado, fallido,
            privilegios_insuficientes) aunque queden en cero.
    """

    lineas: tuple
    total_items: int
    totales_por_estado: dict


class AgregadorReporteLote:
    """Agrega los totales del reporte de lote con funciones masivas de PySpark.

    Recibe la sesión Spark por inyección (mismo patrón que `CapaPersistencia`
    de C2: local en pruebas, provista por el entorno en la Databricks App),
    materializa las líneas del reporte en un DataFrame y agrega los totales por
    estado con `groupBy`/`agg` (funciones masivas, sin ciclos por fila,
    cumpliendo el estándar y el `proposal.md`).
    """

    def __init__(self, sesion):
        """Inicializa el agregador con la sesión Spark inyectada.

        Args:
            sesion: sesión Spark (local en pruebas, del entorno en producción).

        Raises:
            ValueError: si no se recibe sesión.
        """
        if sesion is None:
            raise ValueError(
                "Se requiere una sesión Spark para agregar el reporte de lote."
            )
        self._sesion = sesion

    def Agregar(self, reporte):
        """Agrega los totales del reporte de lote.

        Args:
            reporte (ReporteGrant): reporte con las líneas por ítem.

        Returns:
            ReporteLoteGrant: reporte de lote con `lineas`, `total_items` y
                `totales_por_estado`.
        """
        if not reporte.lineas:
            # Lote vacío: totales en cero, los tres estados presentes.
            return ReporteLoteGrant(
                lineas=tuple(),
                total_items=0,
                totales_por_estado={
                    EstadoItem.OTORGADO: 0,
                    EstadoItem.FALLIDO: 0,
                    EstadoItem.PRIVILEGIOS_INSUFICIENTES: 0,
                },
            )

        # Materializar las líneas en un DataFrame con el estado como columna.
        filas = [
            (linea.item.principal.identificador, linea.item.privilegio,
             linea.item.objeto.identificador, linea.estado.value)
            for linea in reporte.lineas
        ]
        marco = self._sesion.createDataFrame(
            filas, ["principal", "privilegio", "objeto", "estado"]
        )

        # Agregar los totales por estado con groupBy/agg (funciones masivas).
        totales = marco.groupBy("estado").agg(F.count("*").alias("cantidad")).collect()

        # Construir el mapa estado → cantidad, con los tres estados presentes.
        totales_por_estado = {
            EstadoItem.OTORGADO: 0,
            EstadoItem.FALLIDO: 0,
            EstadoItem.PRIVILEGIOS_INSUFICIENTES: 0,
        }
        for fila in totales:
            estado = EstadoItem(fila["estado"])
            totales_por_estado[estado] = fila["cantidad"]

        return ReporteLoteGrant(
            lineas=reporte.lineas,
            total_items=len(reporte.lineas),
            totales_por_estado=totales_por_estado,
        )
