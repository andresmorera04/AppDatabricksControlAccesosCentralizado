"""Pruebas de aceptación del capability `caller-identity`.

Trazabilidad 1:1 con los escenarios del spec delta
`openspec/changes/auth-caller-obo/specs/caller-identity/spec.md`:

- Identificación del llamante vía on-behalf-of:
  - Llamante autenticado -> TestEscenarioLlamanteAutenticado
  - Contexto de llamante ausente -> TestEscenarioContextoDeLlamanteAusente
- El llamante se representa como un principal del dominio:
  - Llamante usuario -> TestEscenarioLlamanteUsuario
  - Llamante service principal con App Id
    -> TestEscenarioLlamanteServicePrincipalConAppId
  - Llamante grupo -> TestEscenarioLlamanteGrupo
- Los service principals son principales independientes:
  - Service principal distinto del usuario llamante
    -> TestEscenarioServicePrincipalDistintoDelUsuarioLlamante
- Resolución de grupos del llamante:
  - Llamante con grupos -> TestEscenarioLlamanteConGrupos
  - Llamante sin grupos -> TestEscenarioLlamanteSinGrupos
- Referencias de identidad para el emparejamiento de otorgamientos:
  - Referencias de un usuario con grupos
    -> TestEscenarioReferenciasDeUnUsuarioConGrupos
  - Referencias de un service principal
    -> TestEscenarioReferenciasDeUnServicePrincipal
- Identidad del llamante disponible para la bitácora de eventos:
  - Bitácora registra usuario del llamante
    -> TestEscenarioBitacoraRegistraUsuarioDelLlamante
  - Bitácora registra evento sin usuario
    -> TestEscenarioBitacoraRegistraEventoSinUsuario
- Errores de autenticación visibles y controlados:
  - Token de usuario inválido o ausente
    -> TestEscenarioTokenDeUsuarioInvalidoOAusente
  - Identificador del llamante vacío
    -> TestEscenarioIdentificadorDelLlamanteVacio

También cubre los criterios del `proposal.md` aplicables a esta capability:
autenticación on-behalf-of detrás de un puerto inyectable, identidad como
principal del dominio con sus grupos, y alimentación del campo `usuario` de la
bitácora de eventos. Todo sin conexión externa (proveedores y canales
simulados), como exige el alcance de solo lectura del change.
"""

from control_accesos.autenticacion.errores import ErrorAutenticacionLlamante
from control_accesos.autenticacion.modelos import ContextoLlamante
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    APP_ID_DEMO,
    ID_GRUPO_ADMINS_DEMO,
    ID_GRUPO_USERS_DEMO,
    IDENTIFICADOR_USUARIO_DEMO,
    NOMBRE_GRUPO_ADMINS_DEMO,
    NOMBRE_GRUPO_USERS_DEMO,
    NOMBRE_SERVICE_PRINCIPAL_DEMO,
    NOMBRE_USUARIO_DEMO,
    ContextoAusente,
    IdentidadGrupo,
    IdentidadServicePrincipal,
    IdentidadUsuarioConGrupos,
    IdentidadUsuarioSinGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants

# App Id de un service principal DISTINTO del llamante, registrado en el
# workspace con otorgamientos propios (valor de prueba, no configuración).
APP_ID_DE_OTRO_SERVICE_PRINCIPAL = "11111111-2222-3333-4444-555555555555"
NOMBRE_DE_OTRO_SERVICE_PRINCIPAL = "sp-ajeno-al-llamante"

# Objeto y beneficiario usados por los escenarios de bitácora de eventos.
CATALOGO_DE_PRUEBA = ObjetoSecurable(
    identificador="control", tipo=TipoObjeto.CATALOGO
)
BENEFICIARIO_DE_PRUEBA = "beneficiario"


