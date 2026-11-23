"""Pruebas de aceptación del capability `app-persistence`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/changes/persistencia-bitacora/specs/app-persistence/spec.md`:

- Creación idempotente del esquema dedicado:
  - Primera creación del esquema -> TestEscenarioPrimeraCreacionDelEsquema
  - Esquema ya existente -> TestEscenarioEsquemaYaExistente
  - Catálogo inaccesible o inexistente -> TestEscenarioCatalogoInaccesibleOInexistente
- Creación idempotente de tablas delta con propiedades del estándar:
  - Creación inicial de una tabla -> TestEscenarioCreacionInicialDeUnaTabla
  - Re-ejecución sobre tabla existente con datos -> TestEscenarioReEjecucionSobreTablaExistenteConDatos
  - Verificación de propiedades delta -> TestEscenarioVerificacionDePropiedadesDelta
- Capa de persistencia con escritura masiva:
  - Inserción de un lote de registros -> TestEscenarioInsercionDeUnLoteDeRegistros
  - Fallo controlado de escritura -> TestEscenarioFalloControladoDeEscritura
- Integridad de llaves garantizada desde el código:
  - Llave primaria duplicada contra la tabla destino -> TestEscenarioLlavePrimariaDuplicadaContraLaTablaDestino
  - Referencia foránea inexistente -> TestEscenarioReferenciaForaneaInexistente
  - Lote íntegro -> TestEscenarioLoteIntegro

Estas pruebas corren contra Spark local con Delta (fixture `sesion_spark`)
usando el catálogo local `spark_catalog`; la creación real sobre el catálogo
`control` del workspace `andresFree` la verifica la capa integral
(`tests/integrales/test_persistencia_andresfree.py`, marker `free`).
"""

import json
import uuid
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
from control_accesos.persistencia.ddl import (
    ESQUEMA_APLICACION,
    PROPIEDADES_DELTA_OBLIGATORIAS,
)
from control_accesos.persistencia.errores import (
    ErrorEscrituraPersistencia,
    ErrorInicializacionPersistencia,
    ErrorIntegridad,
)
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.persistencia.integridad import (
    ReferenciaForanea,
    VerificadorIntegridad,
)

# Catálogo local de Spark con Delta y nombres calificados de las tablas.
CATALOGO_LOCAL = "spark_catalog"
TABLA_EVENTOS = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"

# Esquema de la bitácora de eventos para construir lotes de prueba.
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

# Esquema de la tabla padre sintética usada en los escenarios de FK.
ESQUEMA_PADRE = StructType(
    [StructField("nombre_usuario", StringType(), False)]
)


def CrearConfiguracionLocal(tmp_path, catalogo=CATALOGO_LOCAL):
    """Crea una configuración de aceptación con el catálogo indicado.

    Args:
        tmp_path (Path): directorio temporal de la prueba.
        catalogo (str): catálogo a configurar.

    Returns:
        ConfiguracionApp: configuración cargada desde el archivo temporal.
    """
    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": catalogo}), encoding="utf-8")
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def Inicializar(sesion_spark, tmp_path, catalogo=CATALOGO_LOCAL):
    """Inicializa la persistencia de aceptación y devuelve sus colaboradores.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.
        catalogo (str): catálogo a configurar.

    Returns:
        tuple: (configuracion, inicializador, capa) listos para las aserciones.
    """
    configuracion = CrearConfiguracionLocal(tmp_path, catalogo)
    inicializador = InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    )
    inicializador.Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return configuracion, inicializador, capa


def ConstruirEvento(sesion_spark, id_evento, usuario="usuario_aceptacion"):
    """Construye un DataFrame de un evento con identificador dado.

    Args:
        sesion_spark: sesión Spark local.
        id_evento (str): identificador del evento.
        usuario (str | None): usuario del evento.

    Returns:
        pyspark.sql.DataFrame: lote de un evento con el esquema de la tabla.
    """
    fila = (
        id_evento,
        datetime(2026, 4, 1, 10, 0, 0),
        usuario,
        "accion_aceptacion",
        "detalle de aceptacion",
        "ok",
    )
    return sesion_spark.createDataFrame([fila], ESQUEMA_EVENTOS)


