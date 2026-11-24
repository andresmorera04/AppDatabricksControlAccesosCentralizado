"""Adaptador de pruebas integrales: ejecución de SQL real contra Databricks.

Infraestructura EXCLUSIVA de la capa de pruebas integrales (marker `free`):
ejecuta sentencias SQL contra el workspace real `andresFree` usando la
Statement Execution API a través del CLI de Databricks ya instalado y
autenticado con el perfil CLI (decisión D5 del README). Así las integrales
prueban el código de producción real (el DDL del inicializador) sin instalar
ninguna biblioteca nueva en la Mac (regla "Prohibición de instalación por la
IA"): ni `databricks-sdk` ni `databricks-sql-connector` son necesarios.

El adaptador satisface el contrato mínimo que consume `InicializadorPersistencia`
(un objeto con `.sql(sentencia)`), igual que una `SparkSession`; en la
Databricks App la sesión real la provee el entorno (design.md D3).

Convención de nombres del proyecto: este módulo es infraestructura de pruebas,
pero sigue el estándar (funciones y clases en PascalCase, constantes en
MAYÚSCULAS, comentarios en español).
"""

import json
import subprocess
import time

# Perfil CLI del workspace primario de pruebas (README D5: andresFree; el
# backup andresAzureDev está prohibido sin aprobación expresa).
PERFIL_CLI_INTEGRAL = "andresFree"

# Rutas de la API usadas por el adaptador.
RUTA_API_SENTENCIAS = "/api/2.0/sql/statements"
RUTA_API_WAREHOUSES = "/api/2.0/sql/warehouses"

# Espera síncrona máxima por sentencia (la API admite entre 5s y 50s) y
# sondeo posterior para sentencias largas (por ejemplo, arranque en frío del
# warehouse serverless).
TIEMPO_ESPERA_INICIAL = "50s"
SEGUNDOS_ENTRE_SONDEOS = 5
MAXIMO_SONDEOS = 60

# Estados terminales y no terminales de una sentencia.
ESTADOS_EN_CURSO = ("PENDING", "RUNNING")
ESTADO_EXITO = "SUCCEEDED"

# Tiempo límite del subproceso CLI en segundos.
SEGUNDOS_LIMITE_CLI = 120


class ErrorTransporteDatabricks(RuntimeError):
    """Fallo del transporte CLI/API o de la sentencia en el workspace.

    El inicializador de producción captura esta excepción (como cualquier
    otra) y la traduce a `ErrorInicializacionPersistencia`, que es justo el
    comportamiento que la prueba integral verifica ante un catálogo
    inaccesible.
    """


def EjecutarComandoCli(subcomando, perfil=PERFIL_CLI_INTEGRAL, carga_json=None):
    """Ejecuta `databricks api <subcomando>` y devuelve el JSON de respuesta.

    Args:
        subcomando (list[str]): partes del subcomando `api` (por ejemplo,
            `["post", "/api/2.0/sql/statements"]`).
        perfil (str): perfil CLI autenticado a usar.
        carga_json (dict | None): cuerpo JSON de la petición (solo POST).

    Returns:
        dict: respuesta JSON del CLI.

    Raises:
        ErrorTransporteDatabricks: si el CLI falla o su salida no es JSON.
    """
    comando = ["databricks", "api", *subcomando, "--profile", perfil]
    if carga_json is not None:
        comando += ["--json", json.dumps(carga_json)]

    proceso = subprocess.run(
        comando,
        capture_output=True,
        text=True,
        timeout=SEGUNDOS_LIMITE_CLI,
    )
    if proceso.returncode != 0:
        raise ErrorTransporteDatabricks(
            f"El CLI de Databricks falló al ejecutar {' '.join(subcomando)} "
            f"con el perfil '{perfil}': {proceso.stderr.strip()}"
        )
    try:
        return json.loads(proceso.stdout)
    except json.JSONDecodeError as excepcion:
        raise ErrorTransporteDatabricks(
            f"La respuesta del CLI no es JSON válido: {proceso.stdout[:300]}"
        ) from excepcion


