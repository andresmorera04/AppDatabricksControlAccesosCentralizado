"""Pruebas unitarias de la construcción de sentencias SQL del canal real.

Cubren los requirements "Instrucción de otorgamiento por tipo de objeto" e
"Instrucción de revocación por tipo de objeto" del spec
`uc-data-object-grants`, el requirement "Objetos fuera del alcance de este
change" (del mismo spec, ahora restringido al plano de control tras C6) y los
requirements "Instrucción de otorgamiento para objetos externos",
"Instrucción de revocación para objetos externos" y "Cobertura completa del
plano de datos" del spec `uc-external-object-grants`.

Se ejercita directamente la construcción de sentencias (métodos estáticos de
`CanalSqlDatos`), sin sesión ni conexión externa alguna: se verifica la palabra
clave SQL por tipo de objeto (incluidos external location y connection, con la
palabra de dos tokens `EXTERNAL LOCATION`), el nombre calificado entre comillas
invertidas parte por parte y el principal identificado por su identificador.
"""

import pytest

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


def CrearItem(tipo, identificador, privilegio="SELECT"):
    """Construye un ítem del plano de datos para las pruebas.

    Args:
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str): identificación del objeto.
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


def TestOtorgamientoSobreCatalogo():
    """Grant sobre catálogo usa la palabra clave CATALOG con nombre simple."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.CATALOGO, "control", "USE CATALOG")
    )

    assert sentencia == "GRANT USE CATALOG ON CATALOG `control` TO `usuario_demo`"


def TestOtorgamientoSobreEsquemaCalificado():
    """Grant sobre esquema conserva las dos partes del nombre calificado."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.ESQUEMA, "control.finanzas", "USE SCHEMA")
    )

    assert sentencia == "GRANT USE SCHEMA ON SCHEMA `control`.`finanzas` TO `usuario_demo`"


def TestOtorgamientoSobreTablaDeltaCalificada():
    """Grant sobre tabla delta conserva las tres partes del nombre calificado."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.TABLA_DELTA, "control.produccion.ventas", "SELECT")
    )

    assert sentencia == (
        "GRANT SELECT ON TABLE `control`.`produccion`.`ventas` TO `usuario_demo`"
    )


def TestOtorgamientoSobreVolumen():
    """Grant sobre volumen usa la palabra clave VOLUME."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.VOLUMEN, "control.datos.raw", "READ VOLUME")
    )

    assert sentencia == "GRANT READ VOLUME ON VOLUME `control`.`datos`.`raw` TO `usuario_demo`"


def TestOtorgamientoSobreModeloMl():
    """Grant sobre modelo de ML usa la palabra clave MODEL."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.MODELO_ML, "control.ml.modelo_ventas", "EXECUTE")
    )

    assert sentencia == (
        "GRANT EXECUTE ON MODEL `control`.`ml`.`modelo_ventas` TO `usuario_demo`"
    )


def TestStreamingTableVistaMaterializadaYVistaSqlUsanTable():
    """ST, vista materializada y vista SQL comparten la palabra clave TABLE."""
    casos = (
        (TipoObjeto.STREAMING_TABLE, "control.produccion.st_ventas", "SELECT"),
        (TipoObjeto.VISTA_MATERIALIZADA, "control.produccion.mv_ventas", "REFRESH"),
        (TipoObjeto.VISTA_SQL, "control.produccion.v_ventas", "SELECT"),
    )
    for tipo, identificador, privilegio in casos:
        sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
            CrearItem(tipo, identificador, privilegio)
        )
        assert " ON TABLE " in sentencia


def TestRevocacionSobreTablaDelta():
    """REVOKE construye la instrucción con FROM y la misma palabra clave."""
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem(TipoObjeto.TABLA_DELTA, "control.produccion.ventas", "SELECT")
    )

    assert sentencia == (
        "REVOKE SELECT ON TABLE `control`.`produccion`.`ventas` FROM `usuario_demo`"
    )


