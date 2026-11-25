"""Pruebas unitarias de la verificación posterior al otorgamiento con el canal
real de cómputo y el `Verificador` ya existente (tarea 3.3).

Verifican el comportamiento de punta a punta del verificador: un otorgamiento
confirmado por la ACL se mantiene `otorgado`, y un otorgamiento reportado como
exitoso que no aparece en la ACL pasa a `fallido` con detalle que menciona
privilegio, principal y objeto. No se modifica el verificador: solo se ejerce
con el canal real inyectado como canal de control.
"""

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalControlSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
)
from control_accesos.pipeline.verificador import Verificador


class TransportePermisosFalso:
    """Transporte simulado con una ACL fija por lectura."""

    def __init__(self, entradas=None):
        self._acl = tuple(entradas or ())

    def LeerAcl(self, recurso, identificador):
        return self._acl

    def EscribirAcl(self, recurso, identificador, entradas):
        return None


def _Item():
    principal = Principal(identificador="u@correo.com", tipo=TipoPrincipal.USUARIO)
    objeto = ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO)
    return ItemGrant(principal=principal, privilegio="CAN_USE", objeto=objeto)


def _Verificador(transporte):
    canal = CanalControlComputo(transporte)
    return Verificador(canal_datos=CanalControlSimulado(), canal_control=canal)


class TestVerificacionPosterior:
    def TestOtorgamientoConfirmadoSeMantieneOtorgado(self):
        item = _Item()
        transporte = TransportePermisosFalso(
            entradas=[EntradaAcl(principal=item.principal, nivel="CAN_USE")]
        )
        verificador = _Verificador(transporte)

        resultados = verificador.Verificar([ResultadoItem.Otorgado(item)])

        assert resultados[0].estado is EstadoItem.OTORGADO

    def TestOtorgamientoNoConfirmadoPasaAFallido(self):
        item = _Item()
        verificador = _Verificador(TransportePermisosFalso(entradas=[]))

        resultados = verificador.Verificar([ResultadoItem.Otorgado(item)])

        assert resultados[0].estado is EstadoItem.FALLIDO
        detalle = resultados[0].detalle
        assert "CAN_USE" in detalle
        assert item.principal.identificador in detalle
        assert "ClusterA" in detalle
