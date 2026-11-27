"""Spike desplegable del gate de viabilidad OBO (C9 `web-ui-minimalista`).

ENTRADA MÍNIMA DE SPIKE (tarea 2.4, design.md D4): esta versión de `app.py`
existe SOLO para validar el gate de viabilidad desplegada en `andresFree` y
será sustituida por la entrada delgada de producción en la tarea 6.4.

Qué valida (24 sondas independientes, cada una con `try/except`):

- identidad: resolución OBO del llamante con el código de producción
  (`ProveedorIdentidadDatabricksApp` + `ServicioIdentidadLlamante`);
- descubrimiento SCIM: listados de usuarios, grupos y service principals
  (mide si los scopes por defecto `iam.*` los permiten);
- descubrimiento Unity Catalog: catálogos, esquemas, tablas y conexiones vía
  SDK (scopes `catalog.*`), más las rutas SQL alternativas de volúmenes,
  modelos y external locations (scope `sql`);
- descubrimiento del plano de control: warehouses (`sql`), clusters (sin
  scope documentado: se mide) y apps (`apps`);
- SQL/Spark remoto: sesión Databricks Connect construida con la MISMA
  credencial OBO (`SELECT 1`, `SHOW GRANTS` sobre el catálogo configurado);
- Permissions API: lectura de ACL de warehouse, cluster, app y del singleton
  `authorization/tokens`, y una escritura controlada por sonda: el PUT
  re-aplica la instantánea leída (restauración inmediata por construcción).

Bucle del gate (la creación de la App, los scopes y el consentimiento son
manuales, design.md D4 - "se configuran fuera del código"):

1. el humano crea la App con autorización de usuario y los scopes acordados,
   y despliega este directorio;
2. el humano la visita en el navegador, consiente los scopes, pulsa
   "Ejecutar verificaciones" y descarga la evidencia JSON;
3. el humano guarda la evidencia en
   `results/web-ui-minimalista/spike_obo_evidencia.json`;
4. `tests/integrales/test_ui_spike_obo_andresfree.py` verifica el gate y
   produce el veredicto go/no-go.

Reglas de seguridad respetadas incluso en el spike:

- todas las sondas usan la credencial OBO del llamante (header cuyo nombre
  declara `config/app_properties.json`); NINGUNA usa el token del service
  principal de la App (`DATABRICKS_TOKEN` del entorno): no hay fallback
  elevado (design.md D3);
- la evidencia no incluye tokens ni headers: solo nombres, recuentos y
  descripciones de error truncadas (design.md D11);
- nada hardcodeado: catálogo, nombre del header y variables de entorno se
  leen de la configuración única del proyecto.
"""

import json
import os
from datetime import datetime, timezone

import streamlit as st

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_control_computo import (
    RECURSO_PERMISOS_POR_TIPO_OBJETO,
)
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.configuracion.configuracion_app import (
    ATRIBUTO_CATALOGO,
    ConfiguracionApp,
)
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.fabrica_contexto import CrearSesionSqlRemota
from control_accesos.ui.fabrica_contexto_broker import FabricaContextoBroker
from control_accesos.ui.proveedor_identidad_app import (
    AccederEncabezadosStreamlit,
    CrearClienteWorkspace,
    LeerHostWorkspace,
    LeerTokenObo,
    ProveedorIdentidadDatabricksApp,
)

# Identificación de la página y de la evidencia.
TITULO_PAGINA = "Control de Accesos — Spike del gate OBO (D4)"
ETIQUETA_BOTON_EJECUTAR = "Ejecutar verificaciones del gate D4"
IDENTIFICADOR_SPIKE = "spike-obo-c9"
NOMBRE_ARCHIVO_EVIDENCIA = "spike_obo_evidencia.json"
RUTA_RELATIVA_EVIDENCIA = "results/web-ui-minimalista/spike_obo_evidencia.json"

# Clave del estado de sesión donde vive la evidencia (sin credenciales: solo
# resultados de sondas, design.md D9/D11).
CLAVE_ESTADO_EVIDENCIA = "evidencia_gate_d4"

# Estados posibles de una sonda.
ESTADO_OK = "ok"
ESTADO_FALLO = "fallo"
ESTADO_NO_DISPONIBLE = "no_disponible"

# Nombres de las 24 sondas del gate (la prueba integral los consume).
SONDA_IDENTIDAD_OBO = "identidad_obo"
SONDA_SCIM_USUARIOS = "scim_usuarios"
SONDA_SCIM_GRUPOS = "scim_grupos"
SONDA_SCIM_SERVICE_PRINCIPALS = "scim_service_principals"
SONDA_UC_CATALOGOS = "uc_catalogos"
SONDA_UC_ESQUEMAS = "uc_esquemas"
SONDA_UC_TABLAS = "uc_tablas"
SONDA_UC_CONEXIONES = "uc_conexiones"
SONDA_SQL_WAREHOUSES = "sql_warehouses"
SONDA_COMPUTO_CLUSTERS = "computo_clusters"
SONDA_APPS_LISTA = "apps_lista"
SONDA_SQL_SELECT_UNO = "sql_select_uno"
SONDA_SQL_SHOW_GRANTS = "sql_show_grants"
SONDA_SQL_SHOW_VOLUMENES = "sql_show_volumes"
SONDA_SQL_SHOW_MODELOS = "sql_show_models"
SONDA_SQL_SHOW_EXTERNAL_LOCATIONS = "sql_show_external_locations"
SONDA_ACL_LECTURA_WAREHOUSE = "acl_lectura_warehouse"
SONDA_ACL_LECTURA_CLUSTER = "acl_lectura_cluster"
SONDA_ACL_LECTURA_APP = "acl_lectura_app"
SONDA_ACL_LECTURA_TOKENS = "acl_lectura_tokens"
SONDA_ACL_ESCRITURA_WAREHOUSE = "acl_escritura_warehouse_restaurada"
SONDA_ACL_ESCRITURA_CLUSTER = "acl_escritura_cluster_restaurada"
SONDA_ACL_ESCRITURA_APP = "acl_escritura_app_restaurada"
SONDA_ACL_ESCRITURA_TOKENS = "acl_escritura_tokens_restaurada"

