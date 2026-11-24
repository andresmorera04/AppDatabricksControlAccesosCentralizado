"""Prueba funcional de humo de la sesión Spark local con Delta Lake.

Change C2 (`persistencia-bitacora`), tarea de infraestructura (design.md D3/D8):
antes de construir la capa de persistencia, esta prueba verifica que el entorno
local puede arrancar una sesión Spark con soporte Delta y crear/leer una tabla
delta real en un directorio temporal. Es la base de todas las pruebas
funcionales del change (inicializador de esquemas/tablas, escritores de
bitácora, helpers de integridad).

La sesión la provee la fixture compartida `sesion_spark` del `conftest.py` de la
raíz (scope de sesión: se arranca una sola vez para toda la corrida).
"""


def TestSesionSparkLocalCreaYLeeTablaDelta(sesion_spark, tmp_path):
    """La sesión Spark local debe crear y leer una tabla delta en disco."""
    # Ruta temporal de la tabla delta (aislada por prueba vía tmp_path).
    ruta_tabla = tmp_path / "tabla_humo_delta"

    # Lote pequeño de datos de prueba: (id, nombre).
    datos = [(1, "alfa"), (2, "beta"), (3, "gamma")]

    # Se construye un DataFrame y se escribe en formato delta (operación
    # masiva, sin ciclos por fila).
    marco = sesion_spark.createDataFrame(datos, ["id", "nombre"])
    marco.write.format("delta").mode("overwrite").save(str(ruta_tabla))

    # Se relee la tabla delta escrita y se verifica el contenido.
    marco_leido = sesion_spark.read.format("delta").load(str(ruta_tabla))

    assert marco_leido.count() == 3, (
        "La tabla delta releída debe contener los 3 registros escritos"
    )
    assert {fila.id for fila in marco_leido.collect()} == {1, 2, 3}, (
        "Los identificadores escritos deben coincidir con los releídos"
    )
