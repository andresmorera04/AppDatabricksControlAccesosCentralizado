"""Prueba unitaria de la fábrica del contexto OBO por acción (design.md D3, F2).

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Contrato que fija esta prueba:

- la fábrica compone, PARA CADA ACCIÓN, proveedor OBO, servicio de identidad
  (C3), cliente del workspace, sesión SQL remota (Statement Execution API),
  canales reales de ambos planos, resolutor de privilegios y pipeline completo
  con el agregador de lote en Python (sin SparkSession: corrección F2);
- el cliente SDK recibe el MISMO token OBO del llamante y el host del
  workspace; nunca el token del service principal de la App
  (`DATABRICKS_TOKEN` del entorno), ni aunque exista: no hay fallback elevado;
- el warehouse serverless para el SQL OBO se DESCUBRE con la credencial del
  llamante (precondición operativa, design.md D3); sin warehouse la composición
  falla con error controlado y sin el token; un fallo del descubrimiento se
  traduce sin propagar la causa con el secreto;
- cada `CrearContexto()` construye objetos nuevos: dos acciones —o dos
  llamantes— no comparten cliente, canales, resolutor ni pipeline;
- token OBO ausente -> `ErrorContextoLlamanteAusente` sin construir cliente;
  host ausente o fallo de cliente -> `ErrorAutenticacionLlamante` con mensaje
  limpio (sin token) y causa encadenada;
- la identidad no resuelta (SCIM falla) NO impide la composición: el contexto
  existe con `identidad=None` y el controlador decide deshabilitar el flujo
  (spec - "Contexto o token no válido");
- `Cerrar()` es idempotente y sin recurso que liberar (ya no hay SparkSession).

Todos los colaboradores externos son dobles inyectados: sin red, sin Streamlit
y sin `databricks-connect` (retirado del runtime por la corrección F2).
"""

from dataclasses import dataclass

import pytest

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.fabrica_contexto import (
    ContextoOperacionLlamante,
    FabricaContextoLlamante,
)
from control_accesos.ui.proveedor_identidad_app import (
    ProveedorIdentidadDatabricksApp,
)

# Contratos de configuración (mismos nombres que en las pruebas de 1.3).
CONFIGURACION_PROYECTO = ConfiguracionApp.Cargar()
NOMBRE_ENCABEZADO_TOKEN = CONFIGURACION_PROYECTO.ObtenerAtributo(
    "nombre_encabezado_token_obo"
)
NOMBRE_VARIABLE_HOST = CONFIGURACION_PROYECTO.ObtenerAtributo(
    "variable_entorno_host_workspace"
)

# Nombre de la variable de entorno con la que la plataforma entrega el token
# del service principal PROPIO de la App. La fábrica jamás debe usarlo para
# las operaciones del llamante (design.md D3/D10).
NOMBRE_VARIABLE_TOKEN_APP = "DATABRICKS_TOKEN"

TOKEN_OBO_UNO = "dapiLLAMANTE_UNO_0123456789"
TOKEN_OBO_DOS = "dapiLLAMANTE_DOS_987654321"
TOKEN_APP_SP = "dapiAPP_SERVICE_PRINCIPAL_no_usar"
HOST_WORKSPACE = "https://adb-1234567890.1.azuredatabricks.net"
WAREHOUSE_ID = "abcdef1234567890abcdef12"
USUARIO_UNO = "usuario.uno@example.com"
USUARIO_DOS = "usuario.dos@example.com"


@dataclass(frozen=True)
class GrupoScimFalso:
    """Doble de membresía SCIM."""

    value: str
    display: str = None


@dataclass(frozen=True)
class UsuarioScimFalso:
    """Doble del usuario SCIM devuelto por `current_user.me()`."""

    user_name: str = USUARIO_UNO
    display_name: str = "Usuario Uno"
    groups: tuple = ()


class CurrentUserFalso:
    """Doble de `client.current_user`."""

    def __init__(self, registro=None, excepcion=None):
        self._registro = registro
        self._excepcion = excepcion

    def me(self):
        if self._excepcion is not None:
            raise self._excepcion
        return self._registro


class StatementExecutionFalso:
    """Doble del transporte `statement_execution` (puertos de SesionSqlRemota).

    La fábrica solo construye la sesión remota y la valida; ninguna sentencia
    se ejecuta durante la composición, por lo que el doble solo necesita
    exponer los dos métodos que `SesionSqlRemota` exige en su constructor.
    """

    def execute_statement(self, statement=None, warehouse_id=None, wait_timeout=None, **extra):
        return None

    def get_statement(self, statement_id):
        return None