# Nombres de las sondas SQL: si la sesión Connect no se puede establecer,
# todas fallan con el mismo detalle (sin sesión no hay plano SQL).
SONDAS_SQL = (
    SONDA_SQL_SELECT_UNO,
    SONDA_SQL_SHOW_GRANTS,
    SONDA_SQL_SHOW_VOLUMENES,
    SONDA_SQL_SHOW_MODELOS,
    SONDA_SQL_SHOW_EXTERNAL_LOCATIONS,
)

# Identificación del spike broker y de su evidencia (change
# `app-broker-identidad-ejecucion`): evidencia separada de la del gate OBO de
# C9, porque valida la ejecución con la identidad del service principal.
IDENTIFICADOR_SPIKE_BROKER = "spike-broker-app"
NOMBRE_ARCHIVO_EVIDENCIA_BROKER = "broker_evidencia.json"
RUTA_RELATIVA_EVIDENCIA_BROKER = (
    "results/app-broker-identidad-ejecucion/broker_evidencia.json"
)
CLAVE_ESTADO_EVIDENCIA_BROKER = "evidencia_gate_broker"
ETIQUETA_BOTON_EJECUTAR_BROKER = "Ejecutar verificaciones del gate broker (SP)"

# Nombres de las 11 sondas broker (design.md D6): con la identidad del SP se
# listan por SCIM los principals y los clusters, se lee y escribe (restaurada)
# la ACL de warehouse/clusters/tokens, y se resuelven los privilegios efectivos
# del llamante leyendo la ACL con el SP.
SONDA_BROKER_SCIM_USUARIOS = "broker_scim_usuarios"
SONDA_BROKER_SCIM_GRUPOS = "broker_scim_grupos"
SONDA_BROKER_SCIM_SERVICE_PRINCIPALS = "broker_scim_service_principals"
SONDA_BROKER_CLUSTERS = "broker_clusters"
SONDA_BROKER_SERVERLESS = "broker_serverless"
SONDA_BROKER_ACL_LECTURA_WAREHOUSE = "broker_acl_lectura_warehouse"
SONDA_BROKER_ACL_LECTURA_CLUSTER = "broker_acl_lectura_cluster"
SONDA_BROKER_ACL_LECTURA_SERVERLESS = "broker_acl_lectura_serverless"
SONDA_BROKER_ACL_LECTURA_TOKENS = "broker_acl_lectura_tokens"
SONDA_BROKER_ACL_ESCRITURA_WAREHOUSE = "broker_acl_escritura_warehouse_restaurada"
SONDA_BROKER_ACL_ESCRITURA_CLUSTER = "broker_acl_escritura_cluster_restaurada"
SONDA_BROKER_ACL_ESCRITURA_SERVERLESS = "broker_acl_escritura_serverless_restaurada"
SONDA_BROKER_ACL_ESCRITURA_TOKENS = "broker_acl_escritura_tokens_restaurada"
SONDA_BROKER_RESOLUCION_PRIVILEGIOS = "broker_resolucion_privilegios"

# Catálogos que no se eligen como objetivo de las sondas de descubrimiento
# (metadatos del sistema, no del gobierno de accesos).
CATALOGOS_SISTEMA = ("system", "hive_metastore")

# Esquema de metadatos que se evita como objetivo de las sondas.
ESQUEMA_METADATOS = "information_schema"

# Longitud máxima del detalle de error volcado en la evidencia: suficiente
# para diagnosticar el scope/código HTTP, corto para no filtrar contextos
# enormes (la redacción formal de secretos llega en la tarea 5.3, D11).
LONGITUD_MAXIMA_DETALLE = 400

# Recuento máximo de nombres propios incluidos en el detalle de un listado.
MAXIMO_NOMBRES_EN_DETALLE = 10


def _DescripcionError(excepcion):
    """Describe una excepción para la evidencia, sin exponer credenciales.

    Args:
        excepcion (BaseException): fallo capturado por una sonda.

    Returns:
        str: tipo de error, causa encadenada (si existe) y mensaje truncado.
    """
    partes = [type(excepcion).__name__]
    causa = excepcion.__cause__
    if causa is not None:
        partes.append(f"causa={type(causa).__name__}: {str(causa)[:120]}")
    mensaje = str(excepcion).strip()
    if mensaje:
        partes.append(mensaje[:LONGITUD_MAXIMA_DETALLE])
    return " | ".join(partes)


def _EjecutarSonda(nombre_sonda, funcion_sonda):
    """Ejecuta una sonda de forma aislada y devuelve su resultado.

    Args:
        nombre_sonda (str): nombre identificativo de la sonda.
        funcion_sonda (callable): función sin argumentos que devuelve
            ``(estado, detalle)``.

    Returns:
        dict: resultado con ``nombre``, ``estado`` y ``detalle``; cualquier
            excepción se traduce a estado ``fallo`` con su descripción.
    """
    try:
        estado, detalle = funcion_sonda()
    except Exception as excepcion:  # noqa: BLE001 - sonda aislada del gate
        estado = ESTADO_FALLO
        detalle = _DescripcionError(excepcion)
    return {"nombre": nombre_sonda, "estado": estado, "detalle": detalle}


