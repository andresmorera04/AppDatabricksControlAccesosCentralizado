"""Pruebas unitarias de los contratos de los canales de ejecución.

Cubren los requirements "Contrato unificado de ejecución por canal", "Canal SQL
para el plano de datos", "Canal SDK/REST para el plano de control" y "Errores de
privilegios insuficientes identificables" del spec `channel-adapters`.

Se usa un canal de prueba (subclase concreta mínima) para ejercitar el
contrato: el contrato traduce los errores a resultados por ítem y nunca
propaga excepciones al llamador.
"""

import pytest

from control_accesos.canales.contratos import Canal, CanalControl, CanalDatos
from control_accesos.canales.errores import (
    ErrorCanal,
    ErrorPrivilegiosInsuficientes,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)


class CanalDatosDePrueba(CanalDatos):
    """Canal de datos de prueba con comportamiento configurable por escenario."""

    def __init__(self, error_a_provocar=None, grants_vigentes=None):
        """Guarda el escenario a simular.

        Args:
            error_a_provocar (Exception | None): error que la ejecución lanza.
            grants_vigentes (list[ItemGrant] | None): grants que reporta la
                consulta de grants vigentes.
        """
        self.error_a_provocar = error_a_provocar
        self.grants_vigentes = grants_vigentes or []
        self.items_otorgados = []
        self.items_revocados = []

    def EjecutarOtorgamiento(self, item):
        """Simula la ejecución del GRANT; lanza el error configurado si existe."""
        if self.error_a_provocar is not None:
            raise self.error_a_provocar
        self.items_otorgados.append(item)

    def EjecutarRevocacion(self, item):
        """Simula la ejecución del REVOKE; lanza el error configurado si existe."""
        if self.error_a_provocar is not None:
            raise self.error_a_provocar
        self.items_revocados.append(item)

    def ListarGrantsVigentes(self, objeto):
        """Devuelve los grants vigentes configurados para el objeto."""
        return list(self.grants_vigentes)


def CrearItemDeDatos(privilegio="SELECT"):
    """Construye un ítem del plano de datos para las pruebas."""
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas", tipo=TipoObjeto.TABLA_DELTA
        ),
    )


def TestContratosSonAbstractos():
    """Los contratos no se pueden instanciar directamente (son ABC)."""
    with pytest.raises(TypeError):
        Canal()
    with pytest.raises(TypeError):
        CanalDatos()
    with pytest.raises(TypeError):
        CanalControl()


def TestCanalDatosDerivaDelContratoUnificado():
    """CanalDatos y CanalControl comparten el mismo contrato base."""
    assert issubclass(CanalDatos, Canal)
    assert issubclass(CanalControl, Canal)


def TestOtorgamientoExitosoDevuelveResultadoOtorgado():
    """Escenario del spec: ítem válido otorgado sin errores -> estado otorgado."""
    canal = CanalDatosDePrueba()
    item = CrearItemDeDatos()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert resultado.item == item
    assert canal.items_otorgados == [item]


def TestFalloSeReportaComoResultadoFallidoSinPropagarExcepcion():
    """Escenario del spec: fallo de ejecución -> resultado fallido con detalle."""
    canal = CanalDatosDePrueba(
        error_a_provocar=ErrorCanal("El objeto no existe en el workspace.")
    )
    item = CrearItemDeDatos()

    # El contrato no propaga la excepción: devuelve un resultado por ítem.
    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert canal.items_otorgados == []


def TestPermisoDenegadoSeMarcaComoPrivilegiosInsuficientes():
    """Escenario del spec: permiso denegado -> privilegios insuficientes."""
    canal = CanalDatosDePrueba(
        error_a_provocar=ErrorPrivilegiosInsuficientes(
            "PERMISSION_DENIED: el llamante no puede otorgar SELECT."
        )
    )

    resultado = canal.Otorgar(CrearItemDeDatos())

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "PERMISSION_DENIED" in resultado.detalle


def TestPermisoDenegadoEsDistinguibleDeUnFalloGenerico():
    """La marca de privilegios insuficientes se distingue del fallo genérico."""
    canal_denegado = CanalDatosDePrueba(
        error_a_provocar=ErrorPrivilegiosInsuficientes("PERMISSION_DENIED")
    )
    canal_generico = CanalDatosDePrueba(
        error_a_provocar=ErrorCanal("El objeto no existe.")
    )

    resultado_denegado = canal_denegado.Otorgar(CrearItemDeDatos())
    resultado_generico = canal_generico.Otorgar(CrearItemDeDatos())

    assert (
        resultado_denegado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )
    assert resultado_generico.estado is EstadoItem.FALLIDO
    assert resultado_denegado.estado is not resultado_generico.estado


def TestErrorDePrivilegiosInsuficientesEsErrorDeCanal():
    """La jerarquía de errores permite capturar el error por su tipo."""
    assert issubclass(ErrorPrivilegiosInsuficientes, ErrorCanal)
    assert issubclass(ErrorCanal, Exception)


def TestRevocacionSigueElMismoContrato():
    """Revocar devuelve resultados por ítem con el mismo contrato que otorgar."""
    canal_exitoso = CanalDatosDePrueba()
    item = CrearItemDeDatos()
    resultado_exitoso = canal_exitoso.Revocar(item)
    assert resultado_exitoso.estado is EstadoItem.OTORGADO
    assert canal_exitoso.items_revocados == [item]

    canal_fallido = CanalDatosDePrueba(
        error_a_provocar=ErrorCanal("Fallo al revocar.")
    )
    resultado_fallido = canal_fallido.Revocar(CrearItemDeDatos())
    assert resultado_fallido.estado is EstadoItem.FALLIDO
    assert "revocar" in resultado_fallido.detalle


def TestErrorNoPrevistoSeReportaComoFallo():
    """Cualquier excepción inesperada se traduce a resultado fallido."""
    canal = CanalDatosDePrueba(
        error_a_provocar=RuntimeError("Falla inesperada del entorno.")
    )

    resultado = canal.Otorgar(CrearItemDeDatos())

    assert resultado.estado is EstadoItem.FALLIDO
    assert "inesperada" in resultado.detalle


def TestListarGrantsVigentesDevuelveLosGrantsDelObjeto():
    """Escenario del spec: el canal devuelve los grants vigentes del objeto."""
    item_vigente = CrearItemDeDatos(privilegio="SELECT")
    canal = CanalDatosDePrueba(grants_vigentes=[item_vigente])

    grants = canal.ListarGrantsVigentes(item_vigente.objeto)

    assert grants == [item_vigente]


def TestListarGrantsVigentesDeObjetoSinGrants():
    """Un objeto sin grants vigentes devuelve una lista vacía."""
    canal = CanalDatosDePrueba(grants_vigentes=[])
    objeto = ObjetoSecurable(
        identificador="control.produccion.ventas", tipo=TipoObjeto.TABLA_DELTA
    )
    assert canal.ListarGrantsVigentes(objeto) == []
