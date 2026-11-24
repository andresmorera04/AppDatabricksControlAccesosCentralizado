"""Pruebas de aceptación del capability `audit-logging`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/changes/persistencia-bitacora/specs/audit-logging/spec.md`:

- Registro de eventos generales con usuario:
  - Evento con usuario identificado -> TestEscenarioEventoConUsuarioIdentificado
  - Evento sin identidad de usuario disponible -> TestEscenarioEventoSinIdentidadDeUsuarioDisponible
  - Actividad completa consultable -> TestEscenarioActividadCompletaConsultable
- Registro de errores con detalle estructurado:
  - Error controlado registrado con detalle estructurado -> TestEscenarioErrorControladoRegistradoConDetalleEstructurado
  - Detalle del error consultable por campos -> TestEscenarioDetalleDelErrorConsultablePorCampos
- Bitácoras como tablas delta del esquema dedicado:
  - Creación idempotente de las bitácoras -> TestEscenarioCreacionIdempotenteDeLasBitacoras
  - Escritura masiva de eventos -> TestEscenarioEscrituraMasivaDeEventos
- Degradación controlada ante fallo de la propia bitácora:
  - Fallo al escribir la bitácora de errores -> TestEscenarioFalloAlEscribirLaBitacoraDeErrores

Las pruebas con escritura corren contra Spark local con Delta (fixture
`sesion_spark`) sobre el catálogo local `spark_catalog`; el escenario de
degradación usa destino simulado y no requiere Spark.
"""

import json
from datetime import datetime

import pytest
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from control_accesos.bitacora.escritores import (
    BitacoraErrores,
    BitacoraEventos,
)
from control_accesos.bitacora.modelos import EventoBitacora
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.errores import ErrorEscrituraPersistencia
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo local y tablas calificadas de las bitácoras.
CATALOGO_LOCAL = "spark_catalog"
TABLA_EVENTOS = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"

# Esquema simulado de la bitácora de errores para el escenario de degradación
# (pyspark.sql.types es Python puro: no requiere JVM ni sesión Spark).
ESQUEMA_ERRORES_SIMULADO = StructType(
    [
        StructField("id_error", StringType(), False),
        StructField("marca_tiempo", TimestampType(), False),
        StructField("usuario", StringType(), True),
        StructField("modulo", StringType(), False),
        StructField("detalle", StringType(), False),
    ]
)


