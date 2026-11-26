"""Pruebas de aceptación del change `grants-apps-tokens` (tareas 7.1 y 7.2).

Validan los criterios de aceptación del change: el canal resuelve los cinco
tipos del plano de control, el flujo funcional completo opera sin intervención
manual, la clasificación de errores es específica por caso y la bitácora
registra los fallos sin propagarlos en cascada.
"""

import pytest

from control_accesos.canales.errores import ErrorCanal, ErrorPrivilegiosInsuficientes
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
    RECURSO_PERMISOS_POR_TIPO_OBJETO,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


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


def _pipeline(transporte=None):
    canal_control = CanalControlComputo(transporte or _TransporteSimulado())
    canal_datos = CanalDatosSimulado()
    return PipelineGrants(
        canal_datos=canal_datos, canal_control=canal_control
    )


class TestCriteriosAceptacionAppsTokens:
    """Criterios de aceptación del change grants-apps-tokens."""

    def TestCriterioCincoTiposPlanoDeControl(self):
        """El canal resuelve los cinco tipos del plano de control."""
        tipos = set(RECURSO_PERMISOS_POR_TIPO_OBJETO)
        assert len(tipos) == 5
        assert TipoObjeto.COMPUTO_CLASICO in tipos
        assert TipoObjeto.COMPUTO_SERVERLESS in tipos
        assert TipoObjeto.SQL_WAREHOUSE in tipos
        assert TipoObjeto.DATABRICK_APP in tipos
        assert TipoObjeto.USO_TOKEN in tipos

    def TestCriterioRechazoPlanoDeDatos(self):
        """Tipos del plano de datos se rechazan con ErrorCanal."""
        for tipo in [TipoObjeto.TABLA_DELTA, TipoObjeto.ESQUEMA, TipoObjeto.VOLUMEN]:
            with pytest.raises(ErrorCanal):
                CanalControlComputo.RecursoDeTipo(tipo)

    def TestCriterioRutaAppConIdentificador(self):
        """Databricks Apps construye ruta con id del objeto."""
        app = ObjetoSecurable(
            identificador="mi-app-123", tipo=TipoObjeto.DATABRICK_APP
        )
        ruta = CanalControlComputo.RutaDePermisos(app)
        assert ruta == "/api/2.0/permissions/apps/mi-app-123"

    def TestCriterioRutaTokenSinIdentificador(self):
        """Token Permissions API no lleva id (singleton de workspace)."""
        token = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        ruta = CanalControlComputo.RutaDePermisos(token)
        assert ruta == "/api/2.0/permissions/authorization/tokens"

    def TestCriterioFlujoAppsOtorGadoYVerificado(self):
        """Solicitud de CAN_USE sobre App otorgada y verificada."""
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado()
        reporte = _pipeline(transporte).Procesar(
            SolicitudGrant(principal=sp, privilegios=("CAN_USE",), objeto=app)
        )
        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO

    def TestCriterioFlujoTokenOtorGadoYVerificado(self):
        """Solicitud de CAN_USE sobre uso de tokens otorgada y verificada."""
        sp = _PrincipalSP()
        token = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        transporte = _TransporteSimulado()
        reporte = _pipeline(transporte).Procesar(
            SolicitudGrant(principal=sp, privilegios=("CAN_USE",), objeto=token)
        )
        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.OTORGADO

    def TestCriterioPermisoDenegadoPrivilegiosInsuficientes(self):
        """Permiso denegado → PRIVILEGIOS_INSUFICIENTES."""
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado(
            excepcion=Exception("PERMISSION_DENIED: Access denied")
        )
        reporte = _pipeline(transporte).Procesar(
            SolicitudGrant(principal=sp, privilegios=("CAN_USE",), objeto=app)
        )
        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES

    def TestCriterioFeatureNoHabilitadaFallido(self):
        """Token Permissions API no habilitada → FALLIDO con mensaje específico."""
        sp = _PrincipalSP()
        token = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        transporte = _TransporteSimulado(
            excepcion=Exception("FEATURE_NOT_ENABLED: Token Permissions API is not enabled")
        )
        reporte = _pipeline(transporte).Procesar(
            SolicitudGrant(principal=sp, privilegios=("CAN_USE",), objeto=token)
        )
        assert len(reporte.lineas) == 1
        assert reporte.lineas[0].estado is EstadoItem.FALLIDO
        assert "Token Permissions API" in reporte.lineas[0].detalle
        assert "no habilitada" in reporte.lineas[0].detalle.lower()

    def TestCriterioNoRegresionComputo(self):
        """Los tres tipos de cómputo de C7 siguen operando."""
        sp = _PrincipalSP()
        transporte = _TransporteSimulado()
        canal_control = CanalControlComputo(transporte)
        canal_datos = CanalDatosSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )

        for tipo_id, privilegio in [
            ("cluster-123", "CAN_ATTACH_TO"),
            ("Default", "CAN_USE"),
            ("warehouse-456", "CAN_USE"),
        ]:
            tipo = {
                "CAN_ATTACH_TO": TipoObjeto.COMPUTO_CLASICO,
                "CAN_USE": TipoObjeto.COMPUTO_SERVERLESS if tipo_id == "Default" else TipoObjeto.SQL_WAREHOUSE,
            }[privilegio]
            obj = ObjetoSecurable(identificador=tipo_id, tipo=tipo)
            reporte = pipeline.Procesar(
                SolicitudGrant(principal=sp, privilegios=(privilegio,), objeto=obj)
            )
            assert reporte.lineas[0].estado is EstadoItem.OTORGADO, f"Fallo para {tipo.value}"
