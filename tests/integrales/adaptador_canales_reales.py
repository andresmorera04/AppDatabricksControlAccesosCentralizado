"""Adaptador de pruebas integrales: canales reales de SOLO LECTURA vía CLI.

Infraestructura EXCLUSIVA de la capa de pruebas integrales (marker `free`,
tarea 5.2 del change `auth-caller-obo`): implementa el contrato `Canal` de
producción contra el workspace real, pero **únicamente la lectura de
otorgamientos vigentes**, que es lo que este change necesita para resolver los
privilegios efectivos del llamante:

- Plano de datos (`CanalDatosRealLectura`): `SHOW GRANT ON <securable>`
  ejecutado por la Statement Execution API (reutiliza `SesionSqlDatabricks` de
  `adaptador_sql_databricks.py`).
- Plano de control (`CanalControlRealLectura`): `GET /api/2.0/permissions/...`
  con los tipos reales confirmados contra el workspace: `sql/warehouses`,
  `apps`, `serverless-compute`, `clusters` y `authorization/tokens`.

**`Otorgar` y `Revocar` quedan SIN IMPLEMENTACIÓN en este change** (spec
`caller-privilege-resolution` - "La resolución de este change es de solo
lectura"): lanzan `NotImplementedError` de modo que ninguna escritura pueda
llegar al workspace por accidente, y las pruebas lo verifican. Las
implementaciones reales de escritura llegan en C4 (`grants-catalog-schema`).

No se instala nada: el transporte es el CLI de Databricks ya autenticado con el
perfil del workspace (regla "Prohibición de instalación por la IA"). En
producción la app usará la SDK/REST con el token on-behalf-of del llamante; el
contrato consumido por el `ResolutorPrivilegiosEfectivos` es exactamente el
mismo, por eso estas clases sirven para probarlo contra datos reales.

Convención de nombres del proyecto: infraestructura de pruebas con el mismo
estándar (clases y funciones en PascalCase, constantes en MAYÚSCULAS, SQL en
mayúsculas, comentarios en español).
"""

import re
from dataclasses import dataclass
from typing import Optional

from control_accesos.canales.contratos import CanalControl, CanalDatos
from control_accesos.canales.errores import ErrorCanal
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, Principal
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio

from adaptador_sql_databricks import (
    PERFIL_CLI_INTEGRAL,
    EjecutarComandoCli,
)

# Rutas de la API del plano de control.
RUTA_API_PERMISOS = "/api/2.0/permissions"
RUTA_API_APPS = "/api/2.0/apps"
RUTA_API_SERVERLESS_COMPUTE = "/api/2.0/serverless-compute"
RUTA_API_CLUSTERS = "/api/2.0/clusters/list"

# Tipo de objeto de la Permissions API por tipo de objeto del dominio. Se
# declara como dato (no como if dispersos) y refleja los tipos REALES
# confirmados contra el workspace `andresFree`.
RUTA_PERMISOS_POR_TIPO_OBJETO = {
    TipoObjeto.SQL_WAREHOUSE: "sql/warehouses",
    TipoObjeto.DATABRICK_APP: "apps",
    TipoObjeto.COMPUTO_SERVERLESS: "serverless-compute",
    TipoObjeto.COMPUTO_CLASICO: "clusters",
}

# El uso de personal access token no tiene identificador de objeto: su ACL es
# única en el workspace (decisión D4 del README).
RUTA_PERMISOS_TOKENS = "authorization/tokens"

# Palabra clave SQL de Unity Catalog por tipo de objeto del plano de datos.
# La construcción real de instrucciones GRANT/REVOKE llega en C4; aquí solo se
# necesita la forma de lectura (`SHOW GRANT`).
PALABRA_CLAVE_SQL_POR_TIPO_OBJETO = {
    TipoObjeto.CATALOGO: "CATALOG",
    TipoObjeto.ESQUEMA: "SCHEMA",
    TipoObjeto.TABLA_DELTA: "TABLE",
    TipoObjeto.STREAMING_TABLE: "TABLE",
    TipoObjeto.VISTA_MATERIALIZADA: "TABLE",
    TipoObjeto.VISTA_SQL: "TABLE",
    TipoObjeto.VOLUMEN: "VOLUME",
    TipoObjeto.MODELO_ML: "MODEL",
    TipoObjeto.EXTERNAL_LOCATION: "EXTERNAL LOCATION",
    TipoObjeto.CONNECTION: "CONNECTION",
}

