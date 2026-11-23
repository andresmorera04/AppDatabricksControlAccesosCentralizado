"""Fase de pre-flight del pipeline (capability `grant-pipeline`).

Segunda fase del flujo `plan -> pre-flight -> ejecutar -> verificar -> reporte`
(README.md - Arquitectura). Evalúa cada ítem contra la matriz de
compatibilidad privilegio x tipo de objeto (capability `privilege-matrix`) y
lo clasifica como ejecutable o bloqueado ANTES de ejecutar operación alguna
(spec `grant-pipeline` - "Fase de pre-flight").

Un ítem bloqueado nunca llega a la ejecución: pasa directamente al reporte
como `ResultadoItem` en estado FALLIDO, con el mensaje preciso de la matriz
como motivo (el mensaje identifica el privilegio, el tipo de objeto y los
privilegios válidos alternativos).
"""

from dataclasses import dataclass

from control_accesos.dominio.modelos import ResultadoItem
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios


@dataclass(frozen=True)
class ClasificacionPreFlight:
    """Resultado de la clasificación de los ítems en la fase de pre-flight.

    Attributes:
        items_ejecutables (tuple[ItemGrant, ...]): ítems cuya combinación
            privilegio x tipo de objeto está declarada en la matriz y, por lo
            tanto, pueden pasar a la fase de ejecución.
        items_bloqueados (tuple[ResultadoItem, ...]): ítems rechazados por la
            matriz, ya expresados como resultados por ítem (estado FALLIDO con
            el motivo preciso), listos para incorporarse al reporte.
    """

    items_ejecutables: tuple
    items_bloqueados: tuple


class PreFlight:
    """Fase que clasifica los ítems contra la matriz antes de ejecutarlos."""

    def __init__(self, consultora=None):
        """Inicializa la fase con la consultora de la matriz a utilizar.

        Args:
            consultora (ConsultoraMatrizPrivilegios | None): consultora de la
                matriz de compatibilidad. Si es None, se usa la consultora por
                defecto con la matriz declarada en el proyecto. La inyección
                permite ampliar o restringir la matriz sin tocar esta fase
                (design.md D5: inyección de dependencias por fase).
        """
        self._consultora = (
            ConsultoraMatrizPrivilegios() if consultora is None else consultora
        )

    def Clasificar(self, items):
        """Clasifica una lista de ítems en ejecutables y bloqueados.

        Args:
            items (list[ItemGrant]): ítems atómicos generados por la fase de
                planificación.

        Returns:
            ClasificacionPreFlight: los ítems ejecutables (en el orden
                recibido) y los bloqueados como resultados por ítem con su
                motivo.
        """
        items_ejecutables = []
        items_bloqueados = []

        for item in items:
            if self._consultora.EsCombinacionValida(
                item.privilegio, item.objeto.tipo
            ):
                items_ejecutables.append(item)
                continue

            # Ítem bloqueado: se expresa como resultado FALLIDO con el mensaje
            # preciso de la matriz, y pasa directamente al reporte.
            motivo = self._consultora.MensajeCombinacionInvalida(
                item.privilegio, item.objeto.tipo
            )
            items_bloqueados.append(ResultadoItem.Fallido(item, detalle=motivo))

        return ClasificacionPreFlight(
            items_ejecutables=tuple(items_ejecutables),
            items_bloqueados=tuple(items_bloqueados),
        )
