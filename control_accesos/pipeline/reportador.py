"""Fase de reporte del pipeline (capability `grant-pipeline`).

Quinta y última fase del flujo `plan -> pre-flight -> ejecutar -> verificar ->
reporte` (README.md - Arquitectura). Consolida el resultado por ítem con su
estado final, su detalle o motivo y la trazabilidad de las fases que atravesó
(spec `grant-pipeline` - "Reporte por ítem").

La trazabilidad se registra con las constantes de este módulo, de modo que las
fases y sus consumidores (reportes, bitácoras, UI de C9) usen los mismos
nombres sin hardcodearlos en cada sitio.
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import EstadoItem
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import ItemGrant
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes

# Nombres canónicos de las marcas de trazabilidad por fase.
TRAZABILIDAD_PLANIFICADO = "planificado"
TRAZABILIDAD_PRE_FLIGHT_EJECUTABLE = "pre-flight: ejecutable"
TRAZABILIDAD_PRE_FLIGHT_BLOQUEADO = "pre-flight: bloqueado"
TRAZABILIDAD_EJECUTADO = "ejecutado"
TRAZABILIDAD_VERIFICADO = "verificado"

# Recorrido completo de un ítem que pasó por todas las fases.
TRAZABILIDAD_ITINERARIO_COMPLETO = (
    TRAZABILIDAD_PLANIFICADO,
    TRAZABILIDAD_PRE_FLIGHT_EJECUTABLE,
    TRAZABILIDAD_EJECUTADO,
    TRAZABILIDAD_VERIFICADO,
)

# Recorrido de un ítem bloqueado en pre-flight: nunca se ejecuta ni verifica.
TRAZABILIDAD_ITINERARIO_BLOQUEADO = (
    TRAZABILIDAD_PLANIFICADO,
    TRAZABILIDAD_PRE_FLIGHT_BLOQUEADO,
)


@dataclass(frozen=True)
class LineaReporte:
    """Una línea del reporte: el resultado consolidado de un ítem.

    Attributes:
        item (ItemGrant): ítem al que pertenece la línea.
        estado (EstadoItem): estado final del ítem (otorgado, fallido o
            privilegios insuficientes).
        detalle (Optional[str]): detalle del error, motivo del bloqueo o causa
            de los privilegios insuficientes; None cuando no aplica.
        trazabilidad (tuple[str, ...]): fases que atravesó el ítem, con los
            nombres canónicos de las constantes de este módulo.
        motivo_insuficiencia (MensajePrivilegiosInsuficientes | None): dato
            estructurado del bloqueo por privilegios insuficientes del
            llamante, con objeto, plano, privilegio requerido y faltante
            consultables por campo (change `auth-caller-obo`). None en los
            demás estados y en los bloqueos de la matriz de C1.
    """

    item: ItemGrant
    estado: EstadoItem
    detalle: Optional[str]
    trazabilidad: tuple
    motivo_insuficiencia: Optional[MensajePrivilegiosInsuficientes] = None


@dataclass(frozen=True)
class ReporteGrant:
    """Reporte consolidado de una ejecución del pipeline.

    Attributes:
        lineas (tuple[LineaReporte, ...]): una línea por ítem planificado, en
            el mismo orden de la planificación.
    """

    lineas: tuple

    def ObtenerLineasPorEstado(self, estado):
        """Filtra las líneas del reporte por su estado final.

        Args:
            estado (EstadoItem): estado por el que filtrar.

        Returns:
            list[LineaReporte]: líneas con ese estado, en el orden del reporte.
        """
        return [linea for linea in self.lineas if linea.estado is estado]


class Reportador:
    """Fase que consolida los resultados por ítem en el reporte final."""

    def Reportar(self, items_planificados, clasificacion, resultados_verificados):
        """Consolida el reporte de una ejecución del pipeline.

        Args:
            items_planificados (list[ItemGrant]): ítems generados por la fase
                de planificación, en su orden original.
            clasificacion (ClasificacionPreFlight): clasificación de pre-flight
                con los ítems bloqueados y sus motivos.
            resultados_verificados (list[ResultadoItem]): resultados de la
                ejecución ya confirmados por la fase de verificación.

        Returns:
            ReporteGrant: reporte con una línea por ítem planificado, en el
                mismo orden, con estado final, detalle y trazabilidad.

        Raises:
            ErrorDominio: si un ítem planificado no aparece ni entre los
                bloqueados de pre-flight ni entre los resultados verificados
                (inconsistencia interna del flujo, nunca silenciosa).
        """
        bloqueados_por_item = {
            resultado.item: resultado
            for resultado in clasificacion.items_bloqueados
        }
        resultados_por_item = {
            resultado.item: resultado
            for resultado in resultados_verificados
        }

        # El bloqueo por privilegios insuficientes (change `auth-caller-obo`)
        # llega como dato estructurado desde la clasificación de pre-flight.
        # Se accede por getattr para tolerar clasificaciones construidas sin
        # ese mapa (el comportamiento de C1 sigue siendo válido).
        obtener_mensaje_bloqueo = getattr(
            clasificacion, "mensaje_de_bloqueo", lambda item: None
        )

        lineas = []
        for item in items_planificados:
            if item in bloqueados_por_item:
                lineas.append(
                    self._LineaDeItemBloqueado(
                        item,
                        bloqueados_por_item[item],
                        obtener_mensaje_bloqueo(item),
                    )
                )
                continue

            resultado = resultados_por_item.get(item)
            if resultado is None:
                raise ErrorDominio(
                    f"El ítem {item.privilegio} sobre "
                    f"'{item.objeto.identificador}' fue planificado pero no "
                    "tiene resultado de ejecución ni bloqueo de pre-flight; "
                    "el flujo del pipeline es inconsistente."
                )
            lineas.append(
                self._LineaDeItemEjecutado(item, resultado)
            )

        return ReporteGrant(lineas=tuple(lineas))

    def _LineaDeItemBloqueado(self, item, resultado_bloqueado, motivo_insuficiencia=None):
        """Construye la línea de reporte de un ítem bloqueado en pre-flight.

        Args:
            item (ItemGrant): ítem bloqueado.
            resultado_bloqueado (ResultadoItem): resultado con el motivo del
                bloqueo (mensaje preciso de la matriz, o causa del bloqueo por
                privilegios insuficientes).
            motivo_insuficiencia (MensajePrivilegiosInsuficientes | None):
                dato estructurado del bloqueo por privilegios del llamante,
                para que el reporte y la interfaz consulten objeto, plano,
                privilegio requerido y faltante por campo; None en los
                bloqueos de la matriz de C1.

        Returns:
            LineaReporte: línea con el estado y motivo del bloqueo, y la
                trazabilidad que llega solo hasta pre-flight.
        """
        return LineaReporte(
            item=item,
            estado=resultado_bloqueado.estado,
            detalle=resultado_bloqueado.detalle,
            trazabilidad=TRAZABILIDAD_ITINERARIO_BLOQUEADO,
            motivo_insuficiencia=motivo_insuficiencia,
        )

    def _LineaDeItemEjecutado(self, item, resultado):
        """Construye la línea de reporte de un ítem ejecutado y verificado.

        Args:
            item (ItemGrant): ítem ejecutado.
            resultado (ResultadoItem): resultado final tras la verificación.

        Returns:
            LineaReporte: línea con el estado final, su detalle y la
                trazabilidad del itinerario completo.
        """
        return LineaReporte(
            item=item,
            estado=resultado.estado,
            detalle=resultado.detalle,
            trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
        )