# Plantilla de la sentencia de lectura del plano de datos (SQL en mayúsculas).
SENTENCIA_SHOW_GRANT = "SHOW GRANT ON {palabra_clave} {identificador}"

# Campos con los que la Permissions API identifica al otorgatario, y el tipo de
# principal del dominio que corresponde a cada uno.
CAMPOS_PRINCIPAL_DE_ACL = (
    ("user_name", TipoPrincipal.USUARIO),
    ("group_name", TipoPrincipal.GRUPO),
    ("service_principal_name", TipoPrincipal.SERVICE_PRINCIPAL),
)

# Columnas que devuelve `SHOW GRANT` en Unity Catalog.
COLUMNA_PRINCIPAL = 0
COLUMNA_TIPO_PRIVILEGIO = 1

# Forma del App Id con la que Unity Catalog reporta a un service principal en
# el plano de datos (allí no hay campo de tipo: solo la referencia textual).
EXPRESION_APP_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Referencia con forma de correo: usuario del workspace.
EXPRESION_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Texto del error de las operaciones de escritura, fuera del alcance de C3.
MENSAJE_SIN_ESCRITURA = (
    "El change `auth-caller-obo` es de solo lectura: este adaptador integral "
    "no otorga ni revoca permisos en el workspace. Las operaciones de "
    "escritura reales llegan en C4 (`grants-catalog-schema`)."
)


@dataclass(frozen=True)
class OtorgamientoVigenteReal(ItemGrant):
    """Grant vigente reportado por el workspace, con el origen que informa.

    Extiende el `ItemGrant` del dominio con los dos datos que el
    `ResolutorPrivilegiosEfectivos` lee por duck-typing (`origen` y
    `heredado_de`), de modo que la herencia reportada por la Permissions API
    quede clasificada como `heredado` y la ausencia de informe (plano de datos)
    como `no_determinado`, sin reimplementar la jerarquía (spec
    `caller-privilege-resolution` - "Herencia de otorgamientos reportada por el
    sistema").

    Attributes:
        origen (str | None): `directo` o `heredado` cuando el canal lo informa;
            None cuando el canal no declara el origen.
        heredado_de (str | None): securable padre del que viene el
            otorgamiento, si el canal lo reporta.
    """

    origen: Optional[str] = None
    heredado_de: Optional[str] = None


