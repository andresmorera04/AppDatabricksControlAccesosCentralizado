"""Implementaciones simuladas de los canales (capability `channel-adapters`).

Estos canales *fake* reproducen las respuestas de los sistemas externos
(éxito, permiso denegado, objeto inexistente) sin realizar ninguna conexión,
de modo que las pruebas unitarias y funcionales del pipeline se ejecuten de
forma determinista (spec `channel-adapters` - "Implementaciones simulables
para testing").

Configuración disponible:

- `escenario_por_defecto`: escenario aplicado a todo ítem sin configuración
  propia.
- `ConfigurarEscenario(item, escenario)`: escenario por ítem, para simular
  solicitudes mixtas (unos ítems otorgados, otros denegados).
- `ConfigurarGrantsVigentes(objeto, grants)`: grants vigentes iniciales de un
  objeto, para simular el estado previo del workspace.
- `registrar_grants_otorgados`: cuando es False, lo otorgado no aparece en la
  consulta de grants vigentes, lo que permite ejercitar la discrepancia entre
  ejecución y verificación (spec `grant-pipeline`).

Los códigos de error imitan los de la documentación oficial de Databricks
(`PERMISSION_DENIED` en Unity Catalog; `RESOURCE_DOES_NOT_EXIST` en la REST
API del plano de control) para que las pruebas funcionales se parezcan a las
respuestas reales que contrastarán las pruebas integrales de C4+.
"""

from dataclasses import dataclass
from enum import Enum

from control_accesos.canales.contratos import Canal, CanalControl, CanalDatos
from control_accesos.canales.errores import ErrorCanal, ErrorPrivilegiosInsuficientes


class EscenarioSimulacion(Enum):
    """Escenarios de respuesta que un canal simulado puede reproducir."""

    EXITO = "exito"
    PERMISO_DENEGADO = "permiso_denegado"
    OBJETO_INEXISTENTE = "objeto_inexistente"


@dataclass(frozen=True)
class OperacionEjecutada:
    """Registro de una operación ejecutada por el canal simulado.

    Sirve para la trazabilidad de las pruebas: permite verificar qué ítems
    pasaron por el canal y con qué escenario configurado.

    Attributes:
        operacion (str): "otorgar" o "revocar".
        item (ItemGrant): ítem sobre el que se ejecutó la operación.
        escenario (EscenarioSimulacion): escenario aplicado al ítem.
    """

    operacion: str
    item: object
    escenario: EscenarioSimulacion


