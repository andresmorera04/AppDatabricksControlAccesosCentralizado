"""Pruebas unitarias de otorgamiento sobre Databricks Apps y uso de personal
access tokens (tareas 2.1 y 2.2 del change `grants-apps-tokens`).

Ejercitan `EjecutarOtorgamiento` sobre un transporte simulado, verificando la
escritura aditiva por otorgatario, la idempotencia y la rama singleton para
`USO_TOKEN` (design D4).
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


class TestOtorgamientoApp:
    """Otorgamiento sobre Databricks Apps con escritura aditiva."""

    def TestOtorgamientoASinEntradaPrevia(self):
        """Agregar entrada nueva conservando las de otros otorgatarios."""
        admin = _GrupoDesarrollo()
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado(
            [EntradaAcl(principal=admin, nivel="CAN_MANAGE")]
        )
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        canal.EjecutarOtorgamiento(item)

        assert len(transporte.llamadas_escribir) == 1
        recurso, _, entradas = transporte.llamadas_escribir[0]
        assert recurso == "apps"
        assert len(entradas) == 2
        niveles = {e.nivel for e in entradas}
        assert "CAN_USE" in niveles
        assert "CAN_MANAGE" in niveles

    def TestOtorgamientoSobreEntradaExistente(self):
        """Actualizar nivel sin tocar a otros otorgatarios."""
        sp = _PrincipalSP()
        admin = _GrupoDesarrollo()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado(
            [
                EntradaAcl(principal=sp, nivel="CAN_USE"),
                EntradaAcl(principal=admin, nivel="CAN_MANAGE"),
            ]
        )
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_MANAGE", objeto=app
        )
        canal.EjecutarOtorgamiento(item)

        _, _, entradas = transporte.llamadas_escribir[0]
        for e in entradas:
            if e.principal.identificador == "sp-prueba":
                assert e.nivel == "CAN_MANAGE"
            else:
                assert e.nivel == "CAN_MANAGE"  # admin se conserva

    def TestOtorgamientoIdempotente(self):
        """Otorgar el mismo nivel vigente reporta éxito sin alterar la ACL."""
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
        )
        acl_inicial = [EntradaAcl(principal=sp, nivel="CAN_USE")]
        transporte = _TransporteSimulado(acl_inicial)
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        canal.EjecutarOtorgamiento(item)

        assert len(transporte.llamadas_escribir) == 1
        _, _, entradas = transporte.llamadas_escribir[0]
        assert len(entradas) == 1
        assert entradas[0].nivel == "CAN_USE"

    def TestOperacionEnviadaAlTransporte(self):
        """El transporte recibe recurso, id y nivel derivados del ítem."""
        sp = _PrincipalSP()
        app = ObjetoSecurable(
            identificador="MiApp123", tipo=TipoObjeto.DATABRICK_APP
        )
        transporte = _TransporteSimulado()
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=app
        )
        canal.EjecutarOtorgamiento(item)

        recurso, identificador, _ = transporte.llamadas_escribir[0]
        assert recurso == "apps"
        assert identificador == "MiApp123"


class TestOtorgamientoToken:
    """Otorgamiento sobre uso de personal access tokens (singleton)."""

    def TestOtorgamientoTokenSingleton(self):
        """El id del objeto queda vacío en la llamada de escritura."""
        sp = _PrincipalSP()
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        transporte = _TransporteSimulado()
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=token_obj
        )
        canal.EjecutarOtorgamiento(item)

        recurso, identificador, entradas = transporte.llamadas_escribir[0]
        assert recurso == "authorization/tokens"
        # El canal convierte el identificador a vacío para USO_TOKEN
        # (design D2, singleton del workspace).
        assert identificador == ""
        assert len(entradas) == 1
        assert entradas[0].nivel == "CAN_USE"


class TestNoRegresionComputo:
    """Los tres tipos de cómputo de C7 siguen otorgando correctamente."""

    def TestOtorgamientoCluster(self):
        sp = _PrincipalSP()
        cluster = ObjetoSecurable(
            identificador="1234-567890-abcdef", tipo=TipoObjeto.COMPUTO_CLASICO
        )
        transporte = _TransporteSimulado()
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_ATTACH_TO", objeto=cluster
        )
        canal.EjecutarOtorgamiento(item)

        recurso, _, entradas = transporte.llamadas_escribir[0]
        assert recurso == "clusters"
        assert entradas[0].nivel == "CAN_ATTACH_TO"

    def TestOtorgamientoServerless(self):
        sp = _PrincipalSP()
        ssc = ObjetoSecurable(
            identificador="Default Interactive Compute",
            tipo=TipoObjeto.COMPUTO_SERVERLESS,
        )
        transporte = _TransporteSimulado()
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=ssc
        )
        canal.EjecutarOtorgamiento(item)

        recurso, _, entradas = transporte.llamadas_escribir[0]
        assert recurso == "serverless-compute"
        assert entradas[0].nivel == "CAN_USE"

    def TestOtorgamientoWarehouse(self):
        sp = _PrincipalSP()
        wh = ObjetoSecurable(
            identificador="abc123def456", tipo=TipoObjeto.SQL_WAREHOUSE
        )
        transporte = _TransporteSimulado()
        canal = CanalControlComputo(transporte)

        item = ItemGrant(
            principal=sp, privilegio="CAN_USE", objeto=wh
        )
        canal.EjecutarOtorgamiento(item)

        recurso, _, entradas = transporte.llamadas_escribir[0]
        assert recurso == "sql/warehouses"
        assert entradas[0].nivel == "CAN_USE"
