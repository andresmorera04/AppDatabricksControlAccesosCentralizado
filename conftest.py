"""Configuración de pytest para toda la suite del proyecto.

Este archivo vive en la raíz del proyecto y cumple dos funciones:

1. Garantizar que la raíz del proyecto esté en `sys.path`, de modo que las
   pruebas puedan importar el paquete `control_accesos` sin necesidad de
   instalarlo (el proyecto no usa `pip install -e`; ver la regla del README
   "Prohibición de instalación por la IA"). La ruta se deriva de `__file__`,
   no se escribe a mano (regla: nada hardcodeado).

2. Servir como punto único de configuración compartida de la suite: desde el
   change C2 (`persistencia-bitacora`) aloja la fixture de la sesión Spark
   local con Delta Lake que consumen las pruebas funcionales de la capa de
   persistencia (ver design.md D3).
"""

import sys
from pathlib import Path

import pytest

# Raíz del proyecto, derivada de la ubicación de este archivo (sin hardcodear).
RAIZ_PROYECTO = Path(__file__).resolve().parent

# Se agrega la raíz al sys.path solo si no está ya presente, para no duplicar
# entradas cuando pytest ya la insertó por su modo de importación.
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

# Parámetros de la sesión Spark local de pruebas. Se declaran como constantes
# de la infraestructura de pruebas (no son configuración de la aplicación: la
# única fuente de configuración de la app sigue siendo
# `config/app_properties.json`).
NOMBRE_APLICACION_SPARK_PRUEBAS = "pruebas_control_accesos"
MODO_LOCAL_SPARK = "local[2]"

# Extensiones de Spark que activan Delta Lake en la sesión local. En Databricks
# el runtime ya las incluye; en local las aporta el paquete `delta-spark` vía
# `configure_spark_with_delta_pip` (design.md D3/D8).
EXTENSION_SQL_DELTA = "io.delta.sql.DeltaSparkSessionExtension"
CLASE_CATALOGO_DELTA = "org.apache.spark.sql.delta.catalog.DeltaCatalog"


@pytest.fixture(scope="session")
def sesion_spark(tmp_path_factory):
    """Sesión Spark local con Delta Lake, compartida por la suite funcional.

    Scope de sesión: arrancar Spark cuesta varios segundos, por lo que se crea
    una sola vez por corrida y se detiene al finalizar.

    Aislamiento: el almacén (`spark.sql.warehouse.dir`) y los directorios
    locales se fijan a un temporal de la corrida (vía `tmp_path_factory`), no al
    CWD del repositorio. Sin esto, las tablas gestionadas de una corrida
    anterior persistirían en `spark-warehouse/` y el catálogo en memoria —que
    arranca vacío en cada proceso— chocaría al crearlas de nuevo
    (`DELTA_CREATE_TABLE_WITH_NON_EMPTY_LOCATION`). Con el almacén efímero cada
    corrida parte limpia y no queda estado local en el repo. Cada prueba aísla
    además sus datos con `tmp_path` o identificadores únicos.

    Args:
        tmp_path_factory: fábrica de directorios temporales de pytest (scope
            sesión), usada para el almacén y los directorios locales de Spark.

    Yields:
        pyspark.sql.SparkSession: sesión local configurada con las extensiones
        de Delta Lake y almacén efímero, lista para crear y escribir tablas delta.
    """
    # Importación diferida: las pruebas unitarias no necesitan Spark y no deben
    # pagar el costo de importarlo al recolectar la suite.
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    # Directorio base temporal de la corrida para todo el estado local de Spark
    # (almacén de tablas gestionadas, checkpoints y temporales del driver).
    base_spark = tmp_path_factory.mktemp("spark_local")
    almacen = base_spark / "warehouse"
    temporales = base_spark / "tmp"

    constructor = (
        SparkSession.builder.master(MODO_LOCAL_SPARK)
        .appName(NOMBRE_APLICACION_SPARK_PRUEBAS)
        .config("spark.sql.extensions", EXTENSION_SQL_DELTA)
        .config("spark.sql.catalog.spark_catalog", CLASE_CATALOGO_DELTA)
        # Almacén efímero de la corrida: garantiza aislamiento entre ejecuciones
        # y evita dejar estado local en el repositorio.
        .config("spark.sql.warehouse.dir", str(almacen))
        .config("spark.local.dir", str(temporales))
        # El driver resuelve a localhost para evitar problemas de red/hostname.
        .config("spark.driver.host", "127.0.0.1")
        # Particiones reducidas: los lotes de prueba son pequeños y el valor
        # por defecto (200) solo haría más lenta la suite.
        .config("spark.sql.shuffle.partitions", "4")
        # Sin interfaz web ni salida verbosa del driver en la consola de pytest.
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )

    # `configure_spark_with_delta_pip` resuelve los jars de Delta Lake del
    # paquete pip instalado (no hay cluster ni ivy en el entorno local).
    sesion = configure_spark_with_delta_pip(constructor).getOrCreate()

    yield sesion

    # Se detiene la sesión al terminar la corrida para liberar la JVM.
    sesion.stop()