class CanalDatosRealLectura(CanalDatos):
    """Canal SQL real de solo lectura: `SHOW GRANT` sobre Unity Catalog.

    Attributes:
        consultas_ejecutadas (list[str]): sentencias SQL ejecutadas, en orden;
            permite a las pruebas verificar que la resolución es de solo
            lectura y cuántas consultas hace por objeto.
    """

    def __init__(self, sesion_sql):
        """Inicializa el canal con la sesión SQL real del workspace.

        Args:
            sesion_sql (SesionSqlDatabricks): adaptador que ejecuta sentencias
                contra el SQL warehouse del perfil CLI.
        """
        self._sesion_sql = sesion_sql
        self.consultas_ejecutadas = []

    def ListarGrantsVigentes(self, objeto):
        """Lista los privilegios vigentes del objeto vía `SHOW GRANT`.

        Args:
            objeto (ObjetoSecurable): objeto del plano de datos a consultar.

        Returns:
            list[OtorgamientoVigenteReal]: otorgamientos vigentes tal como los
                reporta Unity Catalog; lista vacía cuando el objeto no tiene
                ninguno (vacío explícito, distinguible de un fallo).

        Raises:
            ErrorCanal: si el tipo de objeto no tiene palabra clave SQL
                declarada.
            ErrorTransporteDatabricks: si la sentencia falla en el workspace
                (objeto inexistente, sin permisos de lectura, etc.); el
                resolutor de producción la traduce a `fallido`.
        """
        sentencia = self._ConstruirShowGrant(objeto)
        self.consultas_ejecutadas.append(sentencia)
        filas = self._sesion_sql.EjecutarYLeer(sentencia)

        return [self._GrantDesdeFila(objeto, fila) for fila in filas]

    def EjecutarOtorgamiento(self, item):
        """Sin implementación: este change no escribe en el workspace.

        Args:
            item (ItemGrant): ítem que se intentaría otorgar.

        Raises:
            NotImplementedError: siempre; la escritura real llega en C4.
        """
        raise NotImplementedError(MENSAJE_SIN_ESCRITURA)

    def EjecutarRevocacion(self, item):
        """Sin implementación: este change no escribe en el workspace.

        Args:
            item (ItemGrant): ítem que se intentaría revocar.

        Raises:
            NotImplementedError: siempre; la escritura real llega en C4.
        """
        raise NotImplementedError(MENSAJE_SIN_ESCRITURA)

    def _ConstruirShowGrant(self, objeto):
        """Construye la sentencia `SHOW GRANT` del objeto.

        Args:
            objeto (ObjetoSecurable): objeto del plano de datos.

        Returns:
            str: sentencia SQL en mayúsculas con el identificador entre
                comillas invertidas (parte por parte, para respetar los nombres
                calificados como `catalogo.esquema`).

        Raises:
            ErrorCanal: si el tipo de objeto no está declarado en el mapa de
                palabras clave SQL.
        """
        palabra_clave = PALABRA_CLAVE_SQL_POR_TIPO_OBJETO.get(objeto.tipo)
        if palabra_clave is None:
            raise ErrorCanal(
                f"El tipo de objeto '{objeto.tipo.value}' no pertenece al "
                "plano de datos: no tiene sentencia SHOW GRANT."
            )

        return SENTENCIA_SHOW_GRANT.format(
            palabra_clave=palabra_clave,
            identificador=_IdentificadorSql(objeto.identificador),
        )

    def _GrantDesdeFila(self, objeto, fila):
        """Traduce una fila de `SHOW GRANT` a un otorgamiento vigente.

        Unity Catalog reporta el otorgatario solo como texto: el correo del
        usuario, el nombre del grupo o el App Id del service principal. El tipo
        se deduce de la forma de la referencia (regla declarada en este
        módulo); en producción (C4) la SDK entrega el tipo de principal.

        Args:
            objeto (ObjetoSecurable): objeto consultado.
            fila (list[str]): fila con columnas `Principal`, `ActionType`,
                `ObjectType`, `ObjectKey`.

        Returns:
            OtorgamientoVigenteReal: otorgamiento vigente con origen
                explícitamente no informado (`None`), porque `SHOW GRANT` no
                declara si el privilegio viene de un securable padre.
        """
        referencia = str(fila[COLUMNA_PRINCIPAL]).strip()
        privilegio = str(fila[COLUMNA_TIPO_PRIVILEGIO]).strip()

        return OtorgamientoVigenteReal(
            principal=Principal(
                identificador=referencia,
                tipo=InferirTipoPrincipal(referencia),
            ),
            privilegio=privilegio,
            objeto=objeto,
            origen=None,
            heredado_de=None,
        )