class ClienteWorkspaceFalso:
    """Doble del `WorkspaceClient`: identidad + puertos del canal y SQL remoto."""

    def __init__(self, current_user):
        self.current_user = current_user
        # Atributos que exige el adaptador ClientePermisosSdk (C7).
        self.permissions = object()
        self.api_client = object()
        # Transporte que exige SesionSqlRemota (F2).
        self.statement_execution = StatementExecutionFalso()


class FabricaClienteFalsa:
    """Fábrica de clientes falsos que registra (host, token) por llamada."""

    def __init__(self, current_user=None, excepcion=None):
        self._current_user = current_user
        self._excepcion = excepcion
        self.llamadas = []

    def __call__(self, host, token):
        self.llamadas.append((host, token))
        if self._excepcion is not None:
            raise self._excepcion
        return ClienteWorkspaceFalso(self._current_user)


class DescubridorWarehouseFalso:
    """Descubridor falso de SQL warehouse serverless que registra al cliente."""

    def __init__(self, warehouse_id=WAREHOUSE_ID, excepcion=None):
        self._warehouse_id = warehouse_id
        self._excepcion = excepcion
        self.llamadas = []

    def __call__(self, cliente):
        self.llamadas.append(cliente)
        if self._excepcion is not None:
            raise self._excepcion
        return self._warehouse_id


class ConfiguracionFalsa:
    """Configuración falsa con las claves que consume la fábrica (IdWarehouse)."""

    def __init__(self, id_warehouse=""):
        self._atributos = {
            "nombre_encabezado_token_obo": "x-forwarded-access-token",
            "variable_entorno_host_workspace": "DATABRICKS_HOST",
            "id_warehouse": id_warehouse,
            "variable_entorno_id_warehouse": "CONTROL_ACCESOS_ID_WAREHOUSE",
        }

    def ObtenerAtributo(self, nombre):
        return self._atributos[nombre]


class RegistradorErroresFalso:
    """Doble de la bitácora de errores que registra las llamadas."""

    def __init__(self):
        self.llamadas = []

    def Registrar(self, excepcion, modulo=None, usuario=None, contexto=""):
        self.llamadas.append((excepcion, modulo, usuario, contexto))


class RegistradorEventosFalso:
    """Doble de la bitácora de eventos (solo presencia para el pipeline)."""

    def __init__(self):
        self.llamadas = []


def _CrearFabrica(
    encabezados=None,
    entorno=None,
    current_user=None,
    excepcion_cliente=None,
    descubridor_warehouse=None,
    registrador_errores=None,
    registrador_eventos=None,
):
    """Construye la fábrica con dobles inyectados.

    Returns:
        tuple: (fábrica, fábrica de clientes falsa, descubridor de warehouse).
    """
    fabrica_clientes = FabricaClienteFalsa(
        current_user=current_user, excepcion=excepcion_cliente
    )
    if descubridor_warehouse is None:
        descubridor_warehouse = DescubridorWarehouseFalso()
    entorno_efectivo = {NOMBRE_VARIABLE_HOST: HOST_WORKSPACE}
    if entorno is not None:
        entorno_efectivo = dict(entorno)
    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: dict(encabezados or {}),
        fabrica_cliente_workspace=fabrica_clientes,
        descubridor_warehouse=descubridor_warehouse,
        configuracion=CONFIGURACION_PROYECTO,
        entorno=entorno_efectivo,
        registrador_eventos=registrador_eventos,
        registrador_errores=registrador_errores,
    )
    return fabrica, fabrica_clientes, descubridor_warehouse


