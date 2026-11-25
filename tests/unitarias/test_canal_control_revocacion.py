"""Pruebas unitarias de la revocación aditiva por otorgatario del canal de
cómputo (tareas 2.3 y 2.4, design D4).

Verifican que `EjecutarRevocacion` elimina únicamente la entrada del principal
del ítem y conserva las entradas de los demás otorgatarios, y que revocar un
permiso que no estaba vigente no altera otras entradas, sobre un transporte
simulado.
"""

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class TransportePermisosFalso:
    """Transporte simulado con ACL en memoria y trazabilidad de llamadas."""

    def __init__(self, entradas=None):
        self._acl = list(entradas or [])
        self.escrituras = []

    def LeerAcl(self, recurso, identificador):
        return tuple(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self._acl = list(entradas)
        self.escrituras.append((recurso, identificador, list(entradas)))


OTRO_PRINCIPAL = Principal(identificador="otro@correo.com", tipo=TipoPrincipal.USUARIO)
OTRO_NIVEL = EntradaAcl(principal=OTRO_PRINCIPAL, nivel="CAN_RESTART")


def _Item(principal_id, privilegio="CAN_USE"):
    return ItemGrant(
        principal=Principal(identificador=principal_id, tipo=TipoPrincipal.USUARIO),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO),
    )


class TestRevocacionAditiva:
    def TestRevocaVigenteConservandoOtros(self):
        objetivo = Principal(identificador="a-revocar@correo.com", tipo=TipoPrincipal.USUARIO)
        transporte = TransportePermisosFalso(
            entradas=[EntradaAcl(principal=objetivo, nivel="CAN_USE"), OTRO_NIVEL]
        )
        canal = CanalControlComputo(transporte)

        resultado = canal.Revocar(_Item("a-revocar@correo.com"))

        assert resultado.estado is EstadoItem.OTORGADO
        (_, _, entradas_escritas) = transporte.escrituras[0]
        assert all(e.principal != objetivo for e in entradas_escritas)
        assert OTRO_NIVEL in entradas_escritas

    def TestRevocaNoVigenteNoAlteraOtros(self):
        transporte = TransportePermisosFalso(entradas=[OTRO_NIVEL])
        canal = CanalControlComputo(transporte)

        resultado = canal.Revocar(_Item("ausente@correo.com"))

        assert resultado.estado is EstadoItem.OTORGADO
        (_, _, entradas_escritas) = transporte.escrituras[0]
        assert entradas_escritas == [OTRO_NIVEL]
