"""Pruebas unitarias de la fase `Reportador` del pipeline.

Cubren el requirement "Reporte por ítem" del spec `grant-pipeline`: el reporte
consolida para cada ítem su estado final, su detalle o motivo y la
trazabilidad de las fases que atravesó (planificado, pre-flight, ejecutado o
bloqueado, verificado).
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
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reportador import (
    TRAZABILIDAD_EJECUTADO,
    TRAZABILIDAD_PLANIFICADO,
    TRAZABILIDAD_PRE_FLIGHT_BLOQUEADO,
    TRAZABILIDAD_PRE_FLIGHT_EJECUTABLE,
    TRAZABILIDAD_VERIFICADO,
    Reportador,
)
from control_accesos.pipeline.verificador import Verificador


def CrearItem(privilegio, tipo=TipoObjeto.TABLA_DELTA, identificador=None):
    """Construye un ítem de prueba.

    Args:
        privilegio (str): privilegio del ítem.
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str | None): identificación del objeto.

    Returns:
        ItemGrant: ítem listo para procesar por el pipeline.
    """
    if identificador is None:
        identificador = "control.produccion.ventas"
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
    )


def ProcesarConPipelineDePrueba(items, escenario_datos=None):
    """Procesa ítems por las cuatro primeras fases con canales simulados.

    Args:
        items (list[ItemGrant]): ítems planificados.
        escenario_datos (EscenarioSimulacion | None): escenario por defecto
            del canal de datos simulado.

    Returns:
        tuple: (clasificacion, resultados_verificados) para construir el reporte.
    """
    canal_datos = CanalDatosSimulado(
        escenario_por_defecto=escenario_datos or EscenarioSimulacion.EXITO
    )
    canal_control = CanalControlSimulado()
    clasificacion = PreFlight().Clasificar(items)
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar(list(clasificacion.items_ejecutables))
    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)
    return clasificacion, verificados


def TestReporteIncluyeItemBloqueadoConSuMotivo():
    """Escenario del spec: el bloqueado en pre-flight se reporta con motivo."""
    item_bloqueado = CrearItem(
        "CAN_USE", tipo=TipoObjeto.CATALOGO, identificador="control"
    )
    clasificacion, verificados = ProcesarConPipelineDePrueba([item_bloqueado])

    reporte = Reportador().Reportar(
        items_planificados=[item_bloqueado],
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    assert len(reporte.lineas) == 1
    linea = reporte.lineas[0]
    assert linea.item == item_bloqueado
    assert linea.estado is EstadoItem.FALLIDO
    # El motivo es el mensaje preciso de la matriz con sus alternativas.
    assert "CAN_USE" in linea.detalle
    assert "USE CATALOG" in linea.detalle


def TestTrazabilidadDeItemBloqueado():
    """El ítem bloqueado no registra ejecución ni verificación."""
    item_bloqueado = CrearItem(
        "CAN_USE", tipo=TipoObjeto.CATALOGO, identificador="control"
    )
    clasificacion, verificados = ProcesarConPipelineDePrueba([item_bloqueado])

    reporte = Reportador().Reportar(
        items_planificados=[item_bloqueado],
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    trazabilidad = reporte.lineas[0].trazabilidad
    assert TRAZABILIDAD_PLANIFICADO in trazabilidad
    assert TRAZABILIDAD_PRE_FLIGHT_BLOQUEADO in trazabilidad
    assert TRAZABILIDAD_EJECUTADO not in trazabilidad
    assert TRAZABILIDAD_VERIFICADO not in trazabilidad


def TestTrazabilidadDeItemEjecutadoYVerificado():
    """El ítem que pasó por todas las fases registra su recorrido completo."""
    item = CrearItem("SELECT")
    clasificacion, verificados = ProcesarConPipelineDePrueba([item])

    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    assert reporte.lineas[0].trazabilidad == (
        TRAZABILIDAD_PLANIFICADO,
        TRAZABILIDAD_PRE_FLIGHT_EJECUTABLE,
        TRAZABILIDAD_EJECUTADO,
        TRAZABILIDAD_VERIFICADO,
    )


def TestReporteConItemsEnLosTresEstados():
    """El reporte consolida otorgado, fallido y privilegios insuficientes."""
    item_otorgado = CrearItem("SELECT")
    item_fallido = CrearItem("MODIFY")
    item_denegado = CrearItem(
        "CAN_USE", tipo=TipoObjeto.SQL_WAREHOUSE, identificador="a1b2c3"
    )
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarEscenario(
        item_fallido, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    canal_control = CanalControlSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )
    items = [item_otorgado, item_fallido, item_denegado]
    clasificacion = PreFlight().Clasificar(items)
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar(list(clasificacion.items_ejecutables))
    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    reporte = Reportador().Reportar(
        items_planificados=items,
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    estados_por_item = {linea.item: linea.estado for linea in reporte.lineas}
    assert estados_por_item[item_otorgado] is EstadoItem.OTORGADO
    assert estados_por_item[item_fallido] is EstadoItem.FALLIDO
    assert estados_por_item[item_denegado] is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )


def TestDetallePresenteEnEstadosConProblema():
    """Los estados con problema llevan su detalle; el otorgado puede no tenerlo."""
    item_fallido = CrearItem("MODIFY")
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarEscenario(
        item_fallido, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    canal_control = CanalControlSimulado()
    clasificacion = PreFlight().Clasificar([item_fallido])
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar(list(clasificacion.items_ejecutables))
    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    reporte = Reportador().Reportar(
        items_planificados=[item_fallido],
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "no existe" in linea.detalle


def TestReporteConservaElOrdenDePlanificacion():
    """Las líneas del reporte siguen el orden de los ítems planificados."""
    items = [
        CrearItem("SELECT"),
        CrearItem("MODIFY"),
        CrearItem("ALL PRIVILEGES"),
    ]
    clasificacion, verificados = ProcesarConPipelineDePrueba(items)

    reporte = Reportador().Reportar(
        items_planificados=items,
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    assert [linea.item for linea in reporte.lineas] == items


def TestReporteSinItemsQuedaVacio():
    """Sin ítems planificados, el reporte no tiene líneas."""
    reporte = Reportador().Reportar(
        items_planificados=[],
        clasificacion=PreFlight().Clasificar([]),
        resultados_verificados=[],
    )
    assert reporte.lineas == ()


def TestReportePermiteConsultarLineasPorEstado():
    """El reporte permite filtrar sus líneas por estado final (útil para UI)."""
    item_otorgado = CrearItem("SELECT")
    item_bloqueado = CrearItem(
        "CAN_USE", tipo=TipoObjeto.CATALOGO, identificador="control"
    )
    clasificacion, verificados = ProcesarConPipelineDePrueba(
        [item_otorgado, item_bloqueado]
    )

    reporte = Reportador().Reportar(
        items_planificados=[item_otorgado, item_bloqueado],
        clasificacion=clasificacion,
        resultados_verificados=verificados,
    )

    otorgados = reporte.ObtenerLineasPorEstado(EstadoItem.OTORGADO)
    fallidos = reporte.ObtenerLineasPorEstado(EstadoItem.FALLIDO)
    assert [linea.item for linea in otorgados] == [item_otorgado]
    assert [linea.item for linea in fallidos] == [item_bloqueado]
