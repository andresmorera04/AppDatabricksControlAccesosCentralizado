"""Pruebas unitarias de la clase `ObjetoSecurable` del modelo de dominio.

Cubren el requirement "Representación de objetos securables tipados" y
"Normalización de identificadores de objetos" del spec `grant-domain-model`:
plano derivado del tipo mediante mapa declarativo, rechazo de tipos no
soportados con mensaje explícito, y resolución de dos referencias con distinta
escritura al mismo objeto.
"""

import pytest

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    MAPA_TIPO_OBJETO_A_PLANO,
    ObjetoSecurable,
)


def TestObjetoCatalogoEsPlanoDatos():
    """Un catálogo pertenece al plano de datos y su plano se deriva del tipo."""
    objeto = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
    assert objeto.plano is Plano.DATOS


def TestObjetoSqlWarehouseEsPlanoControl():
    """Un SQL warehouse pertenece al plano de control (Permissions API)."""
    objeto = ObjetoSecurable(
        identificador="a1b2c3d4e5f6", tipo=TipoObjeto.SQL_WAREHOUSE
    )
    assert objeto.plano is Plano.CONTROL


def TestMapaDePlanosCubreTodosLosTiposDeObjeto():
    """El mapa declarativo TipoObjeto -> Plano cubre los 15 tipos (sin huecos)."""
    assert set(MAPA_TIPO_OBJETO_A_PLANO.keys()) == set(TipoObjeto)
    assert len(MAPA_TIPO_OBJETO_A_PLANO) == 15


def TestPlanoDerivadoDeCadaTipoDeObjeto():
    """Cada tipo de objeto deriva su plano declarado, sin lógica dispersa."""
    tipos_de_datos = {
        TipoObjeto.CATALOGO,
        TipoObjeto.ESQUEMA,
        TipoObjeto.TABLA_DELTA,
        TipoObjeto.STREAMING_TABLE,
        TipoObjeto.VISTA_MATERIALIZADA,
        TipoObjeto.VISTA_SQL,
        TipoObjeto.VOLUMEN,
        TipoObjeto.MODELO_ML,
        TipoObjeto.EXTERNAL_LOCATION,
        TipoObjeto.CONNECTION,
    }
    for tipo in TipoObjeto:
        objeto = ObjetoSecurable(identificador="objeto_demo", tipo=tipo)
        plano_esperado = Plano.DATOS if tipo in tipos_de_datos else Plano.CONTROL
        assert objeto.plano is plano_esperado, f"Plano incorrecto para {tipo.name}"


def TestTipoDeObjetoNoSoportadoSeRechaza():
    """Un tipo fuera de la enumeración se rechaza con mensaje explícito."""
    with pytest.raises(ErrorDominio) as error:
        ObjetoSecurable(identificador="demo", tipo=" impresora")

    mensaje = str(error.value)
    # El mensaje debe indicar el tipo recibido y la lista de tipos soportados.
    assert "impresora" in mensaje
    assert "catalogo" in mensaje
    assert "sql_warehouse" in mensaje


def TestIdentificadorVacioSeRechaza():
    """Un objeto securable sin identificador se rechaza con error explícito."""
    with pytest.raises(ErrorDominio, match="identificador"):
        ObjetoSecurable(identificador="  ", tipo=TipoObjeto.CATALOGO)


def TestNormalizacionDeReferenciasAlMismoCatalogo():
    """Dos referencias con distinta escritura resuelven al mismo objeto (spec)."""
    referencia_mayusculas = ObjetoSecurable(
        identificador="Control", tipo=TipoObjeto.CATALOGO
    )
    referencia_minusculas = ObjetoSecurable(
        identificador="control", tipo=TipoObjeto.CATALOGO
    )
    # Mismo objeto: igualdad estructural y mismo identificador normalizado.
    assert referencia_mayusculas == referencia_minusculas
    assert (
        referencia_mayusculas.identificador
        == referencia_minusculas.identificador
    )


def TestNormalizacionRecortaEspaciosDelIdentificador():
    """El identificador se recorta (sin espacios en los extremos)."""
    objeto = ObjetoSecurable(
        identificador="  control.produccion  ", tipo=TipoObjeto.CATALOGO
    )
    assert objeto.identificador == "control.produccion"


def TestIdentificadorDelPlanoDeControlConservaMayusculas():
    """Los identificadores del plano de control sí distinguen mayúsculas.

    Los nombres de Unity Catalog no distinguen mayúsculas/minúsculas, pero los
    identificadores del plano de control (por ejemplo, ids de clusters o
    warehouses) sí, por lo que la normalización se declara por plano.
    """
    objeto = ObjetoSecurable(
        identificador="AbC123", tipo=TipoObjeto.COMPUTO_CLASICO
    )
    assert objeto.identificador == "AbC123"
