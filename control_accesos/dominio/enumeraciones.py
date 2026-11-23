"""Enumeraciones tipadas del modelo de dominio (capability `grant-domain-model`).

Los miembros se nombran en MAYÚSCULAS por ser constantes (estándar del
proyecto) y sus valores están en español. Estas enumeraciones son los dos
únicos puntos de extensión declarados del dominio: agregar un tipo de objeto o
un estado nuevo se hace aquí (ver design.md - Risks).
"""

from enum import Enum


class TipoPrincipal(Enum):
    """Tipos de principal soportados por el sistema.

    Un *principal* es la entidad que recibe o pierde privilegios. Según el
    README, puede ser un usuario, un grupo o un service principal.
    """

    USUARIO = "usuario"
    GRUPO = "grupo"
    SERVICE_PRINCIPAL = "service_principal"


class TipoObjeto(Enum):
    """Tipos de objeto securable soportados por el sistema.

    Cubre los 15 tipos del README: 10 del plano de datos (Unity Catalog) y 5
    del plano de control (workspace). La clasificación por plano se declara en
    `MAPA_TIPO_OBJETO_A_PLANO` (ver modelos.py), no con lógica dispersa.
    """

    # Plano de datos (Unity Catalog), canal SQL GRANT/REVOKE.
    CATALOGO = "catalogo"
    ESQUEMA = "esquema"
    TABLA_DELTA = "tabla_delta"
    STREAMING_TABLE = "streaming_table"
    VISTA_MATERIALIZADA = "vista_materializada"
    VISTA_SQL = "vista_sql"
    VOLUMEN = "volumen"
    MODELO_ML = "modelo_ml"
    EXTERNAL_LOCATION = "external_location"
    CONNECTION = "connection"

    # Plano de control (workspace), canal SDK/REST (Permissions API).
    COMPUTO_CLASICO = "computo_clasico"
    COMPUTO_SERVERLESS = "computo_serverless"
    SQL_WAREHOUSE = "sql_warehouse"
    DATABRICK_APP = "databricks_app"
    USO_TOKEN = "uso_token"


class Plano(Enum):
    """Planos de autorización de Databricks.

    - DATOS: objetos de Unity Catalog, autorizados por instrucciones SQL.
    - CONTROL: objetos del workspace, autorizados por la Permissions API.
    """

    DATOS = "datos"
    CONTROL = "control"


class EstadoItem(Enum):
    """Estados finales del resultado por ítem de grant (spec `grant-domain-model`).

    - OTORGADO: el privilegio se concedió y se verificó.
    - FALLIDO: la ejecución o la verificación falló por otra causa.
    - PRIVILEGIOS_INSUFICIENTES: el ejecutor no tiene privilegios para otorgarlo.
    """

    OTORGADO = "otorgado"
    FALLIDO = "fallido"
    PRIVILEGIOS_INSUFICIENTES = "privilegios_insuficientes"


def ListarValoresDeEnumeracion(enumeracion):
    """Devuelve la lista de valores (en español) de una enumeración.

    Se usa para construir mensajes de error explícitos que listan los valores
    válidos, según exige el spec `grant-domain-model`.

    Args:
        enumeracion: clase de enumeración (`Enum`) de la que listar valores.

    Returns:
        list[str]: valores de cada miembro, en el orden de declaración.
    """
    return [miembro.value for miembro in enumeracion]
