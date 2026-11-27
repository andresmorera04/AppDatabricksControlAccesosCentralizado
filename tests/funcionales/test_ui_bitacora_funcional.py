"""Prueba funcional de la bitácora con escritor REST de la App (design.md D10).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 5.2.

Composición real sobre canales simulados (sin red) y una sesión SQL falsa que
registra las sentencias INSERT: el pipeline usa `BitacoraEventosRemota` y
`BitacoraErroresRemota` (puerto `.sql`) con la identidad de la App.

Contrato que fija esta prueba (D10):

- los eventos conservan `usuario` OBO del llamante y la marca de ejecución de la
  App en el detalle cuando el pipeline opera en modo broker;
- los errores conservan `usuario`, `modulo` y el detalle STRUCT (NAMED_STRUCT);
- un fallo de bitácora NO oculta el reporte ya obtenido (degradación);
- la inicialización persiste idempotente (CREATE ... IF NOT EXISTS re-usable).
"""

import pytest

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.bitacora.escritores_remotos import (
    BitacoraErroresRemota,
    BitacoraEventosRemota,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.reporte_lote import AgregadorReporteLotePython
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.servicio_ejecucion import ServicioEjecucionGrantsUi

CONFIGURACION = ConfiguracionApp.Cargar()
LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)


class SesionSqlFalsa:
    """Sesión SQL falsa que registra las sentencias y, opcionalmente, falla."""

    def __init__(self, fallar=False):
        self.sentencias = []
        self._fallar = fallar

    def sql(self, sentencia):
        self.sentencias.append(sentencia)
        if self._fallar:
            raise RuntimeError("fallo de la Statement Execution API")
        return []


def _Identidad():
    return IdentidadLlamante(principal=LLAMANTE)


def _Construir(identidad_ejecucion=None, sesion=None):
    """Compone pipeline con escritores remotos sobre canales simulados.

    Returns:
        tuple: (SesionSqlFalsa, PipelineGrants).
    """
    sesion = sesion or SesionSqlFalsa()
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        VENTAS, [ItemGrant(principal=LLAMANTE, privilegio="SELECT", objeto=VENTAS)]
    )
    canal_control = CanalControlSimulado()
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=_Identidad(),
        resolutor_privilegios=resolutor,
        agregador_lote=AgregadorReporteLotePython(),
        registrador_eventos=BitacoraEventosRemota(sesion=sesion, configuracion=CONFIGURACION),
        registrador_errores=BitacoraErroresRemota(sesion=sesion, configuracion=CONFIGURACION),
        identidad_ejecucion=identidad_ejecucion,
    )
    return sesion, pipeline


def TestEventosConservanUsuarioOboYEjecucionBroker():
    """Los eventos registran usuario OBO y la marca de ejecución de la App."""
    sesion, pipeline = _Construir(identidad_ejecucion="app")
    solicitud = SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS)

    ServicioEjecucionGrantsUi(pipeline).Ejecutar(solicitud, _Identidad())

    inserts_eventos = [
        s for s in sesion.sentencias
        if "INSERT INTO" in s and "bitacora_eventos" in s
    ]
    assert inserts_eventos, "Debe registrarse al menos un evento en la bitácora."
    sentencia = inserts_eventos[-1]
    assert "caller@example.com" in sentencia, (
        "El campo usuario debe conservar la identidad OBO del llamante."
    )
    assert "ejecución: identidad de la App" in sentencia, (
        "El detalle del evento debe marcar que la ejecución usó la identidad de la App."
    )
    # SQL generado en mayúsculas y sin secretos: sentencia de columna-valores.
    assert sentencia.lstrip().upper().startswith("INSERT INTO")


def TestErroresConservanModuloUsuarioYStruct():
    """Los errores registran modulo, usuario y detalle STRUCT (NAMED_STRUCT)."""
    sesion = SesionSqlFalsa()
    bitacora = BitacoraErroresRemota(sesion=sesion, configuracion=CONFIGURACION)

    try:
        raise RuntimeError("fallo controlado de ejemplo")
    except RuntimeError as excepcion:
        bitacora.Registrar(excepcion, modulo="ui.controlador", usuario="caller@example.com")

    sentencia = sesion.sentencias[-1]
    assert "bitacora_errores" in sentencia
    assert "ui.controlador" in sentencia
    assert "caller@example.com" in sentencia
    assert "NAMED_STRUCT(" in sentencia
    assert "tipo_excepcion" in sentencia and "RuntimeError" in sentencia


def TestFalloDeBitacoraNoOcultaElReporte():
    """Un fallo al escribir la bitácora no impide devolver el reporte."""
    sesion_falla = SesionSqlFalsa(fallar=True)
    _, pipeline = _Construir(identidad_ejecucion="app", sesion=sesion_falla)
    solicitud = SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS)

    reporte = ServicioEjecucionGrantsUi(pipeline).Ejecutar(solicitud, _Identidad())

    assert reporte is not None
    assert reporte.lineas, "El reporte con el resultado se devuelve igual."


def TestInicializacionPersistenciaEsIdempotente():
    """El DDL es re-ejecutable (CREATE ... IF NOT EXISTS) sin fallar."""
    sesion = SesionSqlFalsa()
    inicializador = InicializadorPersistencia(sesion=sesion, configuracion=CONFIGURACION)

    inicializador.Inicializar()
    primera = list(sesion.sentencias)
    inicializador.Inicializar()
    segunda = list(sesion.sentencias)

    assert len(segunda) == 2 * len(primera)
    assert all("IF NOT EXISTS" in s for s in primera)