class CanalSimulado(Canal):
    """Lógica compartida de los canales simulados (configurables por escenario).

    Implementa los métodos abstractos del contrato `Canal` sobre estado en
    memoria, sin ninguna conexión externa. Las subclases por plano solo ajustan
    los códigos de error que reportan.
    """

    # Código de permiso denegado (común a ambos planos en la doc oficial).
    CODIGO_PERMISO_DENEGADO = "PERMISSION_DENIED"
    # Código de objeto inexistente; cada plano declara el suyo.
    CODIGO_OBJETO_INEXISTENTE = "OBJECT_NOT_FOUND"

    def __init__(
        self,
        escenario_por_defecto: EscenarioSimulacion = EscenarioSimulacion.EXITO,
        registrar_grants_otorgados: bool = True,
    ):
        """Inicializa el canal simulado con su configuración de escenarios.

        Args:
            escenario_por_defecto (EscenarioSimulacion): escenario aplicado a
                los ítems que no tengan un escenario propio configurado.
            registrar_grants_otorgados (bool): si True, cada otorgamiento
                exitoso queda visible en la consulta de grants vigentes; si
                False, se simula una verificación que no encuentra el grant.
        """
        self._escenario_por_defecto = escenario_por_defecto
        self._registrar_grants_otorgados = registrar_grants_otorgados
        # Escenarios configurados por ítem (ItemGrant es hashable: frozen).
        self._escenarios_por_item = {}
        # Grants vigentes por objeto (ObjetoSecurable es hashable: frozen).
        self._grants_vigentes_por_objeto = {}
        # Trazabilidad de las operaciones ejecutadas, para las pruebas.
        self.operaciones_ejecutadas = []

    def ConfigurarEscenario(self, item, escenario):
        """Configura el escenario de respuesta de un ítem específico.

        Args:
            item (ItemGrant): ítem al que aplica el escenario.
            escenario (EscenarioSimulacion): respuesta que el canal simulará.
        """
        self._escenarios_por_item[item] = escenario

    def ConfigurarGrantsVigentes(self, objeto, grants):
        """Configura los grants vigentes iniciales de un objeto.

        Args:
            objeto (ObjetoSecurable): objeto cuyos grants vigentes se fijan.
            grants (list[ItemGrant]): grants que el canal reportará como
                vigentes antes de cualquier operación.
        """
        self._grants_vigentes_por_objeto[objeto] = list(grants)

    def ObtenerEscenario(self, item):
        """Devuelve el escenario configurado para un ítem (o el por defecto).

        Args:
            item (ItemGrant): ítem a consultar.

        Returns:
            EscenarioSimulacion: escenario que el canal aplicará al ítem.
        """
        return self._escenarios_por_item.get(item, self._escenario_por_defecto)

    def EjecutarOtorgamiento(self, item):
        """Simula la ejecución de un otorgamiento según el escenario del ítem.

        Args:
            item (ItemGrant): ítem a otorgar.

        Raises:
            ErrorPrivilegiosInsuficientes: si el escenario es permiso denegado.
            ErrorCanal: si el escenario es objeto inexistente.
        """
        escenario = self.ObtenerEscenario(item)
        self.operaciones_ejecutadas.append(
            OperacionEjecutada(
                operacion="otorgar", item=item, escenario=escenario
            )
        )
        self._ProvocarErrorSegunEscenario(item, escenario)

        # Éxito: el grant queda vigente (salvo que se simule la discrepancia).
        if self._registrar_grants_otorgados:
            self._RegistrarGrantVigente(item)

    def EjecutarRevocacion(self, item):
        """Simula la ejecución de una revocación según el escenario del ítem.

        Args:
            item (ItemGrant): ítem a revocar.

        Raises:
            ErrorPrivilegiosInsuficientes: si el escenario es permiso denegado.
            ErrorCanal: si el escenario es objeto inexistente.
        """
        escenario = self.ObtenerEscenario(item)
        self.operaciones_ejecutadas.append(
            OperacionEjecutada(
                operacion="revocar", item=item, escenario=escenario
            )
        )
        self._ProvocarErrorSegunEscenario(item, escenario)

        # Éxito: el grant deja de estar vigente sobre el objeto.
        self._EliminarGrantVigente(item)

    def ListarGrantsVigentes(self, objeto):
        """Devuelve los grants vigentes en memoria del objeto (sin conexión).

        Args:
            objeto (ObjetoSecurable): objeto cuyos grants vigentes se consultan.

        Returns:
            list[ItemGrant]: grants vigentes del objeto; lista vacía si no hay.
        """
        return list(self._grants_vigentes_por_objeto.get(objeto, []))

    def _ProvocarErrorSegunEscenario(self, item, escenario):
        """Lanza el error del escenario configurado, si corresponde.

        Args:
            item (ItemGrant): ítem en proceso, usado para el mensaje de error.
            escenario (EscenarioSimulacion): escenario configurado del ítem.

        Raises:
            ErrorPrivilegiosInsuficientes: en el escenario de permiso denegado.
            ErrorCanal: en el escenario de objeto inexistente.
        """
        if escenario is EscenarioSimulacion.PERMISO_DENEGADO:
            raise ErrorPrivilegiosInsuficientes(self._MensajePermisoDenegado(item))

        if escenario is EscenarioSimulacion.OBJETO_INEXISTENTE:
            raise ErrorCanal(self._MensajeObjetoInexistente(item))

        # Escenario EXITO: no se lanza ningún error.

    def _MensajePermisoDenegado(self, item):
        """Construye el mensaje de permiso denegado con los datos del ítem.

        Args:
            item (ItemGrant): ítem cuyo otorgamiento fue denegado.

        Returns:
            str: mensaje con el código oficial y el detalle del ítem.
        """
        return (
            f"[{self.CODIGO_PERMISO_DENEGADO}] El ejecutor no tiene "
            f"privilegios para otorgar {item.privilegio} sobre "
            f"{item.objeto.tipo.value} '{item.objeto.identificador}'."
        )

    def _MensajeObjetoInexistente(self, item):
        """Construye el mensaje de objeto inexistente con los datos del ítem.

        Args:
            item (ItemGrant): ítem cuyo objeto no existe.

        Returns:
            str: mensaje con el código del plano y el detalle del objeto.
        """
        return (
            f"[{self.CODIGO_OBJETO_INEXISTENTE}] El objeto "
            f"{item.objeto.tipo.value} '{item.objeto.identificador}' no existe."
        )

    def _RegistrarGrantVigente(self, item):
        """Agrega el ítem a los grants vigentes de su objeto (sin duplicar).

        Args:
            item (ItemGrant): grant otorgado que queda vigente.
        """
        grants_del_objeto = self._grants_vigentes_por_objeto.setdefault(
            item.objeto, []
        )
        if item not in grants_del_objeto:
            grants_del_objeto.append(item)

    def _EliminarGrantVigente(self, item):
        """Quita el ítem de los grants vigentes de su objeto, si estaba.

        Args:
            item (ItemGrant): grant revocado.
        """
        grants_del_objeto = self._grants_vigentes_por_objeto.get(item.objeto, [])
        if item in grants_del_objeto:
            grants_del_objeto.remove(item)


class CanalDatosSimulado(CanalSimulado, CanalDatos):
    """Canal simulado del plano de datos (Unity Catalog, canal SQL).

    Reproduce los códigos de error del motor SQL de Databricks; en C4 será
    sustituido por la implementación real que ejecuta GRANT/REVOKE y
    SHOW GRANTS sobre un workspace.
    """

    # Código de objeto inexistente reportado por el motor SQL.
    CODIGO_OBJETO_INEXISTENTE = "SCHEMA_OR_OBJECT_NOT_FOUND"


class CanalControlSimulado(CanalSimulado, CanalControl):
    """Canal simulado del plano de control (workspace, Permissions API).

    Reproduce los códigos de error de la REST API de Databricks; en C7/C8 será
    sustituido por las implementaciones reales sobre la Permissions API y la
    Token Permissions API.
    """

    # Código de objeto inexistente reportado por la REST API del workspace.
    CODIGO_OBJETO_INEXISTENTE = "RESOURCE_DOES_NOT_EXIST"
