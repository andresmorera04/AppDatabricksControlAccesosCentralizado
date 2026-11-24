"""Pruebas unitarias de la traducción de errores del canal SQL por caso.

Cubren el requirement "Errores del workspace traducidos a mensajes específicos
por caso" del spec `uc-data-object-grants`: el permiso denegado al ejecutor se
reporta como `privilegios_insuficientes`; el objeto inexistente, el principal
inexistente y cualquier otro fallo de la sesión se reportan como `fallido`, cada
uno con su mensaje específico en español. Solo el denegado explícito produce la
marca de privilegios insuficientes (design D3).

La sesión doble lanza excepciones cuyo mensaje imita la forma real del motor SQL
de Databricks (códigos `PERMISSION_DENIED`, `SCHEMA_OR_OBJECT_NOT_FOUND`, etc.),
para ejercitar la clasificación por patrones sin conexión externa.
"""

from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class SesionDoble:
    """Doble de sesión SQL que lanza el error configurado al ejecutar.

    Attributes:
        sentencias_ejecutadas (list[str]): sentencias recibidas, en orden.
    """

    def __init__(self, error=None):
        """Guarda la respuesta configurada.

        Args:
            error (Exception | None): excepción que `sql` lanza, si aplica.
        """
        self.error = error
        self.sentencias_ejecutadas = []

    def sql(self, sentencia):
        """Registra la sentencia y lanza el error configurado, si existe.

        Args:
            sentencia (str): sentencia recibida.

        Raises:
            Exception: el error configurado, si existe.
        """
        self.sentencias_ejecutadas.append(sentencia)
        if self.error is not None:
            raise self.error
        return []


def CrearItem(privilegio="SELECT"):
    """Construye un ítem del plano de datos para las pruebas."""
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )


class ErrorMotorSql(RuntimeError):
    """Excepción genérica con la forma del error que reporta el motor SQL."""


def TestPermisoDenegadoSeReportaComoPrivilegiosInsuficientes():
    """PERMISSION_DENIED -> privilegios_insuficientes con privilegio y objeto."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[PERMISSION_DENIED] El ejecutor no puede otorgar SELECT sobre "
            "'control.produccion.ventas'."
        )
    )
    canal = CanalSqlDatos(sesion)
    item = CrearItem()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "SELECT" in resultado.detalle
    assert "control.produccion.ventas" in resultado.detalle


def TestObjetoInexistenteSeReportaFalloConElObjeto():
    """SCHEMA_OR_OBJECT_NOT_FOUND -> fallido que identifica el objeto."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[SCHEMA_OR_OBJECT_NOT_FOUND] No existe la tabla "
            "'control.produccion.ventas'."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem())

    assert resultado.estado is EstadoItem.FALLIDO
    # El mensaje traducido identifica el objeto por su tipo y su nombre
    # calificado (datos del ítem), no el texto crudo del motor.
    assert "no existe" in resultado.detalle
    assert "tabla_delta" in resultado.detalle
    assert "control.produccion.ventas" in resultado.detalle


def TestPrincipalInexistenteSeReportaFalloConElPrincipal():
    """Principal inexistente -> fallido que identifica el principal del ítem."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[PRINCIPAL_NOT_FOUND] El principal referido no existe en el "
            "workspace."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem())

    assert resultado.estado is EstadoItem.FALLIDO
    # El mensaje traducido identifica al principal destinatario del ítem.
    assert "no existe" in resultado.detalle
    assert "usuario_demo" in resultado.detalle


def TestOtroFalloSeReportaGenericoSinMarcaDePrivilegios():
    """Un fallo de sesión no reconocido queda como fallido genérico."""
    sesion = SesionDoble(
        error=ErrorMotorSql("Fallo de transporte: timeout de conexión.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem())

    assert resultado.estado is EstadoItem.FALLIDO
    assert "timeout" in resultado.detalle
    assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestRevocacionTambienTraducePermisoDenegado():
    """La traducción aplica igual al camino de revocación."""
    sesion = SesionDoble(
        error=ErrorMotorSql("[PERMISSION_DENIED] Sin permisos para revocar.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Revocar(CrearItem())

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
