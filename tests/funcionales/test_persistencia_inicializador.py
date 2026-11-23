"""Prueba funcional del inicializador de persistencia con Spark local.

Change C2 (`persistencia-bitacora`), capability `app-persistence` (design.md
D3/D4): la clase `InicializadorPersistencia` ejecuta el DDL del esquema
dedicado y de las tablas registradas contra la sesión Spark inyectada. Se
verifica con Spark local + Delta (fixture `sesion_spark`):

- la inicialización crea el esquema `control_acceso_app` y las tablas
  `bitacora_eventos` y `bitacora_errores` con sus columnas (incluido el STRUCT
  del detalle del error);
- la segunda inicialización es idempotente: no falla y conserva los datos
  ya escritos;
- un fallo de la sesión se reporta como error explícito y controlado
  (`ErrorInicializacionPersistencia`), no como excepción críptica.

El catálogo local se fija a `spark_catalog` (el catálogo de sesión de Spark
local con Delta) mediante un archivo de propiedades temporal; así se respeta
el diseño (el catálogo proviene de la configuración inyectada) sin depender de
un catálogo `control` que solo existe en el workspace real (ver design.md,
Risks; la creación real sobre `andresFree` se verifica en la capa integral).
"""

import json

import pytest
from pyspark.sql.types import StructType

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.ddl import (
    DEFINICION_BITACORA_ERRORES,
    DEFINICION_BITACORA_EVENTOS,
    ESQUEMA_APLICACION,
)
from control_accesos.persistencia.errores import ErrorInicializacionPersistencia
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo de Spark local con Delta (a diferencia del `control` del workspace).
CATALOGO_LOCAL = "spark_catalog"


def CrearConfiguracionLocal(tmp_path):
    """Crea una configuración de prueba apuntando al catálogo local de Spark.

    Args:
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        ConfiguracionApp: configuración con `catalogo = spark_catalog`.
    """
    ruta = tmp_path / "app_properties.json"
    ruta.write_text(
        json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8"
    )
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def TestInicializacionCreaEsquemaDedicado(sesion_spark, tmp_path):
    """La inicialización debe crear el esquema dedicado en el catálogo."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    inicializador = InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    )

    inicializador.Inicializar()

    nombres_esquema = {base.name for base in sesion_spark.catalog.listDatabases()}
    assert ESQUEMA_APLICACION in nombres_esquema, (
        f"El esquema dedicado '{ESQUEMA_APLICACION}' debe existir tras la "
        f"inicialización; esquemas presentes: {sorted(nombres_esquema)}"
    )


def TestInicializacionCreaTablasConSusColumnas(sesion_spark, tmp_path):
    """Las tablas de bitácora deben crearse con sus columnas declaradas."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()

    nombres_tabla = {
        tabla.name
        for tabla in sesion_spark.catalog.listTables(ESQUEMA_APLICACION)
    }
    assert {
        DEFINICION_BITACORA_EVENTOS.nombre,
        DEFINICION_BITACORA_ERRORES.nombre,
    } <= nombres_tabla, (
        f"Deben existir las dos bitácoras; tablas presentes: "
        f"{sorted(nombres_tabla)}"
    )

    # La bitácora de eventos debe exponer sus columnas declaradas.
    marco_eventos = sesion_spark.table(
        f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.{DEFINICION_BITACORA_EVENTOS.nombre}"
    )
    columnas_esperadas_eventos = {
        columna.nombre for columna in DEFINICION_BITACORA_EVENTOS.columnas
    }
    assert columnas_esperadas_eventos <= set(marco_eventos.columns), (
        f"La bitácora de eventos debe tener las columnas "
        f"{sorted(columnas_esperadas_eventos)}; tiene {marco_eventos.columns}"
    )


def TestDetalleDeBitacoraErroresEsStruct(sesion_spark, tmp_path):
    """El campo `detalle` de la bitácora de errores debe ser de tipo STRUCT."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()

    marco_errores = sesion_spark.table(
        f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.{DEFINICION_BITACORA_ERRORES.nombre}"
    )
    campo_detalle = next(
        campo for campo in marco_errores.schema.fields if campo.name == "detalle"
    )

    assert isinstance(campo_detalle.dataType, StructType), (
        "El detalle del error debe ser de tipo STRUCT (regla del estándar)"
    )
    nombres_campo_struct = {
        campo.name for campo in campo_detalle.dataType.fields
    }
    assert nombres_campo_struct == {
        "tipo_excepcion",
        "mensaje",
        "traza",
        "contexto",
    }, (
        f"El STRUCT del detalle debe tener los cuatro campos del contrato; "
        f"tiene {sorted(nombres_campo_struct)}"
    )


def TestSegundaInicializacionEsIdempotenteYConservaDatos(
    sesion_spark, tmp_path
):
    """Re-inicializar no falla y conserva los datos ya escritos."""
    configuracion = CrearConfiguracionLocal(tmp_path)
    inicializador = InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    )
    inicializador.Inicializar()

    # Se escribe un evento con un identificador único para poder rastrearlo.
    nombre_eventos = (
        f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}."
        f"{DEFINICION_BITACORA_EVENTOS.nombre}"
    )
    sesion_spark.sql(
        f"INSERT INTO {nombre_eventos} "
        f"(id_evento, marca_tiempo, usuario, accion) "
        f"VALUES ('evento_idempotencia', current_timestamp(), 'usuario_demo', "
        f"'prueba_idempotencia')"
    )

    # Segunda inicialización: no debe fallar (IF NOT EXISTS) ni borrar datos.
    inicializador.Inicializar()

    sigue_presente = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {nombre_eventos} "
        f"WHERE id_evento = 'evento_idempotencia'"
    ).collect()[0]["n"]
    assert sigue_presente == 1, (
        "Tras re-inicializar, el evento escrito previamente debe conservarse "
        "(la creación idempotente no altera los datos existentes)"
    )


def TestFalloDeSesionSeReportaComoErrorControlado(tmp_path):
    """Un fallo de la sesión al ejecutar el DDL se reporta de forma controlada."""
    configuracion = CrearConfiguracionLocal(tmp_path)

    class SesionFalla:
        """Sesión simulada cuya ejecución de SQL falla siempre."""

        def sql(self, sentencia):
            raise RuntimeError("fallo simulado de la sesion Spark")

    inicializador = InicializadorPersistencia(
        sesion=SesionFalla(), configuracion=configuracion
    )

    with pytest.raises(ErrorInicializacionPersistencia) as error:
        inicializador.Inicializar()

    assert "fallo simulado" in error.value.mensaje, (
        "El error controlado debe conservar el detalle de la causa original"
    )
