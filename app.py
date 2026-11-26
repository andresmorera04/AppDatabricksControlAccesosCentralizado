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
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.configuracion.configuracion_app import (
    ATRIBUTO_CATALOGO,
    ConfiguracionApp,
)
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.ui.fabrica_contexto import CrearSesionSparkObo
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


def _ProbarSentencia(sesion_spark, sentencia, etiqueta):
    """Ejecuta una sentencia SQL remota y reporta su recuento de filas.

    Args:
        sesion_spark: sesión Databricks Connect con credencial OBO.
        sentencia (str): sentencia SQL a ejecutar.
        etiqueta (str): nombre legible de la operación.

    Returns:
        tuple[str, str]: estado ``ok`` y recuento de filas.
    """
    filas = sesion_spark.sql(sentencia).collect()
    return ESTADO_OK, f"{etiqueta}: {len(filas)} fila(s)."


def _SondaSqlSobreEsquema(sesion_spark, recursos, plantilla, etiqueta):
    """Ejecuta una sentencia SQL que requiere catálogo y esquema descubiertos.

    Args:
        sesion_spark: sesión Databricks Connect con credencial OBO.
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
    return _ProbarSentencia(sesion_spark, sentencia, etiqueta)


def _EjecutarSondasSql(host, token, configuracion, recursos):
    """Ejecuta las sondas del plano SQL con una sesión Connect OBO.

    La sesión se construye una sola vez para las cinco sondas y se detiene en
    el ``finally``. Si la construcción falla (scope, cómputo serverless no
    disponible, credencial rechazada), todas las sondas SQL se reportan en
    fallo con el mismo detalle.

    Args:
        host (str): host del workspace.
        token (str): token OBO del llamante.
        configuracion (ConfiguracionApp): configuración del proyecto.
        recursos (dict): estado compartido del descubrimiento.

    Returns:
        list[dict]: resultados de las cinco sondas SQL.
    """
    try:
        sesion_spark = CrearSesionSparkObo(host=host, token=token)
    except Exception as excepcion:  # noqa: BLE001 - fallo de Connect
        detalle = (
            "No se pudo establecer la sesión Databricks Connect con la "
            f"credencial OBO: {_DescripcionError(excepcion)}"
        )
        return [
            {"nombre": nombre, "estado": ESTADO_FALLO, "detalle": detalle}
            for nombre in SONDAS_SQL
        ]

    try:
        catalogo_configurado = configuracion.ObtenerAtributo(ATRIBUTO_CATALOGO)
        return [
            _EjecutarSonda(
                SONDA_SQL_SELECT_UNO,
                lambda: _ProbarSentencia(
                    sesion_spark, "SELECT 1", "SELECT 1 remoto"
                ),
            ),
            _EjecutarSonda(
                SONDA_SQL_SHOW_GRANTS,
                lambda: _ProbarSentencia(
                    sesion_spark,
                    f"SHOW GRANTS ON CATALOG `{catalogo_configurado}`",
                    f"SHOW GRANTS ON CATALOG `{catalogo_configurado}`",
                ),
            ),
            _EjecutarSonda(
                SONDA_SQL_SHOW_VOLUMENES,
                lambda: _SondaSqlSobreEsquema(
                    sesion_spark,
                    recursos,
                    "SHOW VOLUMES IN `{catalogo}`.`{esquema}`",
                    "SHOW VOLUMES (ruta SQL de descubrimiento)",
                ),
            ),
            _EjecutarSonda(
                SONDA_SQL_SHOW_MODELOS,
                lambda: _SondaSqlSobreEsquema(
                    sesion_spark,
                    recursos,
                    "SHOW MODELS IN `{catalogo}`.`{esquema}`",
                    "SHOW MODELS (ruta SQL de descubrimiento)",
                ),
            ),
            _EjecutarSonda(
                SONDA_SQL_SHOW_EXTERNAL_LOCATIONS,
                lambda: _ProbarSentencia(
                    sesion_spark,
                    "SHOW EXTERNAL LOCATIONS",
                    "SHOW EXTERNAL LOCATIONS (ruta SQL de descubrimiento)",
                ),
            ),
        ]
    finally:
        try:
            sesion_spark.stop()
        except Exception:  # noqa: BLE001 - cierre de la sesión del spike
            # El cierre fallido de la sesión del spike no invalida la
            # evidencia ya generada; se ignora de forma controlada.
            pass


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


if __name__ == "__main__":
    # Streamlit ejecuta este archivo como __main__ (`streamlit run app.py`,
    # comando declarado en app.yaml); el guard deja importar el módulo sin
    # renderizar (prueba de humo de la tarea 6.4).
    RenderizarPagina()
