"""Prueba funcional de los helpers de integridad de llaves (capability `app-persistence`).

Change C2 (`persistencia-bitacora`), design.md D5: Delta no enforcea llave
primaria ni foráneas, así que la aplicación las garantiza desde el código con
operaciones masivas de PySpark (groupBy/anti-join/semi-join), ANTES de
escribir. Se verifica con Spark local + Delta:

- PK duplicada dentro del lote → rechazada con `ErrorIntegridad` y detalle de
  las llaves duplicadas;
- PK duplicada contra la tabla destino → rechazada con el mismo error;
- referencia FK inexistente en la tabla padre → rechazada identificando la
  referencia faltante;
- en toda violación NO se escribe ningún registro del lote;
- un lote íntegro se escribe completo.
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
from control_accesos.persistencia.errores import ErrorIntegridad
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.persistencia.integridad import (
    ReferenciaForanea,
    VerificadorIntegridad,
)

# Catálogo de Spark local con Delta.
CATALOGO_LOCAL = "spark_catalog"

# Esquema de la bitácora de eventos (tabla hija de las pruebas de FK: se usa
# `usuario` como columna con referencia foránea de ejemplo hacia una tabla
# padre creada por la prueba).
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

# Esquema de la tabla padre de prueba para las referencias foráneas.
ESQUEMA_PADRE = StructType([StructField("nombre_usuario", StringType(), False)])

# Columnas de la llave primaria de la bitácora de eventos.
CLAVE_PRIMARIA_EVENTOS = ("id_evento",)


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


def PrepararPersistencia(sesion_spark, tmp_path):
    """Inicializa esquema/tablas y devuelve configuración, capa y verificador.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        tuple: (configuracion, capa, verificador) listos para las aserciones.
    """
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    verificador = VerificadorIntegridad(sesion=sesion_spark)
    return configuracion, capa, verificador


def ConstruirLoteEventos(sesion_spark, identificadores, usuario="usuario_ok"):
    """Construye un DataFrame de eventos con los identificadores indicados.

    Args:
        sesion_spark: sesión Spark local.
        identificadores (list[str]): valores de `id_evento` del lote.
        usuario (str): valor de la columna `usuario` (referencia foránea de
            las pruebas).

    Returns:
        pyspark.sql.DataFrame: lote de eventos con el esquema de la tabla.
    """
    filas = [
        (
            identificador,
            datetime(2026, 1, 1, 12, 0, 0),
            usuario,
            "accion_prueba",
            None,
            None,
        )
        for identificador in identificadores
    ]
    return sesion_spark.createDataFrame(filas, ESQUEMA_EVENTOS)


def NombreTabla(nombre):
    """Nombre calificado de una tabla del esquema dedicado local.

    Args:
        nombre (str): nombre de la tabla.

    Returns:
        str: nombre calificado `<catalogo>.<esquema>.<tabla>`.
    """
    return f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.{nombre}"


def TestLoteIntegroSeEscribeCompleto(sesion_spark, tmp_path):
    """Un lote sin violaciones pasa la verificación y se escribe completo."""
    _, capa, verificador = PrepararPersistencia(sesion_spark, tmp_path)
    lote = ConstruirLoteEventos(sesion_spark, ["integridad_ok_1", "integridad_ok_2"])

    capa.EscribirConIntegridad(
        lote,
        "bitacora_eventos",
        claves_primarias=CLAVE_PRIMARIA_EVENTOS,
        verificador=verificador,
    )

    escritos = sesion_spark.sql(
        f"SELECT id_evento FROM {NombreTabla('bitacora_eventos')} "
        f"WHERE id_evento LIKE 'integridad_ok_%'"
    ).collect()
    assert {fila.id_evento for fila in escritos} == {
        "integridad_ok_1",
        "integridad_ok_2",
    }, "El lote íntegro debe escribirse completo"


def TestPkDuplicadaDentroDelLoteEsRechazada(sesion_spark, tmp_path):
    """Dos registros con la misma PK en el lote violan la unicidad."""
    _, capa, verificador = PrepararPersistencia(sesion_spark, tmp_path)
    lote = ConstruirLoteEventos(sesion_spark, ["pk_duplicada_1", "pk_duplicada_1"])

    with pytest.raises(ErrorIntegridad) as error:
        capa.EscribirConIntegridad(
            lote,
            "bitacora_eventos",
            claves_primarias=CLAVE_PRIMARIA_EVENTOS,
            verificador=verificador,
        )

    assert "pk_duplicada_1" in error.value.mensaje, (
        "El error debe identificar la llave primaria duplicada"
    )
    # Ningún registro del lote debe haberse escrito.
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {NombreTabla('bitacora_eventos')} "
        f"WHERE id_evento = 'pk_duplicada_1'"
    ).collect()[0]["n"]
    assert escritos == 0, "Ante la violación no se escribe ningún registro"


def TestPkDuplicadaContraTablaDestinoEsRechazada(sesion_spark, tmp_path):
    """Una PK ya existente en la tabla destino rechaza el nuevo lote."""
    _, capa, verificador = PrepararPersistencia(sesion_spark, tmp_path)

    # Primer lote: escribe la llave en la tabla destino.
    primer_lote = ConstruirLoteEventos(sesion_spark, ["pk_destino_1"])
    capa.EscribirConIntegridad(
        primer_lote,
        "bitacora_eventos",
        claves_primarias=CLAVE_PRIMARIA_EVENTOS,
        verificador=verificador,
    )

    # Segundo lote: repite la misma llave primaria.
    segundo_lote = ConstruirLoteEventos(sesion_spark, ["pk_destino_1", "pk_destino_2"])
    with pytest.raises(ErrorIntegridad) as error:
        capa.EscribirConIntegridad(
            segundo_lote,
            "bitacora_eventos",
            claves_primarias=CLAVE_PRIMARIA_EVENTOS,
            verificador=verificador,
        )

    assert "pk_destino_1" in error.value.mensaje, (
        "El error debe identificar la llave duplicada contra la tabla destino"
    )
    # El segundo lote completo queda sin escribir (ni siquiera su fila íntegra).
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {NombreTabla('bitacora_eventos')} "
        f"WHERE id_evento = 'pk_destino_2'"
    ).collect()[0]["n"]
    assert escritos == 0, "Ante la violación no se escribe ningún registro del lote"


def TestReferenciaForaneaInexistenteEsRechazada(sesion_spark, tmp_path):
    """Una FK que no existe en la tabla padre rechaza la escritura del lote."""
    _, capa, verificador = PrepararPersistencia(sesion_spark, tmp_path)

    # Tabla padre de prueba con un único usuario válido.
    sesion_spark.sql(
        f"CREATE TABLE IF NOT EXISTS {NombreTabla('padre_usuarios_prueba')} "
        f"(nombre_usuario STRING NOT NULL) USING DELTA"
    )
    padre = sesion_spark.createDataFrame([("usuario_ok",)], ESQUEMA_PADRE)
    padre.write.insertInto(NombreTabla("padre_usuarios_prueba"))

    referencias = (
        ReferenciaForanea(
            tabla_padre="padre_usuarios_prueba",
            columnas_hija=("usuario",),
            columnas_padre=("nombre_usuario",),
        ),
    )

    # Lote cuyo usuario NO existe en la tabla padre.
    lote = ConstruirLoteEventos(
        sesion_spark, ["fk_inexistente_1"], usuario="usuario_fantasma"
    )
    with pytest.raises(ErrorIntegridad) as error:
        capa.EscribirConIntegridad(
            lote,
            "bitacora_eventos",
            claves_primarias=CLAVE_PRIMARIA_EVENTOS,
            referencias_foraneas=referencias,
            verificador=verificador,
        )

    assert "usuario_fantasma" in error.value.mensaje, (
        "El error debe identificar la referencia foránea faltante"
    )
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {NombreTabla('bitacora_eventos')} "
        f"WHERE id_evento = 'fk_inexistente_1'"
    ).collect()[0]["n"]
    assert escritos == 0, "Ante la violación de FK no se escribe ningún registro"


def TestReferenciaForaneaValidaSeEscribe(sesion_spark, tmp_path):
    """Una FK presente en la tabla padre permite escribir el lote completo."""
    _, capa, verificador = PrepararPersistencia(sesion_spark, tmp_path)

    sesion_spark.sql(
        f"CREATE TABLE IF NOT EXISTS {NombreTabla('padre_usuarios_prueba')} "
        f"(nombre_usuario STRING NOT NULL) USING DELTA"
    )
    padre = sesion_spark.createDataFrame([("usuario_ok",)], ESQUEMA_PADRE)
    padre.write.insertInto(NombreTabla("padre_usuarios_prueba"))

    referencias = (
        ReferenciaForanea(
            tabla_padre="padre_usuarios_prueba",
            columnas_hija=("usuario",),
            columnas_padre=("nombre_usuario",),
        ),
    )

    lote = ConstruirLoteEventos(sesion_spark, ["fk_valida_1"], usuario="usuario_ok")
    capa.EscribirConIntegridad(
        lote,
        "bitacora_eventos",
        claves_primarias=CLAVE_PRIMARIA_EVENTOS,
        referencias_foraneas=referencias,
        verificador=verificador,
    )

    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {NombreTabla('bitacora_eventos')} "
        f"WHERE id_evento = 'fk_valida_1'"
    ).collect()[0]["n"]
    assert escritos == 1, "El lote con FK válida debe escribirse completo"