def ProbarIdentidadObo(servicio_identidad):
    """Sonda de identidad: resolución OBO con el código de producción.

    Args:
        servicio_identidad (ServicioIdentidadLlamante): servicio de C3 con el
            proveedor real de la App ya cableado.

    Returns:
        tuple[str, str]: estado y detalle (usuario y recuento de grupos).
    """
    identidad = servicio_identidad.ObtenerIdentidadLlamante()
    if identidad is None:
        return (
            ESTADO_FALLO,
            "El ServicioIdentidadLlamante no resolvió la identidad del "
            "llamante (token inválido/expirado o SCIM inaccesible); el fallo "
            "quedó degradado y registrado por el servicio.",
        )
    return (
        ESTADO_OK,
        f"usuario={identidad.principal.identificador}; "
        f"grupos={len(identidad.grupos)}",
    )


def ProbarListado(iterable_listado, etiqueta):
    """Sonda genérica de listado: materializa el iterador del SDK.

    Args:
        iterable_listado (Iterable): iterador paginado del SDK.
        etiqueta (str): nombre legible de la familia listada.

    Returns:
        tuple[str, str]: estado ``ok`` y recuento (la denegación por scope
            llega como excepción y la traduce ``_EjecutarSonda``).
    """
    elementos = list(iterable_listado)
    return ESTADO_OK, f"{etiqueta}: {len(elementos)} elemento(s) listado(s)."


def ProbarCatalogos(cliente, recursos, configuracion):
    """Sonda de catálogos UC: lista y elige el objetivo de las sondas siguientes.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).
        configuracion (ConfiguracionApp): configuración del proyecto.

    Returns:
        tuple[str, str]: estado y detalle con los nombres descubiertos.
    """
    nombres = [catalogo.name for catalogo in cliente.catalogs.list()]
    catalogo_configurado = configuracion.ObtenerAtributo(ATRIBUTO_CATALOGO)
    if catalogo_configurado in nombres:
        objetivo = catalogo_configurado
    else:
        objetivo = next(
            (
                nombre
                for nombre in nombres
                if nombre not in CATALOGOS_SISTEMA
            ),
            nombres[0] if nombres else None,
        )
    recursos["catalogo"] = objetivo
    return (
        ESTADO_OK,
        f"catálogos={nombres[:MAXIMO_NOMBRES_EN_DETALLE]}; objetivo={objetivo}",
    )


def ProbarEsquemas(cliente, recursos):
    """Sonda de esquemas UC sobre el catálogo objetivo descubierto.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle con los esquemas descubiertos.
    """
    catalogo = recursos.get("catalogo")
    if not catalogo:
        return (
            ESTADO_FALLO,
            "La sonda uc_catalogos no dejó un catálogo objetivo; no se puede "
            "listar esquemas.",
        )
    nombres = [
        esquema.name
        for esquema in cliente.schemas.list(catalog_name=catalogo)
    ]
    objetivo = next(
        (nombre for nombre in nombres if nombre != ESQUEMA_METADATOS),
        nombres[0] if nombres else None,
    )
    recursos["esquema"] = objetivo
    return (
        ESTADO_OK,
        f"esquemas en '{catalogo}'="
        f"{nombres[:MAXIMO_NOMBRES_EN_DETALLE]}; objetivo={objetivo}",
    )


def ProbarTablas(cliente, recursos):
    """Sonda de tablas UC sobre el catálogo/esquema objetivo descubiertos.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle con el recuento de tablas.
    """
    catalogo = recursos.get("catalogo")
    esquema = recursos.get("esquema")
    if not catalogo or not esquema:
        return (
            ESTADO_FALLO,
            "Las sondas uc_catalogos/uc_esquemas no dejaron un objetivo; no "
            "se puede listar tablas.",
        )
    tablas = list(
        cliente.tables.list(catalog_name=catalogo, schema_name=esquema)
    )
    nombres = [tabla.name for tabla in tablas]
    return (
        ESTADO_OK,
        f"tablas en '{catalogo}.{esquema}': {len(tablas)}; "
        f"primeras={nombres[:MAXIMO_NOMBRES_EN_DETALLE]}",
    )


def ProbarWarehouses(cliente, recursos):
    """Sonda de SQL warehouses: lista y guarda el primero para las ACL.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle con el recuento y el id elegido.
    """
    warehouses = list(cliente.warehouses.list())
    if warehouses:
        recursos["warehouse_id"] = warehouses[0].id
    return (
        ESTADO_OK,
        f"warehouses: {len(warehouses)}; "
        f"objetivo={recursos.get('warehouse_id')}",
    )


def ProbarClusters(cliente, recursos):
    """Sonda de clusters clásicos: lista y guarda el primero para las ACL.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle (lista vacía es ``ok``: la llamada
            funcionó; la denegación por scope llega como excepción).
    """
    clusters = list(cliente.clusters.list())
    if clusters:
        recursos["cluster_id"] = clusters[0].cluster_id
    return (
        ESTADO_OK,
        f"clusters: {len(clusters)}; objetivo={recursos.get('cluster_id')}",
    )


def ProbarServerlessCompute(cliente, recursos):
    """Sonda de serverless compute: lista y guarda el primero para las ACL.

    Nota "cluster vs compute" (hallazgo 4.2): `clusters.list()` solo devuelve
    cómputo all-purpose; el cómputo serverless es el recurso `serverless-compute`
    de la Permissions API, listado por `serverless_compute_service.list()`. En
    `andresFree` los clusters clásicos son 0, por lo que esta es la superficie
    de cómputo relevante del workspace.

    Args:
        cliente (WorkspaceClient): cliente con la identidad del SP.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle con el recuento y el id elegido.
    """
    computos = list(cliente.serverless_compute_service.list())
    if computos:
        recursos["serverless_compute_id"] = computos[0].serverless_compute_id
    return (
        ESTADO_OK,
        f"serverless compute: {len(computos)}; "
        f"objetivo={recursos.get('serverless_compute_id')}",
    )