class RegistradorErroresEspia:
    """Espía del contrato `BitacoraErrores.Registrar`.

    Attributes:
        registros (list[dict]): llamadas recibidas, con la excepción, el
            módulo, el usuario y el contexto declarados.
    """

    def __init__(self):
        """Inicializa la lista de registros recibidos."""
        self.registros = []

    def Registrar(self, excepcion, modulo=None, usuario=None, contexto=""):
        """Guarda el registro en memoria en lugar de escribirlo en la tabla.

        Args:
            excepcion (BaseException): excepción capturada por el módulo.
            modulo (str | None): módulo que reporta el fallo.
            usuario (str | None): usuario relacionado con el fallo.
            contexto (str): operación que falló.

        Returns:
            dict: el registro guardado por el espía.
        """
        registro = {
            "excepcion": excepcion,
            "modulo": modulo,
            "usuario": usuario,
            "contexto": contexto,
        }
        self.registros.append(registro)
        return registro


class RegistradorEventosEspia:
    """Espía del contrato `BitacoraEventos.Registrar`.

    Attributes:
        eventos (list[dict]): eventos recibidos, con acción, usuario, detalle
            y resultado.
    """

    def __init__(self):
        """Inicializa la lista de eventos recibidos."""
        self.eventos = []

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None,
                  marca_tiempo=None):
        """Guarda el evento en memoria en lugar de escribirlo en la tabla.

        Args:
            accion (str): acción realizada por la aplicación.
            usuario (str | None): usuario que provoca el evento.
            detalle (str | None): detalle libre del evento.
            resultado (str | None): resultado observable del evento.
            marca_tiempo (datetime | None): momento del evento.

        Returns:
            dict: el evento guardado por el espía.
        """
        evento = {
            "accion": accion,
            "usuario": usuario,
            "detalle": detalle,
            "resultado": resultado,
        }
        self.eventos.append(evento)
        return evento


def CrearServicio(contexto=None, proveedor=None, registrador_errores=None):
    """Construye el servicio de identidad con un proveedor simulado.

    Args:
        contexto (ContextoLlamante | None): contexto que devolverá el
            proveedor simulado.
        proveedor (ProveedorIdentidadLlamante | None): proveedor ya construido
            (por ejemplo, uno que lanza una excepción).
        registrador_errores (object | None): escritor de la bitácora de errores.

    Returns:
        ServicioIdentidadLlamante: servicio de producción listo para resolver.
    """
    return ServicioIdentidadLlamante(
        proveedor=proveedor
        or ProveedorIdentidadSimulado(contexto=contexto),
        registrador_errores=registrador_errores,
    )


def CrearPipelineConEventos(identidad_llamante, registrador_eventos):
    """Construye el pipeline con canales simulados y bitácora de eventos.

    Args:
        identidad_llamante (IdentidadLlamante | None): identidad del llamante.
        registrador_eventos (object): escritor de eventos a inyectar.

    Returns:
        PipelineGrants: orquestador listo para procesar una solicitud.
    """
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    return PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=identidad_llamante,
        registrador_eventos=registrador_eventos,
    )


def SolicitudDePrueba():
    """Construye una solicitud 1 a 1 sobre el catálogo de prueba.

    Returns:
        SolicitudGrant: solicitud válida para procesar.
    """
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO_DE_PRUEBA, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=CATALOGO_DE_PRUEBA,
    )


def TestEscenarioLlamanteAutenticado():
    """Escenario: Llamante autenticado.

    WHEN la app recibe una invocación con un contexto on-behalf-of válido
    THEN el sistema resuelve y expone la identidad del llamante de ese contexto.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioConGrupos())

    identidad = servicio.ObtenerIdentidadLlamante()

    assert servicio.IdentidadResuelta is True
    assert identidad is not None
    assert identidad.principal.identificador == IDENTIFICADOR_USUARIO_DEMO, (
        "La identidad expuesta es la del contexto recibido"
    )


def TestEscenarioContextoDeLlamanteAusente():
    """Escenario: Contexto de llamante ausente.

    WHEN la invocación no trae contexto de usuario válido
    THEN la identidad queda explícitamente sin resolver y el fallo se registra
         de forma controlada, sin propagar una excepción.
    """
    registrador = RegistradorErroresEspia()
    servicio = CrearServicio(
        proveedor=ContextoAusente(), registrador_errores=registrador
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad is None, "La identidad queda explícitamente sin resolver"
    assert servicio.IdentidadResuelta is False
    assert len(registrador.registros) == 1, (
        "El fallo se registra en la bitácora de errores"
    )


def TestEscenarioLlamanteUsuario():
    """Escenario: Llamante usuario.

    WHEN el contexto on-behalf-of corresponde a un usuario de Databricks
    THEN la identidad se expone con tipo `usuario` y su identificador.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioConGrupos())

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.USUARIO
    assert identidad.principal.identificador == IDENTIFICADOR_USUARIO_DEMO
    assert identidad.nombre_mostrable == NOMBRE_USUARIO_DEMO


