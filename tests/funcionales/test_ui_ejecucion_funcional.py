"""Prueba funcional del servicio de ejecución de grants de la UI (design.md D8).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 5.1.

Composición real sobre canales simulados (sin red): `CanalDatosSimulado` +
`CanalControlSimulado` -> `ResolutorPrivilegiosEfectivos` -> `PipelineGrants`
(con `AgregadorReporteLotePython`) y `ServicioEjecucionGrantsUi` por encima.

Contrato que fija esta prueba (D8):

- 1 a 1 despacha a `ProcesarDesdeEntradas` y devuelve `ReporteGrant`;
- 1 a N / N a 1 despacha a `ProcesarLoteDesdeEntradas` y devuelve
  `ReporteLoteGrant` con totales;
- la ejecución repite el pre-flight: si la autorización cambia tras la
  previsualización, el reporte revalida y bloquea (TOCTOU);
- incluye los bloqueados en el reporte y no ejecuta cuando todos quedan
  bloqueados (cero escrituras);
- continúa ante fallos parciales (un ítem fallido no aborta el resto).
"""

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.planificador import Planificador
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reporte_lote import (
    AgregadorReporteLotePython,
    ReporteLoteGrant,
)
from control_accesos.pipeline.reportador import ReporteGrant
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.servicio_ejecucion import ServicioEjecucionGrantsUi
from control_accesos.ui.servicio_previsualizacion import (
    ServicioPrevisualizacionGrants,
)

LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)
FINANZAS = ObjetoSecurable("finanzas", TipoObjeto.CATALOGO)


def _Identidad():
    return IdentidadLlamante(principal=LLAMANTE)


def _Construir(grants_por_objeto=None):
    """Compone pipeline real (canales simulados) + servicio de ejecución.

    Args:
        grants_por_objeto (dict | None): objeto -> lista de ItemGrant vigentes
            del llamante (autorización previa del workspace).

    Returns:
        tuple: (ServicioEjecucionGrantsUi, ServicioPrevisualizacionGrants,
            canal_datos, pipeline).
    """
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    for objeto, grants in (grants_por_objeto or {}).items():
        canal_datos.ConfigurarGrantsVigentes(objeto, list(grants))

    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=_Identidad(),
        resolutor_privilegios=resolutor,
        agregador_lote=AgregadorReporteLotePython(),
    )
    previsualizacion = ServicioPrevisualizacionGrants(
        Planificador(),
        PreFlight(resolutor_privilegios=resolutor),
    )
    return (
        ServicioEjecucionGrantsUi(pipeline),
        previsualizacion,
        canal_datos,
        pipeline,
    )


def _Grant(caller_privilegio, objeto):
    return ItemGrant(principal=LLAMANTE, privilegio=caller_privilegio, objeto=objeto)


def TestEjecucion1A1UsaProcesarDesdeEntradas():
    """1 a 1 devuelve ReporteGrant con el ítem otorgado."""
    servicio, _, canal_datos, _ = _Construir(
        {VENTAS: [_Grant("SELECT", VENTAS)]}
    )
    solicitud = SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS)

    reporte = servicio.Ejecutar(solicitud, _Identidad())

    assert isinstance(reporte, ReporteGrant)
    assert [linea.estado for linea in reporte.lineas] == [EstadoItem.OTORGADO]
    assert len(canal_datos.operaciones_ejecutadas) == 1


def TestEjecucionLoteUsaProcesarLoteDesdeEntradasConTotales():
    """1 a N devuelve ReporteLoteGrant con totales."""
    servicio, _, _, _ = _Construir(
        {
            VENTAS: [_Grant("SELECT", VENTAS)],
            FINANZAS: [_Grant("SELECT", FINANZAS)],
        }
    )
    lote = SolicitudLoteGrant(
        principales=(DESTINO,),
        privilegios=("SELECT",),
        objetos=(VENTAS, FINANZAS),
    )

    reporte = servicio.Ejecutar(lote, _Identidad())

    assert isinstance(reporte, ReporteLoteGrant)
    assert reporte.total_items == 2
    assert reporte.totales_por_estado[EstadoItem.OTORGADO] == 2


def TestEjecucionRepitePreFlight():
    """La ejecución revalida: revocar la autorización tras previsualizar bloquea."""
    servicio, previsualizacion, _, _ = _Construir(
        {VENTAS: [_Grant("SELECT", VENTAS)]}
    )
    solicitud = SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS)
    identidad = _Identidad()

    # Previsualización con autorización vigente: 1 ejecutable.
    clasificacion = previsualizacion.Previsualizar(solicitud, identidad)
    assert len(clasificacion.items_ejecutables) == 1

    # Entre la previsualización y la confirmación, el llamante pierde SELECT.
    servicio_actualizado, _, canal_datos, _ = _Construir({VENTAS: []})
    reporte = servicio_actualizado.Ejecutar(solicitud, identidad)

    assert [linea.estado for linea in reporte.lineas] == [
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    ], "La ejecución debe re-ejecutar el pre-flight y bloquear (TOCTOU)."
    assert canal_datos.operaciones_ejecutadas == []


def TestNoEjecutaCuandoTodosBloqueados():
    """Sin autoridad del llamante, no se ejecuta nada y todo queda bloqueado."""
    servicio, _, canal_datos, _ = _Construir({VENTAS: []})
    solicitud = SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS)

    reporte = servicio.Ejecutar(solicitud, _Identidad())

    assert [linea.estado for linea in reporte.lineas] == [
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    ]
    assert canal_datos.operaciones_ejecutadas == []


def TestContinuaAnteFallosParciales():
    """Un ítem fallido no aborta el resto del lote."""
    servicio, _, _, _ = _Construir(
        {
            VENTAS: [_Grant("SELECT", VENTAS)],
            FINANZAS: [_Grant("SELECT", FINANZAS)],
        }
    )
    lote = SolicitudLoteGrant(
        principales=(DESTINO,),
        privilegios=("SELECT",),
        objetos=(VENTAS, FINANZAS),
    )
    items = lote.NormalizarAItems()
    item_finanzas = next(i for i in items if i.objeto == FINANZAS)

    # Configura el fallo por ítem en el canal simulado (objeto inexistente).
    canal_datos_fallo = CanalDatosSimulado()
    canal_datos_fallo.ConfigurarGrantsVigentes(
        VENTAS, [_Grant("SELECT", VENTAS)]
    )
    canal_datos_fallo.ConfigurarGrantsVigentes(
        FINANZAS, [_Grant("SELECT", FINANZAS)]
    )
    canal_datos_fallo.ConfigurarEscenario(
        item_finanzas, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos_fallo, canal_control=CanalControlSimulado()
    )
    pipeline = PipelineGrants(
        canal_datos=canal_datos_fallo,
        canal_control=CanalControlSimulado(),
        identidad_llamante=_Identidad(),
        resolutor_privilegios=resolutor,
        agregador_lote=AgregadorReporteLotePython(),
    )

    reporte = ServicioEjecucionGrantsUi(pipeline).Ejecutar(lote, _Identidad())

    assert reporte.total_items == 2
    assert reporte.totales_por_estado[EstadoItem.OTORGADO] == 1
    assert reporte.totales_por_estado[EstadoItem.FALLIDO] == 1
