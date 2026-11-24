"""Pruebas unitarias de la construcción de sentencias SQL del canal real.

Cubren los requirements "Instrucción de otorgamiento por tipo de objeto" e
"Instrucción de revocación por tipo de objeto" del spec
`uc-data-object-grants`, y el requirement "Objetos fuera del alcance de este
change".

Se ejercita directamente la construcción de sentencias (métodos estáticos de
`CanalSqlDatos`), sin sesión ni conexión externa alguna: se verifica la palabra
clave SQL por tipo de objeto, el nombre calificado entre comillas invertidas
parte por parte y el principal identificado por su identificador.
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


def TestTipoFueraDeAlcanceRechazadoSinConstruirSentencia():
    """External location, connection y plano de control se rechazan con error."""
    fuera_de_alcance = (
        (TipoObjeto.EXTERNAL_LOCATION, "ruta_externa"),
        (TipoObjeto.CONNECTION, "conexion_lakehouse"),
        (TipoObjeto.COMPUTO_CLASICO, "a1b2c3d4"),
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
