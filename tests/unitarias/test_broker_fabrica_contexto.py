"""Prueba unitaria de la fábrica del contexto broker (SP), design.md D4/D6.

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Contrato que fija esta prueba sobre `FabricaContextoBroker`:

- el cliente del service principal se construye desde la AUTOCONFIGURACIÓN del
  entorno de la App (OAuth M2M), SIN host ni token del llamante: el SP jamás se
  usa para la identidad OBO ni para evaluar autorización;
- el canal del plano de control se compone con el transporte `ClientePermisosSdk`
  sobre el cliente SP, cubriendo la lectura/escritura de ACL de los cinco tipos
  (warehouses, clusters, serverless compute objects, Databricks Apps y tokens);
- el descubrimiento SCIM se compone con el cliente SP (`DescubridorPrincipales`)
  y preserva el App Id de los service principals;
- cada `CrearContexto()` construye objetos nuevos (sin compartir mutables entre
  acciones); un fallo del cliente SP se traduce sin exponer secreto alguno.

Todos los colaboradores son dobles inyectados: sin red ni runtime de Databricks.
"""

import types

import pytest

from control_accesos.autenticacion.errores import ErrorAutenticacionLlamante
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.canales.reales.descubrimiento_principales import (
    DescubridorPrincipales,
)
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.ui.fabrica_contexto_broker import (
    ContextoOperacionBroker,
    FabricaContextoBroker,
)

# Registros SCIM de prueba.
USUARIO = types.SimpleNamespace(user_name="usuario@example.com", display_name="Usuario Uno")
GRUPO = types.SimpleNamespace(display_name="analistas")
SERVICE_PRINCIPAL = types.SimpleNamespace(
    application_id="11111111-2222-3333-4444-555555555555",
    display_name="app-service-principal",
)
APP_ID_SP = SERVICE_PRINCIPAL.application_id

LIMITE_OPCIONES = 3


class ServicioListaFalso:
    """Doble de un servicio SCIM (`users`/`groups`/`service_principals`)."""

    def __init__(self, registros=(), excepcion=None):
        self._registros = list(registros)
        self._excepcion = excepcion

    def list(self):
        if self._excepcion is not None:
            raise self._excepcion
        return iter(self._registros)


class ClienteSpFalso:
    """Doble del `WorkspaceClient` del SP: SCIM + puertos del canal SDK."""

    def __init__(self, usuarios=(), grupos=(), service_principals=()):
        self.users = ServicioListaFalso(usuarios)
        self.groups = ServicioListaFalso(grupos)
        self.service_principals = ServicioListaFalso(service_principals)
        # Atributos que exige el adaptador ClientePermisosSdk (C7).
        self.permissions = object()
        self.api_client = object()


class FabricaClienteSpFalsa:
    """Fábrica de clientes SP falsos que registra cada invocación SIN argumentos."""

    def __init__(self, cliente=None, excepcion=None):
        self._cliente = cliente
        self._excepcion = excepcion
        self.llamadas = []

    def __call__(self):
        self.llamadas.append(())
        if self._excepcion is not None:
            raise self._excepcion
        return self._cliente if self._cliente is not None else ClienteSpFalso()


class ConfiguracionFalsa:
    """Doble de configuración con el tope de descubrimiento de las pruebas."""

    def ObtenerAtributo(self, nombre):
        if nombre == "limite_opciones_descubrimiento":
            return LIMITE_OPCIONES
        raise AssertionError(f"Atributo no esperado: {nombre}")


def _ClienteConPrincipales():
    """Construye un cliente SP falso con un principal de cada tipo."""
    return ClienteSpFalso(
        usuarios=[USUARIO],
        grupos=[GRUPO],
        service_principals=[SERVICE_PRINCIPAL],
    )