def TestEscenarioPrimeraCreacionDelEsquema(sesion_spark, tmp_path):
    """Escenario: Primera creación del esquema.

    WHEN se inicializa la persistencia y el esquema no existe en el catálogo
    THEN el sistema crea el esquema y lo deja disponible para las tablas.

    Preparación: se elimina el esquema si una prueba anterior de la corrida lo
    creó (la sesión Spark es compartida), para ejercer de verdad la PRIMERA
    creación.
    """
    sesion_spark.sql(
        f"DROP SCHEMA IF EXISTS {CATALOGO_LOCAL}.{ESQUEMA_APLICACION} CASCADE"
    )

    Inicializar(sesion_spark, tmp_path)

    esquemas = {base.name for base in sesion_spark.catalog.listDatabases()}
    assert ESQUEMA_APLICACION in esquemas
    tablas = {
        tabla.name
        for tabla in sesion_spark.catalog.listTables(ESQUEMA_APLICACION)
    }
    assert {"bitacora_eventos", "bitacora_errores"} <= tablas, (
        "El esquema creado debe quedar disponible para las tablas de la app"
    )


def TestEscenarioEsquemaYaExistente(sesion_spark, tmp_path):
    """Escenario: Esquema ya existente.

    WHEN se inicializa la persistencia y el esquema ya existe
    THEN la inicialización completa sin error y sin modificar el esquema ni
         sus contenidos.
    """
    _, inicializador, _ = Inicializar(sesion_spark, tmp_path)

    # Segunda y tercera inicialización sobre el esquema ya existente.
    inicializador.Inicializar()
    inicializador.Inicializar()

    esquemas = {base.name for base in sesion_spark.catalog.listDatabases()}
    assert ESQUEMA_APLICACION in esquemas, (
        "Re-inicializar no debe eliminar ni alterar el esquema existente"
    )


def TestEscenarioCatalogoInaccesibleOInexistente(sesion_spark, tmp_path):
    """Escenario: Catálogo inaccesible o inexistente.

    WHEN se inicializa la persistencia y el catálogo configurado no existe
    THEN el sistema reporta un error explícito y controlado que indica el
         catálogo y la causa.
    """
    with pytest.raises(ErrorInicializacionPersistencia) as error:
        Inicializar(
            sesion_spark, tmp_path, catalogo="catalogo_inexistente_aceptacion"
        )

    assert "catalogo_inexistente_aceptacion" in error.value.mensaje


def TestEscenarioCreacionInicialDeUnaTabla(sesion_spark, tmp_path):
    """Escenario: Creación inicial de una tabla.

    WHEN se inicializa la persistencia y una tabla de la aplicación no existe
    THEN el sistema la crea como tabla delta con liquid clustering y las
         propiedades CDF, optimizeWrite y autoCompact habilitadas.
    """
    Inicializar(sesion_spark, tmp_path)

    detalle = sesion_spark.sql(f"DESCRIBE DETAIL {TABLA_EVENTOS}").collect()[0]

    assert detalle.format == "delta", "La tabla debe crearse en formato delta"
    assert "marca_tiempo" in (detalle.clusteringColumns or []), (
        "La tabla debe declarar liquid clustering por marca_tiempo"
    )
    propiedades = detalle.properties or {}
    for nombre, valor in PROPIEDADES_DELTA_OBLIGATORIAS:
        assert propiedades.get(nombre) == valor, (
            f"La propiedad '{nombre}' debe quedar habilitada desde la creación"
        )


