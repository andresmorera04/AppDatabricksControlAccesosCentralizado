"""Pruebas unitarias de la traducción de errores del canal SQL por caso.

Cubren el requirement "Errores del workspace traducidos a mensajes específicos
por caso" del spec `uc-data-object-grants` y el requirement homónimo del spec
`uc-external-object-grants` (C6): el permiso denegado al ejecutor se reporta
como `privilegios_insuficientes`; el objeto inexistente, el principal
inexistente y cualquier otro fallo de la sesión se reportan como `fallido`, cada
uno con su mensaje específico en español, tanto para los ocho tipos de C4 como
para external location y connection. Solo el denegado explícito produce la marca
de privilegios insuficientes (design D3).

La sesión doble lanza excepciones cuyo mensaje imita la forma real del motor SQL
de Databricks (códigos `PERMISSION_DENIED`, `SCHEMA_OR_OBJECT_NOT_FOUND`,
`EXTERNAL_LOCATION_NOT_FOUND`, `CONNECTION_NOT_FOUND`, etc.), para ejercitar la
clasificación por patrones sin conexión externa.
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


def CrearItemExterno(tipo, identificador, privilegio):
    """Construye un ítem sobre un objeto externo (C6) para las pruebas.

    Args:
        tipo (TipoObjeto): `EXTERNAL_LOCATION` o `CONNECTION`.
        identificador (str): nombre simple del objeto externo.
        privilegio (str): privilegio a otorgar o revocar.

    Returns:
        ItemGrant: ítem con un principal usuario fijo de las pruebas.
    """
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
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


# --- Objetos externos (spec `uc-external-object-grants`, C6) ----------------


def TestPermisoDenegadoSobreExternalLocation():
    """PERMISSION_DENIED sobre external location -> privilegios_insuficientes.

    El mensaje identifica el privilegio y el objeto, y deja constancia de que
    el ejecutor no puede otorgarlo.
    """
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[PERMISSION_DENIED] El ejecutor no puede otorgar READ FILES sobre "
            "la external location 'ubicacion_externa'."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.EXTERNAL_LOCATION, "ubicacion_externa", "READ FILES"
        )
    )

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "READ FILES" in resultado.detalle
    assert "ubicacion_externa" in resultado.detalle
    assert "no tiene privilegios" in resultado.detalle


def TestPermisoDenegadoSobreConnection():
    """PERMISSION_DENIED sobre connection -> privilegios_insuficientes."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[PERMISSION_DENIED] Sin permisos para otorgar USE CONNECTION."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.CONNECTION, "conexion_lakehouse", "USE CONNECTION"
        )
    )

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "USE CONNECTION" in resultado.detalle
    assert "conexion_lakehouse" in resultado.detalle


def TestExternalLocationInexistenteSeReportaFalloConElObjeto():
    """EXTERNAL_LOCATION_NOT_FOUND -> fallido que identifica la location.

    Patrón propio de objetos externos aprobado por el humano (design D3),
    pendiente de contraste final contra el workspace en las integrales.
    """
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[EXTERNAL_LOCATION_NOT_FOUND] No existe la external location "
            "'ubicacion_inexistente'."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.EXTERNAL_LOCATION, "ubicacion_inexistente", "READ FILES"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    # El mensaje traducido identifica el objeto por su tipo y su nombre (datos
    # del ítem), no el texto crudo del motor.
    assert "no existe" in resultado.detalle
    assert "external_location" in resultado.detalle
    assert "ubicacion_inexistente" in resultado.detalle


def TestConnectionInexistenteSeReportaFalloConElObjeto():
    """CONNECTION_NOT_FOUND -> fallido que identifica la connection."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[CONNECTION_NOT_FOUND] No existe la connection "
            "'conexion_inexistente'."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.CONNECTION, "conexion_inexistente", "USE CONNECTION"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert "connection" in resultado.detalle
    assert "conexion_inexistente" in resultado.detalle


def TestConnectionInexistenteConCodigoRealDelWorkspace():
    """Código real contrastado contra `andresFree`: RESOURCE_DOES_NOT_EXIST.

    La respuesta real del workspace al otorgar sobre una connection inexistente
    es `ErrorClass=RESOURCE_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST` con el texto
    "Connection '<nombre>' does not exist." (no `CONNECTION_NOT_FOUND`, que fue
    la forma sugerida antes del contraste). El ítem debe traducirse al mensaje
    específico en español, no al texto crudo del motor.
    """
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[RequestId=1f481aac ErrorClass=RESOURCE_DOES_NOT_EXIST."
            "RESOURCE_DOES_NOT_EXIST] Connection 'conexion_inexistente' does "
            "not exist."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.CONNECTION, "conexion_inexistente", "USE CONNECTION"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert "connection" in resultado.detalle
    assert "conexion_inexistente" in resultado.detalle


def TestExternalLocationInexistenteConCodigoRealDelWorkspace():
    """Código real contrastado contra `andresAzureDev`: DOES_NOT_EXIST.

    La respuesta real del workspace al otorgar sobre una external location
    inexistente es `ErrorClass=EXTERNAL_LOCATION_DOES_NOT_EXIST.
    RESOURCE_DOES_NOT_EXIST` con el texto "External Location '<nombre>' does not
    exist.". El ítem debe traducirse al mensaje específico en español.
    """
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[RequestId=2613a439 ErrorClass=EXTERNAL_LOCATION_DOES_NOT_EXIST."
            "RESOURCE_DOES_NOT_EXIST] External Location "
            "'ubicacion_inexistente' does not exist."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.EXTERNAL_LOCATION, "ubicacion_inexistente", "READ FILES"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert "external_location" in resultado.detalle
    assert "ubicacion_inexistente" in resultado.detalle


def TestPrincipalInexistenteSobreObjetoExterno():
    """Principal inexistente en un objeto externo -> fallido con el principal."""
    sesion = SesionDoble(
        error=ErrorMotorSql(
            "[PRINCIPAL_DOES_NOT_EXIST] El principal referido no existe en el "
            "workspace."
        )
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.EXTERNAL_LOCATION, "ubicacion_externa", "WRITE FILES"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert "usuario_demo" in resultado.detalle


def TestOtroFalloSobreObjetoExternoQuedaGenerico():
    """Un fallo no reconocido sobre un objeto externo queda como fallido.

    Regla fail-safe del design D3: cualquier patrón no reconocido se reporta
    `fallido` con el detalle del error y nunca como privilegios insuficientes.
    """
    sesion = SesionDoble(
        error=ErrorMotorSql("Fallo de transporte: timeout de conexión.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(
        CrearItemExterno(
            TipoObjeto.CONNECTION, "conexion_lakehouse", "USE CONNECTION"
        )
    )

    assert resultado.estado is EstadoItem.FALLIDO
    assert "timeout" in resultado.detalle
    assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES
