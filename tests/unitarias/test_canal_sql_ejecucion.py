"""Pruebas unitarias de la ejecución del canal SQL por sesión inyectada.

Cubren el requirement "Ejecución de instrucciones por una sesión SQL inyectada"
del spec `uc-data-object-grants`: el canal ejecuta la instrucción construida a
través del puerto `sql(sentencia)` de la sesión inyectada, sin valores de
conexión en el código, y devuelve un resultado por ítem sin propagar
excepciones. Se incluye la normalización de filas del adaptador `SesionSparkSql`.
"""

from control_accesos.canales.reales.canal_sql_datos import (
    CanalSqlDatos,
    SesionSparkSql,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class SesionDoble:
    """Doble de sesión SQL que registra las sentencias y devuelve filas fijas.

    Permite verificar, sin conexión externa, qué instrucciones llegan al puerto
    `sql` y el resultado de cada una.

    Attributes:
        sentencias_ejecutadas (list[str]): sentencias recibidas, en orden.
    """

    def __init__(self, filas=None, error=None):
        """Guarda la respuesta configurada.

        Args:
            filas (list[list[str]] | None): filas que devuelve `sql`.
            error (Exception | None): excepción que `sql` lanza, si aplica.
        """
        self.sentencias_ejecutadas = []
        self.filas = filas or []
        self.error = error

    def sql(self, sentencia):
        """Registra la sentencia y responde según lo configurado.

        Args:
            sentencia (str): sentencia recibida.

        Returns:
            list[list[str]]: filas configuradas.

        Raises:
            Exception: el error configurado, si existe.
        """
        self.sentencias_ejecutadas.append(sentencia)
        if self.error is not None:
            raise self.error
        return list(self.filas)


class MarcoDoble:
    """Doble de DataFrame con `collect()` que devuelve filas fijas."""

    def __init__(self, filas):
        self._filas = filas

    def collect(self):
        """Devuelve las filas del DataFrame simulado."""
        return self._filas


class SparkSesionDoble:
    """Doble de SparkSession cuyo `sql()` devuelve un DataFrame simulado."""

    def __init__(self, filas):
        self._filas = filas
        self.sentencias_ejecutadas = []

    def sql(self, sentencia):
        """Registra la sentencia y devuelve un DataFrame simulado."""
        self.sentencias_ejecutadas.append(sentencia)
        return MarcoDoble(self._filas)


def CrearItem():
    """Construye un ítem del plano de datos para las pruebas."""
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio="SELECT",
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )


def TestOtorgamientoEjecutaLaSentenciaEnLaSesion():
    """El otorgamiento envía la sentencia construida al puerto sql de la sesión."""
    sesion = SesionDoble()
    canal = CanalSqlDatos(sesion)
    item = CrearItem()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert sesion.sentencias_ejecutadas == [
        CanalSqlDatos.ConstruirSentenciaOtorgamiento(item)
    ]


def TestRevocacionEjecutaLaSentenciaEnLaSesion():
    """La revocación envía su sentencia construida al mismo puerto de sesión."""
    sesion = SesionDoble()
    canal = CanalSqlDatos(sesion)
    item = CrearItem()

    resultado = canal.Revocar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert sesion.sentencias_ejecutadas == [
        CanalSqlDatos.ConstruirSentenciaRevocacion(item)
    ]


def TestCanalSinConexionExterna():
    """El canal opera íntegramente contra la sesión doble, sin conexión real."""
    sesion = SesionDoble()
    canal = CanalSqlDatos(sesion)

    assert canal.Otorgar(CrearItem()).estado is EstadoItem.OTORGADO
    # El doble no abre red alguna: solo registra la sentencia recibida.
    assert len(sesion.sentencias_ejecutadas) == 1


def TestSesionSparkSqlNormalizaLasFilasATexto():
    """SesionSparkSql convierte collect() del DataFrame a filas de texto."""
    sesion_spark = SparkSesionDoble(
        [
            ("usuario@correo.com", "SELECT", None),
            ("grupo_analistas", "USE SCHEMA", "control.finanzas"),
        ]
    )
    adaptador = SesionSparkSql(sesion_spark)

    filas = adaptador.sql("SHOW GRANT ON SCHEMA `control`.`finanzas`")

    assert filas == [
        ["usuario@correo.com", "SELECT", ""],
        ["grupo_analistas", "USE SCHEMA", "control.finanzas"],
    ]
    assert sesion_spark.sentencias_ejecutadas == [
        "SHOW GRANT ON SCHEMA `control`.`finanzas`"
    ]


def TestSesionSparkSqlRequiereUnaSesionConSql():
    """Sin una SparkSession con sql() el adaptador falla de forma explícita."""
    class SinSql:
        """Objeto sin el puerto esperado."""

    try:
        SesionSparkSql(SinSql())
    except ValueError as excepcion:
        assert "sql" in str(excepcion)
    else:
        raise AssertionError("Se esperaba un ValueError por sesión inválida.")