def ProbarApps(cliente, recursos):
    """Sonda de Databricks Apps: lista y guarda la primera para las ACL.

    Args:
        cliente (WorkspaceClient): cliente con credencial OBO.
        recursos (dict): estado compartido del descubrimiento (mutable).

    Returns:
        tuple[str, str]: estado y detalle con el recuento y el nombre elegido.
    """
    apps = list(cliente.apps.list())
    if apps:
        recursos["app_nombre"] = apps[0].name
    return (
        ESTADO_OK,
        f"apps: {len(apps)}; objetivo={recursos.get('app_nombre')}",
    )


def _ProbarSentencia(sesion_sql, sentencia, etiqueta):
    """Ejecuta una sentencia SQL remota y reporta su recuento de filas.

    Args:
        sesion_sql: sesión `SesionSqlRemota` (Statement Execution API) con
            credencial OBO; su `sql()` devuelve listas de textos por fila.
        sentencia (str): sentencia SQL a ejecutar.
        etiqueta (str): nombre legible de la operación.

    Returns:
        tuple[str, str]: estado ``ok`` y recuento de filas.
    """
    filas = sesion_sql.sql(sentencia)
    return ESTADO_OK, f"{etiqueta}: {len(filas)} fila(s)."


def _SondaSqlSobreEsquema(sesion_sql, recursos, plantilla, etiqueta):
    """Ejecuta una sentencia SQL que requiere catálogo y esquema descubiertos.

    Args:
        sesion_sql: sesión `SesionSqlRemota` con credencial OBO.
        recursos (dict): estado compartido del descubrimiento.
        plantilla (str): plantilla de la sentencia con ``{catalogo}`` y
            ``{esquema}``.
        etiqueta (str): nombre legible de la operación.

    Returns:
        tuple[str, str]: estado y detalle; ``no_disponible`` si las sondas UC
            no dejaron objetivo.
    """
    catalogo = recursos.get("catalogo")
    esquema = recursos.get("esquema")
    if not catalogo or not esquema:
        return (
            ESTADO_NO_DISPONIBLE,
            "Sin catálogo/esquema objetivo descubierto: la sonda SQL no pudo "
            "ejecutarse.",
        )
    sentencia = plantilla.format(catalogo=catalogo, esquema=esquema)
    return _ProbarSentencia(sesion_sql, sentencia, etiqueta)


def _EjecutarSondasSql(host, token, configuracion, recursos):
    """Ejecuta las sondas del plano SQL con la sesión remota OBO (F2).

    La sesión `SesionSqlRemota` (Statement Execution API) se construye una sola
    vez para las cinco sondas contra el warehouse serverless descubierto en
    ``ProbarWarehouses``. Si el warehouse no se descubrió (scope o cómputo no
    disponible) o la sesión falla, todas las sondas SQL se reportan en fallo
    con el mismo detalle.

    Args:
        host (str): host del workspace.
        token (str): token OBO del llamante.
        configuracion (ConfiguracionApp): configuración del proyecto.
        recursos (dict): estado compartido del descubrimiento.

    Returns:
        list[dict]: resultados de las cinco sondas SQL.
    """
    warehouse_id = recursos.get("warehouse_id")
    if not warehouse_id:
        detalle = (
            "Sin SQL warehouse serverless descubierto: la sonda SQL OBO no "
            "tiene contra quién ejecutarse (design.md D3)."
        )
        return [
            {"nombre": nombre, "estado": ESTADO_FALLO, "detalle": detalle}
            for nombre in SONDAS_SQL
        ]

    try:
        sesion_sql = CrearSesionSqlRemota(
            host=host, token=token, warehouse_id=warehouse_id
        )
    except Exception as excepcion:  # noqa: BLE001 - fallo del transporte SQL
        detalle = (
            "No se pudo establecer la sesión SQL remota (Statement Execution "
            f"API) con la credencial OBO: {_DescripcionError(excepcion)}"
        )
        return [
            {"nombre": nombre, "estado": ESTADO_FALLO, "detalle": detalle}
            for nombre in SONDAS_SQL
        ]

    catalogo_configurado = configuracion.ObtenerAtributo(ATRIBUTO_CATALOGO)
    return [
        _EjecutarSonda(
            SONDA_SQL_SELECT_UNO,
            lambda: _ProbarSentencia(
                sesion_sql, "SELECT 1", "SELECT 1 remoto"
            ),
        ),
        _EjecutarSonda(
            SONDA_SQL_SHOW_GRANTS,
            lambda: _ProbarSentencia(
                sesion_sql,
                f"SHOW GRANTS ON CATALOG `{catalogo_configurado}`",
                f"SHOW GRANTS ON CATALOG `{catalogo_configurado}`",
            ),
        ),
        _EjecutarSonda(
            SONDA_SQL_SHOW_VOLUMENES,
            lambda: _SondaSqlSobreEsquema(
                sesion_sql,
                recursos,
                "SHOW VOLUMES IN `{catalogo}`.`{esquema}`",
                "SHOW VOLUMES (ruta SQL de descubrimiento)",
            ),
        ),
        _EjecutarSonda(
            SONDA_SQL_SHOW_MODELOS,
            lambda: _SondaSqlSobreEsquema(
                sesion_sql,
                recursos,
                "SHOW MODELS IN `{catalogo}`.`{esquema}`",
                "SHOW MODELS (ruta SQL de descubrimiento)",
            ),
        ),
        _EjecutarSonda(
            SONDA_SQL_SHOW_EXTERNAL_LOCATIONS,
            lambda: _ProbarSentencia(
                sesion_sql,
                "SHOW EXTERNAL LOCATIONS",
                "SHOW EXTERNAL LOCATIONS (ruta SQL de descubrimiento)",
            ),
        ),
    ]