def DescubrirWarehouseServerless(perfil=PERFIL_CLI_INTEGRAL):
    """Descubre el id de un SQL warehouse serverless del workspace.

    El identificador NO se hardcodea (regla del proyecto): se consulta la API
    de warehouses y se toma el primero con cómputo serverless habilitado (en
    Free Edition el warehouse serverless arranca bajo demanda aunque figure
    STOPPED).

    Args:
        perfil (str): perfil CLI autenticado.

    Returns:
        str | None: id del warehouse serverless, o `None` si no hay ninguno.
    """
    respuesta = EjecutarComandoCli(["get", RUTA_API_WAREHOUSES], perfil)
    for warehouse in respuesta.get("warehouses", []):
        if warehouse.get("enable_serverless_compute"):
            return warehouse["id"]
    return None


class SesionSqlDatabricks:
    """Doble de `SparkSession` que ejecuta SQL contra el workspace real.

    Expone el método `sql(sentencia)` que consume el inicializador de
    producción y un método `EjecutarYLeer` que además devuelve las filas de la
    consulta (listas de textos, como entrega la Statement Execution API), para
    las verificaciones de las pruebas.

    Attributes:
        warehouse_id (str): id del SQL warehouse descubierto en el workspace.
        perfil (str): perfil CLI autenticado.
    """

    def __init__(self, warehouse_id, perfil=PERFIL_CLI_INTEGRAL):
        """Inicializa el adaptador con el warehouse y el perfil descubiertos.

        Args:
            warehouse_id (str): id del SQL warehouse serverless del workspace.
            perfil (str): perfil CLI autenticado (por defecto, `andresFree`).

        Raises:
            ValueError: si no se recibe el id del warehouse.
        """
        if not warehouse_id:
            raise ValueError(
                "Se requiere el id de un SQL warehouse para ejecutar "
                "sentencias contra el workspace."
            )
        self.warehouse_id = warehouse_id
        self.perfil = perfil

    def sql(self, sentencia):
        """Ejecuta una sentencia SQL en el workspace y devuelve sus filas.

        Compatible con el uso que hace `InicializadorPersistencia` de la
        sesión Spark (`.sql(ddl)`): ejecuta, espera al estado terminal y lanza
        si la sentencia falla.

        Args:
            sentencia (str): sentencia SQL a ejecutar.

        Returns:
            list[list[str]]: filas del resultado (`data_array`), vacía para
            sentencias DDL sin resultado.

        Raises:
            ErrorTransporteDatabricks: si la sentencia falla en el workspace
                o el transporte CLI falla.
        """
        return self.EjecutarYLeer(sentencia)

    def EjecutarYLeer(self, sentencia):
        """Ejecuta la sentencia, espera su fin y devuelve las filas leídas.

        Args:
            sentencia (str): sentencia SQL a ejecutar.

        Returns:
            list[list[str]]: filas del resultado como listas de textos.

        Raises:
            ErrorTransporteDatabricks: si la sentencia no termina en éxito
                (el mensaje incluye el estado, el error del workspace y la
                sentencia original) o si el transporte falla.
        """
        respuesta = EjecutarComandoCli(
            ["post", RUTA_API_SENTENCIAS],
            self.perfil,
            {
                "warehouse_id": self.warehouse_id,
                "statement": sentencia,
                "wait_timeout": TIEMPO_ESPERA_INICIAL,
            },
        )
        estado = (respuesta.get("status") or {}).get("state")
        id_sentencia = respuesta.get("statement_id")

        # Sondeo acotado mientras la sentencia siga en curso (por ejemplo,
        # durante el arranque en frío del warehouse serverless).
        sondios = 0
        while estado in ESTADOS_EN_CURSO and sondios < MAXIMO_SONDEOS:
            time.sleep(SEGUNDOS_ENTRE_SONDEOS)
            respuesta = EjecutarComandoCli(
                ["get", f"{RUTA_API_SENTENCIAS}/{id_sentencia}"], self.perfil
            )
            estado = (respuesta.get("status") or {}).get("state")
            sondios += 1

        if estado != ESTADO_EXITO:
            detalle_error = (respuesta.get("status") or {}).get("error") or {}
            raise ErrorTransporteDatabricks(
                f"La sentencia no terminó en éxito en el workspace "
                f"(estado: {estado}): {detalle_error.get('message')} | "
                f"SQL: {sentencia}"
            )

        return (respuesta.get("result") or {}).get("data_array") or []