class CanalControlRealLectura(CanalControl):
    """Canal REST real de solo lectura: ACL de la Permissions API.

    Attributes:
        perfil (str): perfil CLI autenticado contra el workspace.
        consultas_ejecutadas (list[str]): rutas de permisos consultadas, en
            orden; permite verificar que la resolución es de solo lectura.
    """

    def __init__(self, perfil=PERFIL_CLI_INTEGRAL):
        """Inicializa el canal con el perfil CLI del workspace.

        Args:
            perfil (str): perfil CLI autenticado (por defecto, `andresFree`).
        """
        self.perfil = perfil
        self.consultas_ejecutadas = []

    def ListarGrantsVigentes(self, objeto):
        """Lista los permisos vigentes del objeto vía Permissions API.

        Args:
            objeto (ObjetoSecurable): objeto del plano de control a consultar.

        Returns:
            list[OtorgamientoVigenteReal]: un otorgamiento por nivel de permiso
                de cada otorgatario de la ACL, con su origen (directo o
                heredado) tal como lo informa el workspace; lista vacía cuando
                la ACL no tiene entradas.

        Raises:
            ErrorCanal: si el tipo de objeto no tiene ruta de permisos
                declarada.
            ErrorTransporteDatabricks: si el objeto no existe o el transporte
                falla; el resolutor de producción la traduce a `fallido`.
        """
        ruta = self._RutaDePermisos(objeto)
        self.consultas_ejecutadas.append(ruta)
        respuesta = EjecutarComandoCli(["get", ruta], self.perfil)

        grants = []
        for entrada in respuesta.get("access_control_list") or ():
            principal = _PrincipalDesdeEntradaAcl(entrada)
            if principal is None:
                # Entrada sin otorgatario identificable: se omite (no se
                # inventa un principal).
                continue
            for permiso in entrada.get("all_permissions") or ():
                grants.append(
                    OtorgamientoVigenteReal(
                        principal=principal,
                        privilegio=str(permiso.get("permission_level")).strip(),
                        objeto=objeto,
                        origen=_OrigenDesdePermiso(permiso),
                        heredado_de=_PadreDesdePermiso(permiso),
                    )
                )
        return grants

    def EjecutarOtorgamiento(self, item):
        """Sin implementación: este change no escribe en el workspace.

        Args:
            item (ItemGrant): ítem que se intentaría otorgar.

        Raises:
            NotImplementedError: siempre; la escritura real llega en C7/C8.
        """
        raise NotImplementedError(MENSAJE_SIN_ESCRITURA)

    def EjecutarRevocacion(self, item):
        """Sin implementación: este change no escribe en el workspace.

        Args:
            item (ItemGrant): ítem que se intentaría revocar.

        Raises:
            NotImplementedError: siempre; la escritura real llega en C7/C8.
        """
        raise NotImplementedError(MENSAJE_SIN_ESCRITURA)

    def _RutaDePermisos(self, objeto):
        """Construye la ruta de la Permissions API para el objeto.

        Args:
            objeto (ObjetoSecurable): objeto del plano de control.

        Returns:
            str: ruta completa, por ejemplo
                `/api/2.0/permissions/sql/warehouses/<id>`.

        Raises:
            ErrorCanal: si el tipo de objeto no pertenece al plano de control.
        """
        if objeto.tipo is TipoObjeto.USO_TOKEN:
            tipo_api = RUTA_PERMISOS_TOKENS
            return f"{RUTA_API_PERMISOS}/{tipo_api}"

        tipo_api = RUTA_PERMISOS_POR_TIPO_OBJETO.get(objeto.tipo)
        if tipo_api is None:
            raise ErrorCanal(
                f"El tipo de objeto '{objeto.tipo.value}' no pertenece al "
                "plano de control: no tiene ruta en la Permissions API."
            )
        return f"{RUTA_API_PERMISOS}/{tipo_api}/{objeto.identificador}"


def InferirTipoPrincipal(referencia):
    """Deduce el tipo de principal desde la forma de la referencia textual.

    Regla declarada de la capa integral (el plano de datos solo entrega texto):

    - forma de App Id (UUID) -> `service_principal`;
    - forma de correo -> `usuario`;
    - cualquier otro texto -> `grupo` (Unity Catalog reporta los grupos por su
      nombre).

    Args:
        referencia (str): texto del otorgatario reportado por el workspace.

    Returns:
        TipoPrincipal: tipo deducido.
    """
    if EXPRESION_APP_ID.match(referencia):
        return TipoPrincipal.SERVICE_PRINCIPAL
    if EXPRESION_CORREO.match(referencia):
        return TipoPrincipal.USUARIO
    return TipoPrincipal.GRUPO


