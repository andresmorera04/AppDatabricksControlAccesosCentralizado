"""Presentador de grants de la UI (design.md D2, tarea 4.4).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Capa de presentación que transforma la previsualización y el reporte del
pipeline en filas inmutables listas para la vista, sin reimplementar lógica ni
parsear textos: cada campo de la fila proviene del modelo del dominio y, para
el motivo de privilegios insuficientes, del `MensajePrivilegiosInsuficientes`
estructurado (privilegio requerido/faltante por campo). No serializa ni expone
credenciales (el dominio no las contiene).

Fila presentada (modelo de vista):
- principal (identificador y tipo), privilegio, objeto (identificador y tipo);
- estado, detalle y trazabilidad;
- motivo de insuficiencia por campo (privilegio requerido y faltante).
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import EstadoItem
from control_accesos.dominio.modelos import ResultadoItem

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_PRESENTADOR = "ui.presentador"

# Estado de presentación de un ítem ejecutable en la previsualización (no es un
# estado final del dominio: aún no se ejecutó).
ESTADO_PREVISUALIZACION_EJECUTABLE = "ejecutable"


@dataclass(frozen=True)
class FilaPresentacion:
    """Fila inmutable presentada a la vista (previsualización o reporte).

    Attributes:
        principal_identificador (str): identificador del principal del ítem.
        principal_tipo (str): tipo del principal (texto de la enumeración).
        privilegio (str): privilegio del ítem (forma canónica).
        objeto_identificador (str): identificador del objeto.
        objeto_tipo (str): tipo del objeto (texto de la enumeración).
        estado (str): estado para la vista (`ejecutable` en previsualización, o
            el estado final `EstadoItem` en el reporte/blockeos).
        detalle (str | None): detalle del error o motivo; None si no aplica.
        trazabilidad (tuple[str, ...]): fases que atravesó el ítem.
        privilegio_requerido (str | None): privilegio que se pretendía otorgar
            (bloqueos por privilegios insuficientes), desde el dato estructurado.
        privilegio_faltante (str | None): autoridad faltante para poder
            otorgarlo, desde el dato estructurado.
    """

    principal_identificador: str
    principal_tipo: str
    privilegio: str
    objeto_identificador: str
    objeto_tipo: str
    estado: str
    detalle: Optional[str]
    trazabilidad: tuple
    privilegio_requerido: Optional[str] = None
    privilegio_faltante: Optional[str] = None


class PresentadorGrantsUi:
    """Transforma previsualización y reporte en filas para la vista."""

    def PresentarPrevisualizacion(self, clasificacion):
        """Presenta el split de pre-flight (ejecutables y bloqueados).

        Args:
            clasificacion (ClasificacionPreFlight): resultado del pre-flight,
                con ejecutables, bloqueados y mensajes estructurados.

        Returns:
            tuple[FilaPresentacion, ...]: ejecutables primero (estado
                `ejecutable`) y luego bloqueados en su orden, con su estado
                final, detalle y motivo de insuficiencia por campo.
        """
        filas = []

        for item in clasificacion.items_ejecutables:
            filas.append(
                self._FilaDesdeItem(
                    item,
                    estado=ESTADO_PREVISUALIZACION_EJECUTABLE,
                    detalle=None,
                    trazabilidad=(),
                )
            )

        obtener_motivo = getattr(clasificacion, "mensaje_de_bloqueo", lambda i: None)
        for resultado in clasificacion.items_bloqueados:
            motivo = obtener_motivo(resultado.item)
            filas.append(
                self._FilaDesdeResultado(resultado, motivo=motivo)
            )

        return tuple(filas)

    def PresentarReporte(self, reporte):
        """Presenta las líneas del reporte en el orden de planificación.

        Args:
            reporte (ReporteGrant): reporte consolidado con una línea por ítem,
                en el orden de planificación.

        Returns:
            tuple[FilaPresentacion, ...]: una fila por línea, en el mismo orden.
        """
        return tuple(
            self._FilaDesdeLinea(linea) for linea in reporte.lineas
        )

    def PresentarTotales(self, reporte_lote):
        """Presenta los totales del lote, con los tres estados (ceros incluidos).

        Args:
            reporte_lote (ReporteLoteGrant): reporte consolidado del lote.

        Returns:
            dict: `{"total_items": int, "totales_por_estado": {valor_estado:
                cantidad}}` con los tres estados presentes aunque queden en cero.
        """
        totales_por_estado = {
            estado.value: reporte_lote.totales_por_estado.get(estado, 0)
            for estado in EstadoItem
        }
        return {
            "total_items": reporte_lote.total_items,
            "totales_por_estado": totales_por_estado,
        }

    # ------------------------------------------------------------------ #
    # Construcción de filas desde cada forma del dominio.
    # ------------------------------------------------------------------ #

    @staticmethod
    def _FilaDesdeItem(item, estado, detalle, trazabilidad):
        """Construye una fila desde un `ItemGrant` (sin resultado)."""
        return FilaPresentacion(
            principal_identificador=item.principal.identificador,
            principal_tipo=item.principal.tipo.value,
            privilegio=item.privilegio,
            objeto_identificador=item.objeto.identificador,
            objeto_tipo=item.objeto.tipo.value,
            estado=estado,
            detalle=detalle,
            trazabilidad=tuple(trazabilidad),
        )

    @staticmethod
    def _FilaDesdeResultado(resultado, motivo=None):
        """Construye una fila desde un `ResultadoItem` (bloqueado en pre-flight)."""
        return FilaPresentacion(
            principal_identificador=resultado.item.principal.identificador,
            principal_tipo=resultado.item.principal.tipo.value,
            privilegio=resultado.item.privilegio,
            objeto_identificador=resultado.item.objeto.identificador,
            objeto_tipo=resultado.item.objeto.tipo.value,
            estado=resultado.estado.value,
            detalle=resultado.detalle,
            trazabilidad=(),
            privilegio_requerido=(
                getattr(motivo, "privilegio_requerido", None)
                if motivo is not None
                else None
            ),
            privilegio_faltante=(
                getattr(motivo, "privilegio_faltante", None)
                if motivo is not None
                else None
            ),
        )

    @staticmethod
    def _FilaDesdeLinea(linea):
        """Construye una fila desde una `LineaReporte` del reporte."""
        motivo = linea.motivo_insuficiencia
        return FilaPresentacion(
            principal_identificador=linea.item.principal.identificador,
            principal_tipo=linea.item.principal.tipo.value,
            privilegio=linea.item.privilegio,
            objeto_identificador=linea.item.objeto.identificador,
            objeto_tipo=linea.item.objeto.tipo.value,
            estado=linea.estado.value,
            detalle=linea.detalle,
            trazabilidad=tuple(linea.trazabilidad),
            privilegio_requerido=(
                getattr(motivo, "privilegio_requerido", None)
                if motivo is not None
                else None
            ),
            privilegio_faltante=(
                getattr(motivo, "privilegio_faltante", None)
                if motivo is not None
                else None
            ),
        )
