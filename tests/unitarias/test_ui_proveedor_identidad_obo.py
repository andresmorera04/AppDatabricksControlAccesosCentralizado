"""Prueba unitaria del proveedor de identidad OBO de la Databricks App.

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Contrato que fija esta prueba (design.md D3, spec - "Autenticación
on-behalf-of y aislamiento del llamante"):

- el token OBO se lee del header cuyo nombre declara la configuración
  (`nombre_encabezado_token_obo`), con búsqueda insensible a mayúsculas;
- el host del workspace se lee de la variable de entorno cuyo nombre declara
  la configuración (`variable_entorno_host_workspace`);
- la identidad y los grupos se resuelven por SCIM (`current_user.me()`) con
  un cliente construido EXPLÍCITAMENTE con host y token del llamante (nunca
  con las credenciales heredadas de la App);
- token ausente o vacío -> `ErrorContextoLlamanteAusente`; token inválido o
  expirado (la verificación SCIM falla) -> `ErrorAutenticacionLlamante`, con
  la causa encadenada para diagnóstico y mensaje limpio;
- ningún mensaje de error expone el valor del token;
- un service principal conserva su App Id (referencia de emparejamiento);
- el proveedor se integra con `ServicioIdentidadLlamante` (C3): identidad
  resuelta en el caso válido y degradación controlada (None) sin token.

Todos los colaboradores externos (headers, entorno, cliente SCIM) son dobles
inyectados: la prueba no toca la red ni el runtime de Streamlit.
"""

from dataclasses import dataclass

import pytest

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.modelos import Grupo
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.ui.proveedor_identidad_app import (
    CrearClienteWorkspace,
    ProveedorIdentidadDatabricksApp,
)

# Nombres de los atributos de configuración que el proveedor debe consumir
# (mismos contratos que fija test_ui_configuracion_despliegue.py). Se leen de
# la configuración real del proyecto para no duplicar valores a mano.
CONFIGURACION_PROYECTO = ConfiguracionApp.Cargar()
NOMBRE_ATRIBUTO_ENCABEZADO_TOKEN = "nombre_encabezado_token_obo"
NOMBRE_ATRIBUTO_VARIABLE_HOST = "variable_entorno_host_workspace"
NOMBRE_ENCABEZADO_TOKEN = CONFIGURACION_PROYECTO.ObtenerAtributo(
    NOMBRE_ATRIBUTO_ENCABEZADO_TOKEN
)
NOMBRE_VARIABLE_HOST = CONFIGURACION_PROYECTO.ObtenerAtributo(
    NOMBRE_ATRIBUTO_VARIABLE_HOST
)

# Valores de prueba. El token usa a propósito el prefijo real `dapi` para
# comprobar que ningún mensaje de error lo expone.
TOKEN_OBO_DE_PRUEBA = "dapiPRUEBA0123456789abcdef"
HOST_WORKSPACE_DE_PRUEBA = "https://adb-1234567890.1.azuredatabricks.net"
USUARIO_DE_PRUEBA = "usuario.prueba@example.com"
NOMBRE_MOSTRABLE_DE_PRUEBA = "Usuario Prueba"
ID_GRUPO_UNO = "81065872484794"
NOMBRE_GRUPO_UNO = "admins"
ID_GRUPO_DOS = "83195513137921"
NOMBRE_GRUPO_DOS = "users"
APP_ID_DE_PRUEBA = "11111111-2222-3333-4444-555555555555"
NOMBRE_SP_DE_PRUEBA = "sp-app-control-accesos"


@dataclass(frozen=True)
class GrupoScimFalso:
    """Doble de la entrada SCIM de membresía (value/display)."""

    value: str
    display: str = None


@dataclass(frozen=True)
class UsuarioScimFalso:
    """Doble del usuario SCIM que devuelve `current_user.me()`."""

    user_name: str = USUARIO_DE_PRUEBA
    display_name: str = NOMBRE_MOSTRABLE_DE_PRUEBA
    groups: tuple = ()


