"""Pruebas funcionales del flujo de punta a punta para Databricks Apps y uso de
personal access tokens (tarea 5.1 del change `grants-apps-tokens`).

Ejercitan `PipelineGrants` con `CanalControlComputo` (extendido con los dos
tipos nuevos) sobre un transporte simulado que imita respuestas y errores
reales: ACLs, permiso denegado, App inexistente, principal inexistente, Token
Permissions API no habilitada.
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


def _App(identificador="mi-app"):
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.DATABRICK_APP
    )


def _TokenObjeto():
    return ObjetoSecurable(
        identificador="workspace", tipo=TipoObjeto.USO_TOKEN
    )


class _TransporteSimulado:
    """Transporte que responde con ACL configurada o lanza excepciones."""

    def __init__(self, acl_inicial=None, excepcion=None):
        self._acl = acl_inicial or []
        self._excepcion = excepcion
        self.llamadas_leer = []
        self.llamadas_escribir = []

    def LeerAcl(self, recurso, identificador):
        self.llamadas_leer.append((recurso, identificador))
        if self._excepcion:
            raise self._excepcion
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self.llamadas_escribir.append((recurso, identificador, list(entradas)))
        self._acl = list(entradas)


class TestFlujoFuncionalApps:
    """Flujo de punta a punta con `PipelineGrants` sobre Databricks Apps."""

    def _pipeline(self, transporte):
        canal_control = CanalControlComputo(transporte)
        canal_datos = CanalDatosSimulado()
        return PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )

    def TestSolicitud1a1ValidaQuedaOtorgadaYVerificada(self):
        sp = _PrincipalSP()
        app = _App()
        transporte = _TransporteSimulado()
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_USE",),
            objeto=app,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO
        assert len(transporte.llamadas_escribir) == 1

    def TestPrivilegioIncompatibleBloqueaEnPreFlight(self):
        """CAN_RESTART sobre una App → pre-flight bloquea sin llamada al transporte."""
        sp = _PrincipalSP()
        app = _App()
        transporte = _TransporteSimulado()
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_RESTART",),
            objeto=app,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.FALLIDO
        assert len(transporte.llamadas_leer) == 0
        assert len(transporte.llamadas_escribir) == 0

    def TestPermisoDenegadoTraduceAPrivilegiosInsuficientes(self):
        """Permiso denegado → PRIVILEGIOS_INSUFICIENTES (design D6)."""
        sp = _PrincipalSP()
        app = _App()
        transporte = _TransporteSimulado(
            excepcion=Exception("PERMISSION_DENIED: Access denied")
        )
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_USE",),
            objeto=app,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES

    def TestAppInexistenteClasificaComoFallido(self):
        sp = _PrincipalSP()
        app = _App("app-inexistente")
        transporte = _TransporteSimulado(
            excepcion=Exception("RESOURCE_DOES_NOT_EXIST: App 'app-inexistente' does not exist")
        )
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_USE",),
            objeto=app,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.FALLIDO

    def TestTokenPermissionsApiNoHabilitada(self):
        sp = _PrincipalSP()
        token_obj = _TokenObjeto()
        transporte = _TransporteSimulado(
            excepcion=Exception("FEATURE_NOT_ENABLED: Token Permissions API is not enabled")
        )
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_USE",),
            objeto=token_obj,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.FALLIDO
        assert "no habilitada" in reporte.lineas[0].detalle.lower()

    def TestSolicitud1a1TokenOtorgadaYVerificada(self):
        sp = _PrincipalSP()
        token_obj = _TokenObjeto()
        transporte = _TransporteSimulado()
        pipeline = self._pipeline(transporte)

        solicitud = SolicitudGrant(
            principal=sp,
            privilegios=("CAN_USE",),
            objeto=token_obj,
        )
        reporte = pipeline.Procesar(solicitud)

        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO
        recurso, identificador, _ = transporte.llamadas_escribir[0]
        assert recurso == "authorization/tokens"
        assert identificador == ""