def TestFabricaConstruyeClienteSpDesdeAutoconfiguracionSinToken():
    """El cliente SP se obtiene SIN host/token (autoconfiguración OAuth M2M)."""
    cliente_sp = _ClienteConPrincipales()
    fabrica_sp = FabricaClienteSpFalsa(cliente=cliente_sp)
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=fabrica_sp, configuracion=ConfiguracionFalsa()
    )

    contexto = fabrica.CrearContexto()

    assert isinstance(contexto, ContextoOperacionBroker)
    assert contexto.cliente_sp is cliente_sp
    assert fabrica_sp.llamadas == [()], (
        "La fábrica del SP se invoca SIN argumentos: el SDK autoconfigura el "
        "OAuth M2M del service principal desde el entorno de la App; jamás "
        "recibe host ni token del llamante (design.md D4)."
    )


def TestCanalControlUsaElTransporteDelClienteSp():
    """El canal de control lee/escribe ACL con el transporte SDK del SP."""
    cliente_sp = _ClienteConPrincipales()
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=FabricaClienteSpFalsa(cliente=cliente_sp),
        configuracion=ConfiguracionFalsa(),
    )

    contexto = fabrica.CrearContexto()

    assert isinstance(contexto.canal_control, CanalControlComputo)
    transporte = contexto.canal_control.transporte
    assert isinstance(transporte, ClientePermisosSdk)
    assert transporte.cliente is cliente_sp, (
        "Las ACL del plano de control (warehouses, clusters, serverless, apps "
        "y tokens) se operan con el transporte del SP, no con credencial OBO."
    )


def TestDescubridorListaPrincipalesConElClienteSp():
    """El descubridor SCIM se compone con el SP y preserva el App Id."""
    cliente_sp = _ClienteConPrincipales()
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=FabricaClienteSpFalsa(cliente=cliente_sp),
        configuracion=ConfiguracionFalsa(),
    )

    contexto = fabrica.CrearContexto()

    assert isinstance(contexto.descubridor_principales, DescubridorPrincipales)

    principals = contexto.descubridor_principales.ListarPrincipales()
    assert [principal.tipo for principal in principals] == [
        TipoPrincipal.USUARIO,
        TipoPrincipal.GRUPO,
        TipoPrincipal.SERVICE_PRINCIPAL,
    ]
    servicio = principals[-1]
    assert servicio.app_id == APP_ID_SP, (
        "El App Id del service principal se preserva para el emparejamiento de "
        "la resolución de privilegios (design.md D4)."
    )


def TestSpNuncaSeUsaParaLaIdentidadObo():
    """El contexto broker no lee token OBO: el SP solo ejecuta, no autoriza."""
    fabrica_sp = FabricaClienteSpFalsa(cliente=_ClienteConPrincipales())
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=fabrica_sp, configuracion=ConfiguracionFalsa()
    )

    # La fábrica broker no expone acceso a headers ni token: construir el
    # contexto no requiere llamante alguno.
    contexto = fabrica.CrearContexto()

    assert contexto.cliente_sp is not None
    # La única vía de cliente es la del SP; no existe cliente OBO aquí.
    assert fabrica_sp.llamadas == [()]


def TestCadaAccionConstruyeContextoNuevo():
    """Dos acciones broker no comparten canal ni descubridor mutables."""
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=FabricaClienteSpFalsa(cliente=_ClienteConPrincipales()),
        configuracion=ConfiguracionFalsa(),
    )

    primero = fabrica.CrearContexto()
    segundo = fabrica.CrearContexto()

    assert primero.canal_control is not segundo.canal_control
    assert primero.descubridor_principales is not segundo.descubridor_principales


def TestFalloDeClienteSpSeTraduceSinExponerSecreto():
    """Un fallo del cliente SP se traduce a ErrorAutenticacionLlamante."""
    fabrica_sp = FabricaClienteSpFalsa(
        excepcion=RuntimeError("OAuth M2M sin DATABRICKS_CLIENT_ID")
    )
    fabrica = FabricaContextoBroker(
        fabrica_cliente_sp=fabrica_sp, configuracion=ConfiguracionFalsa()
    )

    with pytest.raises(ErrorAutenticacionLlamante) as informacion:
        fabrica.CrearContexto()

    assert isinstance(informacion.value.__cause__, RuntimeError)
