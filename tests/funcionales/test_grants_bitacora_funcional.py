"""Prueba funcional de la auditoría del canal SQL real (capabilities
`uc-data-object-grants` y `uc-external-object-grants`).

Verifica con Spark local y los escritores reales de bitácora (design D6) que,
al procesar una solicitud por el canal SQL real —sobre los objetos de C4 y sobre
los objetos externos de C6 (external location y connection)—:

- el evento queda registrado en `bitacora_eventos` con el `usuario` del llamante
  on-behalf-of y el desglose de estados por ítem;
- un fallo de la sesión SQL durante la ejecución queda registrado en
  `bitacora_errores` con su detalle (STRUCT) y el módulo `canal_sql`.

La sesión SQL es un doble que imita las respuestas del motor real; los
escritores de bitácora operan sobre las tablas delta locales que crea el
inicializador de persistencia (C2).
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.bitacora.escritores import BitacoraErrores, BitacoraEventos
from control_accesos.canales.reales.canal_sql_datos import (
    MODULO_BITACORA_ERRORES,
    CanalSqlDatos,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal, SolicitudGrant
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.pipeline.pipeline_grants import PipelineGrants

# Catálogo de Spark local y tablas delta de bitácora para las consultas.
CATALOGO_LOCAL = "spark_catalog"
TABLA_EVENTOS = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"

# Beneficiario de las pruebas, con forma de correo (como reporta Unity Catalog).
BENEFICIARIO = "beneficiario@example.com"

# Objeto del plano de datos sobre el que se otorga.
OBJETO = ObjetoSecurable(
    identificador="control.prod.ventas", tipo=TipoObjeto.TABLA_DELTA
)


class ErrorMotorSql(RuntimeError):
    """Excepción con la forma del error que reporta el motor SQL real."""


class SesionSqlImitada:
    """Sesión SQL que imita al motor real para las pruebas de auditoría."""

    def __init__(self):
        self.sentencias_ejecutadas = []
        self._filas_show_grant = {}
        self._errores_por_prefijo = []

    def ConfigurarShowGrant(self, objeto, filas):
        """Fija las filas que SHOW GRANT devuelve para el objeto."""
        sentencia = CanalSqlDatos.ConstruirShowGrant(objeto)
        self._filas_show_grant[sentencia] = list(filas)

    def ConfigurarErrorEn(self, prefijo, error):
        """Configura un error para las sentencias cuyo texto empieza por prefijo."""
        self._errores_por_prefijo.append((prefijo, error))

    def sql(self, sentencia):
        """Registra la sentencia y responde según la configuración."""
        self.sentencias_ejecutadas.append(sentencia)
        for prefijo, error in self._errores_por_prefijo:
            if sentencia.startswith(prefijo):
                raise error
        if sentencia.startswith("SHOW GRANT"):
            return list(self._filas_show_grant.get(sentencia, []))
        return []


def CrearConfiguracionLocal(tmp_path):
    """Crea una configuración de prueba apuntando al catálogo local de Spark."""
    import json

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8")
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def PrepararBitacoras(sesion_spark, tmp_path):
    """Inicializa la persistencia y devuelve los escritores de bitácora.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        tuple: (BitacoraEventos, BitacoraErrores) listos contra las tablas delta.
    """
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return (
        BitacoraEventos(sesion=sesion_spark, capa=capa),
        BitacoraErrores(sesion=sesion_spark, capa=capa),
    )


def IdentidadUsuario():
    """Devuelve la identidad on-behalf-of del usuario llamante de prueba."""
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def CrearSolicitud(privilegios):
    """Construye una solicitud 1 a 1 sobre el objeto de prueba."""
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=OBJETO,
    )


def TestEventoRegistradoConUsuarioOboYDesglose(sesion_spark, tmp_path):
    """El evento de la solicitud queda con el usuario del llamante y el desglose.

    Escenario "Solicitud otorgada de punta a punta" del spec (auditoría).
    """
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    sesion_sql = SesionSqlImitada()
    sesion_sql.ConfigurarShowGrant(
        OBJETO, [[BENEFICIARIO, "SELECT", "TABLE", OBJETO.identificador]]
    )
    canal = CanalSqlDatos(sesion_sql, registrador_errores=bitacora_errores)
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )

    reporte = pipeline.Procesar(CrearSolicitud(["SELECT"]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    filas = sesion_spark.sql(
        f"SELECT usuario, resultado FROM {TABLA_EVENTOS} "
        "WHERE detalle = '1 ítem(s) procesado(s): otorgado=1'"
    ).collect()
    assert len(filas) == 1, "El evento de la solicitud debe quedar registrado"
    assert filas[0].usuario == IDENTIFICADOR_USUARIO_DEMO, (
        "El campo usuario debe llevar la identidad on-behalf-of del llamante"
    )
    assert filas[0].resultado == "otorgado"


def TestFalloDeSesionRegistradoEnBitacoraErrores(sesion_spark, tmp_path):
    """Un fallo de la sesión SQL se registra en bitacora_errores con su detalle.

    Escenario del flujo donde la ejecución falla: el canal traduce el error a
    resultado por ítem y, además, deja constancia en la bitácora de errores.
    """
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    sesion_sql = SesionSqlImitada()
    sesion_sql.ConfigurarErrorEn(
        "GRANT SELECT",
        ErrorMotorSql(
            "[SCHEMA_OR_OBJECT_NOT_FOUND] El objeto no existe en el metastore."
        ),
    )
    canal = CanalSqlDatos(sesion_sql, registrador_errores=bitacora_errores)
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )

    reporte = pipeline.Procesar(CrearSolicitud(["SELECT"]))

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    filas = sesion_spark.sql(
        f"SELECT modulo, detalle FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}'"
    ).collect()
    assert len(filas) == 1, "El fallo de ejecución debe quedar en la bitácora"
    assert filas[0].detalle.tipo_excepcion == "ErrorMotorSql"
    assert OBJETO.identificador in filas[0].detalle.contexto


# --- Objetos externos (spec `uc-external-object-grants`, C6) ----------------

# External location y connection de prueba: nombres simples, como los reporta
# Unity Catalog para estos objetos del metastore.
EXTERNAL_LOCATION = ObjetoSecurable(
    identificador="ubicacion_externa_pruebas", tipo=TipoObjeto.EXTERNAL_LOCATION
)
CONNECTION = ObjetoSecurable(
    identificador="conexion_sqlserver_pruebas", tipo=TipoObjeto.CONNECTION
)


def CrearSolicitudExterna(objeto, privilegios):
    """Construye una solicitud 1 a 1 sobre un objeto externo de prueba.

    Args:
        objeto (ObjetoSecurable): external location o connection.
        privilegios (list[str]): privilegios a otorgar al beneficiario.

    Returns:
        SolicitudGrant: solicitud válida para procesar.
    """
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=objeto,
    )


def ContarFilas(sesion_spark, tabla, condicion=""):
    """Cuenta las filas de una tabla de bitácora, opcionalmente filtradas.

    Las tablas delta de bitácora son compartidas por toda la sesión de Spark de
    la corrida, de modo que las filas de las pruebas anteriores persisten. Para
    afirmar que una prueba registró su propio evento se cuenta el incremento
    antes y después de procesar la solicitud (conteo incremental), en lugar de
    asumir que la tabla está vacía.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tabla (str): nombre completo de la tabla de bitácora.
        condicion (str): cláusula WHERE opcional (sin la palabra `WHERE`).

    Returns:
        int: cantidad de filas que cumplen la condición.
    """
    sentencia = f"SELECT COUNT(*) AS total FROM {tabla}"
    if condicion:
        sentencia += f" WHERE {condicion}"
    return sesion_spark.sql(sentencia).collect()[0].total


def TestEventoRegistradoSobreExternalLocationConUsuarioObo(sesion_spark, tmp_path):
    """El grant sobre una external location queda auditado con el usuario OBO.

    Design D6: la auditoría con el `usuario` del llamante y el desglose por ítem
    se verifica en la capa funcional, con Spark local y los escritores reales.
    """
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    sesion_sql = SesionSqlImitada()
    sesion_sql.ConfigurarShowGrant(
        EXTERNAL_LOCATION,
        [
            [
                BENEFICIARIO,
                "READ FILES",
                "EXTERNAL LOCATION",
                EXTERNAL_LOCATION.identificador,
            ]
        ],
    )
    canal = CanalSqlDatos(sesion_sql, registrador_errores=bitacora_errores)
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )
    eventos_otorgados_antes = ContarFilas(
        sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'"
    )

    reporte = pipeline.Procesar(CrearSolicitudExterna(EXTERNAL_LOCATION, ["READ FILES"]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert sesion_sql.sentencias_ejecutadas[0] == (
        "GRANT READ FILES ON EXTERNAL LOCATION `ubicacion_externa_pruebas` "
        f"TO `{BENEFICIARIO}`"
    )
    # La prueba registró exactamente un evento nuevo de otorgamiento (la tabla
    # es compartida con las pruebas anteriores de la sesión).
    assert (
        ContarFilas(sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'")
        - eventos_otorgados_antes
        == 1
    ), "El evento de la solicitud debe quedar registrado"
    fila = sesion_spark.sql(
        f"SELECT usuario, resultado, detalle FROM {TABLA_EVENTOS} "
        "WHERE resultado = 'otorgado' ORDER BY marca_tiempo DESC LIMIT 1"
    ).collect()[0]
    assert fila.usuario == IDENTIFICADOR_USUARIO_DEMO, (
        "El campo usuario debe llevar la identidad on-behalf-of del llamante"
    )
    assert "otorgado=1" in fila.detalle


def TestEventoRegistradoSobreConnectionConUsuarioObo(sesion_spark, tmp_path):
    """El grant sobre una connection queda auditado con el usuario OBO."""
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    sesion_sql = SesionSqlImitada()
    sesion_sql.ConfigurarShowGrant(
        CONNECTION,
        [[BENEFICIARIO, "USE CONNECTION", "CONNECTION", CONNECTION.identificador]],
    )
    canal = CanalSqlDatos(sesion_sql, registrador_errores=bitacora_errores)
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )
    eventos_otorgados_antes = ContarFilas(
        sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'"
    )

    reporte = pipeline.Procesar(CrearSolicitudExterna(CONNECTION, ["USE CONNECTION"]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert (
        ContarFilas(sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'")
        - eventos_otorgados_antes
        == 1
    )
    fila = sesion_spark.sql(
        f"SELECT usuario, resultado FROM {TABLA_EVENTOS} "
        "WHERE resultado = 'otorgado' ORDER BY marca_tiempo DESC LIMIT 1"
    ).collect()[0]
    assert fila.usuario == IDENTIFICADOR_USUARIO_DEMO


def TestFalloSobreConnectionRegistradoEnBitacoraErrores(sesion_spark, tmp_path):
    """Un fallo al otorgar sobre una connection queda en la bitácora de errores.

    Con el código real `CONNECTION_NOT_FOUND` imitado por la sesión: el canal
    traduce el error a resultado por ítem y deja constancia con su detalle y el
    contexto del objeto externo involucrado. La consulta se filtra por el
    contexto del objeto, que sí lo identifica, para no chocar con los errores
    registrados por las pruebas anteriores de la sesión.
    """
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    sesion_sql = SesionSqlImitada()
    sesion_sql.ConfigurarErrorEn(
        "GRANT USE CONNECTION",
        ErrorMotorSql(
            "[CONNECTION_NOT_FOUND] No existe la connection "
            "'conexion_sqlserver_pruebas'."
        ),
    )
    canal = CanalSqlDatos(sesion_sql, registrador_errores=bitacora_errores)
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )

    reporte = pipeline.Procesar(CrearSolicitudExterna(CONNECTION, ["USE CONNECTION"]))

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    filas = sesion_spark.sql(
        f"SELECT modulo, detalle FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}' "
        f"AND detalle.contexto LIKE '%{CONNECTION.identificador}%'"
    ).collect()
    assert len(filas) == 1, "El fallo de ejecución debe quedar en la bitácora"
    assert filas[0].detalle.tipo_excepcion == "ErrorMotorSql"
    assert CONNECTION.identificador in filas[0].detalle.contexto
