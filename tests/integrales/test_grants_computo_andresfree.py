"""Pruebas integrales de cómputo contra `andresFree` (capability
`compute-grants`, marker `free`).

Ejercitan `CanalControlComputo` (producción) con el adaptador SDK del perfil
CLI `andresFree` sobre los objetos existentes aprobados por el humano (design
D8): el SQL warehouse y el serverless compute object *default*. Cada operación
que toca una ACL corre bajo `fixtures_computo.ACLRestaurada`, que guarda y
repone la ACL original, de modo que no quede estado residual. Los otorgatarios
(service principal y grupo `Desarrollador`) son datos de la fixture.

Si el transporte o un recurso no está disponible, la prueba se salta con motivo
documentado y el resto de la suite sigue ejecutándose (spec - "Pruebas por
entorno con restauración del estado original").
"""

import pytest

import fixtures_computo as f
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, SolicitudGrant
from control_accesos.pipeline.pipeline_grants import PipelineGrants

pytestmark = pytest.mark.free

OTORGATARIO_SP, OTORGATARIO_GRUPO = f.OtorgatariosDePerfil(f.PERFIL_FREE)


def _CanalFree():
    """Construye el canal real, omitiendo la prueba si el transporte no responde."""
    try:
        return f.CanalParaPerfil(f.PERFIL_FREE)
    except Exception as error:  # noqa: BLE001 - transporte no disponible
        pytest.skip(f"Transporte contra {f.PERFIL_FREE} no disponible: {error}")


def _Descubrir(descubridor, motivo):
    """Descubre un recurso, omitiendo si no hay transporte o si no existe."""
    try:
        valor = descubridor(f.PERFIL_FREE)
    except Exception as error:  # noqa: BLE001 - transporte no disponible
        pytest.skip(f"Transporte contra {f.PERFIL_FREE} no disponible: {error}")
    if valor is None:
        pytest.skip(motivo)
    return valor


def _ItemWarehouse():
    id_warehouse = _Descubrir(
        f.DescubrirWarehouseId, "El workspace no tiene ningún SQL warehouse."
    )
    return ItemGrant(
        principal=OTORGATARIO_SP,
        privilegio="CAN_USE",
        objeto=ObjetoSecurable(identificador=id_warehouse, tipo=TipoObjeto.SQL_WAREHOUSE),
    )


def _ItemServerless():
    id_objeto = _Descubrir(
        f.DescubrirServerlessDefaultId,
        "El workspace no expone serverless compute objects.",
    )
    return ItemGrant(
        principal=OTORGATARIO_SP,
        privilegio="CAN_USE",
        objeto=ObjetoSecurable(identificador=id_objeto, tipo=TipoObjeto.COMPUTO_SERVERLESS),
    )


def TestOtorgarVerificarRevocarWarehouse():
    """Otorga CAN_USE al SP sobre el warehouse, verifica y revoca; restaura."""
    canal = _CanalFree()
    item = _ItemWarehouse()
    recurso = f.RecursoDeTipo(item.objeto.tipo)

    with f.ACLRestaurada(canal, recurso, item.objeto.identificador):
        assert canal.Otorgar(item).estado is EstadoItem.OTORGADO
        assert item in canal.ListarGrantsVigentes(item.objeto)
        assert canal.Revocar(item).estado is EstadoItem.OTORGADO
        assert item not in canal.ListarGrantsVigentes(item.objeto)


def TestServerlessOtorgarVerificarRevocar():
    """Otorga CAN_USE al SP sobre el serverless compute object *default*."""
    canal = _CanalFree()
    item = _ItemServerless()
    recurso = f.RecursoDeTipo(item.objeto.tipo)

    with f.ACLRestaurada(canal, recurso, item.objeto.identificador):
        assert canal.Otorgar(item).estado is EstadoItem.OTORGADO
        assert item in canal.ListarGrantsVigentes(item.objeto)
        assert canal.Revocar(item).estado is EstadoItem.OTORGADO
        assert item not in canal.ListarGrantsVigentes(item.objeto)


def TestWarehouseInexistenteFallido():
    """Un warehouse inexistente se clasifica fallido con el patrón real."""
    canal = _CanalFree()
    item = ItemGrant(
        principal=OTORGATARIO_SP,
        privilegio="CAN_USE",
        objeto=ObjetoSecurable(
            identificador=f.IDENTIFICADOR_INEXISTENTE, tipo=TipoObjeto.SQL_WAREHOUSE
        ),
    )

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.FALLIDO
    assert resultado.detalle


