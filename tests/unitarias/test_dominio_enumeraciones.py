"""Pruebas unitarias de las enumeraciones del modelo de dominio.

Cubren los cuatro tipos enumerados definidos en el design.md (D2):
`TipoPrincipal`, `TipoObjeto`, `Plano` y `EstadoItem`, con sus miembros y
valores en español (estándar del proyecto).
"""

from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)


def TestMiembrosDeTipoPrincipal():
    """TipoPrincipal debe tener exactamente usuario, grupo y service principal."""
    miembros_esperados = {"USUARIO", "GRUPO", "SERVICE_PRINCIPAL"}
    miembros_reales = {miembro.name for miembro in TipoPrincipal}
    assert miembros_reales == miembros_esperados


def TestValoresDeTipoPrincipalEnEspanol():
    """Los valores de TipoPrincipal deben estar en español (snake_case)."""
    assert TipoPrincipal.USUARIO.value == "usuario"
    assert TipoPrincipal.GRUPO.value == "grupo"
    assert TipoPrincipal.SERVICE_PRINCIPAL.value == "service_principal"


def TestMiembrosDeTipoObjetoCubrenLosQuinceTipos():
    """TipoObjeto debe cubrir los 15 tipos de objeto del README (datos + control)."""
    miembros_esperados = {
        # Plano de datos (Unity Catalog).
        "CATALOGO",
        "ESQUEMA",
        "TABLA_DELTA",
        "STREAMING_TABLE",
        "VISTA_MATERIALIZADA",
        "VISTA_SQL",
        "VOLUMEN",
        "MODELO_ML",
        "EXTERNAL_LOCATION",
        "CONNECTION",
        # Plano de control (workspace).
        "COMPUTO_CLASICO",
        "COMPUTO_SERVERLESS",
        "SQL_WAREHOUSE",
        "DATABRICK_APP",
        "USO_TOKEN",
    }
    miembros_reales = {miembro.name for miembro in TipoObjeto}
    assert miembros_reales == miembros_esperados
    assert len(miembros_reales) == 15, "Debe haber exactamente 15 tipos de objeto"


def TestMiembrosDePlano():
    """Plano debe tener exactamente datos y control."""
    assert {miembro.name for miembro in Plano} == {"DATOS", "CONTROL"}
    assert Plano.DATOS.value == "datos"
    assert Plano.CONTROL.value == "control"


def TestMiembrosDeEstadoItem():
    """EstadoItem debe tener los tres estados del resultado por ítem (spec)."""
    assert {miembro.name for miembro in EstadoItem} == {
        "OTORGADO",
        "FALLIDO",
        "PRIVILEGIOS_INSUFICIENTES",
    }
    assert EstadoItem.OTORGADO.value == "otorgado"
    assert EstadoItem.FALLIDO.value == "fallido"
    assert EstadoItem.PRIVILEGIOS_INSUFICIENTES.value == "privilegios_insuficientes"
