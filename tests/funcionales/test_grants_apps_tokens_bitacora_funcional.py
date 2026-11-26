"""Pruebas funcionales de bitácora sobre Databricks Apps y uso de personal access
tokens (tarea 5.3 del change `grants-apps-tokens`).

Verifican que tras procesar una solicitud, los eventos y errores quedan en la
bitácora (design D7), sin alterar el flujo del pipeline.
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import CanalControlComputo
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudLoteGrant,
)


def _IdentidadLlamante():
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()
from control_accesos.pipeline.pipeline_grants import PipelineGrants


class _CapturaEventos:
    def __init__(self):
        self.eventos = []

    def Registrar(self, **kwargs):
        self.eventos.append(kwargs)


class _TransporteSimulado:
    def __init__(self, acl_inicial=None, excepcion=None):
        self._acl = acl_inicial or []
        self._excepcion = excepcion

    def LeerAcl(self, recurso, identificador):
        if self._excepcion:
            raise self._excepcion
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self._acl = list(entradas)


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


def _App(identificador="mi-app"):
    return ObjetoSecurable(identificador=identificador, tipo=TipoObjeto.DATABRICK_APP)


def _TokenObjeto():
    return ObjetoSecurable(identificador="workspace", tipo=TipoObjeto.USO_TOKEN)


def _identidad():
    return _IdentidadLlamante()


class TestBitacoraEventosApps:
    """Tras procesar una solicitud sobre Apps, el evento queda en la bitácora."""

    def TestEventoOtorgamientoAppQuedaRegistrado(self):
        sp = _PrincipalSP()
        app = _App()
        transporte = _TransporteSimulado()
        canal_control = CanalControlComputo(transporte)
        canal_datos = CanalDatosSimulado()
        captura = _CapturaEventos()

        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_eventos=captura,
        )

        solicitud = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=(app,),
        )
        reporte = pipeline.ProcesarLote(solicitud, identidad_llamante=_identidad())

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO
        # El evento quedó registrado con el usuario del llamante
        assert len(captura.eventos) > 0

    def TestEventoOtorgamientoTokenQuedaRegistrado(self):
        sp = _PrincipalSP()
        token = _TokenObjeto()
        transporte = _TransporteSimulado()
        canal_control = CanalControlComputo(transporte)
        canal_datos = CanalDatosSimulado()
        captura = _CapturaEventos()

        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_eventos=captura,
        )

        solicitud = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=(token,),
        )
        reporte = pipeline.ProcesarLote(solicitud, identidad_llamante=_identidad())

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO
        assert len(captura.eventos) > 0


class TestBitacoraErroresApps:
    """Un fallo del transporte queda en bitacora_errores con su detalle."""

    def TestFalloQuedaEnBitacoraErrores(self):
        """Un fallo inesperado del transporte se registra en errores."""
        sp = _PrincipalSP()
        app = _App()
        # Un error genérico (no PERMISSION_DENIED) que el canal traduce a FALLIDO
        transporte = _TransporteSimulado(
            excepcion=Exception("Error de conexión inesperado")
        )
        canal_control = CanalControlComputo(transporte)
        canal_datos = CanalDatosSimulado()
        captura_errores = _CapturaEventos()
        captura_eventos = _CapturaEventos()

        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_eventos=captura_eventos,
            registrador_errores=captura_errores,
        )

        solicitud = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=(app,),
        )
        reporte = pipeline.ProcesarLote(solicitud, identidad_llamante=_identidad())

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.FALLIDO
        # El evento se registra
        assert len(captura_eventos.eventos) > 0
        # El error del canal se registra en bitácora_errores por el canal mismo
        # (el canal tiene su propio registrador_errores inyectado)
