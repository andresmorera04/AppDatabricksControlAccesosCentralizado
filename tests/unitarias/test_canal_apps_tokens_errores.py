"""Pruebas unitarias de clasificación de errores para Databricks Apps y uso de
personal access tokens (tareas 4.1 y 4.2 del change `grants-apps-tokens`).
"""

import pytest

from control_accesos.canales.errores import ErrorCanal, ErrorPrivilegiosInsuficientes
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


class _TransporteConError:
    """Transporte que siempre lanza una excepción configurable."""

    def __init__(self, excepcion):
        self._excepcion = excepcion

    def LeerAcl(self, recurso, identificador):
        raise self._excepcion

    def EscribirAcl(self, recurso, identificador, entradas):
        raise self._excepcion


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


def _App():
    return ObjetoSecurable(
        identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
    )


class TestClasificacionErrores:
    """El canal traduce errores del transporte por caso (design D6)."""

    def TestPermisoDenegadoPrivilegiosInsuficientes(self):
        canal = CanalControlComputo(
            _TransporteConError(Exception("PERMISSION_DENIED: Access denied"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(ErrorPrivilegiosInsuficientes) as exc:
            canal.EjecutarOtorgamiento(item)
        assert "CAN_USE" in str(exc.value)
        assert "databricks_app" in str(exc.value)

    def TestAppInexistenteFallidoConMensaje(self):
        canal = CanalControlComputo(
            _TransporteConError(Exception("RESOURCE_DOES_NOT_EXIST: App 'mi-app' does not exist"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(ErrorCanal) as exc:
            canal.EjecutarOtorgamiento(item)
        assert "no existe" in str(exc.value)

    def TestPrincipalInexistenteFallidoConMensaje(self):
        canal = CanalControlComputo(
            _TransporteConError(Exception("RESOURCE_DOES_NOT_EXIST: Principal: UserName('no-existe') does not exist"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(ErrorCanal) as exc:
            canal.EjecutarOtorgamiento(item)
        assert "no existe" in str(exc.value)
        assert "sp-prueba" in str(exc.value)

    def TestOtroFalloFallidoConDetalleCrudo(self):
        canal = CanalControlComputo(
            _TransporteConError(Exception("Error inesperado de red"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(ErrorCanal) as exc:
            canal.EjecutarOtorgamiento(item)
        assert "Error inesperado de red" in str(exc.value)
        # No debe tener marca de privilegios insuficientes
        assert not isinstance(exc.value, ErrorPrivilegiosInsuficientes)

    def TestNingunCasoPropagaExcepcionAlLlamador(self):
        """Todos los errores se traducen, nunca se propaga la excepción cruda."""
        canal = CanalControlComputo(
            _TransporteConError(ValueError("error inesperado"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        # No debe propagar ValueError
        with pytest.raises(ErrorCanal):
            canal.EjecutarOtorgamiento(item)

    def TestTokenPermissionsApiNoHabilitada(self):
        """Feature no habilitada → fallido con mensaje que identifica la feature."""
        canal = CanalControlComputo(
            _TransporteConError(Exception("FEATURE_NOT_ENABLED: Token Permissions API is not enabled"))
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(ErrorCanal) as exc:
            canal.EjecutarOtorgamiento(item)
        assert "no habilitada" in str(exc.value)
        assert "Token Permissions API" in str(exc.value)
