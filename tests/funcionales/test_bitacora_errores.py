"""Prueba funcional del escritor de la bitácora de errores (capability `audit-logging`).

Change C2 (`persistencia-bitacora`), design.md D6: la clase `BitacoraErrores`
registra todo error controlado vía try/except con el máximo detalle; el campo
`detalle` es de tipo `STRUCT<tipo_excepcion, mensaje, traza, contexto>` (regla
del estándar, README.md). Se verifica con Spark local + Delta:

- un error provocado por una operación que falla queda registrado con el
  STRUCT completo (tipo, mensaje, traza real y contexto);
- cada campo del STRUCT es consultable de forma independiente (sintaxis
  `detalle.campo` de Spark SQL);
- una excepción construida pero nunca lanzada (sin traza) se registra con una
  marca explícita en el campo traza, en lugar de un valor vacío que oculte el
  hecho.
"""

from datetime import datetime

from control_accesos.bitacora.escritores import BitacoraErrores
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo de Spark local con Delta.
CATALOGO_LOCAL = "spark_catalog"

# Nombre calificado de la bitácora de errores para las consultas de prueba.
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"


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


def PrepararBitacoraErrores(sesion_spark, tmp_path):
    """Inicializa la persistencia y devuelve el escritor de errores.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        BitacoraErrores: escritor listo contra la tabla delta local.
    """
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return BitacoraErrores(sesion=sesion_spark, capa=capa)


def OperacionQueFalla():
    """Operación de prueba que siempre falla, para capturar un error real.

    Raises:
        ValueError: error provocado con un mensaje reconocible, lanzado de
            verdad (con traza real generada por el intérprete).
    """
    raise ValueError("fallo provocado por la prueba funcional")


def TestErrorControladoSeRegistraConDetalleStruct(sesion_spark, tmp_path):
    """Un error capturado por try/except se registra con el STRUCT completo."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    # Control del error vía try/except, como exige el estándar del proyecto.
    try:
        OperacionQueFalla()
    except ValueError as excepcion:
        registro = bitacora.Registrar(
            excepcion=excepcion,
            modulo="pruebas_funcionales",
            usuario="usuario_demo@ejemplo.com",
            contexto="verificacion del registro de errores del change C2",
            marca_tiempo=datetime(2026, 1, 20, 11, 0, 0),
        )

    filas = sesion_spark.sql(
        f"SELECT * FROM {TABLA_ERRORES} WHERE id_error = '{registro.id_error}'"
    ).collect()

    assert len(filas) == 1, "El error registrado debe quedar consultable"
    guardado = filas[0]
    assert guardado.modulo == "pruebas_funcionales"
    assert guardado.usuario == "usuario_demo@ejemplo.com"
    assert guardado.marca_tiempo == datetime(2026, 1, 20, 11, 0, 0)

    # El detalle STRUCT debe traer el máximo detalle disponible del error.
    detalle = guardado.detalle
    assert detalle.tipo_excepcion == "ValueError"
    assert detalle.mensaje == "fallo provocado por la prueba funcional"
    assert "OperacionQueFalla" in detalle.traza, (
        "La traza registrada debe ser la traza real de la excepción lanzada"
    )
    assert detalle.contexto == (
        "verificacion del registro de errores del change C2"
    )


def TestCamposDelStructSonConsultablesIndependientemente(sesion_spark, tmp_path):
    """Cada campo del STRUCT debe poder consultarse por separado en SQL."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    try:
        OperacionQueFalla()
    except ValueError as excepcion:
        registro = bitacora.Registrar(
            excepcion=excepcion,
            modulo="modulo_de_prueba",
            contexto="consulta por campos del struct",
        )

    # Proyección de cada campo del STRUCT por separado (sintaxis punto).
    fila = sesion_spark.sql(
        f"SELECT detalle.tipo_excepcion AS tipo, "
        f"detalle.mensaje AS mensaje, "
        f"detalle.traza AS traza, "
        f"detalle.contexto AS contexto "
        f"FROM {TABLA_ERRORES} WHERE id_error = '{registro.id_error}'"
    ).collect()[0]

    assert fila.tipo == "ValueError"
    assert fila.mensaje == "fallo provocado por la prueba funcional"
    assert "OperacionQueFalla" in fila.traza
    assert fila.contexto == "consulta por campos del struct"


def TestExcepcionSinTrazaSeRegistraConMarcaExplicita(sesion_spark, tmp_path):
    """Una excepción nunca lanzada deja constancia explícita en la traza."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    # Excepción construida a mano, sin lanzarse: no tiene traceback real.
    excepcion_sin_traza = RuntimeError("error sin lanzamiento real")
    registro = bitacora.Registrar(
        excepcion=excepcion_sin_traza,
        modulo="modulo_de_prueba",
        contexto="excepcion construida sin lanzar",
    )

    fila = sesion_spark.sql(
        f"SELECT detalle.traza AS traza FROM {TABLA_ERRORES} "
        f"WHERE id_error = '{registro.id_error}'"
    ).collect()[0]

    assert fila.traza and "sin traza disponible" in fila.traza.lower(), (
        "La traza no debe quedar vacía ni engañosa cuando la excepción nunca "
        "se lanzó; debe declararse explícitamente"
    )