def TestContextoComponeDependenciasConElMismoTokenObo():
    """Cliente y sesión SQL reciben host y token del mismo llamante."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, fabrica_clientes, descubridor = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            NOMBRE_VARIABLE_TOKEN_APP: TOKEN_APP_SP,
        },
        current_user=current_user,
    )

    contexto = fabrica.CrearContexto()

    # Tipos reales de la composición (no dobles): la fábrica cablea las
    # clases de producción con los colaboradores inyectados.
    assert isinstance(contexto, ContextoOperacionLlamante)
    assert isinstance(contexto.proveedor, ProveedorIdentidadDatabricksApp)
    assert isinstance(contexto.servicio_identidad, ServicioIdentidadLlamante)
    assert isinstance(contexto.canal_datos, CanalSqlDatos)
    assert isinstance(contexto.canal_control, CanalControlComputo)
    assert isinstance(contexto.resolutor, ResolutorPrivilegiosEfectivos)
    assert isinstance(contexto.pipeline, PipelineGrants)

    # Identidad resuelta durante la composición con el usuario SCIM.
    assert contexto.identidad is not None
    assert contexto.identidad.principal.identificador == USUARIO_UNO

    # El warehouse serverless se descubrió con el cliente del llamante.
    assert contexto.warehouse_id == WAREHOUSE_ID
    assert len(descubridor.llamadas) == 1

    # Todos los clientes construidos (el del contexto y el del proveedor al
    # resolver la identidad) usan el mismo host y el mismo token OBO.
    assert fabrica_clientes.llamadas, "La fábrica debe construir clientes"
    for host, token in fabrica_clientes.llamadas:
        assert host == HOST_WORKSPACE
        assert token == TOKEN_OBO_UNO


def TestNuncaUsaElTokenDelServicePrincipalDeLaApp():
    """DATABRICKS_TOKEN del entorno jamás alimenta las operaciones OBO."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, fabrica_clientes, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            NOMBRE_VARIABLE_TOKEN_APP: TOKEN_APP_SP,
        },
        current_user=current_user,
    )

    fabrica.CrearContexto()

    tokens_usados = [token for _, token in fabrica_clientes.llamadas]
    assert TOKEN_APP_SP not in tokens_usados, (
        "Ninguna operación del llamante puede usar la credencial propia de "
        "la App: no hay fallback elevado (design.md D3)."
    )


def TestCadaAccionConstruyeDependenciasNuevas():
    """Dos acciones sucesivas no comparten ningún objeto mutable."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, _, descubridor = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
    )

    primero = fabrica.CrearContexto()
    segundo = fabrica.CrearContexto()

    assert primero.proveedor is not segundo.proveedor
    assert primero.servicio_identidad is not segundo.servicio_identidad
    assert primero.cliente_workspace is not segundo.cliente_workspace
    assert primero.canal_datos is not segundo.canal_datos
    assert primero.canal_control is not segundo.canal_control
    assert primero.resolutor is not segundo.resolutor
    assert primero.pipeline is not segundo.pipeline
    assert len(descubridor.llamadas) == 2, (
        "La fábrica no cachea el warehouse entre acciones (design.md D3)."
    )


def TestDosLlamantesQuedanAislados():
    """Dos usuarios sucesivos reciben contextos y credenciales separados."""
    encabezados_actuales = {NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO}
    registros_por_usuario = {
        TOKEN_OBO_UNO: UsuarioScimFalso(user_name=USUARIO_UNO),
        TOKEN_OBO_DOS: UsuarioScimFalso(
            user_name=USUARIO_DOS, display_name="Usuario Dos"
        ),
    }

    class CurrentUserPorToken:
        """Doble que resuelve el registro SCIM según el token en curso."""

        def me(self):
            return registros_por_usuario[encabezados_actuales[NOMBRE_ENCABEZADO_TOKEN]]

    fabrica_clientes = FabricaClienteFalsa(
        current_user=CurrentUserPorToken()
    )
    descubridor = DescubridorWarehouseFalso()
    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: dict(encabezados_actuales),
        fabrica_cliente_workspace=fabrica_clientes,
        descubridor_warehouse=descubridor,
        configuracion=CONFIGURACION_PROYECTO,
        entorno={NOMBRE_VARIABLE_HOST: HOST_WORKSPACE},
    )

    contexto_uno = fabrica.CrearContexto()
    encabezados_actuales[NOMBRE_ENCABEZADO_TOKEN] = TOKEN_OBO_DOS
    contexto_dos = fabrica.CrearContexto()

    assert contexto_uno.identidad.principal.identificador == USUARIO_UNO
    assert contexto_dos.identidad.principal.identificador == USUARIO_DOS
    assert contexto_uno.pipeline is not contexto_dos.pipeline
    assert contexto_uno.canal_datos is not contexto_dos.canal_datos

    # Cada composición usó el token vigente: la primera nunca vio el segundo.
    tokens_usados = [token for _, token in fabrica_clientes.llamadas]
    assert TOKEN_OBO_UNO in tokens_usados
    assert TOKEN_OBO_DOS in tokens_usados


def TestTokenAusenteImpideLaComposicion():
    """Sin header OBO no se construye cliente alguna."""
    fabrica, fabrica_clientes, descubridor = _CrearFabrica(
        encabezados={},
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            NOMBRE_VARIABLE_TOKEN_APP: TOKEN_APP_SP,
        },
    )

    with pytest.raises(ErrorContextoLlamanteAusente):
        fabrica.CrearContexto()

    assert fabrica_clientes.llamadas == []
    assert descubridor.llamadas == [], (
        "Sin token del llamante no se descubre warehouse, ni siquiera con "
        "credenciales de la App."
    )


def TestHostAusenteImpideLaComposicion():
    """Entorno sin host del workspace -> ErrorAutenticacionLlamante."""
    fabrica, fabrica_clientes, descubridor = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        entorno={},
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        fabrica.CrearContexto()

    assert NOMBRE_VARIABLE_HOST in str(informacion.value)
    assert TOKEN_OBO_UNO not in str(informacion.value)
    assert fabrica_clientes.llamadas == []
    assert descubridor.llamadas == []


def TestWarehouseNoDescubiertoImpideLaComposicion():
    """Sin warehouse serverless usable no hay SQL OBO: error limpio."""
    fabrica, fabrica_clientes, descubridor = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        descubridor_warehouse=DescubridorWarehouseFalso(warehouse_id=None),
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        fabrica.CrearContexto()

    assert "warehouse" in str(informacion.value)
    assert TOKEN_OBO_UNO not in str(informacion.value)


def TestFabricaUsaIdWarehouseDeLaConfiguracion():
    """La propiedad IdWarehouse manda: no se descubre si ya está configurada."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica_clientes = FabricaClienteFalsa(current_user=current_user)
    descubridor = DescubridorWarehouseFalso(warehouse_id="no-debe-usarse")

    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: {NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        fabrica_cliente_workspace=fabrica_clientes,
        descubridor_warehouse=descubridor,
        configuracion=ConfiguracionFalsa(id_warehouse=WAREHOUSE_ID),
        entorno={NOMBRE_VARIABLE_HOST: HOST_WORKSPACE},
    )

    contexto = fabrica.CrearContexto()

    assert contexto.warehouse_id == WAREHOUSE_ID
    assert descubridor.llamadas == [], (
        "Con IdWarehouse configurado la fábrica no debe descubrir el warehouse "
        "por la API (decisión 2026-11-27: la propiedad manda)."
    )


