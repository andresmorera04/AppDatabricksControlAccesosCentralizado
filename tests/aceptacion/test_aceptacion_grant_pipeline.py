"""Pruebas de aceptación del capability `grant-pipeline`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/specs/grant-pipeline/spec.md`:

- Fase de planificación:
  - Expansión en ítems atómicos -> TestEscenarioExpansionEnItemsAtomicos
  - Solicitud inválida detectada en planificación
    -> TestEscenarioSolicitudInvalidaDetectadaEnPlanificacion
- Fase de pre-flight:
  - Ítem compatible queda ejecutable
    -> TestEscenarioItemCompatibleQuedaEjecutable
  - Ítem incompatible queda bloqueado
    -> TestEscenarioItemIncompatibleQuedaBloqueado
- Fase de ejecución por canal sin abortar la operación:
  - Fallo puntual no aborta el resto
    -> TestEscenarioFalloPuntualNoAbortaElResto
  - Selección de canal por plano del objeto
    -> TestEscenarioSeleccionDeCanalPorPlanoDelObjeto
- Fase de verificación posterior al grant:
  - Grant verificado con éxito -> TestEscenarioGrantVerificadoConExito
  - Discrepancia entre ejecución y verificación
    -> TestEscenarioDiscrepanciaEntreEjecucionYVerificacion
- Fase de reporte por ítem:
  - Reporte completo con ítem bloqueado
    -> TestEscenarioReporteCompletoConItemBloqueado
  - Reporte con ítems en los tres estados
    -> TestEscenarioReporteConItemsEnLosTresEstados
- Trazabilidad de fases por ítem:
  - Reconstrucción del recorrido de un ítem bloqueado
    -> TestEscenarioReconstruccionDelRecorridoDeUnItemBloqueado
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
from control_accesos.pipeline.planificador import Planificador
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reportador import (
    TRAZABILIDAD_ITINERARIO_BLOQUEADO,
)


def CrearSolicitudDePrueba(privilegios=None, objeto=None):
    """Construye una solicitud de prueba con datos válidos.

    Args:
        privilegios (list[str] | None): privilegios; por defecto SELECT.
        objeto (ObjetoSecurable | None): objeto; por defecto una tabla delta.

    Returns:
        SolicitudGrant: solicitud 1 a 1 lista para procesar.
    """
    if privilegios is None:
        privilegios = ["SELECT"]
    if objeto is None:
        objeto = ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        )
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=privilegios,
        objeto=objeto,
    )


def CrearPipeline(canal_datos=None, canal_control=None):
    """Construye un pipeline de aceptación con canales simulados.

    Args:
        canal_datos (CanalDatosSimulado | None): canal SQL simulado.
        canal_control (CanalControlSimulado | None): canal SDK/REST simulado.

    Returns:
        tuple: (pipeline, canal_datos, canal_control).
    """
    canal_datos = canal_datos or CanalDatosSimulado()
    canal_control = canal_control or CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=canal_control
    )
    return pipeline, canal_datos, canal_control


def TestEscenarioExpansionEnItemsAtomicos():
    """Escenario: Expansión en ítems atómicos.

    WHEN llega una solicitud con un principal, dos privilegios y un objeto
    THEN el pipeline la expande en dos ítems atómicos, uno por privilegio,
         cada uno procesable y reportable de forma independiente.
    """
    pipeline, _, _ = CrearPipeline()
    solicitud = CrearSolicitudDePrueba(privilegios=["SELECT", "MODIFY"])

    reporte = pipeline.Procesar(solicitud)

    # Dos ítems, cada uno con su propia línea de reporte independiente.
    assert len(reporte.lineas) == 2
    privilegios_reportados = [
        linea.item.privilegio for linea in reporte.lineas
    ]
    assert privilegios_reportados == ["SELECT", "MODIFY"]
    assert all(
        linea.item.principal == solicitud.principal
        and linea.item.objeto == solicitud.objeto
        for linea in reporte.lineas
    )


def TestEscenarioSolicitudInvalidaDetectadaEnPlanificacion():
    """Escenario: Solicitud inválida detectada en planificación.

    WHEN llega una solicitud que no cumple la forma cardinalidad 1 a 1
    THEN el pipeline la rechaza con mensaje explícito y no genera ítems ni
         ejecuta fase alguna.
    """
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

    # Ninguna fase posterior se ejecutó: los canales no recibieron nada.
    assert canal_datos.operaciones_ejecutadas == []
    assert canal_control.operaciones_ejecutadas == []


def TestEscenarioItemCompatibleQuedaEjecutable():
    """Escenario: Ítem compatible queda ejecutable.

    WHEN en pre-flight un ítem tiene un privilegio válido para el tipo de su
         objeto
    THEN el pipeline lo clasifica como ejecutable y lo envía a la fase de
         ejecución.
    """
    pipeline, canal_datos, _ = CrearPipeline()
    solicitud = CrearSolicitudDePrueba(privilegios=["SELECT"])

    reporte = pipeline.Procesar(solicitud)

    # Clasificado como ejecutable: llegó al canal y terminó otorgado.
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert len(canal_datos.operaciones_ejecutadas) == 1


def TestEscenarioItemIncompatibleQuedaBloqueado():
    """Escenario: Ítem incompatible queda bloqueado.

    WHEN en pre-flight un ítem tiene un privilegio inválido para el tipo de su
         objeto
    THEN el pipeline lo clasifica como bloqueado con el mensaje de error
         preciso de la matriz, y no lo envía a ejecución.
    """
    pipeline, canal_datos, _ = CrearPipeline()
    solicitud = CrearSolicitudDePrueba(privilegios=["CAN_USE"])

    reporte = pipeline.Procesar(solicitud)

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    # Mensaje preciso de la matriz con el tipo de objeto involucrado.
    assert "CAN_USE" in reporte.lineas[0].detalle
    assert "tabla_delta" in reporte.lineas[0].detalle
    assert "no es válido" in reporte.lineas[0].detalle
    # No llegó a ejecución.
    assert canal_datos.operaciones_ejecutadas == []


def TestEscenarioFalloPuntualNoAbortaElResto():
    """Escenario: Fallo puntual no aborta el resto.

    WHEN de tres ítems ejecutables el segundo falla durante la ejecución
    THEN el pipeline ejecuta y reporta los tres ítems: el fallo del segundo no
         cancela la ejecución del primero ni del tercero.
    """
    canal_datos = CanalDatosSimulado()
    pipeline, _, _ = CrearPipeline(canal_datos=canal_datos)
    solicitud = CrearSolicitudDePrueba(
        privilegios=["SELECT", "MODIFY", "ALL PRIVILEGES"]
    )

    # Se configura el fallo puntual del segundo ítem (MODIFY).
    from control_accesos.dominio.modelos import ItemGrant

    item_que_falla = ItemGrant(
        principal=solicitud.principal,
        privilegio="MODIFY",
        objeto=solicitud.objeto,
    )
    canal_datos.ConfigurarEscenario(
        item_que_falla, EscenarioSimulacion.OBJETO_INEXISTENTE
    )

    reporte = pipeline.Procesar(solicitud)

    # Los tres ítems fueron ejecutados y reportados.
    assert len(canal_datos.operaciones_ejecutadas) == 3
    assert len(reporte.lineas) == 3
    estados_por_privilegio = {
        linea.item.privilegio: linea.estado for linea in reporte.lineas
    }
    assert estados_por_privilegio["SELECT"] is EstadoItem.OTORGADO
    assert estados_por_privilegio["MODIFY"] is EstadoItem.FALLIDO
    assert estados_por_privilegio["ALL PRIVILEGES"] is EstadoItem.OTORGADO


def TestEscenarioSeleccionDeCanalPorPlanoDelObjeto():
    """Escenario: Selección de canal por plano del objeto.

    WHEN se ejecuta un ítem cuyo objeto pertenece al plano de datos
    THEN el pipeline lo envía por el canal SQL; y cuando el objeto pertenece
         al plano de control, lo envía por el canal SDK/REST.
    """
    pipeline, canal_datos, canal_control = CrearPipeline()

    # Ítem del plano de datos -> canal SQL.
    pipeline.Procesar(CrearSolicitudDePrueba(privilegios=["SELECT"]))
    assert len(canal_datos.operaciones_ejecutadas) == 1
    assert canal_control.operaciones_ejecutadas == []

    # Ítem del plano de control -> canal SDK/REST.
    pipeline.Procesar(
        CrearSolicitudDePrueba(
            privilegios=["CAN_USE"],
            objeto=ObjetoSecurable(
                identificador="a1b2c3d4e5f6",
                tipo=TipoObjeto.SQL_WAREHOUSE,
            ),
        )
    )
    assert len(canal_control.operaciones_ejecutadas) == 1
    # El canal SQL no recibió el ítem del plano de control.
    assert len(canal_datos.operaciones_ejecutadas) == 1


def TestEscenarioGrantVerificadoConExito():
    """Escenario: Grant verificado con éxito.

    WHEN un ítem se ejecuta como otorgado y la verificación encuentra el
         privilegio concedido sobre el objeto
    THEN el ítem se reporta con estado `otorgado`.
    """
    canal_datos = CanalDatosSimulado()
    pipeline, _, _ = CrearPipeline(canal_datos=canal_datos)
    solicitud = CrearSolicitudDePrueba(privilegios=["SELECT"])

    reporte = pipeline.Procesar(solicitud)

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    # La verificación consultó los grants vigentes y encontró el privilegio.
    assert len(canal_datos.ListarGrantsVigentes(solicitud.objeto)) == 1


def TestEscenarioDiscrepanciaEntreEjecucionYVerificacion():
    """Escenario: Discrepancia entre ejecución y verificación.

    WHEN un ítem se ejecuta como otorgado pero la verificación no encuentra el
         privilegio concedido
    THEN el ítem se reporta con estado `fallido` y un detalle que indica la
         discrepancia detectada en la verificación.
    """
    canal_datos = CanalDatosSimulado(registrar_grants_otorgados=False)
    pipeline, _, _ = CrearPipeline(canal_datos=canal_datos)

    reporte = pipeline.Procesar(CrearSolicitudDePrueba(privilegios=["SELECT"]))

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert "verificación" in reporte.lineas[0].detalle.lower()


def TestEscenarioReporteCompletoConItemBloqueado():
    """Escenario: Reporte completo con ítem bloqueado.

    WHEN una solicitud de dos ítems termina con uno bloqueado en pre-flight y
         uno otorgado
    THEN el reporte incluye ambos ítems: el bloqueado con su motivo y el
         otorgado con estado `otorgado`.
    """
    pipeline, _, _ = CrearPipeline()
    solicitud = CrearSolicitudDePrueba(
        privilegios=["SELECT", "CAN_USE"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    reporte = pipeline.Procesar(solicitud)

    assert len(reporte.lineas) == 2
    lineas_por_privilegio = {
        linea.item.privilegio: linea for linea in reporte.lineas
    }
    assert (
        lineas_por_privilegio["SELECT"].estado is EstadoItem.OTORGADO
    )
    bloqueada = lineas_por_privilegio["CAN_USE"]
    assert bloqueada.estado is EstadoItem.FALLIDO
    # El motivo del bloqueo es el mensaje preciso de la matriz.
    assert "CAN_USE" in bloqueada.detalle


def TestEscenarioReporteConItemsEnLosTresEstados():
    """Escenario: Reporte con ítems en los tres estados.

    WHEN una solicitud termina con un ítem otorgado, uno fallido y uno con
         privilegios insuficientes
    THEN el reporte incluye los tres ítems, cada uno con su estado y su
         detalle correspondiente.
    """
    canal_datos = CanalDatosSimulado()
    pipeline, _, _ = CrearPipeline(canal_datos=canal_datos)
    solicitud = CrearSolicitudDePrueba(
        privilegios=["SELECT", "MODIFY", "ALL PRIVILEGES"]
    )

    # MODIFY falla por objeto inexistente; ALL PRIVILEGES por permiso denegado.
    from control_accesos.dominio.modelos import ItemGrant

    for privilegio, escenario in (
        ("MODIFY", EscenarioSimulacion.OBJETO_INEXISTENTE),
        ("ALL PRIVILEGES", EscenarioSimulacion.PERMISO_DENEGADO),
    ):
        canal_datos.ConfigurarEscenario(
            ItemGrant(
                principal=solicitud.principal,
                privilegio=privilegio,
                objeto=solicitud.objeto,
            ),
            escenario,
        )

    reporte = pipeline.Procesar(solicitud)

    assert len(reporte.lineas) == 3
    estados_por_privilegio = {
        linea.item.privilegio: linea.estado for linea in reporte.lineas
    }
    assert estados_por_privilegio["SELECT"] is EstadoItem.OTORGADO
    assert estados_por_privilegio["MODIFY"] is EstadoItem.FALLIDO
    assert estados_por_privilegio["ALL PRIVILEGES"] is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )
    # Los estados con problema llevan su detalle.
    detalles_por_privilegio = {
        linea.item.privilegio: linea.detalle for linea in reporte.lineas
    }
    assert "no existe" in detalles_por_privilegio["MODIFY"]
    assert "PERMISSION_DENIED" in detalles_por_privilegio["ALL PRIVILEGES"]


def TestEscenarioReconstruccionDelRecorridoDeUnItemBloqueado():
    """Escenario: Reconstrucción del recorrido de un ítem bloqueado.

    WHEN el reporte incluye un ítem bloqueado en pre-flight
    THEN el ítem muestra que fue planificado, evaluado en pre-flight y
         excluido de ejecución, con el motivo de bloqueo.
    """
    pipeline, _, _ = CrearPipeline()
    solicitud = CrearSolicitudDePrueba(privilegios=["CAN_USE"])

    reporte = pipeline.Procesar(solicitud)

    linea = reporte.lineas[0]
    # Recorrido reconstruible: planificado y bloqueado en pre-flight; las
    # marcas de ejecución y verificación están ausentes.
    assert linea.trazabilidad == TRAZABILIDAD_ITINERARIO_BLOQUEADO
    # El motivo de bloqueo acompaña la trazabilidad.
    assert linea.detalle is not None
    assert "no es válido" in linea.detalle

    # La clasificación de pre-flight por sí sola también es reconstruible.
    clasificacion = PreFlight().Clasificar(
        Planificador().Planificar(solicitud)
    )
    assert clasificacion.items_ejecutables == ()
    assert len(clasificacion.items_bloqueados) == 1
