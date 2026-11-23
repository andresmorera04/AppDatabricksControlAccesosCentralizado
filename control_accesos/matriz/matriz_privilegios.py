"""Declaración de la matriz de compatibilidad privilegio x tipo de objeto.

Esta matriz es el corazón del dominio (README.md): valida solicitudes de grant,
filtra las opciones de la UI y genera mensajes de error precisos. Se declara
como dato (design.md D3), de modo que agregar un tipo de objeto o un
privilegio no requiere tocar lógica alguna (spec `privilege-matrix`).

Fuentes de los conjuntos declarados (documentación oficial de Databricks,
consultada en noviembre de 2026):

- Unity Catalog privileges reference
  https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/privileges-reference
  (privilegios por objeto securable y por objeto contenedor, con herencia).
- Unity Catalog securable objects reference
  https://docs.databricks.com/aws/en/data-governance/unity-catalog/securable-objects
  (las streaming tables se rigen por los privilegios de tabla; REFRESH aplica
  solo a vistas materializadas; los modelos son un tipo de función).
- Access control lists (Permissions API)
  https://docs.databricks.com/aws/en/security/auth/access-control/
  y la referencia de la API
  https://docs.databricks.com/api/workspace/permissions
  (niveles de permiso CAN_* del plano de control: clusters confirma
  CAN_MANAGE, CAN_RESTART y CAN_ATTACH_TO; `authorization/tokens` para el uso
  de personal access tokens).

Convención de escritura de los privilegios: en el plano de datos se usa la
forma SQL de Unity Catalog, con espacios (`USE CATALOG`, `ALL PRIVILEGES`);
en el plano de control se usa la forma de la Permissions API, con guiones
bajos (`CAN_USE`, `CAN_MANAGE`). Cada valor es el literal que su canal
correspondiente envía, por lo que no se traduce entre planos.

Alcance declarado: solo se incluyen los privilegios aplicables a los tipos de
objeto que la app gestiona (ver `TipoObjeto`). Privilegios de contenedor
propios de objetos no gestionados (secret, service, feature, flow, clean room)
se excluyen a propósito para no ofrecer opciones que la app no puede ejecutar.
"""

from control_accesos.dominio.enumeraciones import TipoObjeto

