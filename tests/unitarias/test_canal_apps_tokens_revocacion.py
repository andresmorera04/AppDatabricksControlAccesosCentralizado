"""Pruebas unitarias de revocación sobre Databricks Apps y uso de personal
access tokens (tareas 2.3 y 2.4 del change `grants-apps-tokens`).

Ejercitan `EjecutarRevocacion` sobre un transporte simulado, verificando la
regla aditiva por otorgatario (no altera entradas ajenas) y la revocación
de permisos que no estaban vigentes (no altera la ACL).
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)


class _TransporteSimulado:
    """Transporte que registra las llamadas a LeerAcl y EscribirAcl."""

    def __init__(self, acl_inicial=None):
        self._acl = acl_inicial or []
        self.llamadas_leer = []
        self.llamadas_escribir = []

    def LeerAcl(self, recurso, identificador):
        self.llamadas_leer.append((recurso, identificador))
        return list(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self.llamadas_escribir.append((recurso, identificador, list(entradas)))
        self._acl = list(entradas)


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


def _GrupoDesarrollo():
    return Principal(tipo=TipoPrincipal.GRUPO, identificador="Desarrollador")


class TestRevocacionApp:
    """Revocación sobre Databricks Apps con escritura aditiva."""

    def TestRevocacionPermisoVigente(self):
        """Quitar el permiso al principal conservando las demás entradas."""
        sp = _PrincipalSP()
        admin = _GrupoDesarrollo()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
            EntradaAcl(principal=admin, nivel="CAN_MANAGE"),
        ])
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        canal.EjecutarRevocacion(item)

        assert len(transporte.llamadas_escribir) == 1
        _, _, entradas = transporte.llamadas_escribir[0]
        assert len(entradas) == 1
        assert entradas[0].principal is admin
        assert entradas[0].nivel == "CAN_MANAGE"

    def TestRevocacionPermisoNoVigente(self):
        """Revocar un permiso que no estaba vigente no altera la ACL."""
        admin = _GrupoDesarrollo()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado([
            EntradaAcl(principal=admin, nivel="CAN_MANAGE"),
        ])
        canal = CanalControlComputo(transporte)

        sp = _PrincipalSP()
        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        canal.EjecutarRevocacion(item)

        assert len(transporte.llamadas_escribir) == 1
        _, _, entradas = transporte.llamadas_escribir[0]
        assert len(entradas) == 1
        assert entradas[0].nivel == "CAN_MANAGE"


class TestRevocacionToken:
    """Revocación sobre uso de personal access tokens (singleton)."""

    def TestRevocacionTokenSingleton(self):
        """La revocación opera sobre la ACL singleton con id vacío."""
        sp = _PrincipalSP()
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        transporte = _TransporteSimulado([
            EntradaAcl(principal=sp, nivel="CAN_USE"),
        ])
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=token_obj
        )
        canal.EjecutarRevocacion(item)

        recurso, identificador, entradas = transporte.llamadas_escribir[0]
        assert recurso == "authorization/tokens"
        assert identificador == ""
        assert len(entradas) == 0