def TestOtorgamientoSobreExternalLocation():
    """Grant sobre external location usa la palabra clave EXTERNAL LOCATION.

    El nombre de una external location es simple (sin calificación por
    catálogo/esquema), por lo que queda entrecomillado como una sola parte.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.EXTERNAL_LOCATION, "ubicacion_externa", "READ FILES")
    )

    assert sentencia == (
        "GRANT READ FILES ON EXTERNAL LOCATION `ubicacion_externa` "
        "TO `usuario_demo`"
    )


def TestOtorgamientoSobreExternalLocationPrivilegioEspecifico():
    """EXTERNAL USE LOCATION no forma parte de ALL PRIVILEGES y se envía tal cual.

    Escenario del spec: la instrucción incluye el privilegio válido según la
    matriz de compatibilidad en mayúsculas.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(
            TipoObjeto.EXTERNAL_LOCATION,
            "ubicacion_externa",
            "EXTERNAL USE LOCATION",
        )
    )

    assert sentencia == (
        "GRANT EXTERNAL USE LOCATION ON EXTERNAL LOCATION `ubicacion_externa` "
        "TO `usuario_demo`"
    )


def TestOtorgamientoSobreConnection():
    """Grant sobre connection usa la palabra clave CONNECTION."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(TipoObjeto.CONNECTION, "conexion_lakehouse", "USE CONNECTION")
    )

    assert sentencia == (
        "GRANT USE CONNECTION ON CONNECTION `conexion_lakehouse` TO `usuario_demo`"
    )


def TestOtorgamientoSobreConnectionPrivilegioCreateForeignCatalog():
    """CREATE FOREIGN CATALOG se envía en mayúsculas sobre la connection."""
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem(
            TipoObjeto.CONNECTION,
            "conexion_lakehouse",
            "CREATE FOREIGN CATALOG",
        )
    )

    assert sentencia == (
        "GRANT CREATE FOREIGN CATALOG ON CONNECTION `conexion_lakehouse` "
        "TO `usuario_demo`"
    )


def TestRevocacionSobreExternalLocation():
    """REVOKE sobre external location usa FROM y la misma palabra clave."""
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem(TipoObjeto.EXTERNAL_LOCATION, "ubicacion_externa", "READ FILES")
    )

    assert sentencia == (
        "REVOKE READ FILES ON EXTERNAL LOCATION `ubicacion_externa` "
        "FROM `usuario_demo`"
    )


def TestRevocacionSobreConnection():
    """REVOKE sobre connection usa FROM y la palabra clave CONNECTION."""
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem(TipoObjeto.CONNECTION, "conexion_lakehouse", "USE CONNECTION")
    )

    assert sentencia == (
        "REVOKE USE CONNECTION ON CONNECTION `conexion_lakehouse` "
        "FROM `usuario_demo`"
    )


def TestTipoDelPlanoDeControlRechazadoSinConstruirSentencia():
    """Tras C6 el canal SQL soporta los 10 tipos del plano de datos.

    Solo un objeto del plano de control (canal SDK/REST, C7/C8) se rechaza con
    `ErrorCanal` explícito sin construir sentencia alguna (spec
    `uc-external-object-grants` - "Cobertura completa del plano de datos").
    """
    fuera_de_alcance = (
        (TipoObjeto.COMPUTO_CLASICO, "a1b2c3d4"),
        (TipoObjeto.COMPUTO_SERVERLESS, "b2c3d4e5"),
        (TipoObjeto.SQL_WAREHOUSE, "c3d4e5f6"),
        (TipoObjeto.DATABRICK_APP, "d4e5f6a7"),
        (TipoObjeto.USO_TOKEN, "e5f6a7b8"),
    )
    for tipo, identificador in fuera_de_alcance:
        with pytest.raises(ErrorCanal):
            CanalSqlDatos.ConstruirSentenciaOtorgamiento(
                CrearItem(tipo, identificador)
            )
        with pytest.raises(ErrorCanal):
            CanalSqlDatos.ConstruirSentenciaRevocacion(
                CrearItem(tipo, identificador)
            )
