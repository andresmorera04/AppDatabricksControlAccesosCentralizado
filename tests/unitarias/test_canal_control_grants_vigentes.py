"""Pruebas unitarias de la lectura y normalización de la ACL del canal de
cómputo (tareas 3.1 y 3.2, design D5).

Verifican que `ListarGrantsVigentes` traduce cada entrada directa de la ACL a
un `ItemGrant` con su principal, su nivel y el objeto consultado, y que una ACL
sin entradas devuelve lista vacía distinguible de un fallo, sobre un transporte
simulado.
"""

from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal


class TransportePermisosFalso:
    """Transporte simulado con una ACL fija por lectura."""

    def __init__(self, entradas=None):
        self._acl = tuple(entradas or ())

    def LeerAcl(self, recurso, identificador):
        return self._acl

    def EscribirAcl(self, recurso, identificador, entradas):
        return None


class TestListarGrantsVigentes:
    def TestTraduceCadaEntradaAItemGrant(self):
        objeto = ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO)
        transporte = TransportePermisosFalso(
            entradas=[
                EntradaAcl(Principal(identificador="u@correo.com", tipo=TipoPrincipal.USUARIO), "CAN_USE"),
                EntradaAcl(Principal(identificador="Desarrollador", tipo=TipoPrincipal.GRUPO), "CAN_MANAGE"),
                EntradaAcl(
                    Principal(identificador="1738687d-4838-49ef-83fd-521f935a9ec2", tipo=TipoPrincipal.SERVICE_PRINCIPAL),
                    "CAN_ATTACH_TO",
                ),
            ]
        )
        canal = CanalControlComputo(transporte)

        grants = canal.ListarGrantsVigentes(objeto)

        assert len(grants) == 3
        assert all(g.objeto == objeto for g in grants)
        assert {g.privilegio for g in grants} == {"CAN_USE", "CAN_MANAGE", "CAN_ATTACH_TO"}

    def TestACLSinEntradasDevuelveListaVacia(self):
        objeto = ObjetoSecurable(identificador="Wh-1", tipo=TipoObjeto.SQL_WAREHOUSE)
        canal = CanalControlComputo(TransportePermisosFalso(entradas=[]))

        assert canal.ListarGrantsVigentes(objeto) == []
