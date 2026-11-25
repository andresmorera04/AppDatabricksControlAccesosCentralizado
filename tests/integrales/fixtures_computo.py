"""Fábrica de fixtures autocontenidas de las integrales de cómputo
(capability `compute-grants`, design D8).

Proporciona, por perfil de workspace, la resolución de los objetos existentes
que el humano aprobó para las pruebas (nunca se crean ni se eliminan warehouses,
clusters, serverless compute objects ni otorgatarios) y los otorgatarios de
pruebas como datos de la fixture —fuera del código del canal, regla No HardCoded—,
además de la instantánea y restauración de la ACL que garantiza que ninguna
prueba deje estado residual.

Este módulo vive en la capa de pruebas integrales, pero sigue el estándar del
proyecto (clases y funciones PascalCase, constantes MAYÚSCULAS, comentarios en
español). No conecta con ningún workspace al importarse: el SDK se importa de
forma perezosa dentro de las funciones de descubrimiento, de modo que las suites
de aceptación puedan importar la fábrica sin conexión externa.
"""

from contextlib import contextmanager

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.cliente_permisos_sdk import ClientePermisosSdk
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import Principal

# Perfiles CLI de los workspaces de pruebas (README D5). `andresFree` es el
# entorno primario; `andresAzureDev` solo para lo imposible en Free (cómputo
# clásico) y con el marker `azure_approval` pre-aprobado por el humano.
PERFIL_FREE = "andresFree"
PERFIL_AZURE = "andresAzureDev"

# Objetos existentes aprobados por el humano (design D8): el SQL warehouse de
# Free y el cluster clásico creado para las pruebas en Azure. Sus ids se
# resuelven por API en la fixture y no se hardcodean.
NOMBRE_WAREHOUSE_FREE = "Serverless Starter Warehouse"
NOMBRE_CLUSTER_AZURE = "ComputoPruebasGenerales"

# Otorgatarios de pruebas aprobados por el humano (design D8), como datos de la
# fixture. En el plano de control el service principal se identifica por su
# App Id (application_id) y el grupo por su nombre, tal como la Permissions API
# los expone en `service_principal_name` y `group_name`.
APP_ID_SP_FREE = "1738687d-4838-49ef-83fd-521f935a9ec2"
NOMBRE_GRUPO_FREE = "Desarrollador"
APP_ID_SP_AZURE = "e59aa9cf-ddf5-453a-9abf-98c3b72ab01c"
NOMBRE_GRUPO_AZURE = "desarrollo_regional"

# Perfil que ejecuta cada tipo de objeto de cómputo (decisiones del humano,
# design D8): Free Edition no dispone de cómputo clásico, por lo que los
# clusters viven en `andresAzureDev`.
PERFIL_POR_TIPO_OBJETO = {
    TipoObjeto.COMPUTO_CLASICO: PERFIL_AZURE,
    TipoObjeto.COMPUTO_SERVERLESS: PERFIL_FREE,
    TipoObjeto.SQL_WAREHOUSE: PERFIL_FREE,
}

# Otorgatarios de prueba por perfil: un service principal y un grupo por
# workspace, para ejercitar la cardinalidad N a 1 con principals reales de
# distinto tipo sobre el mismo objeto.
OTORGATARIOS_POR_PERFIL = {
    PERFIL_FREE: (
        Principal(identificador=APP_ID_SP_FREE, tipo=TipoPrincipal.SERVICE_PRINCIPAL),
        Principal(identificador=NOMBRE_GRUPO_FREE, tipo=TipoPrincipal.GRUPO),
    ),
    PERFIL_AZURE: (
        Principal(identificador=APP_ID_SP_AZURE, tipo=TipoPrincipal.SERVICE_PRINCIPAL),
        Principal(identificador=NOMBRE_GRUPO_AZURE, tipo=TipoPrincipal.GRUPO),
    ),
}

# Identificador obviamente inexistente para los casos de "objeto inexistente".
IDENTIFICADOR_INEXISTENTE = "no-existe-computo-pruebas"

# Ejecutor restringido para la integral de permiso denegado (decisión del humano):
# un service principal sin privilegios administrativos que ejecuta el grant
# autenticado como sí mismo, de modo que el workspace responde `PERMISSION_DENIED`
# de forma real. El `client_id` no es secreto (es el mismo App Id ya declarado);
# el secret se lee de la variable de entorno y nunca vive en el código.
APP_ID_SP_EJECUTOR_RESTRINGIDO = "1738687d-4838-49ef-83fd-521f935a9ec2"
VARIABLE_SECRET_EJECUTOR = "CONTROL_ACCESOS_SP_CLIENT_SECRET"


def HostDePerfil(perfil):
    """Devuelve el host del workspace de un perfil CLI, sin credenciales nuevas.

    Args:
        perfil (str): perfil CLI autenticado del workspace.

    Returns:
        str: host del workspace (por ejemplo
            `https://dbc-xxxx.cloud.databricks.com`).
    """
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=perfil).config.host


