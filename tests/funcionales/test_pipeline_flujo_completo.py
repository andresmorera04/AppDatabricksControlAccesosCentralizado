"""Pruebas funcionales del flujo completo del pipeline con canales simulados.

Cubren el escenario "Reporte mixto" del spec `grant-pipeline` de punta a
punta: una solicitud mixta con ítem bloqueado en pre-flight, ítem otorgado,
ítem fallido e ítem con privilegios insuficientes, todos reportados sin
abortar la operación. Se usan únicamente los canales simulados: ninguna prueba
de este change interactúa con sistemas externos (spec `channel-adapters`).
"""

import pytest

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
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.reportador import (
    TRAZABILIDAD_ITINERARIO_BLOQUEADO,
    TRAZABILIDAD_ITINERARIO_COMPLETO,
)


def CrearPipeline(canal_datos=None, canal_control=None):
    """Construye un pipeline con canales simulados configurables.

    Args:
        canal_datos (CanalDatosSimulado | None): canal SQL simulado; por
            defecto uno nuevo en escenario de éxito.
        canal_control (CanalControlSimulado | None): canal SDK/REST simulado;
            por defecto uno nuevo en escenario de éxito.

    Returns:
        tuple: (pipeline, canal_datos, canal_control) para inspeccionar las
            operaciones ejecutadas.
    """
    canal_datos = canal_datos or CanalDatosSimulado()
    canal_control = canal_control or CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=canal_control
    )
    return pipeline, canal_datos, canal_control


def TestFlujoCompletoConSolicitudMixtaDeCuatroEstados():
    """Escenario del spec: bloqueado + otorgado + fallido + insuficiente.

    Una única solicitud sobre un SQL warehouse con cuatro privilegios:

    - CAN_USE: combinación válida, ejecución exitosa y verificación confirmada
      -> OTORGADO.
    - CAN_MANAGE: combinación válida, ejecución con objeto inexistente
      -> FALLIDO.
    - CAN_MONITOR: combinación válida, ejecución con permiso denegado
      -> PRIVILEGIOS_INSUFICIENTES.
    - SELECT: combinación inválida para sql_warehouse -> bloqueado en
      pre-flight, reportado como FALLIDO con el mensaje de la matriz.

    Ningún ítem aborta la operación: el reporte incluye los cuatro.
    """
    canal_control = CanalControlSimulado()
    pipeline, _, _ = CrearPipeline(canal_control=canal_control)

    warehouse = ObjetoSecurable(
        identificador="a1b2c3d4e5f6", tipo=TipoObjeto.SQL_WAREHOUSE
    )
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["CAN_USE", "CAN_MANAGE", "CAN_MONITOR", "SELECT"],
        objeto=warehouse,
    )

    # Se configuran los escenarios por ítem: el fallo puntual y el permiso
    # denegado no deben impedir el otorgamiento del resto.
    item_fallido = next(
        item
        for item in _ItemsDeSolicitud(solicitud)
        if item.privilegio == "CAN_MANAGE"
    )
    item_denegado = next(
        item
        for item in _ItemsDeSolicitud(solicitud)
        if item.privilegio == "CAN_MONITOR"
    )
    canal_control.ConfigurarEscenario(
        item_fallido, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    canal_control.ConfigurarEscenario(
        item_denegado, EscenarioSimulacion.PERMISO_DENEGADO
    )

    reporte = pipeline.Procesar(solicitud)

    # Los cuatro ítems están reportados, sin abortar la operación.
    assert len(reporte.lineas) == 4
    estados_por_privilegio = {
        linea.item.privilegio: linea.estado for linea in reporte.lineas
    }
    assert estados_por_privilegio["CAN_USE"] is EstadoItem.OTORGADO
    assert estados_por_privilegio["CAN_MANAGE"] is EstadoItem.FALLIDO
    assert estados_por_privilegio["CAN_MONITOR"] is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )
    assert estados_por_privilegio["SELECT"] is EstadoItem.FALLIDO

    # El bloqueado lleva el motivo preciso de la matriz y su trazabilidad
    # llega solo hasta pre-flight; los demás recorrieron el flujo completo.
    lineas_por_privilegio = {
        linea.item.privilegio: linea for linea in reporte.lineas
    }
    linea_bloqueada = lineas_por_privilegio["SELECT"]
    assert "no es válido" in linea_bloqueada.detalle
    assert "CAN_USE" in linea_bloqueada.detalle
    assert linea_bloqueada.trazabilidad == TRAZABILIDAD_ITINERARIO_BLOQUEADO
    assert (
        lineas_por_privilegio["CAN_USE"].trazabilidad
        == TRAZABILIDAD_ITINERARIO_COMPLETO
    )