def TestEscenarioLlamanteServicePrincipalConAppId():
    """Escenario: Llamante service principal con App Id.

    WHEN la app se ejecuta con la identidad de su propio service principal
    THEN la identidad se expone con tipo `service_principal`, su App Id y nombre.
    """
    servicio = CrearServicio(contexto=IdentidadServicePrincipal())

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL
    assert identidad.app_id == APP_ID_DEMO
    assert identidad.principal.identificador == NOMBRE_SERVICE_PRINCIPAL_DEMO


def TestEscenarioLlamanteGrupo():
    """Escenario: Llamante grupo.

    WHEN el llamante autenticado corresponde a un grupo
    THEN la identidad se expone con tipo `grupo` y su identificador.
    """
    servicio = CrearServicio(contexto=IdentidadGrupo())

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad.principal.tipo is TipoPrincipal.GRUPO
    assert identidad.principal.identificador == NOMBRE_GRUPO_ADMINS_DEMO


def TestEscenarioServicePrincipalDistintoDelUsuarioLlamante():
    """Escenario: Service principal distinto del usuario llamante.

    WHEN el llamante es un usuario y el workspace tiene service principals con
         otorgamientos propios
    THEN el sistema no atribuye al usuario la identidad de esos service
         principals: sus App Id y nombres no son referencias del llamante.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioConGrupos())

    identidad = servicio.ObtenerIdentidadLlamante()
    referencias = set(identidad.ReferenciasDeIdentidad())

    assert identidad.app_id is None, (
        "Un usuario no lleva App Id: no se le atribuye identidad de SP"
    )
    assert APP_ID_DE_OTRO_SERVICE_PRINCIPAL not in referencias
    assert NOMBRE_DE_OTRO_SERVICE_PRINCIPAL not in referencias
    assert APP_ID_DEMO not in referencias, (
        "Tampoco se le atribuye el App Id del service principal de la app"
    )


def TestEscenarioLlamanteConGrupos():
    """Escenario: Llamante con grupos.

    WHEN se resuelven los grupos de un llamante con varias membresías
    THEN se devuelve la lista completa, cada grupo con nombre e identificador.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioConGrupos())

    grupos = servicio.ObtenerGruposLlamante()

    assert len(grupos) == 2
    identificadores = {grupo.identificador for grupo in grupos}
    nombres = {grupo.nombre for grupo in grupos}
    assert identificadores == {ID_GRUPO_ADMINS_DEMO, ID_GRUPO_USERS_DEMO}
    assert nombres == {NOMBRE_GRUPO_ADMINS_DEMO, NOMBRE_GRUPO_USERS_DEMO}


