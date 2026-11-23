"""Pruebas unitarias de la fase `PreFlight` del pipeline.

Cubren el requirement "Fase de pre-flight" del spec `grant-pipeline`: cada ítem
se evalúa contra la matriz de compatibilidad y se clasifica como ejecutable o
bloqueado antes de ejecutar nada; los bloqueados quedan excluidos de la
ejecución y llevan el mensaje preciso de la matriz como motivo.
"""

from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pre_flight import PreFlight


def CrearItem(privilegio, tipo=TipoObjeto.CATALOGO, identificador="control"):
    """Construye un ítem de prueba con el privilegio y tipo indicados.

    Args:
        privilegio (str): privilegio del ítem.
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str): identificación del objeto.

    Returns:
        ItemGrant: ítem listo para clasificar en pre-flight.
    """
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
    )


def TestItemCompatibleQuedaEjecutable():
    """Escenario del spec: privilegio válido para el tipo -> ítem ejecutable."""
    items = [CrearItem("USE CATALOG")]

    clasificacion = PreFlight().Clasificar(items)

    assert clasificacion.items_ejecutables == tuple(items)
    assert clasificacion.items_bloqueados == ()


def TestItemIncompatibleQuedaBloqueado():
    """Escenario del spec: privilegio inválido para el tipo -> ítem bloqueado."""
    items = [CrearItem("CAN_USE")]

    clasificacion = PreFlight().Clasificar(items)

    assert clasificacion.items_ejecutables == ()
    assert len(clasificacion.items_bloqueados) == 1


def TestBloqueadoLlevaElMensajePrecisoDeLaMatriz():
    """El motivo del bloqueo es el mensaje de la matriz con sus alternativas."""
    clasificacion = PreFlight().Clasificar([CrearItem("CAN_USE")])

    resultado_bloqueado = clasificacion.items_bloqueados[0]
    assert resultado_bloqueado.estado is EstadoItem.FALLIDO
    assert "CAN_USE" in resultado_bloqueado.detalle
    assert "catalogo" in resultado_bloqueado.detalle
    # El mensaje lista los privilegios válidos alternativos para el tipo.
    assert "USE CATALOG" in resultado_bloqueado.detalle


def TestBloqueadoConservaSuItem():
    """El resultado del ítem bloqueado referencia el ítem que lo originó."""
    item = CrearItem("CAN_USE")

    clasificacion = PreFlight().Clasificar([item])

    assert clasificacion.items_bloqueados[0].item == item


def TestClasificacionDeItemsMixtos():
    """En una lista mixta, cada ítem se clasifica por separado."""
    item_valido = CrearItem("SELECT", tipo=TipoObjeto.TABLA_DELTA)
    item_invalido = CrearItem("READ VOLUME", tipo=TipoObjeto.TABLA_DELTA)

    clasificacion = PreFlight().Clasificar([item_valido, item_invalido])

    assert clasificacion.items_ejecutables == (item_valido,)
    assert len(clasificacion.items_bloqueados) == 1
    assert clasificacion.items_bloqueados[0].item == item_invalido


def TestListaVaciaNoGeneraClasificacion():
    """Sin ítems, la clasificación queda vacía en ambas listas."""
    clasificacion = PreFlight().Clasificar([])

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados == ()


def TestPreFlightUsaLaMatrizInyectada():
    """La matriz se inyecta: una matriz parcial bloquea el tipo no declarado."""
    # Matriz parcial: solo declara el catálogo, sin el SQL warehouse.
    consultora_parcial = ConsultoraMatrizPrivilegios(
        matriz={
            TipoObjeto.CATALOGO: frozenset({"USE CATALOG"}),
        }
    )
    pre_flight = PreFlight(consultora=consultora_parcial)
    item_warehouse = CrearItem(
        "CAN_USE", tipo=TipoObjeto.SQL_WAREHOUSE, identificador="a1b2c3"
    )

    clasificacion = pre_flight.Clasificar([item_warehouse])

    assert clasificacion.items_ejecutables == ()
    assert len(clasificacion.items_bloqueados) == 1


def TestItemsDelPlanoDeControlSeClasificanConSuMatriz():
    """Los niveles CAN_* del plano de control se validan igual que los SQL."""
    item_valido = CrearItem(
        "CAN_USE", tipo=TipoObjeto.SQL_WAREHOUSE, identificador="a1b2c3"
    )
    item_invalido = CrearItem(
        "CAN_ATTACH_TO", tipo=TipoObjeto.SQL_WAREHOUSE, identificador="a1b2c3"
    )

    clasificacion = PreFlight().Clasificar([item_valido, item_invalido])

    assert clasificacion.items_ejecutables == (item_valido,)
    assert clasificacion.items_bloqueados[0].item == item_invalido
