"""Contratos de los canales de ejecución de grants (capability `channel-adapters`).

Definen el contrato unificado del dominio (design.md D4): cada canal recibe un
`ItemGrant` ya validado y devuelve un `ResultadoItem`, sin propagar excepciones
al llamador. Los tres canales del proyecto (SQL, SDK y REST) responden a este
contrato, de modo que el pipeline puede seleccionar el canal según el plano del
objeto sin conocer su mecánica interna.

En este change solo existen contratos e implementaciones simuladas; las
implementaciones reales (SQL sobre workspace, SDK y REST) llegan en C4 en
adelante (spec `channel-adapters` - "En este change no se ejecutan operaciones
externas reales").

Los contratos no usan tipos del SDK: trabajan con tipos propios del dominio
para que las pruebas y el pipeline no dependan de la versión de una biblioteca
externa. La lista de grants vigentes se expresa con el mismo `ItemGrant`
(principal + privilegio + objeto), que es la forma en la que el verificador del
pipeline compara lo otorgado con lo vigente.
"""

from abc import ABC, abstractmethod

from control_accesos.canales.errores import ErrorPrivilegiosInsuficientes
from control_accesos.dominio.modelos import ResultadoItem


class Canal(ABC):
    """Contrato unificado de un canal de ejecución de grants.

    Las implementaciones concretas (reales o simuladas) solo definen cómo se
    ejecuta cada operación; la traducción de errores a resultados por ítem la
    hace este contrato, garantizando que ninguna excepción llegue al pipeline.
    """

    def Otorgar(self, item):
        """Otorga el privilegio del ítem y devuelve su resultado.

        Args:
            item (ItemGrant): ítem validado (principal, privilegio, objeto).

        Returns:
            ResultadoItem: resultado con estado OTORGADO, FALLIDO o
                PRIVILEGIOS_INSUFICIENTES según lo ocurrido en la ejecución.
        """
        try:
            self.EjecutarOtorgamiento(item)
        except ErrorPrivilegiosInsuficientes as error:
            # Permiso denegado del sistema externo: estado distinguible.
            return ResultadoItem.PrivilegiosInsuficientes(item, causa=str(error))
        except Exception as error:  # noqa: BLE001 - el contrato nunca propaga
            # Cualquier otro fallo (incluidos los no previstos) se reporta.
            return ResultadoItem.Fallido(item, detalle=self._DetalleDeError(error))

        return ResultadoItem.Otorgado(item)

    def Revocar(self, item):
        """Revoca el privilegio del ítem y devuelve su resultado.

        Args:
            item (ItemGrant): ítem validado a revocar.

        Returns:
            ResultadoItem: resultado por ítem, con el mismo contrato que
                `Otorgar`.
        """
        try:
            self.EjecutarRevocacion(item)
        except ErrorPrivilegiosInsuficientes as error:
            return ResultadoItem.PrivilegiosInsuficientes(item, causa=str(error))
        except Exception as error:  # noqa: BLE001 - el contrato nunca propaga
            return ResultadoItem.Fallido(item, detalle=self._DetalleDeError(error))

        return ResultadoItem.Otorgado(item)

    def _DetalleDeError(self, error):
        """Construye el detalle de un error para el resultado por ítem.

        Args:
            error (Exception): excepción ocurrida durante la ejecución.

        Returns:
            str: texto del error; si el error no trae mensaje, se usa el nombre
                de su tipo para que el detalle nunca quede vacío (el resultado
                FALLIDO exige detalle).
        """
        detalle = str(error).strip()
        if detalle:
            return detalle
        return f"Error sin mensaje del tipo {type(error).__name__}."

    @abstractmethod
    def EjecutarOtorgamiento(self, item):
        """Ejecuta el otorgamiento en el sistema externo (implementación concreta).

        Args:
            item (ItemGrant): ítem a otorgar.

        Raises:
            ErrorPrivilegiosInsuficientes: si el sistema externo responde con
                permiso denegado para el ejecutor.
            ErrorCanal: si ocurre cualquier otro fallo de ejecución.
        """

    @abstractmethod
    def EjecutarRevocacion(self, item):
        """Ejecuta la revocación en el sistema externo (implementación concreta).

        Args:
            item (ItemGrant): ítem a revocar.

        Raises:
            ErrorPrivilegiosInsuficientes: si el sistema externo responde con
                permiso denegado para el ejecutor.
            ErrorCanal: si ocurre cualquier otro fallo de ejecución.
        """

    @abstractmethod
    def ListarGrantsVigentes(self, objeto):
        """Lista los privilegios vigentes de un objeto (para la verificación).

        Args:
            objeto (ObjetoSecurable): objeto cuyos grants vigentes se consultan.

        Returns:
            list[ItemGrant]: grants vigentes del objeto tal como el sistema los
                reporta (en el plano de datos equivale a SHOW GRANTS; en el
                plano de control, a la lectura de la ACL del objeto).
        """


class CanalDatos(Canal):
    """Contrato del canal SQL para el plano de datos (Unity Catalog).

    Las implementaciones concretas construyen y ejecutan instrucciones SQL
    GRANT/REVOKE (en mayúsculas, según el estándar del proyecto) y consultan
    los grants vigentes con SHOW GRANTS.
    """


class CanalControl(Canal):
    """Contrato del canal SDK/REST para el plano de control (workspace).

    Las implementaciones concretas otorgan y revocan permisos mediante la
    Permissions API, y para el uso de personal access tokens mediante la Token
    Permissions API (`authorization/tokens`); los grants vigentes se obtienen
    leyendo la ACL del objeto.
    """
