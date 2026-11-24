"""Prueba funcional de la capa de persistencia con escritura masiva.

Change C2 (`persistencia-bitacora`), capability `app-persistence` (design.md
D3): la clase `CapaPersistencia` escribe lotes de registros en las tablas delta
mediante operaciones masivas de PySpark (append de un DataFrame de una sola
vez, sin ciclos por fila). Se verifica con Spark local + Delta:

- un lote de varios registros se inserta en una operación masiva y queda
  consultable;
- un fallo de escritura (tabla inexistente) se reporta como error explícito y
  controlado (`ErrorEscrituraPersistencia`), no como excepción críptica.

Usa el catálogo local `spark_catalog` vía un archivo de propiedades temporal
(igual que `test_persistencia_inicializador.py`).
"""

from datetime import datetime

import pytest
from pyspark.sql.types import (
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.errores import ErrorEscrituraPersistencia
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo de Spark local con Delta.
CATALOGO_LOCAL = "spark_catalog"

# Esquema de la bitácora de eventos para construir DataFrames de prueba con los
# tipos exactos de la tabla delta (id/acción no nulos, usuario/detalle/resultado
# nulos, marca de tiempo timestamp).
ESQUEMA_EVENTOS = StructType(
    [
        StructField("id_evento", StringType(), False),
        StructField("marca_tiempo", TimestampType(), False),
        StructField("usuario", StringType(), True),
        StructField("accion", StringType(), False),
        StructField("detalle", StringType(), True),
        StructField("resultado", StringType(), True),
    ]
)


def CrearConfiguracionLocal(tmp_path):
    """Crea una configuración de prueba apuntando al catálogo local de Spark.

    Args:
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        ConfiguracionApp: configuración con `catalogo = spark_catalog`.
    """
    import json

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8")
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def TestEscrituraMasivaInsertaLoteCompleto(sesion_spark, tmp_path):
    """Un lote de varios registros se inserta masivamente y queda consultable."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)

    # Lote de tres eventos con identificadores únicos (evita colisiones entre
    # pruebas que comparten la sesión Spark de la corrida).
    lote = [
        ("lote_e1", datetime(2026, 1, 1, 10, 0, 0), "usuario_a", "accion_1",
         "detalle_1", "ok"),
        ("lote_e2", datetime(2026, 1, 1, 10, 1, 0), "usuario_b", "accion_2",
         None, None),
        ("lote_e3", datetime(2026, 1, 1, 10, 2, 0), None, "accion_3",
         "detalle_3", "parcial"),
    ]
    marco_lote = sesion_spark.createDataFrame(lote, ESQUEMA_EVENTOS)

    # Escritura masiva del lote completo en una sola operación.
    capa.Escribir(marco_lote, "bitacora_eventos")

    # Se releen los tres identificadores escritos.
    nombre_tabla = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"
    presentes = sesion_spark.sql(
        f"SELECT id_evento FROM {nombre_tabla} "
        f"WHERE id_evento IN ('lote_e1', 'lote_e2', 'lote_e3')"
    ).collect()

    assert {fila.id_evento for fila in presentes} == {
        "lote_e1",
        "lote_e2",
        "lote_e3",
    }, "El lote completo debe quedar consultable tras la escritura masiva"


def TestEscrituraEnTablaInexistenteFallaDeFormaControlada(sesion_spark, tmp_path):
    """Escribir en una tabla que no existe se reporta como error controlado."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)

    # Un DataFrame mínimo; el fallo ocurre al resolver la tabla inexistente,
    # antes de escribir, y debe traducirse a ErrorEscrituraPersistencia.
    marco = sesion_spark.createDataFrame([("x",)], ["id_evento"])

    with pytest.raises(ErrorEscrituraPersistencia) as error:
        capa.Escribir(marco, "tabla_que_no_existe")

    assert "tabla_que_no_existe" in error.value.mensaje, (
        "El error controlado debe indicar la tabla destino que falló"
    )
