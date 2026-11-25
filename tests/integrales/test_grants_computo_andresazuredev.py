"""Pruebas integrales de cómputo clásico contra `andresAzureDev` (capability
`compute-grants`, marker `azure_approval`).

Pre-aprobadas por el humano (README D5 y design D8): Free Edition no dispone de
clusters clásicos, por lo que estos casos corren exclusivamente contra Azure,
usando el cluster existente `ComputoPruebasGenerales` (resuelto por nombre vía
API, nunca hardcodeado). Cada operación que toca la ACL corre bajo
`fixtures_computo.ACLRestaurada`, con restauración del estado original.
"""

import pytest

import fixtures_computo as f
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable

pytestmark = pytest.mark.azure_approval

OTORGATARIO_SP, OTORGATARIO_GRUPO = f.OtorgatariosDePerfil(f.PERFIL_AZURE)


def _Cluster():
    id_cluster = f.DescubrirClusterPorNombre(f.PERFIL_AZURE, f.NOMBRE_CLUSTER_AZURE)
    if id_cluster is None:
        pytest.skip(f"No se encontró el cluster '{f.NOMBRE_CLUSTER_AZURE}'.")
    return ObjetoSecurable(identificador=id_cluster, tipo=TipoObjeto.COMPUTO_CLASICO)


def TestOtorgarVerificarRevocarCluster():
    """Otorga CAN_ATTACH_TO al SP sobre el cluster, verifica y revoca."""
    try:
        canal = f.CanalParaPerfil(f.PERFIL_AZURE)
    except Exception as error:  # noqa: BLE001 - transporte no disponible
        pytest.skip(f"Transporte contra {f.PERFIL_AZURE} no disponible: {error}")

    objeto = _Cluster()
    item = ItemGrant(principal=OTORGATARIO_SP, privilegio="CAN_ATTACH_TO", objeto=objeto)
    recurso = f.RecursoDeTipo(objeto.tipo)

    with f.ACLRestaurada(canal, recurso, objeto.identificador):
        assert canal.Otorgar(item).estado is EstadoItem.OTORGADO
        assert item in canal.ListarGrantsVigentes(objeto)
        assert canal.Revocar(item).estado is EstadoItem.OTORGADO
        assert item not in canal.ListarGrantsVigentes(objeto)


def TestLoteN_A_1SobreCluster():
    """Lote N a 1 con SP y grupo `desarrollo_regional` sobre el cluster."""
    try:
        canal = f.CanalParaPerfil(f.PERFIL_AZURE)
    except Exception as error:  # noqa: BLE001 - transporte no disponible
        pytest.skip(f"Transporte contra {f.PERFIL_AZURE} no disponible: {error}")

    objeto = _Cluster()
    recurso = f.RecursoDeTipo(objeto.tipo)

    with f.ACLRestaurada(canal, recurso, objeto.identificador):
        resultados = [
            canal.Otorgar(
                ItemGrant(principal=p, privilegio="CAN_ATTACH_TO", objeto=objeto)
            )
            for p in (OTORGATARIO_SP, OTORGATARIO_GRUPO)
        ]

    assert all(r.estado is EstadoItem.OTORGADO for r in resultados)


def TestClusterInexistenteFallido():
    """Un cluster inexistente se clasifica fallido con el patrón real."""
    try:
        canal = f.CanalParaPerfil(f.PERFIL_AZURE)
    except Exception as error:  # noqa: BLE001 - transporte no disponible
        pytest.skip(f"Transporte contra {f.PERFIL_AZURE} no disponible: {error}")

    item = ItemGrant(
        principal=OTORGATARIO_SP,
        privilegio="CAN_ATTACH_TO",
        objeto=ObjetoSecurable(
            identificador=f.IDENTIFICADOR_INEXISTENTE, tipo=TipoObjeto.COMPUTO_CLASICO
        ),
    )

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.FALLIDO
    assert resultado.detalle
