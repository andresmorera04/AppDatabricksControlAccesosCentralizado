"""Pruebas unitarias del enrutador de canales por plano.

El enrutador (`control_accesos/pipeline/enrutador.py`) es el único criterio
de selección `Plano -> canal`, compartido por la ejecución, la verificación y
la resolución de privilegios efectivos del llamante (change
`auth-caller-obo`). Estas pruebas cubren:

- `CanalParaItem`: el ítem del plano de datos va al canal de datos y el del
  plano de control al canal de control (spec `grant-pipeline`).
- `CanalParaObjeto`: el mismo criterio aplicado a un objeto sin ítem, que es
  lo que necesita el resolutor de privilegios antes de clasificar nada.
- Rechazo de canales que no implementan el contrato `Canal`.
- Rechazo controlado de un plano sin canal configurado.
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import Plano, TipoObjeto, TipoPrincipal
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.pipeline.enrutador import EnrutadorCanales


def CrearEnrutador():
    """Construye el enrutador con los canales simulados de cada plano.

    Returns:
        EnrutadorCanales: enrutador listo para enrutar.
    """
    return EnrutadorCanales(
        canal_datos=CanalDatosSimulado(), canal_control=CanalControlSimulado()
    )


def CrearItem(tipo_objeto, identificador="x"):
    """Construye un ítem cuyo plano depende del tipo de objeto recibido.

    Args:
        tipo_objeto (TipoObjeto): tipo del objeto del ítem.
        identificador (str): identificación del objeto.

    Returns:
        ItemGrant: ítem para enrutar.
    """
    return ItemGrant(
        principal=Principal(identificador="principal_demo", tipo=TipoPrincipal.USUARIO),
        privilegio="SELECT",
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo_objeto),
    )


def TestItemDelPlanoDeDatosUsaCanalDeDatos():
    """Un ítem de Unity Catalog se enruta al canal SQL."""
    enrutador = CrearEnrutador()
    canal_esperado = enrutador._canales_por_plano[Plano.DATOS]

    assert enrutador.CanalParaItem(CrearItem(TipoObjeto.TABLA_DELTA)) is canal_esperado


def TestItemDelPlanoDeControlUsaCanalDeControl():
    """Un ítem del workspace se enruta al canal SDK/REST."""
    enrutador = CrearEnrutador()
    canal_esperado = enrutador._canales_por_plano[Plano.CONTROL]

    assert (
        enrutador.CanalParaItem(CrearItem(TipoObjeto.SQL_WAREHOUSE))
        is canal_esperado
    )


def TestCanalParaObjetoCoincideConCanalParaItem():
    """El criterio por objeto es idéntico al por ítem: no hay bifurcación.

    Este es el requisito que añade el change `auth-caller-obo`: el resolutor
    consulta otorgamientos sobre el objeto antes de que exista un resultado
    de clasificación, y debe usar exactamente el mismo canal que usará
    después la ejecución.
    """
    enrutador = CrearEnrutador()

    for tipo_objeto in (TipoObjeto.CATALOGO, TipoObjeto.COMPUTO_SERVERLESS):
        item = CrearItem(tipo_objeto, "mismo_objeto")

        assert enrutador.CanalParaObjeto(item.objeto) is enrutador.CanalParaItem(item), (
            "CanalParaObjeto y CanalParaItem deben devolver el mismo canal"
        )


def TestCanalParaObjetoRechazaEntradaSinPlano():
    """Un objeto sin plano (no del dominio) se rechaza de forma controlada."""
    enrutador = CrearEnrutador()

    class CosaSinPlano:
        """Doble sin atributo `plano`, para verificar el rechazo explícito."""

    with pytest.raises(ErrorDominio):
        enrutador.CanalParaObjeto(CosaSinPlano())


def TestCanalParaObjetoFallaSinCanalParaElPlano():
    """Si el mapa no tiene canal para el plano, el fallo es explícito."""

    class EnrutadorSinCanalDeControl:
        """Reproduce el mapa de un plano sin canal configurado."""

        _canales_por_plano = {Plano.DATOS: CanalDatosSimulado()}

        CanalParaObjeto = EnrutadorCanales.CanalParaObjeto

    enrutador = EnrutadorSinCanalDeControl()
    objeto_control = ObjetoSecurable(
        identificador="wh1", tipo=TipoObjeto.SQL_WAREHOUSE
    )

    with pytest.raises(ErrorDominio) as error:
        enrutador.CanalParaObjeto(objeto_control)

    assert "no tiene canal de ejecución configurado" in str(error.value)


def TestCanalInvalidoSeRechazaAlConstruir():
    """Un objeto que no implementa `Canal` se rechaza al construir el enrutador."""
    with pytest.raises(ErrorDominio):
        EnrutadorCanales(canal_datos=object(), canal_control=CanalControlSimulado())

    with pytest.raises(ErrorDominio):
        EnrutadorCanales(canal_datos=CanalDatosSimulado(), canal_control=None)
