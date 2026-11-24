"""Prueba funcional del escritor de la bitácora de eventos (capability `audit-logging`).

Change C2 (`persistencia-bitacora`), design.md D6: la clase `BitacoraEventos`
construye modelos de registro explícitos (`EventoBitacora`) y los escribe de
forma masiva vía la capa de persistencia, con verificación de llave primaria.
Se verifica con Spark local + Delta:

- un evento con usuario registra todos sus campos;
- un evento sin identidad OBO se registra con el usuario explícitamente sin
  valor (el campo existe y queda nulo; el evento NO se rechaza — la identidad
  real llega en C3);
- varios eventos se escriben en lote (una operación masiva);
- la actividad queda consultable y ordenable cronológicamente por
  `marca_tiempo`.
"""

from datetime import datetime

from control_accesos.bitacora.escritores import BitacoraEventos
from control_accesos.bitacora.modelos import EventoBitacora
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo de Spark local con Delta.
CATALOGO_LOCAL = "spark_catalog"

# Nombre calificado de la bitácora de eventos para las consultas de prueba.
TABLA_EVENTOS = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"


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


def PrepararBitacoraEventos(sesion_spark, tmp_path):
    """Inicializa la persistencia y devuelve el escritor de eventos.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        BitacoraEventos: escritor listo contra la tabla delta local.
    """
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return BitacoraEventos(sesion=sesion_spark, capa=capa)


def TestEventoConUsuarioRegistraTodosSusCampos(sesion_spark, tmp_path):
    """Un evento con usuario debe registrar todos sus campos en la tabla."""
    bitacora = PrepararBitacoraEventos(sesion_spark, tmp_path)

    evento = bitacora.Registrar(
        accion="otorgar_privilegios",
        usuario="usuario_demo@ejemplo.com",
        detalle="solicitud 1 a 1 sobre catalogo ventas",
        resultado="otorgado",
        marca_tiempo=datetime(2026, 1, 15, 9, 30, 0),
    )

    filas = sesion_spark.sql(
        f"SELECT * FROM {TABLA_EVENTOS} WHERE id_evento = '{evento.id_evento}'"
    ).collect()

    assert len(filas) == 1, "El evento registrado debe quedar consultable"
    registrado = filas[0]
    assert registrado.accion == "otorgar_privilegios"
    assert registrado.usuario == "usuario_demo@ejemplo.com"
    assert registrado.detalle == "solicitud 1 a 1 sobre catalogo ventas"
    assert registrado.resultado == "otorgado"
    assert registrado.marca_tiempo == datetime(2026, 1, 15, 9, 30, 0)
    assert registrado.id_evento == evento.id_evento


def TestEventoSinIdentidadSeRegistraConUsuarioVacio(sesion_spark, tmp_path):
    """Un evento sin identidad OBO se registra con el usuario sin valor."""
    bitacora = PrepararBitacoraEventos(sesion_spark, tmp_path)

    # No se pasa usuario: hasta C3 no existe identidad on-behalf-of. El evento
    # NO debe rechazarse y el campo debe quedar explícitamente nulo.
    evento = bitacora.Registrar(
        accion="inicializar_persistencia",
        detalle="arranque de la aplicacion",
        resultado="ok",
    )

    filas = sesion_spark.sql(
        f"SELECT usuario FROM {TABLA_EVENTOS} "
        f"WHERE id_evento = '{evento.id_evento}'"
    ).collect()

    assert len(filas) == 1, "El evento sin usuario debe registrarse igual"
    assert filas[0].usuario is None, (
        "El campo usuario debe quedar explícitamente sin valor (nulo), no con "
        "un marcador hardcodeado"
    )


def TestVariosEventosSeEscribenEnLote(sesion_spark, tmp_path):
    """Un lote de eventos se escribe en una sola operación masiva."""
    bitacora = PrepararBitacoraEventos(sesion_spark, tmp_path)

    lote = tuple(
        EventoBitacora(
            accion=f"accion_lote_{indice}",
            usuario=f"usuario_{indice}",
            detalle=f"detalle del evento {indice}",
            resultado="ok",
            marca_tiempo=datetime(2026, 2, 1, 8, 0, indice),
        )
        for indice in range(5)
    )

    registrados = bitacora.RegistrarLote(lote)

    assert len(registrados) == 5, "El escritor debe devolver los 5 eventos"
    identificadores = ", ".join(
        f"'{evento.id_evento}'" for evento in registrados
    )
    escritos = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {TABLA_EVENTOS} "
        f"WHERE id_evento IN ({identificadores})"
    ).collect()[0]["n"]
    assert escritos == 5, "Los cinco eventos del lote deben quedar escritos"


def TestActividadOrdenablePorMarcaTiempo(sesion_spark, tmp_path):
    """La actividad registrada debe poder ordenarse cronológicamente."""
    bitacora = PrepararBitacoraEventos(sesion_spark, tmp_path)

    # Se registran deliberadamente fuera de orden cronológico.
    primero = bitacora.Registrar(
        accion="evento_temprano",
        marca_tiempo=datetime(2026, 3, 1, 8, 0, 0),
    )
    tercero = bitacora.Registrar(
        accion="evento_tardio",
        marca_tiempo=datetime(2026, 3, 1, 10, 0, 0),
    )
    segundo = bitacora.Registrar(
        accion="evento_intermedio",
        marca_tiempo=datetime(2026, 3, 1, 9, 0, 0),
    )

    identificadores = ", ".join(
        f"'{evento.id_evento}'" for evento in (primero, segundo, tercero)
    )
    acciones_ordenadas = [
        fila.accion
        for fila in sesion_spark.sql(
            f"SELECT accion FROM {TABLA_EVENTOS} "
            f"WHERE id_evento IN ({identificadores}) "
            f"ORDER BY marca_tiempo ASC"
        ).collect()
    ]

    assert acciones_ordenadas == [
        "evento_temprano",
        "evento_intermedio",
        "evento_tardio",
    ], "La consulta ordenada por marca_tiempo debe devolver la cronología real"
