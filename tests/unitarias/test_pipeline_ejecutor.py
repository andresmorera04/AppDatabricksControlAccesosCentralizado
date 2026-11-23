"""Pruebas unitarias de la fase `Ejecutor` del pipeline.

Cubren el requirement "Fase de ejecución por canal según el plano" del spec
`grant-pipeline`: cada ítem ejecutable se envía al canal que corresponde al
plano de su objeto (datos -> canal SQL; control -> canal SDK/REST), y cada
ítem produce su propio resultado sin que un fallo puntual aborte la ejecución
completa.
"""

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
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
from control_accesos.pipeline.ejecutor import Ejecutor


def CrearItem(privilegio, tipo, identificador):
    """Construye un ítem de prueba del plano que corresponde al tipo.

    Args:
        privilegio (str): privilegio del ítem.
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str): identificación del objeto.

    Returns:
        ItemGrant: ítem listo para ejecutar.
    """
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
    )


def CrearItemDeDatos(privilegio="SELECT"):
    """Construye un ítem del plano de datos (tabla delta)."""
    return CrearItem(
        privilegio=privilegio,
        tipo=TipoObjeto.TABLA_DELTA,
        identificador="control.produccion.ventas",
    )


def CrearItemDeControl(privilegio="CAN_USE"):
    """Construye un ítem del plano de control (SQL warehouse)."""
    return CrearItem(
        privilegio=privilegio,
        tipo=TipoObjeto.SQL_WAREHOUSE,
        identificador="a1b2c3d4e5f6",
    )


def CrearEjecutorDePrueba(escenario_datos=None, escenario_control=None):
    """Construye un ejecutor con canales simulados configurables.

    Args:
        escenario_datos (EscenarioSimulacion | None): escenario del canal SQL.
        escenario_control (EscenarioSimulacion | None): escenario del canal
            SDK/REST.

    Returns:
        tuple: (ejecutor, canal_datos, canal_control) para inspeccionar las
            operaciones ejecutadas en las pruebas.
    """
    canal_datos = CanalDatosSimulado(
        escenario_por_defecto=escenario_datos or EscenarioSimulacion.EXITO
    )
    canal_control = CanalControlSimulado(
        escenario_por_defecto=escenario_control or EscenarioSimulacion.EXITO
    )
    ejecutor = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    )
    return ejecutor, canal_datos, canal_control


def TestItemDeDatosSeEjecutaPorElCanalSql():
    """Escenario del spec: objeto del plano de datos -> canal SQL."""
    ejecutor, canal_datos, canal_control = CrearEjecutorDePrueba()
    item = CrearItemDeDatos()

    resultados = ejecutor.Ejecutar([item])

    assert len(resultados) == 1
    assert resultados[0].estado is EstadoItem.OTORGADO
    assert canal_datos.operaciones_ejecutadas[0].item == item
    assert canal_control.operaciones_ejecutadas == []


def TestItemDeControlSeEjecutaPorElCanalSdkRest():
    """Escenario del spec: objeto del plano de control -> canal SDK/REST."""
    ejecutor, canal_datos, canal_control = CrearEjecutorDePrueba()
    item = CrearItemDeControl()

    resultados = ejecutor.Ejecutar([item])

    assert len(resultados) == 1
    assert resultados[0].estado is EstadoItem.OTORGADO
    assert canal_control.operaciones_ejecutadas[0].item == item
    assert canal_datos.operaciones_ejecutadas == []


def TestSolicitudMixtaEnrutaCadaItemPorSuPlano():
    """En una lista mixta, cada ítem va al canal de su propio plano."""
    ejecutor, canal_datos, canal_control = CrearEjecutorDePrueba()
    item_datos = CrearItemDeDatos()
    item_control = CrearItemDeControl()

    resultados = ejecutor.Ejecutar([item_datos, item_control])

    assert len(resultados) == 2
    assert all(
        resultado.estado is EstadoItem.OTORGADO for resultado in resultados
    )
    assert len(canal_datos.operaciones_ejecutadas) == 1
    assert len(canal_control.operaciones_ejecutadas) == 1


def TestFalloPuntualNoAbortaLaEjecucionCompleta():
    """Escenario del spec: un fallo puntual no aborta los demás ítems."""
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    ejecutor = Ejecutor(canal_datos=canal_datos, canal_control=canal_control)

    item_fallido = CrearItemDeDatos(privilegio="MODIFY")
    canal_datos.ConfigurarEscenario(
        item_fallido, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    item_exitoso = CrearItemDeDatos(privilegio="SELECT")

    resultados = ejecutor.Ejecutar([item_fallido, item_exitoso])

    assert len(resultados) == 2
    estados = {resultado.item: resultado.estado for resultado in resultados}
    assert estados[item_fallido] is EstadoItem.FALLIDO
    assert estados[item_exitoso] is EstadoItem.OTORGADO


def TestPermisoDenegadoSeReportaComoPrivilegiosInsuficientes():
    """El permiso denegado del canal se reporta distinguible por ítem."""
    ejecutor, _, _ = CrearEjecutorDePrueba(
        escenario_control=EscenarioSimulacion.PERMISO_DENEGADO
    )

    resultados = ejecutor.Ejecutar([CrearItemDeControl()])

    assert resultados[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestResultadosConservanElOrdenDeLosItems():
    """Los resultados se devuelven en el mismo orden que los ítems."""
    ejecutor, _, _ = CrearEjecutorDePrueba()
    items = [
        CrearItemDeDatos(privilegio="SELECT"),
        CrearItemDeControl(),
        CrearItemDeDatos(privilegio="MODIFY"),
    ]

    resultados = ejecutor.Ejecutar(items)

    assert [resultado.item for resultado in resultados] == items


def TestListaVaciaNoEjecutaNada():
    """Sin ítems ejecutables, el ejecutor no invoca ningún canal."""
    ejecutor, canal_datos, canal_control = CrearEjecutorDePrueba()

    resultados = ejecutor.Ejecutar([])

    assert resultados == []
    assert canal_datos.operaciones_ejecutadas == []
    assert canal_control.operaciones_ejecutadas == []


def TestEjecutorAceptaOperacionDeRevocacion():
    """El ejecutor también enruta revocaciones por el plano del objeto."""
    ejecutor, canal_datos, canal_control = CrearEjecutorDePrueba()
    item_datos = CrearItemDeDatos()
    item_control = CrearItemDeControl()

    resultados = ejecutor.Revocar([item_datos, item_control])

    assert len(resultados) == 2
    assert canal_datos.operaciones_ejecutadas[0].operacion == "revocar"
    assert canal_control.operaciones_ejecutadas[0].operacion == "revocar"
