"""Pruebas unitarias del otorgamiento aditivo por otorgatario del canal de
cómputo (tareas 2.1 y 2.2, design D4).

Verifican que `EjecutarOtorgamiento` compone la ACL modificando únicamente la
entrada del principal del ítem y conservando las entradas de los demás
otorgatarios, sobre un transporte simulado sin conexión externa.
"""

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


def _Item(privilegio, identificador_objeto="obj-1", principal_id="nuevo@correo.com", tipo_objeto=TipoObjeto.COMPUTO_CLASICO):
    return ItemGrant(
        principal=Principal(identificador=principal_id, tipo=TipoPrincipal.USUARIO),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador_objeto, tipo=tipo_objeto),
    )


class TransportePermisosFalso:
    """Transporte simulado con ACL en memoria y trazabilidad de llamadas."""

    def __init__(self, entradas=None, error_escritura=None):
        self._acl = list(entradas or [])
        self.escrituras = []
        self.lecturas = []
        self.error_escritura = error_escritura

    def LeerAcl(self, recurso, identificador):
        self.lecturas.append((recurso, identificador))
        return tuple(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        if self.error_escritura is not None:
            raise self.error_escritura
        self._acl = list(entradas)
        self.escrituras.append((recurso, identificador, list(entradas)))


OTRO_PRINCIPAL = Principal(identificador="otro@correo.com", tipo=TipoPrincipal.USUARIO)
OTRO_NIVEL = EntradaAcl(principal=OTRO_PRINCIPAL, nivel="CAN_RESTART")


class TestOtorgamientoAditivo:
    def TestAgregaEntradaSinAlterarOtros(self):
        transporte = TransportePermisosFalso(entradas=[OTRO_NIVEL])
        canal = CanalControlComputo(transporte)
        item = _Item("CAN_USE", identificador_objeto="ClusterA")

        resultado = canal.Otorgar(item)

        assert resultado.estado is EstadoItem.OTORGADO
        (_, _, entradas_escritas) = transporte.escrituras[0]
        assert EntradaAcl(principal=item.principal, nivel="CAN_USE") in entradas_escritas
        assert OTRO_NIVEL in entradas_escritas

    def TestActualizaEntradaExistenteSinTocarOtros(self):
        principal_previo = Principal(identificador="mismo@correo.com", tipo=TipoPrincipal.USUARIO)
        transporte = TransportePermisosFalso(
            entradas=[
                EntradaAcl(principal=principal_previo, nivel="CAN_USE"),
                OTRO_NIVEL,
            ]
        )
        canal = CanalControlComputo(transporte)
        item = _Item("CAN_MANAGE", principal_id="mismo@correo.com")

        canal.Otorgar(item)

        (_, _, entradas_escritas) = transporte.escrituras[0]
        assert EntradaAcl(principal=principal_previo, nivel="CAN_MANAGE") in entradas_escritas
        assert OTRO_NIVEL in entradas_escritas
        # La entrada previa del mismo principal no se duplica con su nivel antiguo.
        assert sum(1 for e in entradas_escritas if e.principal == principal_previo) == 1

    def TestOtorgarNivelYaVigenteEsIdempotente(self):
        principal = Principal(identificador="mismo@correo.com", tipo=TipoPrincipal.USUARIO)
        transporte = TransportePermisosFalso(
            entradas=[EntradaAcl(principal=principal, nivel="CAN_USE")]
        )
        canal = CanalControlComputo(transporte)
        item = _Item("CAN_USE", principal_id="mismo@correo.com")

        resultado = canal.Otorgar(item)

        assert resultado.estado is EstadoItem.OTORGADO
        (_, _, entradas_escritas) = transporte.escrituras[0]
        assert EntradaAcl(principal=principal, nivel="CAN_USE") in entradas_escritas

    def TestOperacionDerivadaDelItemSinValoresEmbebidos(self):
        transporte = TransportePermisosFalso(entradas=[OTRO_NIVEL])
        canal = CanalControlComputo(transporte)
        item = _Item(
            "CAN_USE", identificador_objeto="Wh-Principal", tipo_objeto=TipoObjeto.SQL_WAREHOUSE
        )

        canal.Otorgar(item)

        (recurso, identificador, _) = transporte.escrituras[0]
        assert recurso == "sql/warehouses"
        assert identificador == "Wh-Principal"


class TransportePermisosConConflicto:
    """Transporte cuya escritura falla N veces con conflicto y luego acepta.

    Imita la respuesta real de la Permissions API cuando otro administrador
    modificó la ACL entre la lectura y la escritura (`RESOURCE_CONFLICT`),
    para verificar el reintento acotado del canal (design D4) de forma
    determinista, sin depender de una carrera real en el workspace.
    """

    def __init__(self, entradas=None, conflictos=1):
        self._acl = list(entradas or [])
        self.escrituras = []
        self.lecturas = []
        self._conflictos_restantes = conflictos

    def LeerAcl(self, recurso, identificador):
        self.lecturas.append((recurso, identificador))
        return tuple(self._acl)

    def EscribirAcl(self, recurso, identificador, entradas):
        self.escrituras.append((recurso, identificador, list(entradas)))
        if self._conflictos_restantes > 0:
            self._conflictos_restantes -= 1
            raise ErrorCanal(
                "[RESOURCE_CONFLICT] La ACL cambió desde su lectura."
            )
        self._acl = list(entradas)


class TestReintentoConflicto:
    """El reintento acotado ante conflicto de concurrencia (design D4)."""

    def TestConflictoPuntualSeReleeYReintentaUnaVez(self):
        """La primera escritura con conflicto se reintenta tras releer y otorga."""
        transporte = TransportePermisosConConflicto(entradas=[OTRO_NIVEL])
        canal = CanalControlComputo(transporte)
        item = _Item("CAN_USE", identificador_objeto="ClusterA")

        resultado = canal.Otorgar(item)

        assert resultado.estado is EstadoItem.OTORGADO
        # Un intento fallido por conflicto + un reintento: ni más ni menos.
        assert len(transporte.escrituras) == 2
        # El reintento relee la ACL antes de recomponer la escritura.
        assert len(transporte.lecturas) == 2
        (_, _, entradas_finales) = transporte.escrituras[-1]
        assert EntradaAcl(principal=item.principal, nivel="CAN_USE") in entradas_finales
        assert OTRO_NIVEL in entradas_finales

    def TestConflictoPersistenteAgotaElReintentoYQuedaFallido(self):
        """Un conflicto que persiste se reporta fallido con el detalle crudo."""
        transporte = TransportePermisosConConflicto(conflictos=99)
        canal = CanalControlComputo(transporte)
        item = _Item("CAN_USE", identificador_objeto="ClusterA")

        resultado = canal.Otorgar(item)

        # El reintento es acotado: dos intentos en total, sin bucle.
        assert len(transporte.escrituras) == 2
        assert resultado.estado is EstadoItem.FALLIDO
        assert "RESOURCE_CONFLICT" in resultado.detalle
        assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES
