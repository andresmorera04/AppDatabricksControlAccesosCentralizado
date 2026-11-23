"""Pruebas unitarias de la fase `Planificador` del pipeline.

Cubren el requirement "Fase de planificación" del spec `grant-pipeline`:
construcción de la solicitud a partir de las entradas y su expansión en ítems
atómicos (uno por privilegio), y el rechazo de una solicitud inválida sin
generar ítems ni ejecutar fase alguna.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.planificador import Planificador


def CrearEntradasValidas(privilegios=None):
    """Construye las entradas (principal, privilegios, objeto) de una solicitud.

    Args:
        privilegios (list[str] | None): privilegios; por defecto dos.

    Returns:
        tuple: (principal, privilegios, objeto) válidos para cardinalidad 1 a 1.
    """
    if privilegios is None:
        privilegios = ["SELECT", "MODIFY"]
    principal = Principal(
        identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
    )
    objeto = ObjetoSecurable(
        identificador="control.produccion.ventas", tipo=TipoObjeto.TABLA_DELTA
    )
    return principal, privilegios, objeto


def TestExpandeSolicitudEnItemsAtomicos():
    """Escenario del spec: dos privilegios -> dos ítems atómicos."""
    principal, privilegios, objeto = CrearEntradasValidas()
    solicitud = SolicitudGrant.Crear(
        principal=principal, privilegios=privilegios, objeto=objeto
    )

    items = Planificador().Planificar(solicitud)

    assert len(items) == 2
    assert all(isinstance(item, ItemGrant) for item in items)
    assert [item.privilegio for item in items] == ["SELECT", "MODIFY"]


def TestCadaItemCompartePrincipalYObjeto():
    """Los ítems de una misma solicitud comparten principal y objeto."""
    principal, privilegios, objeto = CrearEntradasValidas()
    solicitud = SolicitudGrant.Crear(
        principal=principal, privilegios=privilegios, objeto=objeto
    )

    items = Planificador().Planificar(solicitud)

    for item in items:
        assert item.principal == principal
        assert item.objeto == objeto


def TestUnSoloPrivilegioGeneraUnSoloItem():
    """Una solicitud con un privilegio genera exactamente un ítem."""
    principal, _, objeto = CrearEntradasValidas()
    solicitud = SolicitudGrant.Crear(
        principal=principal, privilegios=["SELECT"], objeto=objeto
    )

    assert len(Planificador().Planificar(solicitud)) == 1


def TestPlanificarRechazaEntradaQueNoEsSolicitud():
    """Una entrada que no es `SolicitudGrant` se rechaza sin generar ítems."""
    with pytest.raises(ErrorDominio, match="SolicitudGrant"):
        Planificador().Planificar("no soy una solicitud")


def TestPlanificarDesdeEntradasConstruyeLaSolicitud():
    """La fase construye la solicitud desde las entradas recibidas (spec)."""
    principal, privilegios, objeto = CrearEntradasValidas()

    items = Planificador().PlanificarDesdeEntradas(
        principal=principal, privilegios=privilegios, objeto=objeto
    )

    assert len(items) == 2
    assert [item.privilegio for item in items] == ["SELECT", "MODIFY"]


def TestPlanificarDesdeEntradasSinPrivilegiosSeRechaza():
    """Escenario del spec: solicitud inválida -> rechazo y ningún ítem."""
    principal, _, objeto = CrearEntradasValidas()

    with pytest.raises(ErrorDominio, match="privilegio"):
        Planificador().PlanificarDesdeEntradas(
            principal=principal, privilegios=[], objeto=objeto
        )


def TestPlanificarDesdeConjuntosConCardinalidadUnoAUno():
    """Un principal y un objeto se planifican como una solicitud 1 a 1."""
    principal, privilegios, objeto = CrearEntradasValidas()

    items = Planificador().PlanificarDesdeConjuntos(
        principales=[principal], privilegios=privilegios, objetos=[objeto]
    )

    assert len(items) == 2


def TestPlanificarDesdeConjuntosRechazaCardinalidadNM():
    """Escenario del spec: N a M se rechaza antes de generar ítem alguno."""
    principal, privilegios, objeto = CrearEntradasValidas()
    otro_principal = Principal(
        identificador="grupo_analistas", tipo=TipoPrincipal.GRUPO
    )
    otro_objeto = ObjetoSecurable(
        identificador="control", tipo=TipoObjeto.CATALOGO
    )

    with pytest.raises(ErrorDominio) as error:
        Planificador().PlanificarDesdeConjuntos(
            principales=[principal, otro_principal],
            privilegios=privilegios,
            objetos=[objeto, otro_objeto],
        )

    assert "N a M" in str(error.value)
    assert "fuera de alcance" in str(error.value)
