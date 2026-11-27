"""Servicio de disponibilidad de opciones según privilegios efectivos (design.md D7).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 3.5.

Capa de aplicación entre el resolutor de privilegios efectivos (C3) y la vista:
evalúa, para cada objeto descubierto, si el llamante puede otorgar los
privilegios seleccionados, sin añadir ninguna regla de autorización propia. La
semántica es exactamente la de C3 (coincidencia del privilegio solicitado; no
hay expansión de jerarquías ni atajos por `admins`/`CAN_MANAGE`):

- resuelve **una vez por objeto** dentro de la acción (los objetos se
  desduplican conservando el orden de aparición);
- una combinación objeto-privilegio queda `NO_DISPONIBLE` cuando el privilegio
  no figura entre los efectivos, con el `MensajePrivilegiosInsuficientes`
  estructurado de C3 (objeto, plano, privilegio requerido y autoridad
  faltante declarada en `PRIVILEGIO_AUTORIZADOR_POR_PLANO`);
- un fallo de resolución se distingue del bloqueo: estado `ERROR_RESOLUCION`
  (no se afirma ni se niega el privilegio); nunca se presenta como disponible.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.resolucion.errores import ErrorResolucionPrivilegios
from control_accesos.resolucion.modelos import (
    MensajePrivilegiosInsuficientes,
    PRIVILEGIO_AUTORIZADOR_POR_PLANO,
)

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_DISPONIBILIDAD_UI = "ui.servicio_disponibilidad"


class EstadoDisponibilidad(Enum):
    """Estados de disponibilidad de un objeto para las opciones seleccionadas."""

    DISPONIBLE = "disponible"
    NO_DISPONIBLE = "no_disponible"
    ERROR_RESOLUCION = "error_resolucion"


@dataclass(frozen=True)
class DisponibilidadObjeto:
    """Disponibilidad de un objeto para los privilegios seleccionados.

    Attributes:
        objeto (ObjetoSecurable): objeto evaluado.
        estado (EstadoDisponibilidad): disponible, no disponible o error de
            resolución (distinto del bloqueo por privilegios).
        mensaje (MensajePrivilegiosInsuficientes | None): dato estructurado del
            bloqueo, cuando el estado es NO_DISPONIBLE.
        detalle_error (str | None): descripción del fallo de resolución.
    """

    objeto: ObjetoSecurable
    estado: EstadoDisponibilidad
    mensaje: Optional[MensajePrivilegiosInsuficientes] = None
    detalle_error: Optional[str] = None


class ServicioDisponibilidadOpciones:
    """Evalúa la disponibilidad de objetos según los privilegios efectivos.

    No conserva estado entre invocaciones (por acción): el resultado de una
    evaluación se obtiene en la misma llamada; los objetos se resuelven una vez
    cada uno dentro de esa llamada.

    Attributes:
        resolutor_privilegios: resolutor de C3 con
            `ResolverPrivilegiosEfectivos(identidad, objeto) -> vista` con
            `TieneElPrivilegio(privilegio)`.
    """

    def __init__(self, resolutor_privilegios):
        """Inicializa el servicio con el resolutor inyectado.

        Args:
            resolutor_privilegios: resolutor real o doble en pruebas.

        Raises:
            ValueError: si el resolutor es nulo (fail-fast de cableado).
        """
        if resolutor_privilegios is None:
            raise ValueError(
                "Se requiere un resolutor de privilegios efectivos (C3) para "
                "el servicio de disponibilidad de opciones."
            )
        self._resolutor = resolutor_privilegios

    def Evaluar(self, objetos, privilegios, identidad_llamante):
        """Evalúa la disponibilidad de cada objeto para los privilegios dados.

        Args:
            objetos (Iterable[ObjetoSecurable]): objetos descubiertos a evaluar;
                se desduplican conservando el orden de aparición.
            privilegios (Iterable[str]): privilegios seleccionados a comprobar.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante; None hace que el resolutor falle (error de resolución).

        Returns:
            tuple[DisponibilidadObjeto, ...]: un resultado por objeto distinto,
                en orden de primera aparición.
        """
        resultados = []

        for objeto in self._ObjetosDistintos(objetos):
            resultados.append(
                self._EvaluarObjeto(objeto, privilegios, identidad_llamante)
            )

        return tuple(resultados)

    def _EvaluarObjeto(self, objeto, privilegios, identidad_llamante):
        """Evalúa la disponibilidad de un único objeto.

        Args:
            objeto (ObjetoSecurable): objeto a evaluar.
            privilegios (Iterable[str]): privilegios a comprobar.
            identidad_llamante: identidad del llamante.

        Returns:
            DisponibilidadObjeto: disponible (todos los privilegios efectivos),
                no disponible (algún privilegio faltante, con su mensaje
                estructurado) o error de resolución.
        """
        try:
            vista = self._resolutor.ResolverPrivilegiosEfectivos(
                identidad_llamante, objeto
            )
        except ErrorResolucionPrivilegios as excepcion:
            return DisponibilidadObjeto(
                objeto=objeto,
                estado=EstadoDisponibilidad.ERROR_RESOLUCION,
                detalle_error=str(excepcion),
            )

        for privilegio in privilegios:
            if not vista.TieneElPrivilegio(privilegio):
                return DisponibilidadObjeto(
                    objeto=objeto,
                    estado=EstadoDisponibilidad.NO_DISPONIBLE,
                    mensaje=self._MensajePrivilegiosInsuficientes(
                        objeto, privilegio
                    ),
                )

        return DisponibilidadObjeto(
            objeto=objeto, estado=EstadoDisponibilidad.DISPONIBLE
        )

    @staticmethod
    def _ObjetosDistintos(objetos):
        """Desduplica los objetos conservando el orden de aparición.

        Args:
            objetos (Iterable[ObjetoSecurable]): objetos a desduplicar.

        Returns:
            tuple[ObjetoSecurable, ...]: objetos distintos, en orden.
        """
        return tuple(
            dict.fromkeys(objeto for objeto in (objetos or ()))
        )

    @staticmethod
    def _MensajePrivilegiosInsuficientes(objeto, privilegio):
        """Construye el bloqueo estructurado de C3 (sin regla nueva).

        La autoridad faltante es la declarada por plano en
        `PRIVILEGIO_AUTORIZADOR_POR_PLANO` (MANAGE en datos, CAN_MANAGE en
        control), exactamente como hace el pre-flight de C3.

        Args:
            objeto (ObjetoSecurable): objeto evaluado.
            privilegio (str): privilegio solicitado que el llamante no tiene.

        Returns:
            MensajePrivilegiosInsuficientes: dato del bloqueo.
        """
        plano = objeto.plano
        return MensajePrivilegiosInsuficientes(
            objeto=objeto,
            plano=plano,
            privilegio_requerido=privilegio,
            privilegio_faltante=PRIVILEGIO_AUTORIZADOR_POR_PLANO.get(plano)
            or privilegio,
        )