def TestEscenarioLlamanteSinGrupos():
    """Escenario: Llamante sin grupos.

    WHEN se resuelven los grupos de un llamante sin membresías
    THEN se devuelve una lista explícitamente vacía, distinguible de un fallo.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioSinGrupos())

    grupos = servicio.ObtenerGruposLlamante()

    assert grupos == (), "Vacío explícito, no un fallo de resolución"
    assert servicio.IdentidadResuelta is True, (
        "La identidad sí se resolvió: solo carece de grupos"
    )
    assert servicio.ObtenerIdentidadLlamante() is not None


def TestEscenarioReferenciasDeUnUsuarioConGrupos():
    """Escenario: Referencias de un usuario con grupos.

    WHEN se solicitan las referencias de un usuario miembro de dos grupos
    THEN se devuelve el identificador y nombre del usuario junto con el
         identificador y el nombre de cada grupo.
    """
    servicio = CrearServicio(contexto=IdentidadUsuarioConGrupos())

    referencias = set(servicio.ObtenerIdentidadLlamante().ReferenciasDeIdentidad())

    assert IDENTIFICADOR_USUARIO_DEMO in referencias
    assert NOMBRE_USUARIO_DEMO in referencias
    assert ID_GRUPO_ADMINS_DEMO in referencias
    assert NOMBRE_GRUPO_ADMINS_DEMO in referencias
    assert ID_GRUPO_USERS_DEMO in referencias
    assert NOMBRE_GRUPO_USERS_DEMO in referencias


def TestEscenarioReferenciasDeUnServicePrincipal():
    """Escenario: Referencias de un service principal.

    WHEN se solicitan las referencias de un service principal
    THEN se incluye su App Id y su nombre, además de los identificadores y
         nombres de sus grupos.
    """
    servicio = CrearServicio(contexto=IdentidadServicePrincipal())

    referencias = set(servicio.ObtenerIdentidadLlamante().ReferenciasDeIdentidad())

    assert APP_ID_DEMO in referencias
    assert NOMBRE_SERVICE_PRINCIPAL_DEMO in referencias
    assert ID_GRUPO_USERS_DEMO in referencias
    assert NOMBRE_GRUPO_USERS_DEMO in referencias


def TestEscenarioBitacoraRegistraUsuarioDelLlamante():
    """Escenario: Bitácora registra usuario del llamante.

    WHEN ocurre un evento de la aplicación con una identidad OBO resuelta
    THEN la bitácora registra el evento con el identificador del llamante en
         el campo `usuario`.
    """
    registrador = RegistradorEventosEspia()
    identidad = CrearServicio(
        contexto=IdentidadUsuarioConGrupos()
    ).ObtenerIdentidadLlamante()
    pipeline = CrearPipelineConEventos(identidad, registrador)

    pipeline.Procesar(SolicitudDePrueba())

    assert len(registrador.eventos) == 1
    assert registrador.eventos[0]["usuario"] == IDENTIFICADOR_USUARIO_DEMO


def TestEscenarioBitacoraRegistraEventoSinUsuario():
    """Escenario: Bitácora registra evento sin usuario.

    WHEN ocurre un evento de la aplicación sin identidad OBO resuelta
    THEN la bitácora registra el evento con `usuario` explícitamente sin valor,
         sin rechazarlo.
    """
    registrador = RegistradorEventosEspia()
    pipeline = CrearPipelineConEventos(None, registrador)

    reporte = pipeline.Procesar(SolicitudDePrueba())

    assert len(registrador.eventos) == 1, "El evento se registra igual"
    assert registrador.eventos[0]["usuario"] is None
    assert reporte.lineas, "La operación principal no se interrumpe"


def TestEscenarioTokenDeUsuarioInvalidoOAusente():
    """Escenario: Token de usuario inválido o ausente.

    WHEN la invocación trae un token de usuario ausente, expirado o no
         verificable
    THEN el sistema registra el error en la bitácora de errores y deja la
         identidad del llamante sin resolver.
    """
    registrador = RegistradorErroresEspia()
    servicio = CrearServicio(
        proveedor=ProveedorIdentidadSimulado(
            excepcion=ErrorAutenticacionLlamante(
                "El token on-behalf-of del usuario expiró (simulado)."
            )
        ),
        registrador_errores=registrador,
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad is None
    assert len(registrador.registros) == 1
    registro = registrador.registros[0]
    assert isinstance(registro["excepcion"], ErrorAutenticacionLlamante)
    assert registro["modulo"], "El registro declara el módulo que falló"
    assert registro["contexto"], "El registro declara la operación fallida"


def TestEscenarioIdentificadorDelLlamanteVacio():
    """Escenario: Identificador del llamante vacío.

    WHEN el contexto on-behalf-of devuelve un identificador de usuario vacío
    THEN el sistema registra el error y deja la identidad explícitamente sin
         resolver.
    """
    registrador = RegistradorErroresEspia()
    servicio = CrearServicio(
        contexto=ContextoLlamante(
            tipo=TipoPrincipal.USUARIO,
            identificador="   ",
            nombre_mostrable=NOMBRE_USUARIO_DEMO,
        ),
        registrador_errores=registrador,
    )

    identidad = servicio.ObtenerIdentidadLlamante()

    assert identidad is None, (
        "Sin identificador no hay a quién atribuir privilegios"
    )
    assert len(registrador.registros) == 1, (
        "El fallo queda registrado en la bitácora de errores"
    )
