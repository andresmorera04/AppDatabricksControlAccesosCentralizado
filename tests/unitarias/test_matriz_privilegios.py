"""Pruebas unitarias de la declaración de la matriz de privilegios.

Cubren el requirement "Cobertura de tipos de objeto soportados" del spec
`privilege-matrix`: los 15 tipos declarados con sus privilegios válidos,
incluyendo los mínimos exigidos por el spec (`catalogo` con SELECT y
USE CATALOG; `sql_warehouse` con CAN_USE).

Los conjuntos de privilegios provienen de la documentación oficial de
Databricks (Unity Catalog privileges reference y Access control lists /
Permissions API), citada en el módulo de la matriz.
"""

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto
from control_accesos.dominio.modelos import MAPA_TIPO_OBJETO_A_PLANO
from control_accesos.matriz.matriz_privilegios import MATRIZ_PRIVILEGIOS


def TestMatrizCubreLosQuinceTiposDeObjeto():
    """La matriz declara exactamente los 15 tipos de objeto del README."""
    assert set(MATRIZ_PRIVILEGIOS.keys()) == set(TipoObjeto)
    assert len(MATRIZ_PRIVILEGIOS) == 15


def TestCatalogoIncluyeSelectYUseCatalog():
    """Escenario del spec: `catalogo` incluye al menos SELECT y USE CATALOG."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.CATALOGO]
    assert "SELECT" in privilegios
    assert "USE CATALOG" in privilegios


def TestSqlWarehouseIncluyeCanUse():
    """Escenario del spec: `sql_warehouse` incluye al menos CAN_USE."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.SQL_WAREHOUSE]
    assert "CAN_USE" in privilegios


def TestTodosLosTiposTienenPrivilegiosDeclarados():
    """Ningún tipo de objeto queda con un conjunto vacío de privilegios."""
    for tipo in TipoObjeto:
        assert len(MATRIZ_PRIVILEGIOS[tipo]) > 0, f"{tipo.name} sin privilegios"


def TestTiposDelPlanoDeControlUsanNivelesDePermiso():
    """El plano de control usa niveles de permiso CAN_* (Permissions API)."""
    for tipo, plano in MAPA_TIPO_OBJETO_A_PLANO.items():
        if plano is not Plano.CONTROL:
            continue
        for privilegio in MATRIZ_PRIVILEGIOS[tipo]:
            assert privilegio.startswith("CAN_"), (
                f"{tipo.name}: el nivel {privilegio} no sigue la forma CAN_* "
                "de la Permissions API"
            )


def TestTiposDelPlanoDeDatosNoUsanNivelesDePermiso():
    """El plano de datos usa privilegios SQL (con espacios), no niveles CAN_*."""
    for tipo, plano in MAPA_TIPO_OBJETO_A_PLANO.items():
        if plano is not Plano.DATOS:
            continue
        for privilegio in MATRIZ_PRIVILEGIOS[tipo]:
            assert not privilegio.startswith("CAN_"), (
                f"{tipo.name}: {privilegio} es un nivel de permiso del plano "
                "de control, no un privilegio SQL de Unity Catalog"
            )


def TestTablaDeltaIncluyeSelectYModify():
    """Una tabla delta se lee con SELECT y se escribe con MODIFY."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.TABLA_DELTA]
    assert "SELECT" in privilegios
    assert "MODIFY" in privilegios


def TestStreamingTableSigueLosPrivilegiosDeTabla():
    """Las streaming tables se rigen por los privilegios de tabla (doc oficial)."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.STREAMING_TABLE]
    assert "SELECT" in privilegios
    assert "MODIFY" in privilegios


def TestVistaMaterializadaIncluyeRefresh():
    """REFRESH aplica solo a vistas materializadas (doc oficial)."""
    assert "REFRESH" in MATRIZ_PRIVILEGIOS[TipoObjeto.VISTA_MATERIALIZADA]
    assert "SELECT" in MATRIZ_PRIVILEGIOS[TipoObjeto.VISTA_MATERIALIZADA]
    # REFRESH no aplica a vistas SQL ni a tablas delta según la doc oficial.
    assert "REFRESH" not in MATRIZ_PRIVILEGIOS[TipoObjeto.VISTA_SQL]
    assert "REFRESH" not in MATRIZ_PRIVILEGIOS[TipoObjeto.TABLA_DELTA]


