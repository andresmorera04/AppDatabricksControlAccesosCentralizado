"""Pruebas unitarias de la verificación post-grant para Databricks Apps y uso de
personal access tokens (tarea 3.3 del change `grants-apps-tokens`).
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.pipeline.verificador import Verificador


class _TransporteSimulado:
    """Transporte de permisos que responde con la ACL configurada."""

    def __init__(self, acl_inicial=None):
        self._acl = acl_inicial or []

    def LeerAcl(self, recurso, identificador):
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self._acl = list(entradas)


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


class TestVerificacionPostGrant:
    """El `Verificador` usa `ListarGrantsVigentes` para confirmar permisos."""

    def _canal_de_datos(self):
        return CanalDatosSimulado()

    def _canal_de_control(self, acl_inicial=None):
        return CanalControlComputo(
            _TransporteSimulado(acl_inicial)
        )

    def TestPermisoConfirmadoPorVerificacion(self):
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        canal_control = self._canal_de_control([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
        ])
        verificador = Verificador(
            canal_datos=self._canal_de_datos(),
            canal_control=canal_control,
        )

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        # Simulamos un resultado ya otorgado por la fase de ejecución
        from control_accesos.dominio.modelos import ResultadoItem
        resultado_ejecucion = ResultadoItem.Otorgado(item)
        resultados = verificador.Verificar([resultado_ejecucion])

        assert len(resultados) == 1
        assert resultados[0].estado.value == "otorgado"

    def TestPermisoNoConfirmadoPasaAFallido(self):
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        # ACL sin el permiso otorgado
        canal_control = self._canal_de_control([])
        verificador = Verificador(
            canal_datos=self._canal_de_datos(),
            canal_control=canal_control,
        )

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        from control_accesos.dominio.modelos import ResultadoItem
        resultado_ejecucion = ResultadoItem.Otorgado(item)
        resultados = verificador.Verificar([resultado_ejecucion])

        assert len(resultados) == 1
        assert resultados[0].estado.value == "fallido"

    def TestVerificacionTokenSingleton(self):
        sp = _PrincipalSP()
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        canal_control = self._canal_de_control([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
        ])
        verificador = Verificador(
            canal_datos=self._canal_de_datos(),
            canal_control=canal_control,
        )

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=token_obj
        )
        from control_accesos.dominio.modelos import ResultadoItem
        resultado_ejecucion = ResultadoItem.Otorgado(item)
        resultados = verificador.Verificar([resultado_ejecucion])

        assert len(resultados) == 1
        assert resultados[0].estado.value == "otorgado"