def TestEscenarioReEjecucionSobreTablaExistenteConDatos(sesion_spark, tmp_path):
    """Escenario: Re-ejecución sobre tabla existente con datos.

    WHEN se inicializa la persistencia y las tablas ya existen con datos
    THEN la inicialización completa sin error y los datos previos permanecen
         intactos y consultables.
    """
    _, inicializador, capa = Inicializar(sesion_spark, tmp_path)

    # Se escribe un dato previo con identificador único.
    id_previo = f"aceptacion_{uuid.uuid4()}"
    capa.Escribir(ConstruirEvento(sesion_spark, id_previo), "bitacora_eventos")

    # Re-ejecución de la inicialización con datos ya presentes.
    inicializador.Inicializar()

    presentes = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} WHERE id_evento = '{id_previo}'"
    ).collect()[0][0]
    assert presentes == 1, "Los datos previos deben permanecer intactos"


def TestEscenarioVerificacionDePropiedadesDelta(sesion_spark, tmp_path):
    """Escenario: Verificación de propiedades delta.

    WHEN se inspeccionan las propiedades de una tabla creada por la aplicación
    THEN CDF, optimizeWrite y autoCompact figuran habilitadas y la tabla
         declara sus columnas de liquid clustering.
    """
    Inicializar(sesion_spark, tmp_path)

    for tabla in (TABLA_EVENTOS, TABLA_ERRORES):
        filas = sesion_spark.sql(f"SHOW TBLPROPERTIES {tabla}").collect()
        propiedades = {fila.key: fila.value for fila in filas}
        for nombre, valor in PROPIEDADES_DELTA_OBLIGATORIAS:
            assert propiedades.get(nombre) == valor, (
                f"'{nombre}' debe figurar habilitada ('{valor}') en {tabla}"
            )

        detalle = sesion_spark.sql(f"DESCRIBE DETAIL {tabla}").collect()[0]
        assert detalle.clusteringColumns, (
            f"La tabla {tabla} debe declarar columnas de liquid clustering"
        )


def TestEscenarioInsercionDeUnLoteDeRegistros(sesion_spark, tmp_path):
    """Escenario: Inserción de un lote de registros.

    WHEN se solicita persistir un lote de registros en una tabla
    THEN el sistema inserta el lote completo en una operación masiva y los
         registros quedan consultables.
    """
    _, _, capa = Inicializar(sesion_spark, tmp_path)

    sufijo = uuid.uuid4()
    identificadores = [f"lote_aceptacion_{sufijo}_{i}" for i in range(3)]
    filas = [
        (
            identificador,
            datetime(2026, 4, 1, 11, 0, indice),
            "usuario_aceptacion",
            "accion_lote",
            None,
            "ok",
        )
        for indice, identificador in enumerate(identificadores)
    ]
    lote = sesion_spark.createDataFrame(filas, ESQUEMA_EVENTOS)

    capa.Escribir(lote, "bitacora_eventos")

    lista_ids = ", ".join(f"'{i}'" for i in identificadores)
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} WHERE id_evento IN ({lista_ids})"
    ).collect()[0][0]
    assert escritos == 3, "El lote completo debe quedar consultable"


def TestEscenarioFalloControladoDeEscritura(sesion_spark, tmp_path):
    """Escenario: Fallo controlado de escritura.

    WHEN la operación de escritura falla por una causa externa (tabla
         inaccesible)
    THEN el sistema reporta un error explícito y controlado con el detalle de
         la causa, sin dejar la operación a medias de forma silenciosa.
    """
    _, _, capa = Inicializar(sesion_spark, tmp_path)

    lote = ConstruirEvento(sesion_spark, f"aceptacion_{uuid.uuid4()}")

    with pytest.raises(ErrorEscrituraPersistencia) as error:
        capa.Escribir(lote, "tabla_inaccesible_aceptacion")

    assert "tabla_inaccesible_aceptacion" in error.value.mensaje


