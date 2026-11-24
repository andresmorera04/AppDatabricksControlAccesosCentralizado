"""Adaptador de pruebas integrales: identidad real del llamante vía SCIM + CLI.

Infraestructura EXCLUSIVA de la capa de pruebas integrales (marker `free`,
tarea 5.1 del change `auth-caller-obo`): resuelve la identidad del llamante y
sus grupos contra el workspace real usando la SCIM API a través del CLI de
Databricks ya instalado, **sin instalar ninguna biblioteca nueva** (regla
"Prohibición de instalación por la IA"): no se requiere `databricks-sdk`.

El transporte es el mismo que usa `adaptador_sql_databricks.py`
(`EjecutarComandoCli`), de modo que toda la capa integral comparte un único
mecanismo de acceso al workspace.

**Es el mismo patrón que usará la Databricks App en producción con el token
on-behalf-of del llamante**: la app llamará a SCIM (`/Me`, `/Groups/{id}`,
`/ServicePrincipals`) con el token OBO del usuario y traducirá la respuesta a
un `ContextoLlamante`; aquí se hace con el token del perfil CLI, que en
`andresFree` pertenece al mismo usuario que invocaría la app. Por eso este
proveedor implementa el puerto de producción `ProveedorIdentidadLlamante` y se
inyecta en el `ServicioIdentidadLlamante` real: las integrales ejercitan código
de producción, no un doble.

Convención de nombres del proyecto: infraestructura de pruebas, pero con el
mismo estándar (clases y funciones en PascalCase, constantes en MAYÚSCULAS,
comentarios en español).
"""

from control_accesos.autenticacion.modelos import ContextoLlamante, Grupo
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoPrincipal

from adaptador_sql_databricks import (
    PERFIL_CLI_INTEGRAL,
    EjecutarComandoCli,
)

# Rutas de la SCIM API usadas por el adaptador (identidad y grupos del
# llamante, y service principals del workspace).
RUTA_API_SCIM_YO = "/api/2.0/preview/scim/v2/Me"
RUTA_API_SCIM_GRUPOS = "/api/2.0/preview/scim/v2/Groups"
RUTA_API_SCIM_SERVICE_PRINCIPALS = (
    "/api/2.0/preview/scim/v2/ServicePrincipals"
)

# Ruta de la Apps API, usada para descubrir el service principal con el que se
# ejecuta una Databricks App (su `service_principal_client_id` es el App Id con
# el que Unity Catalog reporta sus otorgamientos).
RUTA_API_APPS = "/api/2.0/apps"

# SCIM reporta membresías directas e indirectas; el spec `caller-identity`
# pide los grupos de los que el llamante es miembro DIRECTO.
TIPO_MEMBRESIA_DIRECTA = "direct"


