"""Prueba unitaria de la sesión Spark OBO de producción (design.md D3/D5).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Contrato que fija esta prueba sobre `CrearSesionSparkObo`:

- la sesión remota se construye con un `Config` EXPLÍCITO de
  `databricks.sdk` (host y token del llamante): las credenciales del
  entorno de la App (`DATABRICKS_HOST`/`DATABRICKS_TOKEN` del service
  principal propio) nunca se heredan, aunque existan;
- se usa cómputo serverless (`serverless(True)`), sin id de warehouse ni de
  cluster embebido (regla No HardCoded; el spike 2.4 valida el runtime);
- se usa `create()` y NO `getOrCreate()`: cada acción obtiene una sesión
  nueva y dos llamantes jamás comparten contexto Spark (design.md D3);
- la importación de `databricks.connect` es perezosa: importar la fábrica no
  carga Connect, que es una dependencia exclusiva del runtime de la App y
  está prohibida en el ~/.venv local (conflicto con `pyspark`, design.md D5).

`databricks.connect` se sustituye por un módulo falso inyectado en
`sys.modules`, y `databricks.sdk.config.Config` por un doble que registra
sus argumentos: el `Config` real de databricks-sdk 0.170 ejecuta un sondeo
de red best-effort en su inicialización, inadmisible en pruebas unitarias
sin workspace. El `Config` real contra el host real se valida en el spike
integral de la tarea 2.4.

Nota TDD: el constructor de producción se introdujo en la tarea 2.2 como
colaborador por defecto de la fábrica; esta prueba (tarea 2.3) fija su
contrato de credenciales y aísla el pin de Connect validado contra la
documentación oficial (imagen de App con Python 3.11 + serverless desde
15.4.10, clientes <= runtime plenamente compatibles).
"""

import subprocess
import sys
import types

from control_accesos.ui.fabrica_contexto import CrearSesionSparkObo

# Valores de prueba.
HOST_WORKSPACE = "https://adb-1234567890.1.azuredatabricks.net"
TOKEN_OBO = "dapiLLAMANTE_OBO_0123456789"
TOKEN_APP_SP = "dapiAPP_SERVICE_PRINCIPAL_no_usar"
HOST_APP_ENTORNO = "https://host-de-la-app-no-usar.example.com"

# Variables de entorno que el SDK podría autoconfigurar; se limpian o fijan
# en cada prueba para que el Config explícito sea el único origen posible.
VARIABLES_ENTORNO_SDK = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_AUTH_TYPE",
)


class SesionSparkFalsaCreada:
    """Doble de la sesión devuelta por `create()`."""


class ConfigSdkFalsa:
    """Doble de `databricks.sdk.config.Config` que registra sus argumentos.

    El Config real hace un sondeo de metadatos del host por red en su
    inicialización (SDK 0.170); las pruebas unitarias no deben depender de
    la red ni de un workspace alcanzable.
    """

    def __init__(self, host=None, token=None, **extra):
        self.host = host
        self.token = token
        self.extra = extra


def _InstalarConfigSdkFalso(monkeypatch):
    """Parchea `databricks.sdk.config.Config` con el doble registrador.

    El constructor de producción importa `Config` desde ese módulo en tiempo
    de llamada, por lo que el parche se aplica sin tocar la implementación.
    """
    import databricks.sdk.config

    monkeypatch.setattr(databricks.sdk.config, "Config", ConfigSdkFalsa)


class ConstructorSesionFalso:
    """Doble del builder de `DatabricksSession` que registra la cadena."""

    def __init__(self):
        self.configuracion_recibida = None
        self.serverless_recibido = None
        self.sesiones_creadas = 0
        self.uso_get_or_create = False

    def sdkConfig(self, configuracion):
        self.configuracion_recibida = configuracion
        return self

    def serverless(self, valor):
        self.serverless_recibido = valor
        return self

    def create(self):
        self.sesiones_creadas += 1
        return SesionSparkFalsaCreada()

    def getOrCreate(self):
        # Si la implementación usara getOrCreate, la sesión podría compartirse
        # entre llamantes (prohibido, design.md D3): se registra para fallar.
        self.uso_get_or_create = True
        return SesionSparkFalsaCreada()


