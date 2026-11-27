"""Servicio de ejecución de grants de la UI (design.md D8, tarea 5.1).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Capa de aplicación entre la confirmación de la UI y el pipeline: despacha la
solicitud validada al camino correcto del `PipelineGrants` — `ProcesarDesdeEntradas`
para 1 a 1 y `ProcesarLoteDesdeEntradas` para 1 a N / N a 1 (que, cuando el
pipeline lleva el `AgregadorReporteLotePython`, devuelve el `ReporteLoteGrant`
con totales). La ejecución NO confía en una previsualización previa: el pipeline
vuelve a ejecutar el pre-flight y revalida la autorización al confirmar, incluye
los bloqueados en el reporte, no ejecuta cuando todos quedan bloqueados y
continúa ante fallos parciales (todos comportamientos ya del pipeline de C1-C8).
"""

from control_accesos.dominio.modelos import SolicitudGrant, SolicitudLoteGrant

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_EJECUCION_UI = "ui.servicio_ejecucion"


class ServicioEjecucionGrantsUi:
    """Despacha la solicitud validada al camino del pipeline según cardinalidad.

    Attributes:
        pipeline (PipelineGrants): pipeline compuesto por la fábrica del
            contexto OBO (con resolutor, identidad y agregador de lote).
    """

    def __init__(self, pipeline):
        """Inicializa el servicio con el pipeline inyectado.

        Args:
            pipeline (PipelineGrants): pipeline real o doble en pruebas.

        Raises:
            ValueError: si no se aporta un pipeline.
        """
        if pipeline is None:
            raise ValueError(
                "El servicio de ejecución requiere un PipelineGrants para "
                "procesar las solicitudes."
            )
        self._pipeline = pipeline

    def Ejecutar(self, solicitud, identidad_llamante=None):
        """Ejecuta la solicitud validada por el camino que le corresponde.

        Args:
            solicitud (SolicitudGrant | SolicitudLoteGrant): solicitud validada
                por `ServicioSolicitudGrantsUi`.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para la revalidación; None usa la inyectada al pipeline.

        Returns:
            ReporteGrant | ReporteLoteGrant: reporte consolidado (el lote se
                agrega con `AgregadorReporteLotePython` cuando está inyectado).

        Raises:
            ValueError: si la solicitud no es `SolicitudGrant` ni
                `SolicitudLoteGrant`.
        """
        if isinstance(solicitud, SolicitudLoteGrant):
            return self._pipeline.ProcesarLoteDesdeEntradas(
                principales=solicitud.principales,
                privilegios=solicitud.privilegios,
                objetos=solicitud.objetos,
                identidad_llamante=identidad_llamante,
            )
        if isinstance(solicitud, SolicitudGrant):
            return self._pipeline.ProcesarDesdeEntradas(
                principal=solicitud.principal,
                privilegios=solicitud.privilegios,
                objeto=solicitud.objeto,
                identidad_llamante=identidad_llamante,
            )
        raise ValueError(
            "El servicio de ejecución solo admite SolicitudGrant (1 a 1) o "
            f"SolicitudLoteGrant (1 a N / N a 1); se recibió "
            f"{type(solicitud).__name__}."
        )
