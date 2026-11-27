"""Prueba unitaria del descubrimiento SCIM con SP y de la bitácora broker.

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Dos contratos fijados aquí:

1. `DescubridorPrincipales` (listado SCIM con el service principal):
   - lista usuarios, grupos y service principals, preservando el App Id de los
     service principals (referencia de emparejamiento de la resolución);
   - pagina: camina el iterador completo y acota con `limite` (regla No
     HardCoded: el valor lo inyecta la fábrica desde la configuración);
   - orden estable: conserva el orden del servicio, sin barajar opciones;
   - un error del listado se distingue de una lista auténticamente vacía:
     `ErrorListadoPrincipales` frente a tupla vacía.
2. `PipelineGrants` en modo broker (`identidad_ejecucion="app"`): el evento de
   bitácora registra el usuario OBO del llamante en `usuario` y declara en su
   `detalle` que la ejecución usó la identidad de la App.

Todos los colaboradores son dobles inyectados: sin red ni tabla delta.
"""

import types

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.reales.descubrimiento_principales import (
    DescubridorPrincipales,
    ErrorListadoPrincipales,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal, SolicitudGrant
from control_accesos.pipeline.pipeline_grants import (
    IDENTIDAD_EJECUCION_APP,
    PipelineGrants,
)

APP_ID_DEMO = "11111111-2222-3333-4444-555555555555"
USUARIO_OBO = "usuario_demo@example.com"


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
    """Doble del cliente SP con los tres servicios SCIM."""

    def __init__(self, usuarios=(), grupos=(), service_principals=()):
        self.users = ServicioListaFalso(usuarios)
        self.groups = ServicioListaFalso(grupos)
        self.service_principals = ServicioListaFalso(service_principals)


def _Usuario(nombre="usuario@example.com", display="Usuario Uno", con_display=True):
    return types.SimpleNamespace(
        user_name=nombre, display_name=display if con_display else None
    )


def _Grupo(nombre="analistas"):
    return types.SimpleNamespace(display_name=nombre)


def _ServicePrincipal(app_id=APP_ID_DEMO, display="app-service-principal"):
    return types.SimpleNamespace(application_id=app_id, display_name=display)


# --- Descubrimiento SCIM con SP ---


def TestListaUsuariosGruposYServicePrincipalsConAppIdPreservado():
    """El agregado devuelve los tres tipos en orden, con el App Id intacto."""
    cliente = ClienteSpFalso(
        usuarios=[_Usuario()],
        grupos=[_Grupo()],
        service_principals=[_ServicePrincipal()],
    )
    descubridor = DescubridorPrincipales(cliente)

    principals = descubridor.ListarPrincipales()

    assert [principal.tipo for principal in principals] == [
        TipoPrincipal.USUARIO,
        TipoPrincipal.GRUPO,
        TipoPrincipal.SERVICE_PRINCIPAL,
    ]
    assert principals[0].identificador == "usuario@example.com"
    assert principals[1].identificador == "analistas"
    assert principals[2].app_id == APP_ID_DEMO, (
        "El App Id del service principal se preserva para el emparejamiento."
    )
    assert principals[2].identificador == APP_ID_DEMO


def TestLimiteAcotaElResultado():
    """Con `limite` se devuelve solo el tope, en el orden del servicio."""
    usuarios = [_Usuario(nombre=f"u{i}@example.com", display=f"U{i}") for i in range(5)]
    cliente = ClienteSpFalso(usuarios=usuarios)
    descubridor = DescubridorPrincipales(cliente, limite=2)

    principals = descubridor.ListarUsuarios()

    assert [p.identificador for p in principals] == [
        "u0@example.com",
        "u1@example.com",
    ]


def TestOrdenEstable():
    """Dos invocaciones devuelven el mismo orden (sin barajar opciones)."""
    cliente = ClienteSpFalso(usuarios=[_Usuario("a@x.com"), _Usuario("b@x.com"), _Usuario("c@x.com")])
    descubridor = DescubridorPrincipales(cliente)

    primera = [p.identificador for p in descubridor.ListarUsuarios()]
    segunda = [p.identificador for p in descubridor.ListarUsuarios()]

    assert primera == segunda == ["a@x.com", "b@x.com", "c@x.com"]


def TestRegistroSinIdentificadorSeOmite():
    """Un usuario sin user_name se descarta sin abortar el listado."""
    cliente = ClienteSpFalso(
        usuarios=[_Usuario("bueno@x.com"), types.SimpleNamespace(user_name=None)]
    )
    descubridor = DescubridorPrincipales(cliente)

    principals = descubridor.ListarUsuarios()

    assert [p.identificador for p in principals] == ["bueno@x.com"]


def TestErrorDeListadoSeDistingueDeListaVacia():
    """Vacío auténtico -> tupla vacía; fallo -> ErrorListadoPrincipales."""
    vacio = ClienteSpFalso(usuarios=[], grupos=[], service_principals=[])
    assert DescubridorPrincipales(vacio).ListarPrincipales() == ()

    roto = ClienteSpFalso(usuarios=[_Usuario()])
    roto.users = ServicioListaFalso(excepcion=RuntimeError("SCIM inaccesible"))

    try:
        DescubridorPrincipales(roto).ListarUsuarios()
    except ErrorListadoPrincipales:
        pass
    else:
        raise AssertionError(
            "Un fallo del listado debe tipificarse como ErrorListadoPrincipales "
            "y no confundirse con una lista vacía."
        )


# --- Bitácora: usuario OBO e identidad de ejecución App ---


class EscritorEventosEspia:
    """Espía del contrato `BitacoraEventos.Registrar`."""

    def __init__(self):
        self.eventos = []

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        self.eventos.append(
            {
                "accion": accion,
                "usuario": usuario,
                "detalle": detalle,
                "resultado": resultado,
            }
        )
        return self.eventos[-1]


def IdentidadUsuario():
    """Identidad OBO resuelta del usuario de prueba."""
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


def CrearSolicitud():
    """Solicitud 1 a 1 sobre un SQL warehouse (plano de control)."""
    return SolicitudGrant.Crear(
        principal=Principal(identificador="beneficiario", tipo=TipoPrincipal.USUARIO),
        privilegios=["CAN_USE"],
        objeto=ObjetoSecurable(identificador="wh-1", tipo=TipoObjeto.SQL_WAREHOUSE),
    )


def CrearPipelineBroker(registrador_eventos):
    """Pipeline en modo broker con canales simulados y registrador espía."""
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    return PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        identidad_ejecucion=IDENTIDAD_EJECUCION_APP,
        registrador_eventos=registrador_eventos,
    )


def TestEventoBrokerRegistraUsuarioOboEIdentidadEjecucionApp():
    """En modo broker, `usuario` es el OBO y el detalle declara la App."""
    bitacora = EscritorEventosEspia()

    CrearPipelineBroker(bitacora).Procesar(CrearSolicitud())

    evento = bitacora.eventos[0]
    assert evento["usuario"] == USUARIO_OBO, (
        "El campo usuario conserva la identidad OBO del llamante."
    )
    assert "identidad de la App" in evento["detalle"], (
        "El detalle del evento declara que la ejecución usó la identidad de la "
        "App (spec app-broker-grants - Aislamiento entre llamantes y auditoría)."
    )


def TestEventoOboNoLlevaMarcadorDeEjecucionDeApp():
    """Sin modo broker, el detalle no declara ejecución con identidad de App."""
    bitacora = EscritorEventosEspia()
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora,
    ).Procesar(CrearSolicitud())

    assert "identidad de la App" not in bitacora.eventos[0]["detalle"]
    assert bitacora.eventos[0]["usuario"] == USUARIO_OBO