def DescubrirApp(perfil=PERFIL_CLI_INTEGRAL):
    """Descubre el nombre de una Databricks App del workspace.

    Args:
        perfil (str): perfil CLI autenticado.

    Returns:
        str | None: nombre de la primera app, o None si el workspace no tiene.
    """
    respuesta = EjecutarComandoCli(["get", RUTA_API_APPS], perfil)
    for app in respuesta.get("apps") or ():
        if app.get("name"):
            return str(app["name"])
    return None


def DescubrirServerlessCompute(perfil=PERFIL_CLI_INTEGRAL):
    """Descubre el id de un serverless compute object del workspace.

    Args:
        perfil (str): perfil CLI autenticado.

    Returns:
        str | None: `serverless_compute_id` del primero disponible, o None si
            el feature no está activado en el workspace.
    """
    respuesta = EjecutarComandoCli(["get", RUTA_API_SERVERLESS_COMPUTE], perfil)
    for computo in respuesta.get("serverless_computes") or ():
        if computo.get("serverless_compute_id"):
            return str(computo["serverless_compute_id"])
    return None


def DescubrirCluster(perfil=PERFIL_CLI_INTEGRAL):
    """Descubre el id de un cluster clásico del workspace.

    En Free Edition no existe cómputo clásico, por lo que devuelve None y la
    prueba correspondiente se salta de forma explícita; contra `andresAzureDev`
    (marker `azure_approval`) devuelve el primer cluster.

    Args:
        perfil (str): perfil CLI autenticado.

    Returns:
        str | None: `cluster_id` del primero disponible, o None si no hay.
    """
    respuesta = EjecutarComandoCli(["get", RUTA_API_CLUSTERS], perfil)
    for cluster in respuesta.get("clusters") or ():
        if cluster.get("cluster_id"):
            return str(cluster["cluster_id"])
    return None


def _IdentificadorSql(identificador):
    """Encierra cada parte del identificador entre comillas invertidas.

    Args:
        identificador (str): identificador del securable, simple (`control`) o
            calificado (`control.finance`).

    Returns:
        str: identificador seguro para la sentencia SQL.
    """
    partes = [parte for parte in str(identificador).split(".") if parte]
    return ".".join(f"`{parte}`" for parte in partes)


def _PrincipalDesdeEntradaAcl(entrada):
    """Construye el principal del dominio desde una entrada de la ACL.

    Args:
        entrada (dict): entrada de `access_control_list`, con uno de los campos
            `user_name`, `group_name` o `service_principal_name`.

    Returns:
        Principal | None: principal con su tipo real, o None si la entrada no
            identifica a ningún otorgatario.
    """
    for campo, tipo in CAMPOS_PRINCIPAL_DE_ACL:
        referencia = entrada.get(campo)
        if referencia:
            return Principal(
                identificador=str(referencia).strip(), tipo=tipo
            )
    return None


def _OrigenDesdePermiso(permiso):
    """Devuelve el origen del permiso según lo informa la Permissions API.

    Args:
        permiso (dict): entrada de `all_permissions` con el flag `inherited`.

    Returns:
        str: `heredado` cuando la API marca el permiso como heredado, `directo`
            en caso contrario.
    """
    if permiso.get("inherited"):
        return OrigenPrivilegio.HEREDADO.value
    return OrigenPrivilegio.DIRECTO.value


def _PadreDesdePermiso(permiso):
    """Devuelve el securable padre del que se hereda el permiso.

    Args:
        permiso (dict): entrada de `all_permissions`, con la lista opcional
            `inherited_from_object`.

    Returns:
        str | None: el primer securable padre reportado, o None si el permiso
            no es heredado.
    """
    padres = permiso.get("inherited_from_object") or ()
    if not padres:
        return None
    return str(padres[0])
