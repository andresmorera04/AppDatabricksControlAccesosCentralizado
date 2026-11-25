"""Pruebas unitarias del registro opcional en la bitácora de errores del canal
de cómputo (tarea 4.3, design D7).

Verifican que, con un registrador inyectado, un fallo de ejecución queda
registrado con su detalle y contexto; y que la auditoría nunca introduce fallos
en cascada: sin registrador, o con un registrador que falla, el ítem conserva su
resultado traducido sin propagar excepción alguna.
"""

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_control_computo import (
    MODULO_BITACORA_ERRORES,
    CanalControlComputo,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class TransportePermisosFalso:
    """Transporte simulado que lanza un fallo al escribir."""

    def LeerAcl(self, recurso, identificador):
        return ()

    def EscribirAcl(self, recurso, identificador, entradas):
        raise ErrorCanal("fallo de red")


class RegistradorErroresFalso:
    """Registrador que acumula llamadas y puede configurarse para fallar."""

    def __init__(self, falla_al_registrar=False):
        self.registros = []
        self.falla_al_registrar = falla_al_registrar

    def Registrar(self, excepcion, modulo=None, usuario=None, contexto=None):
        if self.falla_al_registrar:
            raise RuntimeError("bitácora caída")
        self.registros.append((excepcion, modulo, usuario, contexto))


def _Item():
    return ItemGrant(
        principal=Principal(identificador="u@correo.com", tipo=TipoPrincipal.USUARIO),
        privilegio="CAN_USE",
        objeto=ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO),
    )


class TestBitacoraErrores:
    def TestFalloQuedaRegistrado(self):
        registrador = RegistradorErroresFalso()
        canal = CanalControlComputo(
            TransportePermisosFalso(), registrador_errores=registrador
        )

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
        assert len(registrador.registros) == 1
        (excepcion, modulo, usuario, contexto) = registrador.registros[0]
        assert "fallo de red" in str(excepcion)
        assert modulo == MODULO_BITACORA_ERRORES
        assert usuario is None
        assert "ClusterA" in contexto

    def TestSinRegistradorNoFalla(self):
        canal = CanalControlComputo(TransportePermisosFalso())

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO

    def TestRegistradorQueFallaNoPropaga(self):
        canal = CanalControlComputo(
            TransportePermisosFalso(),
            registrador_errores=RegistradorErroresFalso(falla_al_registrar=True),
        )

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
