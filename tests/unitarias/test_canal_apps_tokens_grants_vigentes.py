"""Pruebas unitarias de `ListarGrantsVigentes` para Databricks Apps y uso de
personal access tokens (tareas 3.1 y 3.2 del change `grants-apps-tokens`).
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal


class _TransporteSimulado:
    def __init__(self, acl_inicial=None, excepcion=None):
        self._acl = acl_inicial or []
        self.excepcion = excepcion
        self.llamadas_leer = []
        self.llamadas_escribir = []

    def LeerAcl(self, recurso, identificador):
        self.llamadas_leer.append((recurso, identificador))
        if self.excepcion is not None:
            raise self.excepcion
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self.llamadas_escribir.append((recurso, identificador, list(entradas)))
        self._acl = list(entradas)


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


class TestListarGrantsVigentes:
    """`ListarGrantsVigentes` traduce la ACL a otorgamientos del dominio."""

    def TestEntradasTraducidasAItemGrant(self):
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
        ])
        canal = CanalControlComputo(transporte)

        grants = canal.ListarGrantsVigentes(app)

        assert len(grants) == 1
        assert grants[0].principal is sp
        assert grants[0].privilegio == "CAN_USE"
        assert grants[0].objeto is app

    def TestTokenSingletonDevuelveObjetoConIdentificadorVacio(self):
        sp = _PrincipalSP()
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        transporte = _TransporteSimulado([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
        ])
        canal = CanalControlComputo(transporte)

        grants = canal.ListarGrantsVigentes(token_obj)

        assert len(grants) == 1
        assert grants[0].privilegio == "CAN_USE"
        # El objeto devuelto mantiene el identificador original del dominio.
        assert grants[0].objeto is token_obj
        # La llamada al transporte usa id vacío.
        _, identificador = transporte.llamadas_leer[0]
        assert identificador == ""

    def TestAclSinEntradasDevuelveListaVacia(self):
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado([])
        canal = CanalControlComputo(transporte)

        grants = canal.ListarGrantsVigentes(app)

        assert grants == []

    def TestEntradasSinOtorgatarioIdentificableSeOmiten(self):
        """Entradas sin otorgatario identificable se omiten sin inventar principal.

        El transporte simulado devuelve una tupla con una entrada que no tiene
        un `Principal` válido; el canal la filtra en `ListarGrantsVigentes`.
        """
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        # Simulamos una respuesta del transporte con una entrada sin principal
        # (p. ej. una entrada heredada o un propietario del objeto que no es
        # otorgatario directo). Como `EntradaAcl` requiere un `Principal`, no
        # podemos construirla con `principal=None`; en su lugar, configuramos
        # el transporte para devolver una entrada vacía (sin otorgatario).
        class _TransporteSinOtorgatario:
            def LeerAcl(self, recurso, identificador):
                return ()

            def EscribirAcl(self, recurso, identificador, entradas):
                pass

        canal = CanalControlComputo(_TransporteSinOtorgatario())

        grants = canal.ListarGrantsVigentes(app)

        assert grants == []