def CanalEjecutorRestringido(client_id, client_secret):
    """Construye el canal autenticado como el service principal restringido.

    Usa OAuth M2M (client credentials) contra el host de `andresFree`, de modo
    que las operaciones se ejecuten con la identidad de ese service principal
    —no como el administrador del perfil CLI— y el permiso denegado sea real.

    Args:
        client_id (str): App Id del service principal ejecutor.
        client_secret (str): secret del service principal ejecutor.

    Returns:
        CanalControlComputo: canal real con el adaptador SDK autenticado como
            el service principal.
    """
    from databricks.sdk import WorkspaceClient

    cliente = WorkspaceClient(
        host=HostDePerfil(PERFIL_FREE),
        client_id=client_id,
        client_secret=client_secret,
    )
    return CanalControlComputo(ClientePermisosSdk(cliente))


def PerfilDeTipo(tipo):
    """Devuelve el perfil que ejecuta las pruebas del tipo de cómputo.

    Args:
        tipo (TipoObjeto): tipo de objeto de cómputo.

    Returns:
        str: perfil CLI del workspace (`andresFree` o `andresAzureDev`).
    """
    return PERFIL_POR_TIPO_OBJETO[tipo]


def OtorgatariosDePerfil(perfil):
    """Devuelve los otorgatarios de prueba del perfil (SP y grupo).

    Args:
        perfil (str): perfil CLI del workspace.

    Returns:
        tuple[Principal, ...]: otorgatarios aprobados por el humano.
    """
    return OTORGATARIOS_POR_PERFIL[perfil]


def CanalParaPerfil(perfil):
    """Construye el canal real de cómputo sobre el SDK del perfil dado.

    Args:
        perfil (str): perfil CLI autenticado del workspace.

    Returns:
        CanalControlComputo: canal real con el adaptador SDK inyectado.
    """
    return CanalControlComputo(ClientePermisosSdk(_WorkspaceClient(perfil)))


def RecursoDeTipo(tipo):
    """Devuelve el recurso de la Permissions API del tipo (design D2).

    Args:
        tipo (TipoObjeto): tipo de objeto de cómputo.

    Returns:
        str: recurso de la Permissions API (`clusters`, `serverless-compute`
            o `sql/warehouses`).
    """
    return CanalControlComputo.RecursoDeTipo(tipo)


def DescubrirWarehouseId(perfil):
    """Resuelve por API el id del SQL warehouse existente del workspace.

    Prefiere el warehouse aprobado por el humano (`Serverless Starter
    Warehouse`); si no estuviera, usa el primero disponible.

    Args:
        perfil (str): perfil CLI del workspace.

    Returns:
        str | None: id del warehouse, o None si el workspace no tiene ninguno.
    """
    cliente = _WorkspaceClient(perfil)
    warehouses = list(cliente.warehouses.list())
    if not warehouses:
        return None
    preferido = next(
        (wh.id for wh in warehouses if wh.name == NOMBRE_WAREHOUSE_FREE), None
    )
    return preferido or warehouses[0].id


def DescubrirServerlessDefaultId(perfil):
    """Resuelve por API el id del serverless compute object *default* del workspace.

    Args:
        perfil (str): perfil CLI del workspace.

    Returns:
        str | None: id del objeto *default* (interactivo), o None si no hay.
    """
    cliente = _WorkspaceClient(perfil)
    objetos = list(cliente.serverless_compute_service.list())
    if not objetos:
        return None
    default = next(
        (objeto.serverless_compute_id for objeto in objetos if objeto.is_default), None
    )
    return default or objetos[0].serverless_compute_id


def DescubrirClusterPorNombre(perfil, nombre):
    """Resuelve por API el id de un cluster clásico por su nombre.

    Args:
        perfil (str): perfil CLI del workspace.
        nombre (str): nombre del cluster a localizar.

    Returns:
        str | None: id del cluster, o None si no existe con ese nombre.
    """
    cliente = _WorkspaceClient(perfil)
    for cluster in cliente.clusters.list():
        if cluster.cluster_name == nombre:
            return cluster.cluster_id
    return None


def _WorkspaceClient(perfil):
    """Importa perezosamente y devuelve el `WorkspaceClient` del perfil."""
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=perfil)


@contextmanager
def ACLRestaurada(canal, recurso, identificador):
    """Instantánea y restauración de la ACL alrededor de una prueba.

    Guarda la ACL directa original del objeto y la repone en `finally`, de modo
    que cualquier permiso otorgado durante la prueba quede revocado y el objeto
    conserve su estado previo (design D8). El canal recibe el adaptador SDK
    (`ClientePermisosSdk`) como transporte, que es quien posee los puertos.

    Args:
        canal (CanalControlComputo): canal real cuyo transporte es el adaptador.
        recurso (str): recurso de la Permissions API del objeto.
        identificador (str): id del objeto.

    Yields:
        tuple[EntradaAcl, ...]: ACL original, por si la prueba la inspecciona.
    """
    adaptador = canal.transporte
    original = adaptador.LeerAcl(recurso, identificador)
    try:
        yield original
    finally:
        adaptador.EscribirAcl(recurso, identificador, list(original))