def ProbarAclLectura(transporte_permisos, tipo_objeto, identificador):
    """Sonda de lectura de ACL sobre la Permissions API con credencial OBO.

    Args:
        transporte_permisos (ClientePermisosSdk): adaptador de producción C7.
        tipo_objeto (TipoObjeto): tipo del plano de control a sondear.
        identificador (str | None): id del objeto; vacío para el singleton
            `USO_TOKEN`.

    Returns:
        tuple[str, str]: estado y detalle con el recuento de entradas
            directas; ``no_disponible`` si el workspace no expone el objeto.
    """
    recurso = RECURSO_PERMISOS_POR_TIPO_OBJETO[tipo_objeto]
    if tipo_objeto is not TipoObjeto.USO_TOKEN and not identificador:
        return (
            ESTADO_NO_DISPONIBLE,
            f"El workspace no expone un objeto '{recurso}' descubierto; la "
            f"lectura de ACL no pudo ejecutarse.",
        )
    entradas = transporte_permisos.LeerAcl(recurso, identificador or "")
    return (
        ESTADO_OK,
        f"ACL de '{recurso}' leída: {len(entradas)} entrada(s) directa(s).",
    )


def ProbarAclEscrituraRestaurada(transporte_permisos, tipo_objeto,
                                 identificador):
    """Sonda de escritura de ACL con instantánea y restauración inmediata.

    La escritura es un PUT que RE-APLICA la instantánea leída (misma ACL,
    mismo estado final): valida que el scope permite el verbo de escritura
    sobre la Permissions API sin mutar el workspace (restauración inmediata
    por construcción, exigencia de la tarea 2.4).

    Args:
        transporte_permisos (ClientePermisosSdk): adaptador de producción C7.
        tipo_objeto (TipoObjeto): tipo del plano de control a sondear.
        identificador (str | None): id del objeto; vacío para el singleton
            `USO_TOKEN`.

    Returns:
        tuple[str, str]: estado y detalle con el recuento de entradas y la
            verificación de la relectura; ``no_disponible`` si el workspace
            no expone el objeto.
    """
    recurso = RECURSO_PERMISOS_POR_TIPO_OBJETO[tipo_objeto]
    if tipo_objeto is not TipoObjeto.USO_TOKEN and not identificador:
        return (
            ESTADO_NO_DISPONIBLE,
            f"El workspace no expone un objeto '{recurso}' descubierto; la "
            f"escritura de ACL no pudo ejecutarse.",
        )
    instantanea = list(
        transporte_permisos.LeerAcl(recurso, identificador or "")
    )
    transporte_permisos.EscribirAcl(recurso, identificador or "",
                                    instantanea)
    restaurada = list(
        transporte_permisos.LeerAcl(recurso, identificador or "")
    )
    coinciden = len(restaurada) == len(instantanea)
    return (
        ESTADO_OK,
        f"PUT sobre '{recurso}' re-aplicó la instantánea "
        f"({len(instantanea)} entrada(s)); relectura coincide={coinciden}.",
    )


def _EjecutarSondasAcl(transporte_permisos, recursos):
    """Ejecuta las ocho sondas de la Permissions API (lectura y escritura).

    Args:
        transporte_permisos (ClientePermisosSdk): adaptador de producción C7.
        recursos (dict): estado compartido del descubrimiento.

    Returns:
        list[dict]: resultados de las sondas de ACL.
    """
    warehouse_id = recursos.get("warehouse_id")
    cluster_id = recursos.get("cluster_id")
    app_nombre = recursos.get("app_nombre")
    objetivos_lectura = (
        (SONDA_ACL_LECTURA_WAREHOUSE, TipoObjeto.SQL_WAREHOUSE, warehouse_id),
        (SONDA_ACL_LECTURA_CLUSTER, TipoObjeto.COMPUTO_CLASICO, cluster_id),
        (SONDA_ACL_LECTURA_APP, TipoObjeto.DATABRICK_APP, app_nombre),
        (SONDA_ACL_LECTURA_TOKENS, TipoObjeto.USO_TOKEN, ""),
    )
    objetivos_escritura = (
        (SONDA_ACL_ESCRITURA_WAREHOUSE, TipoObjeto.SQL_WAREHOUSE,
         warehouse_id),
        (SONDA_ACL_ESCRITURA_CLUSTER, TipoObjeto.COMPUTO_CLASICO, cluster_id),
        (SONDA_ACL_ESCRITURA_APP, TipoObjeto.DATABRICK_APP, app_nombre),
        (SONDA_ACL_ESCRITURA_TOKENS, TipoObjeto.USO_TOKEN, ""),
    )

    sondas = [
        _EjecutarSonda(
            nombre,
            lambda tipo=tipo, identificador=identificador: ProbarAclLectura(
                transporte_permisos, tipo, identificador
            ),
        )
        for nombre, tipo, identificador in objetivos_lectura
    ]
    sondas += [
        _EjecutarSonda(
            nombre,
            lambda tipo=tipo, identificador=identificador: (
                ProbarAclEscrituraRestaurada(
                    transporte_permisos, tipo, identificador
                )
            ),
        )
        for nombre, tipo, identificador in objetivos_escritura
    ]
    return sondas


