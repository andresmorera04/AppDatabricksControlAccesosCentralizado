"""Servicio de previsualización de grants de la UI (design.md D8).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.2.

Capa de aplicación entre la solicitud validada y la vista: planifica la
solicitud en ítems atómicos (según su cardinalidad, reutilizando el
`Planificador`) y delega la clasificación en `PreFlight` con la identidad del
llamante y su resolutor de privilegios efectivos. Devuelve la
`ClasificacionPreFlight` completa (ejecutables, bloqueados con sus motivos y
mensajes estructurados) sin ejecutar nada.

Regla de seguridad que fija esta composición (design.md D8): la previsualización
es **de solo lectura**. Este servicio NO crea ni recibe `PipelineGrants`,
ejecutor ni canales de escritura; solo planifica y clasifica, de modo que no
existe camino de escritura en esta capa.
"""

from control_accesos.dominio.modelos import SolicitudGrant, SolicitudLoteGrant

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_PREVISUALIZACION_UI = "ui.servicio_previsualizacion"


class ServicioPrevisualizacionGrants:
    """Planifica y clasifica una solicitud para su previsualización (solo lectura).

    Attributes:
        planificador: `Planificador` del pipeline (expandir solicitud a ítems).
        pre_flight: `PreFlight` configurado con consultora y resolutor.
    """

    def __init__(self, planificador, pre_flight):
        """Inicializa el servicio con sus colaboradores de solo lectura.

        Args:
            planificador: `Planificador` real o doble en pruebas.
            pre_flight: `PreFlight` real o doble en pruebas.

        Raises:
            ValueError: si falta alguno de los colaboradores.
        """
        if planificador is None or pre_flight is None:
            raise ValueError(
                "La previsualización requiere un Planificador y un PreFlight "
                "para planificar y clasificar sin ejecutar."
            )
        self._planificador = planificador
        self._pre_flight = pre_flight

    def Previsualizar(self, solicitud, identidad_llamante):
        """Planifica la solicitud y devuelve la clasificación del pre-flight.

        Args:
            solicitud (SolicitudGrant | SolicitudLoteGrant): solicitud validada
                por `ServicioSolicitudGrantsUi`.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para el eje de privilegios efectivos.

        Returns:
            ClasificacionPreFlight: ítems ejecutables y bloqueados con sus
                motivos, sin ejecutar operación alguna.

        Raises:
            ValueError: si la solicitud no es `SolicitudGrant` ni
                `SolicitudLoteGrant`.
        """
        items = self._Planificar(solicitud)
        return self._pre_flight.Clasificar(items, identidad_llamante)

    def _Planificar(self, solicitud):
        """Expande la solicitud a ítems según su cardinalidad.

        Args:
            solicitud: solicitud validada (1 a 1 o lote).

        Returns:
            list[ItemGrant]: ítems atómicos de la solicitud.

        Raises:
            ValueError: si el tipo de solicitud no es soportado.
        """
        if isinstance(solicitud, SolicitudLoteGrant):
            return self._planificador.PlanificarLote(solicitud)
        if isinstance(solicitud, SolicitudGrant):
            return self._planificador.Planificar(solicitud)
        raise ValueError(
            "La previsualización solo admite SolicitudGrant (1 a 1) o "
            f"SolicitudLoteGrant (1 a N / N a 1); se recibió "
            f"{type(solicitud).__name__}."
        )
