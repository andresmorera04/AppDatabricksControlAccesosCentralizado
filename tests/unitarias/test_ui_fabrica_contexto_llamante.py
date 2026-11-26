"""Prueba unitaria de la fábrica del contexto OBO por acción (design.md D3).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Contrato que fija esta prueba:

- la fábrica compone, PARA CADA ACCIÓN, proveedor OBO, servicio de identidad
  (C3), cliente del workspace, sesión Spark remota, canales reales de ambos
  planos, resolutor de privilegios y pipeline completo;
- el cliente SDK y la sesión Spark reciben el MISMO token OBO del llamante y
  el host del workspace; nunca el token del service principal de la App
  (`DATABRICKS_TOKEN` del entorno), ni aunque exista: no hay fallback
  elevado;
- cada `CrearContexto()` construye objetos nuevos: dos acciones —o dos
  llamantes— no comparten cliente, sesión, canales, resolutor ni pipeline;
- token OBO ausente -> `ErrorContextoLlamanteAusente` sin construir cliente
  ni sesión; host ausente o fallo de Connect -> `ErrorAutenticacionLlamante`
  con mensaje limpio (sin token) y causa encadenada;
- la identidad no resuelta (SCIM falla) NO impide la composición: el
  contexto existe con `identidad=None` y el controlador decide deshabilitar
  el flujo (spec - "Contexto o token no válido");
- `Cerrar()` detiene la sesión Spark exactamente una vez y degrada de forma
  controlada si el cierre falla.

Todos los colaboradores externos son dobles inyectados: sin red, sin
Streamlit y sin Databricks Connect local (prohibido en ~/.venv, design.md D5).
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


class ClienteWorkspaceFalso:
    """Doble del `WorkspaceClient`: identidad + puertos del canal SDK."""

    def __init__(self, current_user):
        self.current_user = current_user
        # Atributos que exige el adaptador ClientePermisosSdk (C7).
        self.permissions = object()
        self.api_client = object()


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


class SesionSparkFalsa:
    """Doble de la sesión Spark remota con `sql()` y `stop()`."""

    def __init__(self, excepcion_stop=None):
        self.excepcion_stop = excepcion_stop
        self.detenciones = 0

    def sql(self, sentencia):
        # La fábrica solo necesita que la sesión exponga `sql` (adaptador
        # SesionSparkSql); las pruebas de canales cubren su comportamiento.
        return []

    def stop(self):
        self.detenciones += 1
        if self.excepcion_stop is not None:
            raise self.excepcion_stop


class FabricaSesionFalsa:
    """Fábrica de sesiones Spark falsas que registra (host, token)."""

    def __init__(self, excepcion=None, excepcion_stop=None):
        self._excepcion = excepcion
        self._excepcion_stop = excepcion_stop
        self.llamadas = []
        self.sesiones = []

    def __call__(self, host, token):
        self.llamadas.append((host, token))
        if self._excepcion is not None:
            raise self._excepcion
        sesion = SesionSparkFalsa(excepcion_stop=self._excepcion_stop)
        self.sesiones.append(sesion)
        return sesion


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
    excepcion_sesion=None,
    excepcion_stop=None,
    registrador_errores=None,
    registrador_eventos=None,
):
    """Construye la fábrica con dobles inyectados.

    Returns:
        tuple: (fábrica, fábrica de clientes falsa, fábrica de sesiones falsa).
    """
    fabrica_clientes = FabricaClienteFalsa(
        current_user=current_user, excepcion=excepcion_cliente
    )
    fabrica_sesiones = FabricaSesionFalsa(
        excepcion=excepcion_sesion, excepcion_stop=excepcion_stop
    )
    entorno_efectivo = {NOMBRE_VARIABLE_HOST: HOST_WORKSPACE}
    if entorno is not None:
        entorno_efectivo = dict(entorno)
    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: dict(encabezados or {}),
        fabrica_cliente_workspace=fabrica_clientes,
        fabrica_sesion_spark=fabrica_sesiones,
        configuracion=CONFIGURACION_PROYECTO,
        entorno=entorno_efectivo,
        registrador_eventos=registrador_eventos,
        registrador_errores=registrador_errores,
    )
    return fabrica, fabrica_clientes, fabrica_sesiones


def TestContextoComponeDependenciasConElMismoTokenObo():
    """SDK y sesión Spark reciben host y token del mismo llamante."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, fabrica_clientes, fabrica_sesiones = _CrearFabrica(
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

    # La sesión Spark se construyó una vez con host y token OBO.
    assert fabrica_sesiones.llamadas == [(HOST_WORKSPACE, TOKEN_OBO_UNO)]

    # Todos los clientes construidos (el del contexto y el del proveedor al
    # resolver la identidad) usan el mismo host y el mismo token OBO.
    assert fabrica_clientes.llamadas, "La fábrica debe construir clientes"
    for host, token in fabrica_clientes.llamadas:
        assert host == HOST_WORKSPACE
        assert token == TOKEN_OBO_UNO