def ProbarResolucionPrivilegiosBroker(host, token, canal_control_sp,
                                      warehouse_id, identidad):
    """Resuelve los privilegios efectivos del llamante leyendo la ACL con el SP.

    Es la sonda que demuestra el corazón del modelo broker (design.md D2): la
    ACL del warehouse se LEE con la identidad del service principal (no con la
    OBO) y el resolutor de C3 empareja esas entradas con la identidad y los
    grupos del llamante, devolviendo los privilegios efectivos.

    Args:
        host (str): host del workspace.
        token (str): token OBO del llamante (solo para el canal de datos OBO).
        canal_control_sp (CanalControlComputo): canal del plano de control del
            SP (lee la ACL del warehouse).
        warehouse_id (str | None): id del warehouse objetivo.
        identidad (IdentidadLlamante | None): identidad OBO del llamante.

    Returns:
        tuple[str, str]: estado y detalle con los privilegios efectivos;
            ``no_disponible`` sin warehouse y ``fallo`` sin identidad.
    """
    if not warehouse_id:
        return (
            ESTADO_NO_DISPONIBLE,
            "Sin SQL warehouse descubierto para resolver la ACL con el SP.",
        )
    if identidad is None:
        return (
            ESTADO_FALLO,
            "Identidad OBO del llamante no resuelta: no hay a quién evaluar.",
        )
    objeto = ObjetoSecurable(
        identificador=warehouse_id, tipo=TipoObjeto.SQL_WAREHOUSE
    )
    canal_datos_obo = CanalSqlDatos(
        sesion_sql=CrearSesionSqlRemota(host, token, warehouse_id)
    )
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos_obo, canal_control=canal_control_sp
    )
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad, objeto)
    privilegios = sorted(vista.privilegios_efectivos)
    return (
        ESTADO_OK,
        f"privilegios efectivos del llamante sobre el warehouse (ACL leída "
        f"con SP): {privilegios}",
    )


def _DescubrirObjetivosBroker(cliente_sp):
    """Descubre warehouse y cluster para las sondas ACL con el SP.

    Un fallo de descubrimiento no aborta el gate: se devuelve el id ausente y
    las sondas ACL correspondientes quedan ``no_disponible``.

    Args:
        cliente_sp (WorkspaceClient): cliente con la identidad del SP.

    Returns:
        dict: estado compartido con ``warehouse_id`` y ``cluster_id``.
    """
    recursos = {}
    for funcion in (ProbarWarehouses, ProbarClusters, ProbarServerlessCompute):
        try:
            funcion(cliente_sp, recursos)
        except Exception:  # noqa: BLE001 - descubrimiento degradado
            # La sonda de descubrimiento correspondiente queda ausente; las
            # sondas de ACL sobre ese objeto reportarán no_disponible.
            pass
    return recursos