def TestEscenarioLlavePrimariaDuplicadaContraLaTablaDestino(
    sesion_spark, tmp_path
):
    """Escenario: Llave primaria duplicada contra la tabla destino.

    WHEN se solicita escribir un registro cuya llave primaria ya existe en la
         tabla destino
    THEN el sistema rechaza la escritura con un error explícito que identifica
         la llave duplicada y no escribe el lote.
    """
    _, _, capa = Inicializar(sesion_spark, tmp_path)
    verificador = VerificadorIntegridad(sesion=sesion_spark)

    id_duplicado = f"pk_aceptacion_{uuid.uuid4()}"
    capa.EscribirConIntegridad(
        ConstruirEvento(sesion_spark, id_duplicado),
        "bitacora_eventos",
        claves_primarias=("id_evento",),
        verificador=verificador,
    )

    with pytest.raises(ErrorIntegridad) as error:
        capa.EscribirConIntegridad(
            ConstruirEvento(sesion_spark, id_duplicado),
            "bitacora_eventos",
            claves_primarias=("id_evento",),
            verificador=verificador,
        )

    assert id_duplicado in error.value.mensaje
    total = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} WHERE id_evento = '{id_duplicado}'"
    ).collect()[0][0]
    assert total == 1, "Solo debe existir la primera escritura de la llave"


def TestEscenarioReferenciaForaneaInexistente(sesion_spark, tmp_path):
    """Escenario: Referencia foránea inexistente.

    WHEN se solicita escribir un registro cuya llave foránea no existe en la
         tabla padre
    THEN el sistema rechaza la escritura con un error explícito que identifica
         la referencia faltante y no escribe el lote.
    """
    _, _, capa = Inicializar(sesion_spark, tmp_path)
    verificador = VerificadorIntegridad(sesion=sesion_spark)

    # Tabla padre sintética con un único usuario válido.
    tabla_padre = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.padre_aceptacion"
    sesion_spark.sql(
        f"CREATE TABLE IF NOT EXISTS {tabla_padre} "
        f"(nombre_usuario STRING NOT NULL) USING DELTA"
    )
    sesion_spark.createDataFrame(
        [("usuario_valido",)], ESQUEMA_PADRE
    ).write.insertInto(tabla_padre)

    referencias = (
        ReferenciaForanea(
            tabla_padre="padre_aceptacion",
            columnas_hija=("usuario",),
            columnas_padre=("nombre_usuario",),
        ),
    )
    lote_huerfano = ConstruirEvento(
        sesion_spark,
        f"fk_aceptacion_{uuid.uuid4()}",
        usuario="usuario_fantasma",
    )

    with pytest.raises(ErrorIntegridad) as error:
        capa.EscribirConIntegridad(
            lote_huerfano,
            "bitacora_eventos",
            claves_primarias=("id_evento",),
            referencias_foraneas=referencias,
            verificador=verificador,
        )

    assert "usuario_fantasma" in error.value.mensaje


def TestEscenarioLoteIntegro(sesion_spark, tmp_path):
    """Escenario: Lote íntegro.

    WHEN se solicita escribir un lote que cumple la unicidad de llave primaria
         y todas sus referencias foráneas
    THEN el sistema escribe el lote completo y los registros quedan
         consultables.
    """
    _, _, capa = Inicializar(sesion_spark, tmp_path)
    verificador = VerificadorIntegridad(sesion=sesion_spark)

    sufijo = uuid.uuid4()
    identificadores = [f"intero_aceptacion_{sufijo}_{i}" for i in range(2)]
    filas = [
        (
            identificador,
            datetime(2026, 4, 1, 12, 0, indice),
            "usuario_valido",
            "accion_integra",
            None,
            "ok",
        )
        for indice, identificador in enumerate(identificadores)
    ]
    lote = sesion_spark.createDataFrame(filas, ESQUEMA_EVENTOS)

    capa.EscribirConIntegridad(
        lote,
        "bitacora_eventos",
        claves_primarias=("id_evento",),
        verificador=verificador,
    )

    lista_ids = ", ".join(f"'{i}'" for i in identificadores)
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} WHERE id_evento IN ({lista_ids})"
    ).collect()[0][0]
    assert escritos == 2, "El lote íntegro debe escribirse completo"
