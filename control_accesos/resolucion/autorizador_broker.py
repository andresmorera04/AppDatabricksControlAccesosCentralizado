"""Autorizador de las escrituras del modo broker (design.md D2).

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Es el cerrojo que cierra el modelo broker: aunque el service principal de la App
PUEDA ejecutar cualquier escritura de ACL del plano de control (rol Workspace
admin + entitlements, design.md D5), ninguna escritura se ejecuta sin validar
previamente, en la MISMA acción, que el llamante posee el privilegio efectivo que
autoriza esa operación (spec `app-broker-grants` - "Autorización por llamante
previa a toda ejecución elevada").

Cómo funciona:

- la autoridad del llamante se resuelve leyendo las ACL/grants con el canal del
  service principal (el `ResolutorPrivilegiosEfectivos` inyectado), que empareja
  los otorgamientos con la identidad y los grupos del llamante (semántica C3 sin
  cambios);
- el privilegio que autoriza gestionar un objeto es el declarado por plano en
  `PRIVILEGIO_AUTORIZADOR_POR_PLANO` (`CAN_MANAGE` en el plano de control,
  `MANAGE` en el de datos);
- la escritura se DELEGA al canal del SP solo tras validar esa autoridad; sin
  autoridad se lanza `ErrorPrivilegiosInsuficientes` (que el contrato traduce a
  resultado bloqueado por ítem) y la operación NO llega al workspace;
- cada escritura re-valida (re-resuelve) en el momento de ejecutarse: los
  privilegios vigentes se releen, no se cachean entre previsualización y
  confirmación (TOCTOU, spec - "Revalidación al confirmar");
- no existe estado compartido entre llamantes: el autorizador no guarda
  cache de autoridad alguna (spec - "Aislamiento entre llamantes").
"""

from control_accesos.canales.errores import ErrorPrivilegiosInsuficientes
from control_accesos.resolucion.errores import ErrorIdentidadNoResuelta
from control_accesos.resolucion.modelos import PRIVILEGIO_AUTORIZADOR_POR_PLANO

# Identificador del módulo para la bitácora de errores.
MODULO_AUTORIZADOR_BROKER = "resolucion.autorizador_broker"


class AutorizadorBroker:
    """Valida la autoridad del llamante antes de cada escritura del SP.

    Attributes:
        canal_control: canal del plano de control con la identidad del SP
            (`CanalControlComputo` en producción), que ejecuta la escritura
            una vez validada la autoridad del llamante.
        resolutor_privilegios: `ResolutorPrivilegiosEfectivos` que lee las ACL
            con el canal del SP y las empareja con la identidad del llamante.
    """

    def __init__(
        self,
        canal_control,
        resolutor_privilegios,
        registrador_errores=None,
    ):
        """Inicializa el autorizador con el canal SP y el resolutor inyectados.

        Args:
            canal_control: canal del SP con `EjecutarOtorgamiento(item)` y
                `EjecutarRevocacion(item)` (la escritura delegada).
            resolutor_privilegios: resolutor cuyo `ResolverPrivilegiosEfectivos`
                devuelve la vista de privilegios efectivos del llamante.
            registrador_errores (BitacoraErrores | None): bitácora opcional.

        Raises:
            ValueError: si falta el canal o el resolutor.
        """
        if canal_control is None:
            raise ValueError("Se requiere el canal de control del SP para el broker.")
        if resolutor_privilegios is None:
            raise ValueError(
                "Se requiere el resolutor de privilegios efectivos para validar "
                "la autoridad del llamante."
            )
        self._canal_control = canal_control
        self._resolutor_privilegios = resolutor_privilegios
        self._registrador_errores = registrador_errores

    def ValidarAutoridad(self, identidad_llamante, objeto):
        """Indica si el llamante tiene la autoridad para gestionar el objeto.

        Re-resuelve SIEMPRE los privilegios vigentes (sin cache), de modo que un
        cambio entre previsualización y confirmación se detecta aquí (TOCTOU).

        Args:
            identidad_llamante (IdentidadLlamante): identidad del llamante.
            objeto (ObjetoSecurable): objeto sobre el que se va a escribir.

        Returns:
            bool: True si el llamante tiene el privilegio autorizador del plano.

        Raises:
            ErrorPrivilegiosInsuficientes: si no hay identidad que evaluar (no
                se afirma autoridad, fail-safe).
        """
        vista = self._resolutor_privilegios.ResolverPrivilegiosEfectivos(
            identidad_llamante, objeto
        )
        if not vista.FueConsultaExitosa:
            return False
        autorizador = PRIVILEGIO_AUTORIZADOR_POR_PLANO.get(objeto.plano)
        if autorizador is None:
            # Sin autoridad declarada para el plano (no debe ocurrir) no se
            # autoriza a ciegas: nadie ejecuta.
            return False
        return vista.TieneElPrivilegio(autorizador)

    def EjecutarOtorgamiento(self, item, identidad_llamante):
        """Valida la autoridad del llamante y, si la tiene, otorga con el SP.

        Args:
            item (ItemGrant): ítem a otorgar (escritura del broker).
            identidad_llamante (IdentidadLlamante): identidad del llamante.

        Raises:
            ErrorPrivilegiosInsuficientes: si el llamante no tiene la autoridad.
        """
        self._ExigirAutoridad(identidad_llamante, item.objeto)
        return self._canal_control.EjecutarOtorgamiento(item)

    def EjecutarRevocacion(self, item, identidad_llamante):
        """Valida la autoridad del llamante y, si la tiene, revoca con el SP.

        Args:
            item (ItemGrant): ítem a revocar (escritura del broker).
            identidad_llamante (IdentidadLlamante): identidad del llamante.

        Raises:
            ErrorPrivilegiosInsuficientes: si el llamante no tiene la autoridad.
        """
        self._ExigirAutoridad(identidad_llamante, item.objeto)
        return self._canal_control.EjecutarRevocacion(item)

    def _ExigirAutoridad(self, identidad_llamante, objeto):
        """Bloquea la escritura si el llamante no tiene la autoridad requerida.

        Args:
            identidad_llamante (IdentidadLlamante): identidad del llamante.
            objeto (ObjetoSecurable): objeto sobre el que se escribe.

        Raises:
            ErrorPrivilegiosInsuficientes: si no hay identidad o falta el
                privilegio autorizador; la escritura NO se ejecuta.
        """
        if not self.ValidarAutoridad(identidad_llamante, objeto):
            autorizador = PRIVILEGIO_AUTORIZADOR_POR_PLANO.get(
                objeto.plano, "el privilegio autorizador"
            )
            raise ErrorPrivilegiosInsuficientes(
                f"[{MODULO_AUTORIZADOR_BROKER}] Escritura en modo broker "
                f"bloqueada sobre {objeto.tipo.value} "
                f"'{objeto.identificador}': el llamante no tiene {autorizador} "
                f"sobre el objeto (autorización por llamante, design.md D2)."
            )