def TestNuncaUsaElTokenDelServicePrincipalDeLaApp():
    """DATABRICKS_TOKEN del entorno jamás alimenta las operaciones OBO."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, fabrica_clientes, fabrica_sesiones = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            NOMBRE_VARIABLE_TOKEN_APP: TOKEN_APP_SP,
        },
        current_user=current_user,
    )

    fabrica.CrearContexto()

    tokens_usados = [
        token
        for _, token in fabrica_clientes.llamadas + fabrica_sesiones.llamadas
    ]
    assert TOKEN_APP_SP not in tokens_usados, (
        "Ninguna operación del llamante puede usar la credencial propia de "
        "la App: no hay fallback elevado (design.md D3)."
    )


def TestCadaAccionConstruyeDependenciasNuevas():
    """Dos acciones sucesivas no comparten ningún objeto mutable."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, _, fabrica_sesiones = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
    )

    primero = fabrica.CrearContexto()
    segundo = fabrica.CrearContexto()

    assert primero.proveedor is not segundo.proveedor
    assert primero.servicio_identidad is not segundo.servicio_identidad
    assert primero.cliente_workspace is not segundo.cliente_workspace
    assert primero.sesion_spark is not segundo.sesion_spark
    assert primero.canal_datos is not segundo.canal_datos
    assert primero.canal_control is not segundo.canal_control
    assert primero.resolutor is not segundo.resolutor
    assert primero.pipeline is not segundo.pipeline
    assert len(fabrica_sesiones.llamadas) == 2, (
        "La fábrica no cachea sesiones entre acciones (design.md D3)."
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
    fabrica_sesiones = FabricaSesionFalsa()
    fabrica = FabricaContextoLlamante(
        acceso_encabezados=lambda: dict(encabezados_actuales),
        fabrica_cliente_workspace=fabrica_clientes,
        fabrica_sesion_spark=fabrica_sesiones,
        configuracion=CONFIGURACION_PROYECTO,
        entorno={NOMBRE_VARIABLE_HOST: HOST_WORKSPACE},
    )

    contexto_uno = fabrica.CrearContexto()
    encabezados_actuales[NOMBRE_ENCABEZADO_TOKEN] = TOKEN_OBO_DOS
    contexto_dos = fabrica.CrearContexto()

    assert contexto_uno.identidad.principal.identificador == USUARIO_UNO
    assert contexto_dos.identidad.principal.identificador == USUARIO_DOS
    assert contexto_uno.pipeline is not contexto_dos.pipeline
    assert contexto_uno.sesion_spark is not contexto_dos.sesion_spark

    # Cada composición usó el token vigente: la primera nunca vio el segundo.
    tokens_por_sesion = [token for _, token in fabrica_sesiones.llamadas]
    assert tokens_por_sesion == [TOKEN_OBO_UNO, TOKEN_OBO_DOS]


def TestTokenAusenteImpideLaComposicion():
    """Sin header OBO no se construye cliente ni sesión alguna."""
    fabrica, fabrica_clientes, fabrica_sesiones = _CrearFabrica(
        encabezados={},
        entorno={
            NOMBRE_VARIABLE_HOST: HOST_WORKSPACE,
            NOMBRE_VARIABLE_TOKEN_APP: TOKEN_APP_SP,
        },
    )

    with pytest.raises(ErrorContextoLlamanteAusente):
        fabrica.CrearContexto()

    assert fabrica_clientes.llamadas == []
    assert fabrica_sesiones.llamadas == [], (
        "Sin token del llamante no se establece ninguna sesión, ni siquiera "
        "con credenciales de la App."
    )


def TestHostAusenteImpideLaComposicion():
    """Entorno sin host del workspace -> ErrorAutenticacionLlamante."""
    fabrica, fabrica_clientes, fabrica_sesiones = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        entorno={},
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        fabrica.CrearContexto()

    assert NOMBRE_VARIABLE_HOST in str(informacion.value)
    assert TOKEN_OBO_UNO not in str(informacion.value)
    assert fabrica_clientes.llamadas == []
    assert fabrica_sesiones.llamadas == []


def TestFalloDeSesionSparkSeTraduceSinExponerToken():
    """Connect falla -> ErrorAutenticacionLlamante limpio con causa."""
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        excepcion_sesion=RuntimeError("databricks-connect no disponible"),
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


def TestCerrarDetieneLaSesionUnaSolaVez():
    """Cerrar() es idempotente: un único stop() por contexto."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    fabrica, _, fabrica_sesiones = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
    )

    contexto = fabrica.CrearContexto()
    contexto.Cerrar()
    contexto.Cerrar()

    assert fabrica_sesiones.sesiones[0].detenciones == 1


def TestCerrarDegradaControladamenteSiStopFalla():
    """Un stop() fallido no propaga la excepción al controlador."""
    current_user = CurrentUserFalso(registro=UsuarioScimFalso())
    registrador_errores = RegistradorErroresFalso()
    fabrica, _, _ = _CrearFabrica(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_UNO},
        current_user=current_user,
        excepcion_stop=RuntimeError("sesión ya terminada"),
        registrador_errores=registrador_errores,
    )

    contexto = fabrica.CrearContexto()
    contexto.Cerrar()  # no debe lanzar

    # El fallo de cierre quedó registrado con el usuario OBO cuando existe.
    assert registrador_errores.llamadas
    _, _, usuario, _ = registrador_errores.llamadas[-1]
    assert usuario == USUARIO_UNO


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