def EjecutarVerificacionesBroker(configuracion):
    """Ejecuta las 11 sondas broker con la identidad del SP.

    La autorización del llamante (OBO) sigue presente en la resolución de
    privilegios (lectura de ACL con SP + emparejamiento con la identidad);
    la EJECUCIÓN de las sondas de descubrimiento y ACL usa el SP.

    Args:
        configuracion (ConfiguracionApp): configuración única del proyecto.

    Returns:
        dict: evidencia del gate broker con ``spike``, ``timestamp_utc``,
            ``usuario`` (identidad OBO) y ``sondas``.

    Raises:
        ErrorContextoLlamanteAusente: sin token OBO (fuera de la App).
        ErrorAutenticacionLlamante: sin host o sin cliente SP.
    """
    token = LeerTokenObo(AccederEncabezadosStreamlit, configuracion)
    host = LeerHostWorkspace(os.environ, configuracion)

    cliente_obo = CrearClienteWorkspace(host=host, token=token)
    contexto_broker = FabricaContextoBroker().CrearContexto()
    cliente_sp = contexto_broker.cliente_sp
    canal_control_sp = contexto_broker.canal_control
    transporte_sp = canal_control_sp.transporte

    proveedor = ProveedorIdentidadDatabricksApp(configuracion=configuracion)
    servicio_identidad = ServicioIdentidadLlamante(proveedor=proveedor)
    identidad = servicio_identidad.ObtenerIdentidadLlamante()

    recursos = _DescubrirObjetivosBroker(cliente_sp)
    warehouse_id = recursos.get("warehouse_id")
    cluster_id = recursos.get("cluster_id")
    serverless_compute_id = recursos.get("serverless_compute_id")

    sondas = [
        _EjecutarSonda(
            SONDA_BROKER_SCIM_USUARIOS,
            lambda: ProbarListado(
                contexto_broker.descubridor_principales.ListarUsuarios(),
                "usuarios SCIM (SP)",
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_SCIM_GRUPOS,
            lambda: ProbarListado(
                contexto_broker.descubridor_principales.ListarGrupos(),
                "grupos SCIM (SP)",
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_SCIM_SERVICE_PRINCIPALS,
            lambda: ProbarListado(
                contexto_broker.descubridor_principales.ListarServicePrincipals(),
                "service principals SCIM (SP)",
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_CLUSTERS,
            lambda: ProbarClusters(cliente_sp, recursos),
        ),
        _EjecutarSonda(
            SONDA_BROKER_SERVERLESS,
            lambda: ProbarServerlessCompute(cliente_sp, recursos),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_LECTURA_WAREHOUSE,
            lambda: ProbarAclLectura(
                transporte_sp, TipoObjeto.SQL_WAREHOUSE, warehouse_id
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_LECTURA_CLUSTER,
            lambda: ProbarAclLectura(
                transporte_sp, TipoObjeto.COMPUTO_CLASICO, cluster_id
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_LECTURA_SERVERLESS,
            lambda: ProbarAclLectura(
                transporte_sp, TipoObjeto.COMPUTO_SERVERLESS,
                serverless_compute_id,
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_LECTURA_TOKENS,
            lambda: ProbarAclLectura(transporte_sp, TipoObjeto.USO_TOKEN, ""),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_ESCRITURA_WAREHOUSE,
            lambda: ProbarAclEscrituraRestaurada(
                transporte_sp, TipoObjeto.SQL_WAREHOUSE, warehouse_id
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_ESCRITURA_CLUSTER,
            lambda: ProbarAclEscrituraRestaurada(
                transporte_sp, TipoObjeto.COMPUTO_CLASICO, cluster_id
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_ESCRITURA_SERVERLESS,
            lambda: ProbarAclEscrituraRestaurada(
                transporte_sp, TipoObjeto.COMPUTO_SERVERLESS,
                serverless_compute_id,
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_ACL_ESCRITURA_TOKENS,
            lambda: ProbarAclEscrituraRestaurada(
                transporte_sp, TipoObjeto.USO_TOKEN, ""
            ),
        ),
        _EjecutarSonda(
            SONDA_BROKER_RESOLUCION_PRIVILEGIOS,
            lambda: ProbarResolucionPrivilegiosBroker(
                host, token, canal_control_sp, warehouse_id, identidad
            ),
        ),
    ]

    return {
        "spike": IDENTIFICADOR_SPIKE_BROKER,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "usuario": (
            identidad.principal.identificador if identidad is not None
            else None
        ),
        "sondas": sondas,
    }


def EjecutarVerificaciones(configuracion):
    """Ejecuta las 24 sondas del gate con la credencial OBO del llamante.

    Args:
        configuracion (ConfiguracionApp): configuración única del proyecto.

    Returns:
        dict: evidencia del gate con ``spike``, ``timestamp_utc``,
            ``usuario`` (identidad OBO resuelta) y ``sondas``.

    Raises:
        ErrorContextoLlamanteAusente: si la invocación no trae token OBO
            (ejecución fuera de la Databricks App).
        ErrorAutenticacionLlamante: si el entorno no informa el host.
    """
    token = LeerTokenObo(AccederEncabezadosStreamlit, configuracion)
    host = LeerHostWorkspace(os.environ, configuracion)

    # Cliente SDK con credencial explícita del llamante (nunca la de la App).
    cliente = CrearClienteWorkspace(host=host, token=token)
    transporte_permisos = ClientePermisosSdk(cliente)

    # Identidad con el código de producción de C3/C9.
    proveedor = ProveedorIdentidadDatabricksApp(configuracion=configuracion)
    servicio_identidad = ServicioIdentidadLlamante(proveedor=proveedor)

    recursos = {}
    sondas = [
        _EjecutarSonda(
            SONDA_IDENTIDAD_OBO,
            lambda: ProbarIdentidadObo(servicio_identidad),
        ),
        _EjecutarSonda(
            SONDA_SCIM_USUARIOS,
            lambda: ProbarListado(cliente.users.list(), "usuarios SCIM"),
        ),
        _EjecutarSonda(
            SONDA_SCIM_GRUPOS,
            lambda: ProbarListado(cliente.groups.list(), "grupos SCIM"),
        ),
        _EjecutarSonda(
            SONDA_SCIM_SERVICE_PRINCIPALS,
            lambda: ProbarListado(
                cliente.service_principals.list(), "service principals SCIM"
            ),
        ),
        _EjecutarSonda(
            SONDA_UC_CATALOGOS,
            lambda: ProbarCatalogos(cliente, recursos, configuracion),
        ),
        _EjecutarSonda(
            SONDA_UC_ESQUEMAS,
            lambda: ProbarEsquemas(cliente, recursos),
        ),
        _EjecutarSonda(
            SONDA_UC_TABLAS,
            lambda: ProbarTablas(cliente, recursos),
        ),
        _EjecutarSonda(
            SONDA_UC_CONEXIONES,
            lambda: ProbarListado(
                cliente.connections.list(), "conexiones UC"
            ),
        ),
        _EjecutarSonda(
            SONDA_SQL_WAREHOUSES,
            lambda: ProbarWarehouses(cliente, recursos),
        ),
        _EjecutarSonda(
            SONDA_COMPUTO_CLUSTERS,
            lambda: ProbarClusters(cliente, recursos),
        ),
        _EjecutarSonda(
            SONDA_APPS_LISTA,
            lambda: ProbarApps(cliente, recursos),
        ),
    ]
    sondas += _EjecutarSondasSql(host, token, configuracion, recursos)
    sondas += _EjecutarSondasAcl(transporte_permisos, recursos)

    identidad = servicio_identidad.ObtenerIdentidadLlamante()
    return {
        "spike": IDENTIFICADOR_SPIKE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "usuario": (
            identidad.principal.identificador if identidad is not None
            else None
        ),
        "sondas": sondas,
    }


def _RenderizarResultados(evidencia):
    """Presenta la evidencia del gate en la página.

    Args:
        evidencia (dict): resultado de ``EjecutarVerificaciones``.
    """
    st.subheader("Resultados del gate D4")
    recuento_ok = sum(
        1 for sonda in evidencia["sondas"] if sonda["estado"] == ESTADO_OK
    )
    recuento_fallo = sum(
        1 for sonda in evidencia["sondas"] if sonda["estado"] == ESTADO_FALLO
    )
    recuento_no_disponible = sum(
        1
        for sonda in evidencia["sondas"]
        if sonda["estado"] == ESTADO_NO_DISPONIBLE
    )
    columna_ok, columna_fallo, columna_no_disponible = st.columns(3)
    columna_ok.metric("Sondas en verde", recuento_ok)
    columna_fallo.metric("Sondas en fallo", recuento_fallo)
    columna_no_disponible.metric(
        "Sondas no disponibles", recuento_no_disponible
    )

    st.dataframe(evidencia["sondas"])

    texto_evidencia = json.dumps(evidencia, indent=2, ensure_ascii=False)
    st.download_button(
        "Descargar evidencia JSON",
        data=texto_evidencia,
        file_name=NOMBRE_ARCHIVO_EVIDENCIA,
        mime="application/json",
    )
    st.caption(
        f"Evidencia generada por '{evidencia['usuario']}' a las "
        f"{evidencia['timestamp_utc']}. Guarde el JSON en "
        f"`{RUTA_RELATIVA_EVIDENCIA}` para que la prueba integral "
        f"`tests/integrales/test_ui_spike_obo_andresfree.py` verifique el "
        f"gate."
    )
    with st.expander("Evidencia JSON (copiable)"):
        st.code(texto_evidencia, language="json")


def _RenderizarResultadosBroker(evidencia):
    """Presenta la evidencia del gate broker en la página.

    Args:
        evidencia (dict): resultado de ``EjecutarVerificacionesBroker``.
    """
    st.subheader("Resultados del gate broker (SP)")
    recuento_ok = sum(
        1 for sonda in evidencia["sondas"] if sonda["estado"] == ESTADO_OK
    )
    recuento_fallo = sum(
        1 for sonda in evidencia["sondas"] if sonda["estado"] == ESTADO_FALLO
    )
    recuento_no_disponible = sum(
        1
        for sonda in evidencia["sondas"]
        if sonda["estado"] == ESTADO_NO_DISPONIBLE
    )
    columna_ok, columna_fallo, columna_no_disponible = st.columns(3)
    columna_ok.metric("Sondas broker en verde", recuento_ok)
    columna_fallo.metric("Sondas broker en fallo", recuento_fallo)
    columna_no_disponible.metric(
        "Sondas broker no disponibles", recuento_no_disponible
    )

    st.dataframe(evidencia["sondas"])

    texto_evidencia = json.dumps(evidencia, indent=2, ensure_ascii=False)
    st.download_button(
        "Descargar evidencia broker JSON",
        data=texto_evidencia,
        file_name=NOMBRE_ARCHIVO_EVIDENCIA_BROKER,
        mime="application/json",
    )
    st.caption(
        f"Evidencia broker generada por '{evidencia['usuario']}' a las "
        f"{evidencia['timestamp_utc']}. Guarde el JSON en "
        f"`{RUTA_RELATIVA_EVIDENCIA_BROKER}` para que "
        f"`tests/integrales/test_broker_spike_andresfree.py` verifique el "
        f"gate."
    )
    with st.expander("Evidencia broker JSON (copiable)"):
        st.code(texto_evidencia, language="json")


def RenderizarPagina():
    """Punto de entrada de la página del spike (entrada mínima desplegable)."""
    st.set_page_config(page_title=TITULO_PAGINA, layout="wide")
    st.title(TITULO_PAGINA)
    st.markdown(
        "Spike del gate de viabilidad OBO (change C9, decisión D4). Todas las "
        "sondas se ejecutan con **su** credencial on-behalf-of (la que la "
        "plataforma entrega en el header del request); ninguna usa la "
        "identidad del service principal de la App. Las escrituras de ACL "
        "re-aplican la instantánea leída: el estado del workspace no cambia."
    )

    try:
        configuracion = ConfiguracionApp.Cargar()
    except Exception as excepcion:  # noqa: BLE001 - fallo de configuración
        st.error(
            f"No se pudo cargar la configuración del proyecto: "
            f"{_DescripcionError(excepcion)}"
        )
        return

    if st.button(ETIQUETA_BOTON_EJECUTAR, type="primary"):
        with st.spinner(
            "Ejecutando las sondas del gate con la credencial OBO..."
        ):
            try:
                st.session_state[CLAVE_ESTADO_EVIDENCIA] = (
                    EjecutarVerificaciones(configuracion)
                )
            except ErrorContextoLlamanteAusente:
                st.warning(
                    "La invocación no trae un token on-behalf-of: ejecute "
                    "esta página dentro de la Databricks App desplegada, con "
                    "autorización de usuario habilitada y los scopes "
                    "consentidos."
                )
            except ErrorAutenticacionLlamante as excepcion:
                st.error(
                    f"No se pudo componer la credencial OBO del llamante: "
                    f"{excepcion.mensaje}"
                )
            except Exception as excepcion:  # noqa: BLE001 - fallo del spike
                st.error(
                    f"Fallo inesperado al ejecutar las sondas: "
                    f"{_DescripcionError(excepcion)}"
                )

    if CLAVE_ESTADO_EVIDENCIA in st.session_state:
        _RenderizarResultados(st.session_state[CLAVE_ESTADO_EVIDENCIA])

    st.divider()
    st.subheader("Gate broker (identidad del service principal)")
    st.markdown(
        "Sondas del change `app-broker-identidad-ejecucion`: el descubrimiento "
        "SCIM/clusters y la lectura/escritura de ACL usan la identidad del "
        "service principal de la App; la resolución de privilegios sigue "
        "evaluando al llamante OBO sobre esa ACL."
    )

    if st.button(ETIQUETA_BOTON_EJECUTAR_BROKER):
        with st.spinner(
            "Ejecutando las sondas broker con la identidad del SP..."
        ):
            try:
                st.session_state[CLAVE_ESTADO_EVIDENCIA_BROKER] = (
                    EjecutarVerificacionesBroker(configuracion)
                )
            except ErrorContextoLlamanteAusente:
                st.warning(
                    "La invocación no trae un token on-behalf-of: ejecute esta "
                    "página dentro de la Databricks App desplegada."
                )
            except ErrorAutenticacionLlamante as excepcion:
                st.error(
                    f"No se pudo componer la identidad del service principal: "
                    f"{excepcion.mensaje}"
                )
            except Exception as excepcion:  # noqa: BLE001 - fallo del spike
                st.error(
                    f"Fallo inesperado en las sondas broker: "
                    f"{_DescripcionError(excepcion)}"
                )

    if CLAVE_ESTADO_EVIDENCIA_BROKER in st.session_state:
        _RenderizarResultadosBroker(
            st.session_state[CLAVE_ESTADO_EVIDENCIA_BROKER]
        )


if __name__ == "__main__":
    # Streamlit ejecuta este archivo como __main__ (`streamlit run app.py`,
    # comando declarado en app.yaml); el guard deja importar el módulo sin
    # renderizar (prueba de humo de la tarea 6.4).
    RenderizarPagina()
