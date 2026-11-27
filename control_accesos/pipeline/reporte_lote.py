"""Reporte consolidado del lote, con agregación PySpark o Python puro.

Change `grants-batch` (C5), capability `batch-grant-operations` (design.md
D3): el reporte de lote expone el total de ítems, los totales por estado final
(otorgado, fallido, privilegios_insuficientes) y el detalle por ítem en el
orden de la planificación (spec - "Reporte consolidado del lote").

Dos agregadores sobre el MISMO puerto (`Agregar(reporte) -> ReporteLoteGrant`):

- `AgregadorReporteLote`: con funciones masivas de PySpark (`groupBy`/`agg`,
  sin ciclos por fila) sobre una sesión inyectada —la ruta CLI/lote, donde el
  estándar exige el cálculo masivo con Spark—;
- `AgregadorReporteLotePython` (change `app-broker-identidad-ejecucion`, F2):
  el mismo resultado en Python puro, para la Databricks App del modo broker,
  donde no hay SparkSession (OBO SQL por Statement Execution API).

El camino 1 a 1 no requiere agregación: solo se invoca en el camino de lote.
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


def _TotalesIniciales():
    """Devuelve el mapa de totales con los tres estados finales en cero.

    Returns:
        dict[EstadoItem, int]: mapa estado → cantidad, con los tres estados
            presentes (otorgado, fallido, privilegios_insuficientes) en cero.
    """
    return {
        EstadoItem.OTORGADO: 0,
        EstadoItem.FALLIDO: 0,
        EstadoItem.PRIVILEGIOS_INSUFICIENTES: 0,
    }


class AgregadorReporteLotePython:
    """Agrega los totales del reporte de lote en Python puro (sin Spark).

    Change `app-broker-identidad-ejecucion` (corrección F2 de C9): implementa el
    MISMO puerto que `AgregadorReporteLote` (`Agregar(reporte)`) para la
    Databricks App del modo broker, donde el SQL OBO va por Statement Execution
    API y no existe SparkSession alguna (`databricks-connect` es inviable en la
    imagen de la App). El bucle sobre líneas es acotado por el tamaño del lote
    (`limite_items_por_lote`, de la configuración), nunca un ciclo masivo sobre
    datos de catálogo.

    Su salida es idéntica a la del agregador PySpark: un `ReporteLoteGrant` con
    `lineas` (en el orden de planificación), `total_items` y `totales_por_estado`
    con los tres estados presentes aunque queden en cero.
    """

    def __init__(self):
        """Inicializa el agregador: no requiere sesión ni dependencia alguna."""

    def Agregar(self, reporte):
        """Agrega los totales del reporte de lote contando estados en Python.

        Args:
            reporte (ReporteGrant): reporte con las líneas por ítem.

        Returns:
            ReporteLoteGrant: reporte de lote con `lineas`, `total_items` y
                `totales_por_estado`.
        """
        totales_por_estado = _TotalesIniciales()
        for linea in reporte.lineas:
            if linea.estado in totales_por_estado:
                totales_por_estado[linea.estado] += 1

        return ReporteLoteGrant(
            lineas=reporte.lineas,
            total_items=len(reporte.lineas),
            totales_por_estado=totales_por_estado,
        )
