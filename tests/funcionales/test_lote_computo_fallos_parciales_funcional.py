"""Pruebas funcionales de lotes con fallos parciales sobre objetos de cómputo
(capability `compute-grants`, spec - "Cardinalidades y resultados parciales").

Usan `PipelineGrants` con `CanalControlComputo` sobre un transporte que imita la
Permissions API: lotes 1 a N y N a 1 con resultados parciales por ítem, un fallo
puntual que no aborta el resto, y rechazo explícito de la cardinalidad N a M sin
llamada alguna al transporte (design D1: el pipeline y la normalización de C5 se
reutilizan sin cambios).
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.pipeline.pipeline_grants import PipelineGrants


class TransportePermisosControlFalso:
    """Transporte que imita la Permissions API: ACL en memoria y errores."""

    def __init__(self):
        self._acl = {}
        self._inexistentes = set()
        self.escrituras = []

    def RegistrarObjeto(self, objeto, entradas=()):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._acl[(recurso, objeto.identificador)] = list(entradas)

    def MarcarInexistente(self, objeto):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._inexistentes.add((recurso, objeto.identificador))

    def LeerAcl(self, recurso, identificador):
        if (recurso, identificador) in self._inexistentes:
            from control_accesos.canales.errores import ErrorCanal

            raise ErrorCanal(
                f"[RESOURCE_DOES_NOT_EXIST] El objeto '{identificador}' no existe."
            )
        return tuple(self._acl.get((recurso, identificador), []))

    def EscribirAcl(self, recurso, identificador, entradas):
        self.escrituras.append((recurso, identificador, list(entradas)))
        self._acl[(recurso, identificador)] = list(entradas)


def CrearPrincipal(email):
    return Principal(identificador=email, tipo=TipoPrincipal.USUARIO)


def CrearObjeto(tipo, identificador):
    return ObjetoSecurable(identificador=identificador, tipo=tipo)


class TestLoteFallosParcialesComputo:
    def TestLote1aNConObjetoInexistenteTerminaParcial(self):
        """Un lote 1 a N con un objeto inexistente termina parcial (otorgado + fallido)."""
        principal = CrearPrincipal("beneficiario@example.com")
        objeto_ok1 = CrearObjeto(TipoObjeto.COMPUTO_CLASICO, "cluster-ok-1")
        objeto_ok2 = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "warehouse-ok")
        objeto_inexistente = CrearObjeto(TipoObjeto.COMPUTO_CLASICO, "cluster-inexistente")

        transporte = TransportePermisosControlFalso()
        transporte.RegistrarObjeto(objeto_ok1)
        transporte.RegistrarObjeto(objeto_ok2)
        transporte.RegistrarObjeto(objeto_inexistente)
        transporte.MarcarInexistente(objeto_inexistente)

        canal_control = CanalControlComputo(transporte)
        pipeline = PipelineGrants(
            canal_datos=CanalDatosSimulado(), canal_control=canal_control
        )

        reporte = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["CAN_MANAGE"],
            objetos=[objeto_ok1, objeto_inexistente, objeto_ok2],
        )

        assert len(reporte.lineas) == 3
        otorgados = [l for l in reporte.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in reporte.lineas if l.estado is EstadoItem.FALLIDO]
        assert len(otorgados) == 2
        assert len(fallidos) == 1
        assert fallidos[0].item.objeto.identificador == "cluster-inexistente"

    def TestLoteN_A_1ConVariosPrincipals(self):
        """Un lote N a 1 otorga a varios principals sobre el mismo objeto."""
        principal_1 = CrearPrincipal("usuario1@example.com")
        principal_2 = Principal(identificador="Desarrollador", tipo=TipoPrincipal.GRUPO)
        objeto = CrearObjeto(TipoObjeto.SQL_WAREHOUSE, "warehouse-1")

        transporte = TransportePermisosControlFalso()
        transporte.RegistrarObjeto(objeto)
        canal_control = CanalControlComputo(transporte)
        pipeline = PipelineGrants(
            canal_datos=CanalDatosSimulado(), canal_control=canal_control
        )

        reporte = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal_1, principal_2],
            privilegios=["CAN_MANAGE"],
            objetos=[objeto],
        )

        assert len(reporte.lineas) == 2
        assert all(l.estado is EstadoItem.OTORGADO for l in reporte.lineas)
        assert {l.item.principal.identificador for l in reporte.lineas} == {
            "usuario1@example.com",
            "Desarrollador",
        }

    def TestCardinalidadN_M_RechazadaSinLlamada(self):
        """La cardinalidad N a M se rechaza sin ejecutar instrucción alguna."""
        transporte = TransportePermisosControlFalso()
        canal_control = CanalControlComputo(transporte)
        pipeline = PipelineGrants(
            canal_datos=CanalDatosSimulado(), canal_control=canal_control
        )

        with pytest.raises(ErrorDominio):
            pipeline.ProcesarLoteDesdeEntradas(
                principales=[
                    CrearPrincipal("u1@example.com"),
                    CrearPrincipal("u2@example.com"),
                ],
                privilegios=["CAN_MANAGE"],
                objetos=[
                    CrearObjeto(TipoObjeto.COMPUTO_CLASICO, "cluster-1"),
                    CrearObjeto(TipoObjeto.COMPUTO_CLASICO, "cluster-2"),
                ],
            )

        assert transporte.escrituras == []
