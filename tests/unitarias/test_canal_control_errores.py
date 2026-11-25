"""Pruebas unitarias de la clasificación de errores del canal de cómputo
(tareas 4.1 y 4.2, design D6).

Verifican que el canal distingue por caso las respuestas de error del transporte
y las traduce al estado correspondiente sin propagar excepciones al llamador,
con la regla fail-safe: solo el denegado explícito marca privilegios
insuficientes.
"""

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal


class TransportePermisosFalso:
    """Transporte simulado que lanza el error de escritura configurado."""

    def __init__(self, error_escritura=None):
        self.error_escritura = error_escritura

    def LeerAcl(self, recurso, identificador):
        return ()

    def EscribirAcl(self, recurso, identificador, entradas):
        if self.error_escritura is not None:
            raise self.error_escritura


def _Item():
    return ItemGrant(
        principal=Principal(identificador="destino@correo.com", tipo=TipoPrincipal.USUARIO),
        privilegio="CAN_USE",
        objeto=ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO),
    )


class TestClasificacionErrores:
    def TestPermisoDenegadoMarcaPrivilegiosInsuficientes(self):
        transporte = TransportePermisosFalso(
            error_escritura=ErrorCanal("[PERMISSION_DENIED] Acceso denegado.")
        )
        canal = CanalControlComputo(transporte)

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
        assert "CAN_USE" in resultado.detalle
        assert "ClusterA" in resultado.detalle

    def TestObjetoInexistenteMarcaFallido(self):
        transporte = TransportePermisosFalso(
            error_escritura=ErrorCanal("[RESOURCE_DOES_NOT_EXIST] Cluster 'xyz' no existe.")
        )
        canal = CanalControlComputo(transporte)

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
        assert "no existe" in resultado.detalle
        assert "ClusterA" in resultado.detalle

    def TestPrincipalInexistenteMarcaFallidoConPrincipal(self):
        transporte = TransportePermisosFalso(
            error_escritura=ErrorCanal("[PRINCIPAL_DOES_NOT_EXIST] El principal no existe.")
        )
        canal = CanalControlComputo(transporte)

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
        assert "destino@correo.com" in resultado.detalle

    def TestErrorGenericoMarcaFallidoSinPrivilegios(self):
        transporte = TransportePermisosFalso(error_escritura=ErrorCanal("boom inesperado"))
        canal = CanalControlComputo(transporte)

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
        assert "boom inesperado" in resultado.detalle

    def TestNingunCasoPropagaExcepcion(self):
        transporte = TransportePermisosFalso(error_escritura=ErrorCanal("boom"))
        canal = CanalControlComputo(transporte)

        resultado = canal.Otorgar(_Item())

        assert resultado.estado is EstadoItem.FALLIDO