def TestVistaSqlIncluyeSelect():
    """Una vista SQL se consulta con SELECT."""
    assert "SELECT" in MATRIZ_PRIVILEGIOS[TipoObjeto.VISTA_SQL]


def TestVolumenIncluyeReadVolumeYWriteVolume():
    """Un volumen se lee con READ VOLUME y se escribe con WRITE VOLUME."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.VOLUMEN]
    assert "READ VOLUME" in privilegios
    assert "WRITE VOLUME" in privilegios


def TestModeloMlIncluyeExecuteYCreateModelVersion():
    """Un modelo ML se ejecuta con EXECUTE y versiona con CREATE MODEL VERSION."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.MODELO_ML]
    assert "EXECUTE" in privilegios
    assert "CREATE MODEL VERSION" in privilegios


def TestEsquemaIncluyeUseSchemaYCreacionDeObjetos():
    """Un esquema requiere USE SCHEMA y permite crear objetos hijos."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.ESQUEMA]
    assert "USE SCHEMA" in privilegios
    assert "CREATE TABLE" in privilegios
    assert "CREATE VOLUME" in privilegios


def TestExternalLocationIncluyeReadFilesYWriteFiles():
    """Una external location se lee con READ FILES y se escribe con WRITE FILES."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.EXTERNAL_LOCATION]
    assert "READ FILES" in privilegios
    assert "WRITE FILES" in privilegios
    assert "CREATE EXTERNAL TABLE" in privilegios


def TestConnectionIncluyeUseConnectionYCreateForeignCatalog():
    """Una connection se usa con USE CONNECTION y permite catálogos externos."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.CONNECTION]
    assert "USE CONNECTION" in privilegios
    assert "CREATE FOREIGN CATALOG" in privilegios


def TestComputoClasicoIncluyeSusTresNiveles():
    """El cómputo clásico usa CAN_ATTACH_TO, CAN_RESTART y CAN_MANAGE (API)."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.COMPUTO_CLASICO]
    assert {"CAN_ATTACH_TO", "CAN_RESTART", "CAN_MANAGE"} <= privilegios


def TestComputoServerlessIncluyeCanUseYCanManage():
    """El cómputo serverless usa CAN_USE y CAN_MANAGE (decisión D3 del README)."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.COMPUTO_SERVERLESS]
    assert {"CAN_USE", "CAN_MANAGE"} <= privilegios


def TestDatabricksAppIncluyeCanUseYCanManage():
    """Una Databricks App usa CAN_USE y CAN_MANAGE (Permissions API)."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.DATABRICK_APP]
    assert {"CAN_USE", "CAN_MANAGE"} <= privilegios


def TestUsoTokenIncluyeCanUse():
    """El uso de personal access token usa CAN_USE (decisión D4 del README)."""
    privilegios = MATRIZ_PRIVILEGIOS[TipoObjeto.USO_TOKEN]
    assert "CAN_USE" in privilegios


def TestPrivilegiosEnMayusculasYSinEspaciosSobrantes():
    """Todo privilegio es texto en mayúsculas y sin espacios en los extremos."""
    for tipo, privilegios in MATRIZ_PRIVILEGIOS.items():
        for privilegio in privilegios:
            assert isinstance(privilegio, str), f"{tipo.name}: no es texto"
            assert privilegio == privilegio.strip().upper(), (
                f"{tipo.name}: el privilegio {privilegio!r} no está en "
                "mayúsculas o tiene espacios sobrantes"
            )


def TestMatrizEsInmutablePorTipo():
    """Los conjuntos de privilegios son inmutables (frozenset) por diseño."""
    for tipo, privilegios in MATRIZ_PRIVILEGIOS.items():
        assert isinstance(privilegios, frozenset), (
            f"{tipo.name}: debe declararse como frozenset inmutable"
        )