def _InstalarConnectFalso(monkeypatch, constructor):
    """Injecta un módulo falso `databricks.connect` en sys.modules.

    Args:
        monkeypatch: fixture de pytest para el parcheo.
        constructor (ConstructorSesionFalso): builder que registrará la
            cadena de construcción.
    """
    modulo_falso = types.ModuleType("databricks.connect")
    clase_falsa = type(
        "DatabricksSession", (), {"builder": constructor}
    )
    modulo_falso.DatabricksSession = clase_falsa
    monkeypatch.setitem(sys.modules, "databricks.connect", modulo_falso)


def _LimpiarEntornoSdk(monkeypatch):
    """Elimina las variables de entorno que el SDK autoconfiguraría."""
    for nombre in VARIABLES_ENTORNO_SDK:
        monkeypatch.delenv(nombre, raising=False)


def TestSesionSeConstruyeConConfigOboExplicitaYServerless(monkeypatch):
    """Config(host, token) explícito + serverless(True) + create()."""
    _LimpiarEntornoSdk(monkeypatch)
    _InstalarConfigSdkFalso(monkeypatch)
    constructor = ConstructorSesionFalso()
    _InstalarConnectFalso(monkeypatch, constructor)

    sesion = CrearSesionSparkObo(host=HOST_WORKSPACE, token=TOKEN_OBO)

    assert isinstance(sesion, SesionSparkFalsaCreada)
    configuracion = constructor.configuracion_recibida
    assert configuracion is not None, (
        "La sesión debe construirse con sdkConfig(Config(...)): el token OBO "
        "se pasa explícitamente al cliente de Databricks Connect."
    )
    assert str(configuracion.host).rstrip("/") == HOST_WORKSPACE.rstrip("/")
    assert configuracion.token == TOKEN_OBO
    assert constructor.serverless_recibido is True, (
        "El cómputo serverless se activa sin ids embebidos (regla No "
        "HardCoded); el spike de la tarea 2.4 lo valida en el runtime real."
    )
    assert constructor.sesiones_creadas == 1


def TestNuncaUsaGetOrCreateParaNoCompartirSesion(monkeypatch):
    """create() garantiza una sesión nueva por acción (aislamiento D3)."""
    _LimpiarEntornoSdk(monkeypatch)
    _InstalarConfigSdkFalso(monkeypatch)
    constructor = ConstructorSesionFalso()
    _InstalarConnectFalso(monkeypatch, constructor)

    CrearSesionSparkObo(host=HOST_WORKSPACE, token=TOKEN_OBO)

    assert not constructor.uso_get_or_create, (
        "getOrCreate() puede devolver una sesión compartida entre acciones o "
        "llamantes; el aislamiento OBO exige create() (design.md D3)."
    )


def TestConfigNoHeredaCredencialesDelEntornoDeLaApp(monkeypatch):
    """Con DATABRICKS_TOKEN/HOST de la App presentes, gana el OBO explícito."""
    monkeypatch.setenv("DATABRICKS_HOST", HOST_APP_ENTORNO)
    monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN_APP_SP)
    _InstalarConfigSdkFalso(monkeypatch)
    constructor = ConstructorSesionFalso()
    _InstalarConnectFalso(monkeypatch, constructor)

    CrearSesionSparkObo(host=HOST_WORKSPACE, token=TOKEN_OBO)

    configuracion = constructor.configuracion_recibida
    assert configuracion.token == TOKEN_OBO, (
        "La sesión Spark del llamante jamás usa el token del service "
        "principal de la App (no hay fallback elevado, design.md D3)."
    )
    assert str(configuracion.host).rstrip("/") == HOST_WORKSPACE.rstrip("/")


def TestImportarLaFabricaNoCargaDatabricksConnect():
    """La importación de Connect es perezosa (D5: prohibida en ~/.venv)."""
    codigo = (
        "import sys; "
        "import control_accesos.ui.fabrica_contexto; "
        "sys.exit(0 if 'databricks.connect' not in sys.modules else 1)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
    )

    assert resultado.returncode == 0, (
        "Importar la fábrica no debe cargar 'databricks.connect': Connect es "
        "dependencia exclusiva del runtime de la App y no está instalado (ni "
        f"debe instalarse) en el entorno local. Salida: {resultado.stderr}"
    )