@dataclass(frozen=True)
class ServicePrincipalScimFalso:
    """Doble del service principal SCIM (lleva `application_id`)."""

    application_id: str = APP_ID_DE_PRUEBA
    user_name: str = NOMBRE_SP_DE_PRUEBA
    display_name: str = NOMBRE_SP_DE_PRUEBA
    groups: tuple = ()


class CurrentUserFalso:
    """Doble de `client.current_user`: devuelve el registro o falla."""

    def __init__(self, registro=None, excepcion=None):
        self._registro = registro
        self._excepcion = excepcion

    def me(self):
        if self._excepcion is not None:
            raise self._excepcion
        return self._registro


class ClienteWorkspaceFalso:
    """Doble del `WorkspaceClient` con el API de identidad usada."""

    def __init__(self, current_user):
        self.current_user = current_user


class FabricaClienteFalsa:
    """Doble de la fábrica de clientes; registra los argumentos recibidos."""

    def __init__(self, current_user=None, excepcion=None):
        self._current_user = current_user
        self._excepcion = excepcion
        self.llamadas = []

    def __call__(self, host, token):
        self.llamadas.append((host, token))
        if self._excepcion is not None:
            raise self._excepcion
        return ClienteWorkspaceFalso(self._current_user)


def _CrearProveedor(
    encabezados=None,
    entorno=None,
    current_user=None,
    excepcion_fabrica=None,
    configuracion=None,
):
    """Construye el proveedor con dobles inyectados.

    Returns:
        tuple: (proveedor, fábrica falsa) para inspeccionar llamadas.
    """
    fabrica = FabricaClienteFalsa(
        current_user=current_user, excepcion=excepcion_fabrica
    )
    proveedor = ProveedorIdentidadDatabricksApp(
        acceso_encabezados=lambda: dict(encabezados or {}),
        fabrica_cliente=fabrica,
        configuracion=configuracion or CONFIGURACION_PROYECTO,
        entorno=dict(entorno if entorno is not None else {NOMBRE_VARIABLE_HOST: HOST_WORKSPACE_DE_PRUEBA}),
    )
    return proveedor, fabrica


def TestTokenValidoResuelveContextoDeUsuario():
    """Token válido + SCIM -> contexto de usuario con identidad y grupos."""
    grupos_scim = (
        GrupoScimFalso(value=ID_GRUPO_UNO, display=NOMBRE_GRUPO_UNO),
        GrupoScimFalso(value=ID_GRUPO_DOS, display=NOMBRE_GRUPO_DOS),
    )
    proveedor, fabrica = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(registro=UsuarioScimFalso(groups=grupos_scim)),
    )

    contexto = proveedor.ObtenerContexto()

    assert contexto.tipo is TipoPrincipal.USUARIO
    assert contexto.identificador == USUARIO_DE_PRUEBA
    assert contexto.nombre_mostrable == NOMBRE_MOSTRABLE_DE_PRUEBA
    assert contexto.app_id is None, (
        "Un usuario no puede llevar App Id: los service principals son "
        "principales independientes (spec caller-identity)."
    )
    assert contexto.grupos == (
        Grupo(identificador=ID_GRUPO_UNO, nombre=NOMBRE_GRUPO_UNO),
        Grupo(identificador=ID_GRUPO_DOS, nombre=NOMBRE_GRUPO_DOS),
    )
    # El cliente se construyó con el host del entorno y el token del header:
    # credenciales explícitas del llamante, nunca heredadas de la App (D3).
    assert fabrica.llamadas == [(HOST_WORKSPACE_DE_PRUEBA, TOKEN_OBO_DE_PRUEBA)]


def TestEncabezadoTokenAusenteLanzaContextoAusente():
    """Sin header OBO -> ErrorContextoLlamanteAusente y sin cliente."""
    proveedor, fabrica = _CrearProveedor(encabezados={})

    with pytest.raises(ErrorContextoLlamanteAusente):
        proveedor.ObtenerContexto()

    assert fabrica.llamadas == [], (
        "Sin token del llamante no se debe construir ningún cliente del "
        "workspace (ni siquiera con credenciales de la App)."
    )


