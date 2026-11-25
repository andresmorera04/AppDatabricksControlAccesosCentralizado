"""Pruebas unitarias del adaptador del puerto de permisos sobre
`databricks-sdk` (tareas 1.3 y 1.4, design D3).

Ejercitan `ClientePermisosSdk` con un cliente simulado y sin cargar el SDK: la
lectura devuelve las entradas directas de la ACL omitiendo heredadas y sin
otorgatario; la escritura envía por PUT el conjunto completo con el campo del
principal correcto; y los errores del SDK llegan como `ErrorCanal` con el código
antepuesto y su detalle. Sin credenciales ni valores de conexión embebidos.
"""

from types import SimpleNamespace

import pytest

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
    _CampoDePrincipal,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.dominio.modelos import Principal


class ErrorSdkFalso(Exception):
    """Excepción con la forma de los errores del SDK (`error_code` + mensaje)."""

    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.error_code = codigo


class _ServicioPermisosFalso:
    """Doble del servicio `permissions` del SDK, con ACL en memoria."""

    def __init__(self, error_get=None):
        self.error_get = error_get
        self.acl = SimpleNamespace(access_control_list=[])

    def get(self, recurso, identificador):
        if self.error_get is not None:
            raise self.error_get
        return self.acl


class _ApiClientFalso:
    """Doble de `api_client` que registra las escrituras por PUT."""

    def __init__(self, error=None):
        self.llamadas = []
        self.error = error

    def do(self, method, path, body=None, headers=None, **kwargs):
        if self.error is not None:
            raise self.error
        self.llamadas.append((method, path, body))
        return {}


class _ClienteFalso:
    def __init__(self, servicio, api_client=_ApiClientFalso()):
        self.permissions = servicio
        self.api_client = api_client


def _Permiso(nivel_texto, heredado=False):
    return SimpleNamespace(permission_level=_Nivel(nivel_texto), inherited=heredado)


class _Nivel:
    def __init__(self, valor):
        self.value = valor


class TestLeerACL:
    """La lectura devuelve solo entradas directas e identificables."""

    def TestDevuelveEntradasDirectas(self):
        servicio = _ServicioPermisosFalso()
        servicio.acl = SimpleNamespace(
            access_control_list=[
                SimpleNamespace(
                    user_name="usuario@correo.com",
                    all_permissions=[_Permiso("CAN_USE")],
                ),
                SimpleNamespace(
                    group_name="Desarrollador",
                    all_permissions=[_Permiso("CAN_MANAGE")],
                ),
            ]
        )
        adaptador = ClientePermisosSdk(_ClienteFalso(servicio))

        entradas = adaptador.LeerAcl("clusters", "id-1")

        assert entradas == (
            EntradaAcl(Principal(identificador="usuario@correo.com", tipo=TipoPrincipal.USUARIO), "CAN_USE"),
            EntradaAcl(Principal(identificador="Desarrollador", tipo=TipoPrincipal.GRUPO), "CAN_MANAGE"),
        )

    def TestDevuelveEntradaDeServicePrincipal(self):
        servicio = _ServicioPermisosFalso()
        servicio.acl = SimpleNamespace(
            access_control_list=[
                SimpleNamespace(
                    service_principal_name="1738687d-4838-49ef-83fd-521f935a9ec2",
                    all_permissions=[_Permiso("CAN_USE")],
                ),
            ]
        )
        adaptador = ClientePermisosSdk(_ClienteFalso(servicio))

        (entrada,) = adaptador.LeerAcl("clusters", "id-1")

        assert entrada.principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL
        assert entrada.principal.identificador == "1738687d-4838-49ef-83fd-521f935a9ec2"

    def TestOmiteNivelesHeredados(self):
        servicio = _ServicioPermisosFalso()
        servicio.acl = SimpleNamespace(
            access_control_list=[
                SimpleNamespace(
                    user_name="usuario@correo.com",
                    all_permissions=[_Permiso("CAN_USE", heredado=True)],
                ),
            ]
        )
        adaptador = ClientePermisosSdk(_ClienteFalso(servicio))

        assert adaptador.LeerAcl("clusters", "id-1") == ()

    def TestOmiteEntradaSinOtorgatario(self):
        servicio = _ServicioPermisosFalso()
        servicio.acl = SimpleNamespace(
            access_control_list=[SimpleNamespace(all_permissions=[_Permiso("CAN_USE")])],
        )
        adaptador = ClientePermisosSdk(_ClienteFalso(servicio))

        assert adaptador.LeerAcl("clusters", "id-1") == ()