# Matriz declarativa privilegio x tipo de objeto.
# Clave: TipoObjeto. Valor: frozenset inmutable de privilegios válidos.
MATRIZ_PRIVILEGIOS = {
    # ------------------------------------------------------------------
    # Plano de datos (Unity Catalog), canal SQL GRANT/REVOKE.
    # ------------------------------------------------------------------
    # Catálogo: objeto contenedor. Además de sus privilegios propios
    # (USE CATALOG, CREATE SCHEMA, BROWSE), admite los privilegios que se
    # heredan a los objetos hijos (SELECT, MODIFY, READ VOLUME, ...).
    TipoObjeto.CATALOGO: frozenset(
        {
            "ALL PRIVILEGES",
            "USE CATALOG",
            "CREATE SCHEMA",
            "BROWSE",
            "MANAGE",
            "READ METADATA",
            "SELECT",
            "MODIFY",
            "INSERT",
            "UPDATE",
            "DELETE",
            "USE SCHEMA",
            "CREATE TABLE",
            "CREATE FUNCTION",
            "CREATE MATERIALIZED VIEW",
            "CREATE MODEL",
            "CREATE VOLUME",
            "EXECUTE",
            "APPLY TAG",
            "READ VOLUME",
            "WRITE VOLUME",
            "REFRESH",
        }
    ),
    # Esquema: objeto contenedor dentro de un catálogo. USE SCHEMA es el
    # privilegio de uso propio; los demás se heredan a tablas, vistas,
    # volúmenes, funciones y modelos del esquema.
    TipoObjeto.ESQUEMA: frozenset(
        {
            "ALL PRIVILEGES",
            "USE SCHEMA",
            "EXTERNAL USE SCHEMA",
            "CREATE TABLE",
            "CREATE FUNCTION",
            "CREATE MATERIALIZED VIEW",
            "CREATE MODEL",
            "CREATE VOLUME",
            "SELECT",
            "MODIFY",
            "INSERT",
            "UPDATE",
            "DELETE",
            "EXECUTE",
            "APPLY TAG",
            "READ VOLUME",
            "WRITE VOLUME",
            "REFRESH",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Tabla delta: lectura con SELECT, escritura con MODIFY o con los
    # privilegios DML finos (INSERT, UPDATE, DELETE).
    TipoObjeto.TABLA_DELTA: frozenset(
        {
            "ALL PRIVILEGES",
            "SELECT",
            "MODIFY",
            "INSERT",
            "UPDATE",
            "DELETE",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Streaming table: la documentación oficial no le asigna privilegios
    # propios; se rige por los mismos privilegios de tabla.
    TipoObjeto.STREAMING_TABLE: frozenset(
        {
            "ALL PRIVILEGES",
            "SELECT",
            "MODIFY",
            "INSERT",
            "UPDATE",
            "DELETE",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Vista materializada: mismo modelo de permisos que la vista, más REFRESH
    # (único tipo de objeto al que aplica REFRESH según la doc oficial).
    TipoObjeto.VISTA_MATERIALIZADA: frozenset(
        {
            "ALL PRIVILEGES",
            "SELECT",
            "REFRESH",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Vista SQL: objeto de solo lectura; se consulta con SELECT.
    TipoObjeto.VISTA_SQL: frozenset(
        {
            "ALL PRIVILEGES",
            "SELECT",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Volumen: acceso a nivel de archivo con READ VOLUME y WRITE VOLUME.
    TipoObjeto.VOLUMEN: frozenset(
        {
            "ALL PRIVILEGES",
            "READ VOLUME",
            "WRITE VOLUME",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Modelo de ML (registered model): es un tipo de función en Unity Catalog,
    # por lo que se ejecuta con EXECUTE; además admite CREATE MODEL VERSION
    # para registrar nuevas versiones sin permitir ejecutarlas.
    TipoObjeto.MODELO_ML: frozenset(
        {
            "ALL PRIVILEGES",
            "EXECUTE",
            "CREATE MODEL VERSION",
            "APPLY TAG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # External location: acceso directo a archivos en el almacenamiento externo
    # y permisos de creación sobre esa ruta. EXTERNAL USE LOCATION no está
    # incluido en ALL PRIVILEGES (debe otorgarse explícitamente).
    TipoObjeto.EXTERNAL_LOCATION: frozenset(
        {
            "ALL PRIVILEGES",
            "READ FILES",
            "WRITE FILES",
            "CREATE EXTERNAL TABLE",
            "CREATE EXTERNAL VOLUME",
            "CREATE FOREIGN SECURABLE",
            "CREATE MANAGED STORAGE",
            "EXTERNAL USE LOCATION",
            "BROWSE",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # Connection de Unity Catalog (Lakehouse Federation): se usa con
    # USE CONNECTION y permite crear catálogos externos.
    TipoObjeto.CONNECTION: frozenset(
        {
            "ALL PRIVILEGES",
            "USE CONNECTION",
            "CREATE FOREIGN CATALOG",
            "MANAGE",
            "READ METADATA",
        }
    ),
    # ------------------------------------------------------------------
    # Plano de control (workspace), canal SDK/REST (Permissions API).
    # ------------------------------------------------------------------
    # Cómputo clásico (cluster all-purpose): niveles confirmados por la
    # referencia de la Permissions API. CAN_VIEW queda excluido por estar en
    # beta (preview del workspace) hasta que sea GA.
    TipoObjeto.COMPUTO_CLASICO: frozenset(
        {
            "CAN_ATTACH_TO",
            "CAN_RESTART",
            "CAN_MANAGE",
        }
    ),
    # Cómputo serverless (interactive y automated) vía serverless compute
    # objects: CAN_USE y CAN_MANAGE (decisión D3 del README).
    TipoObjeto.COMPUTO_SERVERLESS: frozenset(
        {
            "CAN_USE",
            "CAN_MANAGE",
        }
    ),
    # SQL warehouse: CAN_USE para consultar y CAN_MANAGE para administrarlo;
    # CAN MONITOR es el nivel mínimo documentado para reiniciarlo manualmente.
    TipoObjeto.SQL_WAREHOUSE: frozenset(
        {
            "CAN_USE",
            "CAN_MANAGE",
            "CAN_MONITOR",
        }
    ),
    # Databricks App: CAN_USE para usarla y CAN_MANAGE para administrarla
    # (el detalle exacto de niveles se contrasta en C8 contra el workspace).
    TipoObjeto.DATABRICK_APP: frozenset(
        {
            "CAN_USE",
            "CAN_MANAGE",
        }
    ),
    # Uso de personal access token (Token Permissions API,
    # `authorization/tokens`): CAN_USE (decisión D4 del README).
    TipoObjeto.USO_TOKEN: frozenset(
        {
            "CAN_USE",
        }
    ),
}