def _ItemsDeSolicitud(solicitud):
    """Expande una solicitud en sus ítems atómicos (auxiliar de la prueba).

    Args:
        solicitud (SolicitudGrant): solicitud a expandir.

    Returns:
        list[ItemGrant]: ítems atómicos de la solicitud.
    """
    from control_accesos.pipeline.planificador import Planificador

    return Planificador().Planificar(solicitud)


def TestFlujoCompletoDelPlanoDeDatos():
    """Una solicitud sobre catálogo se ejecuta por el canal SQL simulado."""
    pipeline, canal_datos, canal_control = CrearPipeline()
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="grupo_analistas", tipo=TipoPrincipal.GRUPO
        ),
        privilegios=["USE CATALOG", "SELECT"],
        objeto=ObjetoSecurable(
            identificador="control", tipo=TipoObjeto.CATALOGO
        ),
    )

    reporte = pipeline.Procesar(solicitud)

    assert len(reporte.lineas) == 2
    assert all(
        linea.estado is EstadoItem.OTORGADO for linea in reporte.lineas
    )
    # Todo pasó por el canal de datos; el canal de control no se usó.
    assert len(canal_datos.operaciones_ejecutadas) == 2
    assert canal_control.operaciones_ejecutadas == []
    # La verificación confirmó los grants vigentes sobre el objeto.
    assert len(canal_datos.ListarGrantsVigentes(solicitud.objeto)) == 2


def TestProcesarDesdeEntradasConstruyeLaSolicitud():
    """El pipeline acepta las entradas directamente (camino de la UI, C9)."""
    pipeline, _, _ = CrearPipeline()

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="sp_pipelines",
            tipo=TipoPrincipal.SERVICE_PRINCIPAL,
        ),
        privilegios=["select"],
        objeto=ObjetoSecurable(
            identificador="Control.Produccion.Ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    assert len(reporte.lineas) == 1
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    # Las entradas se normalizaron: privilegio en mayúsculas y, en el plano
    # de datos, identificador en minúsculas.
    assert reporte.lineas[0].item.privilegio == "SELECT"
    assert (
        reporte.lineas[0].item.objeto.identificador
        == "control.produccion.ventas"
    )


def TestSolicitudInvalidaSeRechazaAntesDeEjecutar():
    """Sin privilegios válidos no se genera ningún ítem ni se toca un canal."""
    pipeline, canal_datos, canal_control = CrearPipeline()

    with pytest.raises(ErrorDominio):
        pipeline.ProcesarDesdeEntradas(
            principal=Principal(
                identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
            ),
            privilegios=[],
            objeto=ObjetoSecurable(
                identificador="control", tipo=TipoObjeto.CATALOGO
            ),
        )

    assert canal_datos.operaciones_ejecutadas == []
    assert canal_control.operaciones_ejecutadas == []


def TestDiscrepanciaDeVerificacionSeReportaEnFlujoCompleto():
    """Otorgado que no queda vigente se reporta FALLIDO de punta a punta."""
    canal_datos = CanalDatosSimulado(registrar_grants_otorgados=False)
    pipeline, _, _ = CrearPipeline(canal_datos=canal_datos)
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    reporte = pipeline.Procesar(solicitud)

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert "verificación" in reporte.lineas[0].detalle.lower()


def TestMatrizInyectadaAmpliaElComportamiento():
    """La matriz se inyecta: una matriz ampliada habilita nuevas combinaciones.

    Demuestra la extensibilidad declarada en el spec `privilege-matrix` sin
    tocar el código del pipeline.
    """
    from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
    from control_accesos.matriz.matriz_privilegios import MATRIZ_PRIVILEGIOS

    # Matriz ampliada: se agrega un privilegio nuevo al catálogo.
    matriz_ampliada = dict(MATRIZ_PRIVILEGIOS)
    matriz_ampliada[TipoObjeto.CATALOGO] = MATRIZ_PRIVILEGIOS[
        TipoObjeto.CATALOGO
    ] | {"PRIVILEGIO_NUEVO"}

    canal_datos = CanalDatosSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=CanalControlSimulado(),
        consultora=ConsultoraMatrizPrivilegios(matriz=matriz_ampliada),
    )
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["PRIVILEGIO_NUEVO"],
        objeto=ObjetoSecurable(
            identificador="control", tipo=TipoObjeto.CATALOGO
        ),
    )

    reporte = pipeline.Procesar(solicitud)

    # Con la matriz declarada del proyecto estaría bloqueado; con la ampliada
    # es ejecutable y termina otorgado.
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
