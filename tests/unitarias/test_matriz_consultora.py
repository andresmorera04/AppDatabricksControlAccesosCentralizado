"""Pruebas unitarias de la clase consultora de la matriz de privilegios.

Cubren los requirements "Validación de compatibilidad privilegio-objeto",
"Mensajes de error precisos", "Filtrado de opciones para la UI" y
"Declarativa y extensible sin modificar el comportamiento" del spec
`privilege-matrix`.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.matriz.errores import ErrorCombinacionInvalida
from control_accesos.matriz.matriz_privilegios import MATRIZ_PRIVILEGIOS


def TestConsultaPrivilegiosDeUnTipo():
    """La consulta por tipo devuelve los privilegios declarados en la matriz."""
    consultora = ConsultoraMatrizPrivilegios()
    privilegios = consultora.ObtenerPrivilegios(TipoObjeto.CATALOGO)
    assert privilegios == MATRIZ_PRIVILEGIOS[TipoObjeto.CATALOGO]


def TestConsultaDeTipoSinDeclaracionNoProvocaError():
    """Un tipo sin entrada en la matriz responde vacío, sin error del sistema.

    Escenario del spec: la consultora no lanza KeyError cuando la matriz no
    declara el tipo (caso de extensión o de matriz parcial inyectada).
    """
    # Matriz parcial inyectada: falta la entrada de COMPUTO_SERVERLESS.
    matriz_parcial = {
        tipo: privilegios
        for tipo, privilegios in MATRIZ_PRIVILEGIOS.items()
        if tipo is not TipoObjeto.COMPUTO_SERVERLESS
    }
    consultora = ConsultoraMatrizPrivilegios(matriz=matriz_parcial)

    privilegios = consultora.ObtenerPrivilegios(TipoObjeto.COMPUTO_SERVERLESS)
    assert privilegios == frozenset()


def TestCombinacionValida():
    """Escenario del spec: SELECT contra tabla_delta es una combinación válida."""
    consultora = ConsultoraMatrizPrivilegios()
    assert consultora.EsCombinacionValida("SELECT", TipoObjeto.TABLA_DELTA)


def TestCombinacionInvalida():
    """Escenario del spec: CAN_USE contra catalogo es una combinación inválida."""
    consultora = ConsultoraMatrizPrivilegios()
    assert not consultora.EsCombinacionValida("CAN_USE", TipoObjeto.CATALOGO)


def TestPrivilegioSeNormalizaAntesDeValidar():
    """Un privilegio en minúsculas o con espacios se valida en su forma canónica."""
    consultora = ConsultoraMatrizPrivilegios()
    assert consultora.EsCombinacionValida(" select ", TipoObjeto.TABLA_DELTA)
    assert consultora.EsCombinacionValida("can_use", TipoObjeto.SQL_WAREHOUSE)


def TestValidarNoLanzaErrorConCombinacionValida():
    """Validar una combinación válida no lanza excepción."""
    consultora = ConsultoraMatrizPrivilegios()
    consultora.ValidarCombinacion("USE CATALOG", TipoObjeto.CATALOGO)


def TestValidarLanzaErrorConMensajePreciso():
    """El error de combinación inválida menciona privilegio, tipo y alternativas.

    Escenario del spec "Mensaje con alternativas": el mensaje identifica el
    privilegio solicitado, el tipo de objeto y lista los privilegios válidos.
    """
    consultora = ConsultoraMatrizPrivilegios()
    with pytest.raises(ErrorCombinacionInvalida) as error:
        consultora.ValidarCombinacion("CAN_USE", TipoObjeto.CATALOGO)

    mensaje = str(error.value)
    assert "CAN_USE" in mensaje
    assert TipoObjeto.CATALOGO.value in mensaje
    # Al menos una alternativa válida para catálogos debe aparecer listada.
    assert "USE CATALOG" in mensaje
    assert "SELECT" in mensaje


def TestErrorDeCombinacionInvalidaEsErrorDeDominio():
    """El error de la matriz es un error de dominio (capturable como ErrorDominio)."""
    assert issubclass(ErrorCombinacionInvalida, ErrorDominio)


def TestListarOpcionesParaUiDevuelveSoloLosPrivilegiosDelTipo():
    """Escenario del spec: las opciones para la UI son solo las del tipo pedido."""
    consultora = ConsultoraMatrizPrivilegios()
    opciones = consultora.ListarOpcionesParaUi(TipoObjeto.VOLUMEN)

    assert set(opciones) == MATRIZ_PRIVILEGIOS[TipoObjeto.VOLUMEN]
    # No debe filtrarse ningún privilegio de otros tipos.
    assert "SELECT" not in opciones
    assert "CAN_USE" not in opciones


def TestListarOpcionesParaUiDevuelveListaOrdenada():
    """Las opciones para la UI vienen ordenadas, para una presentación estable."""
    consultora = ConsultoraMatrizPrivilegios()
    opciones = consultora.ListarOpcionesParaUi(TipoObjeto.TABLA_DELTA)
    assert isinstance(opciones, list)
    assert opciones == sorted(opciones)


def TestListarOpcionesParaUiDeTipoSinDeclaracion():
    """Un tipo sin declaración devuelve una lista vacía de opciones (sin error)."""
    consultora = ConsultoraMatrizPrivilegios(matriz={})
    assert consultora.ListarOpcionesParaUi(TipoObjeto.CATALOGO) == []


def TestMatrizInyectadaNoSeModifica():
    """La consultora no altera la matriz que recibe (comportamiento extensible)."""
    consultora = ConsultoraMatrizPrivilegios()
    consultora.ObtenerPrivilegios(TipoObjeto.CATALOGO)
    consultora.ListarOpcionesParaUi(TipoObjeto.VOLUMEN)
    # La matriz declarada conserva exactamente sus 15 entradas originales.
    assert len(MATRIZ_PRIVILEGIOS) == 15
    assert MATRIZ_PRIVILEGIOS[TipoObjeto.CATALOGO] == frozenset(
        MATRIZ_PRIVILEGIOS[TipoObjeto.CATALOGO]
    )


def TestPrivilegioVacioSeRechaza():
    """Un privilegio vacío no es una combinación válida para ningún tipo."""
    consultora = ConsultoraMatrizPrivilegios()
    assert not consultora.EsCombinacionValida("  ", TipoObjeto.CATALOGO)