def TestTokenVacioLanzaContextoAusente():
    """Header presente pero vacío -> ErrorContextoLlamanteAusente."""
    proveedor, fabrica = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: "   "}
    )

    with pytest.raises(ErrorContextoLlamanteAusente):
        proveedor.ObtenerContexto()

    assert fabrica.llamadas == []


def TestTokenExpiradoFallaVerificacionScim():
    """SCIM falla (token inválido/expirado) -> ErrorAutenticacionLlamante."""
    proveedor, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(
            excepcion=RuntimeError("HTTP 401: token expired")
        ),
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        proveedor.ObtenerContexto()

    # Mensaje limpio: nunca expone el token...
    assert TOKEN_OBO_DE_PRUEBA not in str(informacion.value)
    # ...y conserva la causa original encadenada para el diagnóstico.
    assert isinstance(informacion.value.__cause__, RuntimeError)


def TestHostAusenteLanzaErrorAutenticacion():
    """Entorno sin host del workspace -> ErrorAutenticacionLlamante."""
    proveedor, fabrica = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        entorno={},
        current_user=CurrentUserFalso(registro=UsuarioScimFalso()),
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        proveedor.ObtenerContexto()

    assert fabrica.llamadas == []
    # El mensaje nombra la variable de entorno esperada (dato no sensible)
    # para que el fallo de despliegue sea diagnosticable.
    assert NOMBRE_VARIABLE_HOST in str(informacion.value)


def TestFallaConstruccionClienteLanzaErrorAutenticacion():
    """La fábrica de clientes falla -> ErrorAutenticacionLlamante sin token."""
    proveedor, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        excepcion_fabrica=RuntimeError("fallo de transporte"),
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        proveedor.ObtenerContexto()

    assert TOKEN_OBO_DE_PRUEBA not in str(informacion.value)
    assert isinstance(informacion.value.__cause__, RuntimeError)


def TestServicePrincipalConservaAppId():
    """SCIM de service principal -> contexto con tipo y App Id correctos."""
    proveedor, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(
            registro=ServicePrincipalScimFalso(
                groups=(GrupoScimFalso(value=ID_GRUPO_DOS, display=NOMBRE_GRUPO_DOS),)
            )
        ),
    )

    contexto = proveedor.ObtenerContexto()

    assert contexto.tipo is TipoPrincipal.SERVICE_PRINCIPAL
    assert contexto.identificador == NOMBRE_SP_DE_PRUEBA
    assert contexto.app_id == APP_ID_DE_PRUEBA
    assert len(contexto.grupos) == 1


def TestIdentificadorScimVacioLanzaErrorAutenticacion():
    """SCIM sin userName utilizable -> ErrorAutenticacionLlamante."""
    proveedor, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(
            registro=UsuarioScimFalso(user_name="  ", display_name=None)
        ),
    )

    with pytest.raises(ErrorAutenticacionLlamante):
        proveedor.ObtenerContexto()


def TestBusquedaDeEncabezadoInsensibleAMayusculas():
    """El header se encuentra aunque el mapa use otras mayúsculas."""
    proveedor, _ = _CrearProveedor(
        encabezados={"X-Forwarded-Access-Token": TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(registro=UsuarioScimFalso()),
    )

    contexto = proveedor.ObtenerContexto()

    assert contexto.identificador == USUARIO_DE_PRUEBA


def TestGrupoSinIdentificadorSeIgnora():
    """Una membresía SCIM sin `value` no entra en los grupos del contexto."""
    proveedor, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(
            registro=UsuarioScimFalso(
                groups=(
                    GrupoScimFalso(value="", display="grupo-sin-id"),
                    GrupoScimFalso(value=ID_GRUPO_UNO, display=NOMBRE_GRUPO_UNO),
                )
            )
        ),
    )

    contexto = proveedor.ObtenerContexto()

    assert contexto.grupos == (
        Grupo(identificador=ID_GRUPO_UNO, nombre=NOMBRE_GRUPO_UNO),
    )