class ProveedorIdentidadScimCli(ProveedorIdentidadLlamante):
    """Proveedor real del contexto on-behalf-of, apoyado en SCIM y el CLI.

    Implementa el puerto de producción `ProveedorIdentidadLlamante`:

    - `ObtenerContexto()` resuelve al llamante autenticado (`/Me`), que es el
      caso real de una invocación con token OBO de usuario;
    - `ObtenerContextoDeServicePrincipal()` resuelve la identidad de un
      service principal del workspace por su App Id o por su nombre, que es el
      caso de la app ejecutándose con su propia identidad.

    Attributes:
        perfil (str): perfil CLI autenticado contra el workspace.
        consultas_ejecutadas (list[str]): rutas SCIM consultadas, en orden;
            permite a las pruebas verificar que la resolución es de SOLO
            LECTURA (spec `caller-privilege-resolution`).
    """

    def __init__(self, perfil=PERFIL_CLI_INTEGRAL):
        """Inicializa el proveedor con el perfil CLI del workspace.

        Args:
            perfil (str): perfil CLI autenticado (por defecto, `andresFree`).
        """
        self.perfil = perfil
        self.consultas_ejecutadas = []

    def ObtenerContexto(self):
        """Resuelve el contexto del llamante autenticado vía SCIM `/Me`.

        Returns:
            ContextoLlamante | None: contexto de tipo `usuario` con su correo
                (`userName`), su nombre para mostrar y sus grupos de membresía
                directa; None cuando el workspace no reporta un usuario
                autenticado (escenario 'Contexto de llamante ausente').

        Raises:
            ErrorTransporteDatabricks: si el CLI falla o la respuesta no es
                JSON válido (el `ServicioIdentidadLlamante` de producción lo
                captura y degrada sin propagarlo).
        """
        respuesta = self._Consultar(RUTA_API_SCIM_YO)

        identificador = respuesta.get("userName")
        if not identificador or not str(identificador).strip():
            # Sin `userName` no hay a quién atribuir privilegios: el servicio
            # tratará la ausencia de contexto (no se inventa un identificador).
            return None

        return ContextoLlamante(
            tipo=TipoPrincipal.USUARIO,
            identificador=str(identificador).strip(),
            nombre_mostrable=respuesta.get("displayName"),
            grupos=self._GruposDeMembresiaDirecta(respuesta.get("groups")),
        )

    def ObtenerContextoDeServicePrincipal(self, app_id=None, nombre=None):
        """Resuelve el contexto de un service principal del workspace.

        Args:
            app_id (str | None): App Id (`applicationId`) del service
                principal; referencia con la que Unity Catalog reporta sus
                otorgamientos.
            nombre (str | None): nombre para mostrar del service principal
                (`displayName`); referencia con la que lo reporta la
                Permissions API del plano de control.

        Returns:
            ContextoLlamante | None: contexto de tipo `service_principal` con
                su App Id y sus grupos de membresía directa; None si ningún
                service principal del workspace coincide con el criterio.

        Raises:
            ValueError: si no se indica ni `app_id` ni `nombre`.
            ErrorTransporteDatabricks: si falla el transporte CLI.
        """
        if not app_id and not nombre:
            raise ValueError(
                "Para resolver un service principal se requiere su App Id o "
                "su nombre; no se admite buscar sin criterio."
            )

        for service_principal in self.ListarServicePrincipales():
            coincide_app_id = (
                app_id is not None
                and service_principal.get("applicationId") == app_id
            )
            coincide_nombre = (
                nombre is not None
                and service_principal.get("displayName") == nombre
            )
            if not (coincide_app_id or coincide_nombre):
                continue

            nombre_sp = service_principal.get("displayName")
            return ContextoLlamante(
                tipo=TipoPrincipal.SERVICE_PRINCIPAL,
                identificador=nombre_sp,
                nombre_mostrable=nombre_sp,
                app_id=service_principal.get("applicationId"),
                grupos=self._GruposDeMembresiaDirecta(
                    service_principal.get("groups")
                ),
            )
        return None

    def ListarServicePrincipales(self):
        """Lista los service principals registrados en el workspace.

        Returns:
            list[dict]: recursos SCIM de service principals, con `displayName`,
                `applicationId`, `id` y `groups`.

        Raises:
            ErrorTransporteDatabricks: si falla el transporte CLI.
        """
        respuesta = self._Consultar(RUTA_API_SCIM_SERVICE_PRINCIPALS)
        return list(respuesta.get("Resources") or [])

    def ObtenerGrupo(self, identificador_grupo):
        """Resuelve un grupo del workspace por su identificador SCIM.

        Args:
            identificador_grupo (str): id SCIM del grupo (el `value` que
                reporta la membresía).

        Returns:
            tuple[Grupo, tuple[str, ...]] | None: el grupo con su nombre real y
                los identificadores de sus miembros, o None si no existe.

        Raises:
            ErrorTransporteDatabricks: si falla el transporte CLI.
        """
        respuesta = self._Consultar(
            f"{RUTA_API_SCIM_GRUPOS}/{identificador_grupo}"
        )
        if not respuesta.get("id"):
            return None

        miembros = tuple(
            str(miembro.get("value"))
            for miembro in (respuesta.get("members") or [])
            if miembro.get("value")
        )
        return (
            Grupo(
                identificador=str(respuesta["id"]),
                nombre=respuesta.get("displayName"),
            ),
            miembros,
        )

    def _GruposDeMembresiaDirecta(self, grupos_scim):
        """Traduce las membresías SCIM a los `Grupo` del dominio.

        Args:
            grupos_scim (list[dict] | None): membresías reportadas por SCIM,
                cada una con `value` (id) y `display` (nombre).

        Returns:
            tuple[Grupo, ...]: grupos de membresía directa; tupla vacía cuando
                el llamante no tiene grupos (vacío explícito, distinguible de
                un fallo de resolución).
        """
        grupos = []
        for membresia in grupos_scim or ():
            if membresia.get("type") != TIPO_MEMBRESIA_DIRECTA:
                # Solo membresías directas (spec `caller-identity`).
                continue
            identificador = membresia.get("value")
            if not identificador:
                continue
            grupos.append(
                Grupo(
                    identificador=str(identificador),
                    nombre=membresia.get("display"),
                )
            )
        return tuple(grupos)

    def _Consultar(self, ruta):
        """Ejecuta un GET de SCIM y deja constancia de la lectura.

        Args:
            ruta (str): ruta de la API a consultar.

        Returns:
            dict: respuesta JSON del workspace.

        Raises:
            ErrorTransporteDatabricks: si el CLI falla o la respuesta no es
                JSON válido.
        """
        self.consultas_ejecutadas.append(ruta)
        return EjecutarComandoCli(["get", ruta], self.perfil)


