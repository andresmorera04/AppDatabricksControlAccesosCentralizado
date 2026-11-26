"""Pruebas unitarias de la bitácora de errores del canal para Databricks Apps y
uso de personal access tokens (tarea 4.3 del change `grants-apps-tokens`).
"""

import pytest

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
    MODULO_BITACORA_ERRORES,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class _TransporteConError:
    def __init__(self, excepcion):
        self._excepcion = excepcion

    def LeerAcl(self, recurso, identificador):
        raise self._excepcion

    def EscribirAcl(self, recurso, identificador, entradas):
        raise self._excepcion


class _RegistradorCaptura:
    """Doble de la bitácora de errores que captura las llamadas."""

    def __init__(self):
        self.registros = []
        self.fallar = False

    def Registrar(self, excepcion, modulo=None, usuario=None, contexto=None):
        if self.fallar:
            raise RuntimeError("Bitácora no disponible")
        self.registros.append({
            "excepcion": excepcion,
            "modulo": modulo,
            "usuario": usuario,
            "contexto": contexto,
        })


def _PrincipalSP():
    return Principal(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL, identificador="sp-prueba"
    )


def _App():
    return ObjetoSecurable(
        identificador="mi-app", tipo=TipoObjeto.DATABRICK_APP
    )


class TestBitacoraErroresCanal:
    """El canal registra fallos en la bitácora sin propagarlos (design D7)."""

    def TestFalloQuedaRegistradoConDetalleYContexto(self):
        registrador = _RegistradorCaptura()
        canal = CanalControlComputo(
            _TransporteConError(Exception("Error de red")),
            registrador_errores=registrador,
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        with pytest.raises(Exception):
            canal.EjecutarOtorgamiento(item)

        assert len(registrador.registros) == 1
        registro = registrador.registros[0]
        assert registro["modulo"] == MODULO_BITACORA_ERRORES
        assert registro["contexto"] is not None
        assert "databricks_app" in registro["contexto"]
        assert "mi-app" in registro["contexto"]

    def TestSinRegistradorNoPropagaExcepcionDelRegistro(self):
        """Sin registrador, el canal solo traduce el error del transporte."""
        canal = CanalControlComputo(
            _TransporteConError(Exception("Error de red")),
            registrador_errores=None,
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        # Debe traducir el error sin intentar registrar
        from control_accesos.canales.errores import ErrorCanal
        with pytest.raises(ErrorCanal):
            canal.EjecutarOtorgamiento(item)

    def TestRegistradorQueFallaNoPropagaEnCascada(self):
        """Si la bitácora falla al registrar, el canal no propaga (design D7)."""
        registrador = _RegistradorCaptura()
        registrador.fallar = True
        canal = CanalControlComputo(
            _TransporteConError(Exception("Error de red")),
            registrador_errores=registrador,
        )
        item = ItemGrant(
            principal=_PrincipalSP(), privilegio="CAN_USE", objeto=_App()
        )
        # El error del transporte se traduce; el fallo del registrador NO
        # se propaga en cascada.
        from control_accesos.canales.errores import ErrorCanal
        with pytest.raises(ErrorCanal):
            canal.EjecutarOtorgamiento(item)