class ConfiguracionFalsa:
    """Doble de configuración con nombres de atributos alternativos."""

    def __init__(self, atributos):
        self._atributos = atributos

    def ObtenerAtributo(self, nombre_atributo):
        return self._atributos[nombre_atributo]


def TestNombresDeEncabezadoYVariableSonConfigurables():
    """El proveedor usa los nombres declarados en la configuración (D11)."""
    configuracion = ConfiguracionFalsa(
        {
            NOMBRE_ATRIBUTO_ENCABEZADO_TOKEN: "x-token-alternativo",
            NOMBRE_ATRIBUTO_VARIABLE_HOST: "HOST_ALTERNATIVO",
        }
    )
    proveedor, fabrica = _CrearProveedor(
        encabezados={"x-token-alternativo": TOKEN_OBO_DE_PRUEBA},
        entorno={"HOST_ALTERNATIVO": HOST_WORKSPACE_DE_PRUEBA},
        current_user=CurrentUserFalso(registro=UsuarioScimFalso()),
        configuracion=configuracion,
    )

    contexto = proveedor.ObtenerContexto()

    assert contexto.identificador == USUARIO_DE_PRUEBA
    assert fabrica.llamadas == [(HOST_WORKSPACE_DE_PRUEBA, TOKEN_OBO_DE_PRUEBA)]


def TestFabricaClienteProduccionFijaAuthTypePat(monkeypatch):
    """CrearClienteWorkspace fija auth_type='pat' (spike 2.4: oauth+pat).

    En el runtime de la Databricks App el entorno ya trae credenciales OAuth
    del service principal propio; si el constructor no fija el método, el SDK
    rechaza la combinación ('more than one authorization method configured:
    oauth and pat') o, peor, podría preferir el OAuth de la App. Con
    auth_type='pat' solo se usa el token OBO del llamante (design.md D3).
    """
    import databricks.sdk

    llamadas = []

    class WorkspaceClientFalso:
        def __init__(self, **kwargs):
            llamadas.append(kwargs)

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", WorkspaceClientFalso)

    CrearClienteWorkspace(
        host=HOST_WORKSPACE_DE_PRUEBA, token=TOKEN_OBO_DE_PRUEBA
    )

    assert llamadas == [
        {
            "host": HOST_WORKSPACE_DE_PRUEBA,
            "token": TOKEN_OBO_DE_PRUEBA,
            "auth_type": "pat",
        }
    ]


def TestIntegracionConServicioIdentidadLlamante():
    """Proveedor real de la App + servicio de C3: resuelve o degrada."""
    proveedor_valido, _ = _CrearProveedor(
        encabezados={NOMBRE_ENCABEZADO_TOKEN: TOKEN_OBO_DE_PRUEBA},
        current_user=CurrentUserFalso(
            registro=UsuarioScimFalso(
                groups=(GrupoScimFalso(value=ID_GRUPO_UNO, display=NOMBRE_GRUPO_UNO),)
            )
        ),
    )
    servicio = ServicioIdentidadLlamante(proveedor=proveedor_valido)

    assert servicio.IdentidadResuelta
    identidad = servicio.ObtenerIdentidadLlamante()
    assert identidad.principal.tipo is TipoPrincipal.USUARIO
    assert identidad.principal.identificador == USUARIO_DE_PRUEBA
    assert identidad.usuario_bitacora == USUARIO_DE_PRUEBA
    assert NOMBRE_GRUPO_UNO in identidad.ReferenciasDeIdentidad()

    # Sin token: el servicio degrada a None sin propagar la excepción.
    proveedor_sin_token, _ = _CrearProveedor(encabezados={})
    servicio_sin_token = ServicioIdentidadLlamante(proveedor=proveedor_sin_token)

    assert not servicio_sin_token.IdentidadResuelta
    assert servicio_sin_token.ObtenerIdentidadLlamante() is None
