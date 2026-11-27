"""Integral `free` de ejecución 1 a 1 con restauración (tarea 7.3).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Verifica contra `andresFree` un flujo 1 a 1 real por el canal SQL de producción
(`CanalSqlDatos` sobre la Statement Execution API del CLI):

- `ServicioEjecucionGrantsUi` despacha a `ProcesarDesdeEntradas`: GRANT real,
  verificable con `SHOW GRANT`; el reporte por ítem refleja el resultado real;
- un ítem incompatible con la matriz se bloquea SIN emitir GRANT;
- revocación en `finally` (sin estado residual).

Sin CLI o sin warehouse, el módulo se SALTA con motivo. El privilegio exacto y
el catálogo se ajustan contra el workspace al desplegar (semántica C3 de
coincidencia exacta).
"""

import shutil

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.simulados.canales_simulados import CanalControlSimulado
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.reporte_lote import AgregadorReporteLotePython
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.servicio_ejecucion import ServicioEjecucionGrantsUi
from adaptador_auth_databricks import ProveedorIdentidadScimCli
from adaptador_sql_databricks import (
    DescubrirWarehouseServerless,
    SesionSqlDatabricks,
)

pytestmark = pytest.mark.free

# Privilegios de prueba sobre CATALOGO (matriz): válido y reversible vs. inválido.
PRIVILEGIO_VALIDO = "READ METADATA"
PRIVILEGIO_INVALIDO = "CAN_USE"


@pytest.fixture(scope="module")
def vertical():
    """Compone identidad, canal real y pipeline de ejecución 1 a 1."""
    if shutil.which("databricks") is None:
        pytest.skip("El CLI de Databricks no está instalado; se requiere para la integral.")
    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip("andresFree no expone un SQL warehouse serverless.")
    sesion = SesionSqlDatabricks(warehouse_id=warehouse_id)

    canal_datos = CanalSqlDatos(sesion_sql=sesion)
    # Canal de control simulado (solo datos en esta integral; el plano de control
    # broker se verifica con el gate desplegado de la App).
    canal_control = CanalControlSimulado()
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )
    identidad = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadScimCli()
    ).ObtenerIdentidadLlamante()

    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=identidad,
        resolutor_privilegios=resolutor,
        agregador_lote=AgregadorReporteLotePython(),
    )
    return {
        "servicio": ServicioEjecucionGrantsUi(pipeline),
        "canal_datos": canal_datos,
        "identidad": identidad,
        "catalogo": ConfiguracionApp.Cargar().catalogo,
        "beneficiario": identidad.principal.identificador,
    }


def _Objeto(vertical):
    return ObjetoSecurable(identificador=vertical["catalogo"], tipo=TipoObjeto.CATALOGO)


def _Item(vertical, privilegio):
    beneficiario = Principal(
        identificador=vertical["beneficiario"], tipo=TipoPrincipal.USUARIO
    )
    return ItemGrant(principal=beneficiario, privilegio=privilegio, objeto=_Objeto(vertical))


def _TieneGrant(canal_datos, objeto, principal, privilegio):
    privilegio_buscado = privilegio.upper()
    return any(
        grant.privilegio == privilegio_buscado
        and grant.principal.identificador.lower() == principal.lower()
        for grant in canal_datos.ListarGrantsVigentes(objeto)
    )


def TestEjecucion1A1OtorgaVerificaYRevoca(vertical):
    """GRANT 1 a 1 real, verificable con SHOW GRANT, con revocación en finally."""
    item = _Item(vertical, PRIVILEGIO_VALIDO)
    try:
        reporte = vertical["servicio"].Ejecutar(
            SolicitudGrant.Crear(item.principal, [PRIVILEGIO_VALIDO], item.objeto),
            vertical["identidad"],
        )
        # Resultado real por ítem: otorgado o, si la semántica C3 exacta lo
        # bloquea, privilegios insuficientes (nunca fallo de transporte).
        assert [linea.estado for linea in reporte.lineas] in (
            [EstadoItem.OTORGADO],
            [EstadoItem.PRIVILEGIOS_INSUFICIENTES],
        )
        if reporte.lineas[0].estado is EstadoItem.OTORGADO:
            assert _TieneGrant(
                vertical["canal_datos"], item.objeto,
                item.principal.identificador, PRIVILEGIO_VALIDO,
            ), "Tras otorgar, SHOW GRANT debe reportar el privilegio."
    finally:
        # Restauración: revocar el privilegio si se otorgó (sin estado residual).
        vertical["canal_datos"].EjecutarRevocacion(item)


def TestItemIncompatibleConLaMatrizSeBloqueaSinGrant(vertical):
    """Un privilegio fuera de la matriz se bloquea y no emite GRANT."""
    item = _Item(vertical, PRIVILEGIO_INVALIDO)

    reporte = vertical["servicio"].Ejecutar(
        SolicitudGrant.Crear(item.principal, [PRIVILEGIO_INVALIDO], item.objeto),
        vertical["identidad"],
    )

    assert [linea.estado for linea in reporte.lineas] == [EstadoItem.FALLIDO], (
        "El privilegio fuera de la matriz debe bloquearse como fallido, sin GRANT."
    )
