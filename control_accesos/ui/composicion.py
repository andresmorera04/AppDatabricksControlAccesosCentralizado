"""Composición de la vertical de la UI de grants (design.md D1/D2/D10, tarea 6.4).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Ensamblador de producción que construye, a partir de la configuración, ambos
contextos del modelo broker (`FabricaContextoLlamante` OBO y
`FabricaContextoBroker` SP) y cables todos los servicios del controlador:

- **disponibilidad/resolución** con el resolutor híbrido del design.md D2 broker:
  canal de datos OBO (SHOW GRANTS) + canal de control SP (lectura de ACL);
- **ejecución** con un transporte de permisos mixto (apps -> OBO; resto del
  plano de control -> SP), el agregador de lote en Python y la marca de
  identidad de ejecución `app` en la bitácora;
- **auditoría** con escritores remotos (INSERT vía Statement Execution) sobre la
  identidad del SP, sin sesión Spark (corrección F2);
- **descubrimiento** con los tres descubridores (SCIM-SP, UC-OBO y control SP/OBO).

La entrada delgada (`app.py`) llama a `CrearControladorGrantsUi` y solo renderiza.
"""

from control_accesos.bitacora.escritores_remotos import (
    BitacoraErroresRemota,
    BitacoraEventosRemota,
)
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.cliente_permisos_sdk import ClientePermisosSdk
from control_accesos.canales.reales.descubrimiento_control import DescubridorControl
from control_accesos.canales.reales.descubrimiento_uc import DescubridorUc
from control_accesos.canales.reales.sesion_sql_remota import SesionSqlRemota
from control_accesos.canales.reales.transporte_permisos_mixto import (
    TransportePermisosMixto,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.planificador import Planificador
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reporte_lote import AgregadorReporteLotePython
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.controlador import ControladorGrantsUi
from control_accesos.ui.fabrica_contexto import FabricaContextoLlamante
from control_accesos.ui.fabrica_contexto_broker import FabricaContextoBroker
from control_accesos.ui.presentador import PresentadorGrantsUi
from control_accesos.ui.redaccion import RedactorSecretos
from control_accesos.ui.servicio_descubrimiento import ServicioDescubrimientoUi
from control_accesos.ui.servicio_disponibilidad import (
    ServicioDisponibilidadOpciones,
)
from control_accesos.ui.servicio_ejecucion import ServicioEjecucionGrantsUi
from control_accesos.ui.servicio_previsualizacion import (
    ServicioPrevisualizacionGrants,
)
from control_accesos.ui.servicio_solicitud import ServicioSolicitudGrantsUi

from dataclasses import dataclass

# Identificador del módulo para trazas (convención del proyecto).
MODULO_COMPOSICION = "ui.composicion"

# Identidad de ejecución del modo broker en la bitácora (pipeline).
IDENTIDAD_EJECUCION_BROKER = "app"


@dataclass(frozen=True)
class VerticalUi:
    """Vertical ensamblada: controlador + identidad OBO resuelta del llamante.

    Attributes:
        controlador (ControladorGrantsUi): controlador con todos los servicios.
        identidad (IdentidadLlamante | None): identidad OBO resuelta (None si el
            token no pudo verificarse; el controlador deshabilita la ejecución).
    """

    controlador: "ControladorGrantsUi"
    identidad: object


def CrearVerticalUi(configuracion):
    """Construye la vertical completa (controlador + identidad OBO).

    Args:
        configuracion (ConfiguracionApp): configuración única del proyecto.

    Returns:
        VerticalUi: controlador listo para la pantalla Streamlit y la identidad
            OBO resuelta (la entrada delgada solo consume y renderiza).

    Raises:
        ErrorContextoLlamanteAusente / ErrorAutenticacionLlamante: si no hay
            token OBO o no se puede componer el contexto (la App lo muestra y
            deshabilita la ejecución).
    """
    contexto_llamante = FabricaContextoLlamante(
        configuracion=configuracion
    ).CrearContexto()
    contexto_broker = FabricaContextoBroker(configuracion=configuracion).CrearContexto()

    consultora = ConsultoraMatrizPrivilegios()

    # Resolutores: disponibilidad con canal de control SP (lectura de ACL) y
    # canal de datos OBO (design.md D2 broker).
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=contexto_llamante.canal_datos,
        canal_control=contexto_broker.canal_control,
    )

    # Ejecución: canal de control mixto (apps -> OBO, resto -> SP).
    transporte_mixto = TransportePermisosMixto(
        transporte_apps_obo=ClientePermisosSdk(
            contexto_llamante.cliente_workspace
        ),
        transporte_control_sp=ClientePermisosSdk(contexto_broker.cliente_sp),
    )

    # Auditoría con identidad de la App (INSERT vía Statement Execution).
    sesion_auditoria = SesionSqlRemota(
        api_ejecucion=contexto_broker.cliente_sp.statement_execution,
        warehouse_id=contexto_llamante.warehouse_id,
        token=None,
    )
    registrador_eventos = BitacoraEventosRemota(
        sesion=sesion_auditoria, configuracion=configuracion
    )
    registrador_errores = BitacoraErroresRemota(
        sesion=sesion_auditoria, configuracion=configuracion
    )

    canal_control_ejecucion = CanalControlComputo(
        transporte=transporte_mixto, registrador_errores=registrador_errores
    )
    pipeline = PipelineGrants(
        canal_datos=contexto_llamante.canal_datos,
        canal_control=canal_control_ejecucion,
        consultora=consultora,
        identidad_llamante=contexto_llamante.identidad,
        resolutor_privilegios=resolutor,
        registrador_eventos=registrador_eventos,
        registrador_errores=registrador_errores,
        agregador_lote=AgregadorReporteLotePython(),
        identidad_ejecucion=IDENTIDAD_EJECUCION_BROKER,
    )

    # Descubrimiento: SCIM-SP, UC-OBO y control SP/OBO.
    identificador_logico_token = configuracion.ObtenerAtributo(
        "identificador_logico_uso_token"
    )
    descubrimiento = ServicioDescubrimientoUi(
        descubridor_principales=contexto_broker.descubridor_principales,
        descubridor_uc=DescubridorUc(
            cliente=contexto_llamante.cliente_workspace,
            limite=contexto_broker.limite_opciones,
        ),
        descubridor_control=DescubridorControl(
            cliente_sp=contexto_broker.cliente_sp,
            cliente_obo=contexto_llamante.cliente_workspace,
            limite=contexto_broker.limite_opciones,
            identificador_logico_token=identificador_logico_token,
        ),
    )

    previsualizacion = ServicioPrevisualizacionGrants(
        Planificador(),
        PreFlight(consultora=consultora, resolutor_privilegios=resolutor),
    )

    controlador = ControladorGrantsUi(
        servicio_descubrimiento=descubrimiento,
        servicio_solicitud=ServicioSolicitudGrantsUi(consultora=consultora),
        servicio_disponibilidad=ServicioDisponibilidadOpciones(resolutor),
        servicio_previsualizacion=previsualizacion,
        servicio_ejecucion=ServicioEjecucionGrantsUi(pipeline),
        presentador=PresentadorGrantsUi(),
        consultora=consultora,
        redactor=RedactorSecretos(),
    )
    return VerticalUi(
        controlador=controlador, identidad=contexto_llamante.identidad
    )