class TestEscribirACL:
    """La escritura envía por PUT el conjunto completo con el campo correcto."""

    def TestEscribePorPutElConjuntoRecibido(self):
        api = _ApiClientFalso()
        adaptador = ClientePermisosSdk(_ClienteFalso(_ServicioPermisosFalso(), api_client=api))
        entrada = EntradaAcl(
            Principal(identificador="1738687d-4838-49ef-83fd-521f935a9ec2", tipo=TipoPrincipal.SERVICE_PRINCIPAL),
            "CAN_USE",
        )

        adaptador.EscribirAcl("sql/warehouses", "wh-1", [entrada])

        (metodo, ruta, cuerpo) = api.llamadas[0]
        assert metodo == "PUT"
        assert ruta == "/api/2.0/permissions/sql/warehouses/wh-1"
        assert cuerpo == {
            "access_control_list": [
                {"service_principal_name": "1738687d-4838-49ef-83fd-521f935a9ec2", "permission_level": "CAN_USE"}
            ]
        }

    def TestEscribeLaListaRecibidaSinReemplazo(self):
        api = _ApiClientFalso()
        adaptador = ClientePermisosSdk(_ClienteFalso(_ServicioPermisosFalso(), api_client=api))
        entradas = [
            EntradaAcl(Principal(identificador="grupo-x", tipo=TipoPrincipal.GRUPO), "CAN_RESTART"),
            EntradaAcl(Principal(identificador="u@correo.com", tipo=TipoPrincipal.USUARIO), "CAN_USE"),
        ]

        adaptador.EscribirAcl("clusters", "c-1", entradas)

        (_, ruta, cuerpo) = api.llamadas[0]
        assert ruta == "/api/2.0/permissions/clusters/c-1"
        assert len(cuerpo["access_control_list"]) == 2


class TestCampoDePrincipal:
    """El mapeo tipo -> campo de la ACL es declarativo y libre de SDK."""

    def TestMapeoDeTipos(self):
        assert _CampoDePrincipal(TipoPrincipal.USUARIO) == "user_name"
        assert _CampoDePrincipal(TipoPrincipal.GRUPO) == "group_name"
        assert _CampoDePrincipal(TipoPrincipal.SERVICE_PRINCIPAL) == "service_principal_name"


class TestTraduccionErrores:
    """Los errores del SDK llegan como `ErrorCanal` con código y detalle."""

    def TestCodigoAntepuesto(self):
        servicio = _ServicioPermisosFalso(
            error_get=ErrorSdkFalso("Cluster 'xyz' does not exist.", codigo="RESOURCE_DOES_NOT_EXIST")
        )
        adaptador = ClientePermisosSdk(_ClienteFalso(servicio))

        with pytest.raises(ErrorCanal) as capturado:
            adaptador.LeerAcl("clusters", "xyz")

        assert "[RESOURCE_DOES_NOT_EXIST]" in str(capturado.value)

    def TestErrorSinCodigoConservaDetalle(self):
        api = _ApiClientFalso(error=ErrorSdkFalso("fallo de transporte"))
        adaptador = ClientePermisosSdk(_ClienteFalso(_ServicioPermisosFalso(), api_client=api))

        with pytest.raises(ErrorCanal) as capturado:
            adaptador.EscribirAcl("clusters", "c-1", [])

        assert "fallo de transporte" in str(capturado.value)


class TestConstruccionAdaptador:
    """Validación del cliente en el constructor, sin credenciales embebidas."""

    def TestClienteSinServicioPermisosSeRechaza(self):
        with pytest.raises(ValueError):
            ClientePermisosSdk(SimpleNamespace())

    def TestClienteSinApiClientSeRechaza(self):
        with pytest.raises(ValueError):
            ClientePermisosSdk(SimpleNamespace(permissions=_ServicioPermisosFalso()))

    def TestClienteNuloSeRechaza(self):
        with pytest.raises(ValueError):
            ClientePermisosSdk(None)