def TestFabricaUsaIdWarehouseDeLaVariableDeEntorno():
    """IdWarehouse vacío en configuración se suple por la variable de entorno."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica_clientes = FabricaClienteFalsa(current_user=current_user)
    descubridor = DescubridorWarehouseFalso(warehouse_id="no-debe-usarse")

    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: {NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        fabrica_cliente_workspace=fabrica_clientes,
        descubridor_warehouse=descubridor,
        configuracion=ConfiguracionFalsa(id_warehouse=""),
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            "CONTROL_ACCESOS_ID_WAREHOUSE": WAREHOUSE_ID,
        },
    )

    contexto = fabrica.CrearContexto()

    assert contexto.warehouse_id == WAREHOUSE_ID
    assert descubridor.llamadas == [], (
        "Con la variable de entorno IdWarehouse tampoco se descubre por API."
    )


def TestFalloDeDescubrimientoWarehouseSeTraduceSinExponerToken():
    """Un fallo del descubrimiento se traduce con causa encadenada y sin token."""
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        descubridor_warehouse=DescubridorWarehouseFalso(
            excepcion=RuntimeError("warehouses API sin scope sql")
        ),
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        fabrica.CrearContexto()

    assert TOKEN_OBO_UNO not in str(informacion.value)
    assert isinstance(informacion.value.__cause__, RuntimeError)


def TestIdentidadNoResueltaNoImpideLaComposicion():
    """SCIM falla (token expirado): contexto compuesto con identidad None."""
    registrador_errores = RegistradorErroresFalso()
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=CurrentUserFalso(
            excepcion=RuntimeError("HTTP 401: token expired")
        ),
        registrador_errores=registrador_errores,
    )

    contexto = fabrica.CrearContexto()

    assert contexto.identidad is None
    assert not contexto.servicio_identidad.IdentidadResuelta
    # El fallo de identidad quedó registrado por el servicio de C3 (degradación
    # controlada) y el resto de la composición existe: el controlador decide
    # deshabilitar previsualización y ejecución (spec).
    assert registrador_errores.llamadas
    assert isinstance(contexto.pipeline, PipelineGrants)


def TestCerrarEsIdempotente():
    """Cerrar() no libera recurso alguno y nunca lanza (sin Spark, F2)."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
    )

    contexto = fabrica.CrearContexto()
    # Dos llamadas consecutivas sin efecto ni excepción (compat C9).
    contexto.Cerrar()
    contexto.Cerrar()


def TestRegistradoresSeExponenEnElContexto():
    """El contexto expone los mismos registradores inyectados a la fábrica."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    registrador_errores = RegistradorErroresFalso()
    registrador_eventos = RegistradorEventosFalso()
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
        registrador_errores=registrador_errores,
        registrador_eventos=registrador_eventos,
    )

    contexto = fabrica.CrearContexto()

    assert contexto.registrador_errores is registrador_errores
    assert contexto.registrador_eventos is registrador_eventos