def TestLoteN_A_1SobreWarehouse():
    """Lote N a 1 con SP y grupo sobre el warehouse, con resultados por ítem."""
    canal = _CanalFree()
    id_warehouse = _Descubrir(
        f.DescubrirWarehouseId, "El workspace no tiene ningún SQL warehouse."
    )
    objeto = ObjetoSecurable(identificador=id_warehouse, tipo=TipoObjeto.SQL_WAREHOUSE)
    pipeline = PipelineGrants(canal_datos=CanalDatosSimulado(), canal_control=canal)
    recurso = f.RecursoDeTipo(objeto.tipo)

    with f.ACLRestaurada(canal, recurso, id_warehouse):
        reporte = pipeline.ProcesarLoteDesdeEntradas(
            principales=[OTORGATARIO_SP, OTORGATARIO_GRUPO],
            privilegios=["CAN_USE"],
            objetos=[objeto],
        )

    assert len(reporte.lineas) == 2
    assert all(linea.estado is EstadoItem.OTORGADO for linea in reporte.lineas)


def TestVerticalSlicePipeline():
    """Vertical slice de punta a punta: 1 a 1 y lote 1 a N sobre Free."""
    canal = _CanalFree()
    id_warehouse = _Descubrir(
        f.DescubrirWarehouseId, "El workspace no tiene ningún SQL warehouse."
    )
    warehouse = ObjetoSecurable(identificador=id_warehouse, tipo=TipoObjeto.SQL_WAREHOUSE)
    pipeline = PipelineGrants(canal_datos=CanalDatosSimulado(), canal_control=canal)

    objetos = [warehouse]
    id_serverless = None
    try:
        id_serverless = f.DescubrirServerlessDefaultId(f.PERFIL_FREE)
    except Exception:  # noqa: BLE001 - no cambia el alcance de la slice
        id_serverless = None
    if id_serverless is not None:
        objetos.append(
            ObjetoSecurable(identificador=id_serverless, tipo=TipoObjeto.COMPUTO_SERVERLESS)
        )

    # Solicitud 1 a 1 sobre el warehouse.
    with f.ACLRestaurada(canal, f.RecursoDeTipo(warehouse.tipo), id_warehouse):
        reporte_1a1 = pipeline.Procesar(
            SolicitudGrant.Crear(
                principal=OTORGATARIO_SP, privilegios=["CAN_USE"], objeto=warehouse
            )
        )
    assert reporte_1a1.lineas[0].estado is EstadoItem.OTORGADO

    # Lote 1 a N sobre los objetos disponibles.
    with f.ACLRestaurada(canal, f.RecursoDeTipo(warehouse.tipo), id_warehouse):
        if id_serverless is not None:
            with f.ACLRestaurada(
                canal, f.RecursoDeTipo(TipoObjeto.COMPUTO_SERVERLESS), id_serverless
            ):
                reporte_lote = pipeline.ProcesarLoteDesdeEntradas(
                    principales=[OTORGATARIO_SP],
                    privilegios=["CAN_USE"],
                    objetos=objetos,
                )
        else:
            reporte_lote = pipeline.ProcesarLoteDesdeEntradas(
                principales=[OTORGATARIO_SP],
                privilegios=["CAN_USE"],
                objetos=objetos,
            )

    assert len(reporte_lote.lineas) == len(objetos)
    assert all(linea.estado is EstadoItem.OTORGADO for linea in reporte_lote.lineas)


def TestPermisoDenegadoConIdentidadRestringida():
    """Un otorgamiento como SP restringido se reporta privilegios_insuficientes.

    Escenario "Permiso denegado con identidad ejecutora restringida" del spec:
    la integral ejecuta el grant autenticada como el service principal sin
    privilegios administrativos (`1738687d-...`), de modo que Databricks responde
    con permiso denegado de forma real. El secret se lee de la variable de
    entorno y nunca vive en el código; sin ella, la prueba se salta con motivo.
    """
    import os

    secret = os.environ.get(f.VARIABLE_SECRET_EJECUTOR)
    if not secret:
        pytest.skip(
            f"Sin la variable de entorno {f.VARIABLE_SECRET_EJECUTOR} "
            "(secret del service principal restringido): no se puede ejecutar "
            "el grant con identidad restringida."
        )

    id_warehouse = _Descubrir(
        f.DescubrirWarehouseId, "El workspace no tiene ningún SQL warehouse."
    )
    objeto = ObjetoSecurable(identificador=id_warehouse, tipo=TipoObjeto.SQL_WAREHOUSE)
    recurso = f.RecursoDeTipo(objeto.tipo)

    # Instantánea de la ACL con el canal administrador, para afirmar que la
    # tentativa restringida no altera nada.
    canal_admin = _CanalFree()
    acl_antes = canal_admin.ListarGrantsVigentes(objeto)

    canal_restringido = f.CanalEjecutorRestringido(
        f.APP_ID_SP_EJECUTOR_RESTRINGIDO, secret
    )
    item = ItemGrant(
        principal=OTORGATARIO_GRUPO, privilegio="CAN_USE", objeto=objeto
    )

    resultado = canal_restringido.Otorgar(item)

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert resultado.detalle
    # La ACL no cambió: el fallo de permisos no dejó estado residual.
    assert canal_admin.ListarGrantsVigentes(objeto) == acl_antes