def CrearConfiguracionLocal(tmp_path):
    """Crea una configuración de aceptación apuntando al catálogo local.

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


def PrepararBitacoras(sesion_spark, tmp_path):
    """Inicializa la persistencia y devuelve los dos escritores de bitácora.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        tuple: (bitacora_eventos, bitacora_errores, inicializador).
    """
    configuracion = CrearConfiguracionLocal(tmp_path)
    inicializador = InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    )
    inicializador.Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return (
        BitacoraEventos(sesion=sesion_spark, capa=capa),
        BitacoraErrores(sesion=sesion_spark, capa=capa),
        inicializador,
    )


def OperacionQueFalla():
    """Operación de aceptación que siempre falla con un error reconocible.

    Raises:
        PermissionError: error provocado con mensaje reconocible, lanzado de
            verdad (con traza real generada por el intérprete).
    """
    raise PermissionError("privilegios insuficientes sobre el catalogo")


def TestEscenarioEventoConUsuarioIdentificado(sesion_spark, tmp_path):
    """Escenario: Evento con usuario identificado.

    WHEN ocurre un evento provocado por un usuario cuya identidad está
         disponible
    THEN el sistema registra el evento con ese usuario, la acción, el detalle,
         el resultado y su marca de tiempo.
    """
    bitacora_eventos, _, _ = PrepararBitacoras(sesion_spark, tmp_path)

    evento = bitacora_eventos.Registrar(
        accion="otorgar_select",
        usuario="andresmorera04@gmail.com",
        detalle="grant 1 a 1 sobre tabla del catalogo control",
        resultado="otorgado",
        marca_tiempo=datetime(2026, 5, 1, 9, 0, 0),
    )

    fila = sesion_spark.sql(
        f"SELECT * FROM {TABLA_EVENTOS} WHERE id_evento = '{evento.id_evento}'"
    ).collect()[0]
    assert fila.usuario == "andresmorera04@gmail.com"
    assert fila.accion == "otorgar_select"
    assert fila.detalle == "grant 1 a 1 sobre tabla del catalogo control"
    assert fila.resultado == "otorgado"
    assert fila.marca_tiempo == datetime(2026, 5, 1, 9, 0, 0)


def TestEscenarioEventoSinIdentidadDeUsuarioDisponible(sesion_spark, tmp_path):
    """Escenario: Evento sin identidad de usuario disponible.

    WHEN ocurre un evento antes de que exista identidad on-behalf-of
    THEN el sistema registra el evento con el campo de usuario explícitamente
         sin valor, sin rechazar el evento.
    """
    bitacora_eventos, _, _ = PrepararBitacoras(sesion_spark, tmp_path)

    # Sin usuario: la identidad OBO llega en C3; el evento NO se rechaza.
    evento = bitacora_eventos.Registrar(
        accion="inicializar_persistencia", resultado="ok"
    )

    fila = sesion_spark.sql(
        f"SELECT usuario FROM {TABLA_EVENTOS} "
        f"WHERE id_evento = '{evento.id_evento}'"
    ).collect()[0]
    assert fila.usuario is None, (
        "El usuario debe quedar explícitamente sin valor (nulo), nunca con un "
        "marcador hardcodeado"
    )


def TestEscenarioActividadCompletaConsultable(sesion_spark, tmp_path):
    """Escenario: Actividad completa consultable.

    WHEN se consulta la bitácora tras varias acciones de la aplicación
    THEN cada acción figura como un evento con su usuario, acción, detalle,
         resultado y marca de tiempo, ordenables cronológicamente.
    """
    bitacora_eventos, _, _ = PrepararBitacoras(sesion_spark, tmp_path)

    # Tres acciones registradas fuera de orden cronológico.
    acciones = [
        ("accion_tardia", datetime(2026, 5, 2, 12, 0, 0)),
        ("accion_temprana", datetime(2026, 5, 2, 8, 0, 0)),
        ("accion_media", datetime(2026, 5, 2, 10, 0, 0)),
    ]
    eventos = [
        bitacora_eventos.Registrar(
            accion=accion,
            usuario="usuario_demo",
            detalle=f"detalle de {accion}",
            resultado="ok",
            marca_tiempo=marca,
        )
        for accion, marca in acciones
    ]

    lista_ids = ", ".join(f"'{e.id_evento}'" for e in eventos)
    filas = sesion_spark.sql(
        f"SELECT accion, usuario, detalle, resultado, marca_tiempo "
        f"FROM {TABLA_EVENTOS} WHERE id_evento IN ({lista_ids}) "
        f"ORDER BY marca_tiempo ASC"
    ).collect()

    assert [fila.accion for fila in filas] == [
        "accion_temprana",
        "accion_media",
        "accion_tardia",
    ]
    for fila in filas:
        assert fila.usuario == "usuario_demo"
        assert fila.resultado == "ok"
        assert fila.detalle == f"detalle de {fila.accion}"


def TestEscenarioErrorControladoRegistradoConDetalleEstructurado(
    sesion_spark, tmp_path
):
    """Escenario: Error controlado registrado con detalle estructurado.

    WHEN una operación falla y el error es capturado por try/except
    THEN el sistema lo registra con el detalle STRUCT poblado con tipo de
         excepción, mensaje, traza y contexto.
    """
    _, bitacora_errores, _ = PrepararBitacoras(sesion_spark, tmp_path)

    try:
        OperacionQueFalla()
    except PermissionError as excepcion:
        registro = bitacora_errores.Registrar(
            excepcion=excepcion,
            modulo="canal_datos",
            usuario="usuario_demo",
            contexto="otorgando SELECT sobre tabla del catalogo control",
            marca_tiempo=datetime(2026, 5, 3, 15, 30, 0),
        )

    fila = sesion_spark.sql(
        f"SELECT * FROM {TABLA_ERRORES} WHERE id_error = '{registro.id_error}'"
    ).collect()[0]
    assert fila.modulo == "canal_datos"
    assert fila.usuario == "usuario_demo"
    assert fila.detalle.tipo_excepcion == "PermissionError"
    assert fila.detalle.mensaje == "privilegios insuficientes sobre el catalogo"
    assert "OperacionQueFalla" in fila.detalle.traza
    assert fila.detalle.contexto == (
        "otorgando SELECT sobre tabla del catalogo control"
    )


def TestEscenarioDetalleDelErrorConsultablePorCampos(sesion_spark, tmp_path):
    """Escenario: Detalle del error consultable por campos.

    WHEN se consulta el detalle de un error registrado
    THEN cada componente del STRUCT es accesible de forma independiente.
    """
    _, bitacora_errores, _ = PrepararBitacoras(sesion_spark, tmp_path)

    try:
        OperacionQueFalla()
    except PermissionError as excepcion:
        registro = bitacora_errores.Registrar(
            excepcion=excepcion, modulo="pre_flight", contexto="validando"
        )

    fila = sesion_spark.sql(
        f"SELECT detalle.tipo_excepcion AS tipo, detalle.mensaje AS mensaje, "
        f"detalle.traza AS traza, detalle.contexto AS contexto "
        f"FROM {TABLA_ERRORES} WHERE id_error = '{registro.id_error}'"
    ).collect()[0]

    assert fila.tipo == "PermissionError"
    assert fila.mensaje == "privilegios insuficientes sobre el catalogo"
    assert "OperacionQueFalla" in fila.traza
    assert fila.contexto == "validando"


def TestEscenarioCreacionIdempotenteDeLasBitacoras(sesion_spark, tmp_path):
    """Escenario: Creación idempotente de las bitácoras.

    WHEN se inicializa la persistencia y las tablas de bitácora ya existen
    THEN la inicialización completa sin error y los registros históricos
         permanecen intactos.
    """
    bitacora_eventos, _, inicializador = PrepararBitacoras(
        sesion_spark, tmp_path
    )

    # Registro histórico previo a la re-inicialización.
    evento = bitacora_eventos.Registrar(
        accion="historico_previo", resultado="ok"
    )

    # Re-inicialización con las bitácoras ya creadas y con datos.
    inicializador.Inicializar()

    presentes = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} "
        f"WHERE id_evento = '{evento.id_evento}'"
    ).collect()[0][0]
    assert presentes == 1, "Los registros históricos deben permanecer intactos"


def TestEscenarioEscrituraMasivaDeEventos(sesion_spark, tmp_path):
    """Escenario: Escritura masiva de eventos.

    WHEN se solicita registrar un lote de varios eventos
    THEN el sistema los escribe en una operación masiva, sin ciclos por fila.
    """
    bitacora_eventos, _, _ = PrepararBitacoras(sesion_spark, tmp_path)

    lote = tuple(
        EventoBitacora(
            accion=f"accion_masiva_{indice}",
            usuario="usuario_demo",
            resultado="ok",
            marca_tiempo=datetime(2026, 5, 4, 8, 0, indice),
        )
        for indice in range(10)
    )

    registrados = bitacora_eventos.RegistrarLote(lote)

    assert len(registrados) == 10
    lista_ids = ", ".join(f"'{e.id_evento}'" for e in registrados)
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) FROM {TABLA_EVENTOS} WHERE id_evento IN ({lista_ids})"
    ).collect()[0][0]
    assert escritos == 10, "El lote completo debe escribirse en la operación"


class TablaSimulada:
    """Tabla simulada que solo expone su esquema (escenario de degradación)."""

    def __init__(self, esquema):
        self.schema = esquema


class SesionSimulada:
    """Sesión simulada para el escenario de degradación (sin Spark real)."""

    def table(self, nombre_calificado):
        return TablaSimulada(ESQUEMA_ERRORES_SIMULADO)

    def createDataFrame(self, filas, esquema):
        return object()


class CapaSimuladaCaida:
    """Capa de persistencia simulada cuya escritura falla siempre."""

    def __init__(self):
        self.intentos = 0

    def NombreTablaCalificado(self, nombre_tabla):
        return f"simulado.{ESQUEMA_APLICACION}.{nombre_tabla}"

    def EscribirConIntegridad(self, marco, nombre_tabla, claves_primarias=()):
        self.intentos += 1
        raise ErrorEscrituraPersistencia("tabla de errores inaccesible")


def TestEscenarioFalloAlEscribirLaBitacoraDeErrores(capsys):
    """Escenario: Fallo al escribir la bitácora de errores.

    WHEN el registro de un error en la bitácora de errores falla por causa
         externa
    THEN el sistema deja constancia visible del fallo en la salida local y la
         ejecución continúa sin excepción no controlada ni reintentos
         recursivos.
    """
    capa_caida = CapaSimuladaCaida()
    bitacora_errores = BitacoraErrores(
        sesion=SesionSimulada(), capa=capa_caida
    )

    try:
        OperacionQueFalla()
    except PermissionError as excepcion:
        # NO debe propagar excepción: la ejecución principal continúa.
        registro = bitacora_errores.Registrar(
            excepcion=excepcion, modulo="canal_datos", contexto="otorgando"
        )

    assert registro.detalle.tipo_excepcion == "PermissionError"
    salida_local = capsys.readouterr().err
    assert "tabla de errores inaccesible" in salida_local, (
        "El fallo debe quedar visible en la salida local (stderr)"
    )
    assert capa_caida.intentos == 1, (
        "No debe haber reintentos recursivos: exactamente un intento de "
        "escritura fallido"
    )