class ProveedorIdentidadServicePrincipalScimCli(ProveedorIdentidadLlamante):
    """Proveedor real para el caso "la app ejecutada con su propia identidad".

    Resuelve por SCIM el service principal indicado (por App Id o por nombre) y
    lo entrega como contexto del llamante, que es lo que ocurre cuando una
    Databricks App corre con su identidad de service principal en lugar del
    token on-behalf-of de un usuario (spec `caller-identity` - "Llamante
    service principal con App Id").

    Attributes:
        proveedor_base (ProveedorIdentidadScimCli): proveedor que consulta SCIM.
        app_id (str | None): App Id del service principal a resolver.
        nombre (str | None): nombre del service principal a resolver.
    """

    def __init__(self, app_id=None, nombre=None, perfil=PERFIL_CLI_INTEGRAL,
                 proveedor_base=None):
        """Inicializa el proveedor con el criterio de búsqueda del SP.

        Args:
            app_id (str | None): App Id del service principal.
            nombre (str | None): nombre para mostrar del service principal.
            perfil (str): perfil CLI autenticado.
            proveedor_base (ProveedorIdentidadScimCli | None): proveedor que
                hace las consultas SCIM; si es None se construye uno.

        Raises:
            ValueError: si no se indica ni `app_id` ni `nombre`.
        """
        if not app_id and not nombre:
            raise ValueError(
                "El proveedor de service principal requiere un App Id o un "
                "nombre para resolver la identidad."
            )
        self.proveedor_base = proveedor_base or ProveedorIdentidadScimCli(
            perfil=perfil
        )
        self.app_id = app_id
        self.nombre = nombre

    def ObtenerContexto(self):
        """Resuelve el contexto del service principal indicado.

        Returns:
            ContextoLlamante | None: contexto de tipo `service_principal` con
                su App Id y sus grupos; None si el workspace no lo tiene
                registrado (el servicio lo tratará como identidad no resuelta).

        Raises:
            ErrorTransporteDatabricks: si falla el transporte CLI.
        """
        return self.proveedor_base.ObtenerContextoDeServicePrincipal(
            app_id=self.app_id, nombre=self.nombre
        )


def DescubrirAppConSuServicePrincipal(perfil=PERFIL_CLI_INTEGRAL):
    """Descubre una Databricks App del workspace y su service principal.

    El identificador NO se hardcodea (regla del proyecto): se consulta la Apps
    API y se toma la primera app que declare el client id de su service
    principal, que es el App Id con el que Unity Catalog reporta los
    otorgamientos de la app.

    Args:
        perfil (str): perfil CLI autenticado.

    Returns:
        dict | None: datos de la app (`nombre`, `app_id`,
            `nombre_service_principal`), o None si el workspace no tiene apps.

    Raises:
        ErrorTransporteDatabricks: si falla el transporte CLI.
    """
    respuesta = EjecutarComandoCli(["get", RUTA_API_APPS], perfil)
    for app in respuesta.get("apps") or ():
        app_id = app.get("service_principal_client_id")
        if not app_id:
            continue
        return {
            "nombre": app.get("name"),
            "app_id": app_id,
            "nombre_service_principal": app.get("service_principal_name"),
        }
    return None
