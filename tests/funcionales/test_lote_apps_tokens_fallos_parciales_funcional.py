"""Pruebas funcionales de lote con resultados parciales para Databricks Apps y
uso de personal access tokens (tarea 5.2 del change `grants-apps-tokens`).

Ejercitan `ProcesarLote` con `PipelineGrants` y `CanalControlComputo` sobre un
transporte simulado: lote 1 a N sobre varias Apps con resultados parciales,
lote N a 1 sobre tokens (varios principals sobre el singleton) y rechazo de N a M.
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import CanalControlComputo
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants


def _PrincipalSP(nombre):
    return Principal(tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador=nombre)


def _App(identificador):
    return ObjetoSecurable(identificador=identificador, tipo=TipoObjeto.DATABRICK_APP)


def _TokenObjeto():
    return ObjetoSecurable(identificador="workspace", tipo=TipoObjeto.USO_TOKEN)


class _TransporteSimulado:
    """Transporte que responde con ACL configurada o lanza excepciones."""

    def __init__(self, acl_inicial=None, excepcion_por_recurso=None):
        self._acl = acl_inicial or []
        self._excepcion_por_recurso = excepcion_por_recurso or {}
        self.llamadas_leer = []
        self.llamadas_escribir = []

    def LeerAcl(self, recurso, identificador):
        self.llamadas_leer.append((recurso, identificador))
        clave = (recurso, identificador)
        if clave in self._excepcion_por_recurso:
            raise self._excepcion_por_recurso[clave]
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self.llamadas_escribir.append((recurso, identificador, list(entradas)))
        self._acl = list(entradas)


def _pipeline(transporte):
    canal_control = CanalControlComputo(transporte)
    canal_datos = CanalDatosSimulado()
    return PipelineGrants(canal_datos=canal_datos, canal_control=canal_control)


class TestLoteAppsResultadosParciales:
    """Lote 1 a N sobre varias Databricks Apps con resultados parciales."""

    def TestLote1aNAplicanSobreTodasLasApps(self):
        """Lote 1 a N: un principal recibe CAN_USE sobre varias Apps."""
        sp = _PrincipalSP("sp-prueba")
        apps = [_App("app-1"), _App("app-2"), _App("app-3")]
        transporte = _TransporteSimulado()
        pipeline = _pipeline(transporte)

        solicitud_lote = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=tuple(apps),
        )
        reporte = pipeline.ProcesarLote(solicitud_lote)

        assert len(reporte.lineas) == 3
        for linea in reporte.lineas:
            assert linea.estado is EstadoItem.OTORGADO
        assert len(transporte.llamadas_escribir) == 3

    def TestLote1aNFalloParcialEnUnaApp(self):
        """Una App falla (permiso denegado), las demás se otorgan."""
        sp = _PrincipalSP("sp-prueba")
        apps = [_App("app-ok"), _App("app-denegada"), _App("app-ok-2")]
        transporte = _TransporteSimulado(
            excepcion_por_recurso={
                ("apps", "app-denegada"): Exception("PERMISSION_DENIED"),
            }
        )
        pipeline = _pipeline(transporte)

        solicitud_lote = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=tuple(apps),
        )
        reporte = pipeline.ProcesarLote(solicitud_lote)

        assert len(reporte.lineas) == 3
        estados = {linea.item.objeto.identificador: linea.estado for linea in reporte.lineas}
        assert estados["app-ok"] is EstadoItem.OTORGADO
        assert estados["app-ok-2"] is EstadoItem.OTORGADO
        # La app con PERMISSION_DENIED → PRIVILEGIOS_INSUFICIENTES
        assert estados["app-denegada"] is EstadoItem.PRIVILEGIOS_INSUFICIENTES

    def TestLote1aNAppInexistenteClasificaComoFallido(self):
        """App inexistente → FALLIDO con mensaje que identifica el objeto."""
        sp = _PrincipalSP("sp-prueba")
        apps = [_App("app-ok"), _App("app-inexistente")]
        transporte = _TransporteSimulado(
            excepcion_por_recurso={
                ("apps", "app-inexistente"): Exception(
                    "RESOURCE_DOES_NOT_EXIST: App 'app-inexistente' does not exist"
                ),
            }
        )
        pipeline = _pipeline(transporte)

        solicitud_lote = SolicitudLoteGrant(
            principales=(sp,),
            privilegios=("CAN_USE",),
            objetos=tuple(apps),
        )
        reporte = pipeline.ProcesarLote(solicitud_lote)

        assert len(reporte.lineas) == 2
        estados = {linea.item.objeto.identificador: linea.estado for linea in reporte.lineas}
        assert estados["app-ok"] is EstadoItem.OTORGADO
        assert estados["app-inexistente"] is EstadoItem.FALLIDO


class TestLoteTokensN_a_1:
    """Lote N a 1: varios principals reciben CAN_USE sobre el singleton de tokens."""

    def TestLoteN_a_1TokenSingleton(self):
        """Varios principals otorgan CAN_USE sobre USO_TOKEN (singleton)."""
        sp1 = _PrincipalSP("sp-uno")
        sp2 = _PrincipalSP("sp-dos")
        token = _TokenObjeto()
        transporte = _TransporteSimulado()
        pipeline = _pipeline(transporte)

        solicitud_lote = SolicitudLoteGrant(
            principales=(sp1, sp2),
            privilegios=("CAN_USE",),
            objetos=(token,),
        )
        reporte = pipeline.ProcesarLote(solicitud_lote)

        assert len(reporte.lineas) == 2
        for linea in reporte.lineas:
            assert linea.estado is EstadoItem.OTORGADO
        recurso, identificador, _ = transporte.llamadas_escribir[-1]
        assert recurso == "authorization/tokens"
        assert identificador == ""


class TestRechazoNM:
    """Rechazo explícito de solicitudes N a M (múltiples principals, múltiples objetos)."""

    def TestSolicitudNMRechazadaPorDominio(self):
        """Múltiples principals sobre múltiples objetos → ErrorDominio (N a M)."""
        sp1 = _PrincipalSP("sp-uno")
        sp2 = _PrincipalSP("sp-dos")
        apps = (_App("app-1"), _App("app-2"))

        # N a M se rechaza en el constructor de SolicitudLoteGrant
        from control_accesos.dominio.errores import ErrorDominio
        with pytest.raises(ErrorDominio) as exc:
            SolicitudLoteGrant(
                principales=(sp1, sp2),
                privilegios=("CAN_USE",),
                objetos=apps,
            )
        assert "N a M" in str(exc.value) or "fuera de alcance" in str(exc.value).lower()
