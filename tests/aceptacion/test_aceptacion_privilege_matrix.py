"""Pruebas de aceptación del capability `privilege-matrix`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/specs/privilege-matrix/spec.md`:

- Cobertura de tipos de objeto soportados:
  - Consulta de privilegios de un tipo de datos
    -> TestEscenarioConsultaDePrivilegiosDeUnTipoDeDatos
  - Consulta de privilegios de un tipo de control
    -> TestEscenarioConsultaDePrivilegiosDeUnTipoDeControl
  - Consulta de un tipo de objeto inexistente en la matriz
    -> TestEscenarioConsultaDeUnTipoDeObjetoInexistenteEnLaMatriz
- Validación de compatibilidad privilegio-objeto:
  - Combinación válida -> TestEscenarioCombinacionValida
  - Combinación inválida -> TestEscenarioCombinacionInvalida
- Mensajes de error precisos:
  - Mensaje con alternativas -> TestEscenarioMensajeConAlternativas
- Filtrado de opciones para la UI:
  - Obtención de opciones para un tipo
    -> TestEscenarioObtencionDeOpcionesParaUnTipo
- Declarativa y extensible sin modificar el comportamiento:
  - Extensión con un nuevo tipo -> TestEscenarioExtensionConUnNuevoTipo
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.matriz.errores import ErrorCombinacionInvalida
from control_accesos.matriz.matriz_privilegios import MATRIZ_PRIVILEGIOS


def TestEscenarioConsultaDePrivilegiosDeUnTipoDeDatos():
    """Escenario: Consulta de privilegios de un tipo de datos.

    WHEN se consulta la matriz por el tipo `catalogo`
    THEN la matriz devuelve el conjunto de privilegios válidos para catálogos
         (incluyendo al menos `SELECT` y `USE CATALOG`).
    """
    consultora = ConsultoraMatrizPrivilegios()

    privilegios = consultora.ObtenerPrivilegios(TipoObjeto.CATALOGO)

    assert "SELECT" in privilegios
    assert "USE CATALOG" in privilegios


def TestEscenarioConsultaDePrivilegiosDeUnTipoDeControl():
    """Escenario: Consulta de privilegios de un tipo de control.

    WHEN se consulta la matriz por el tipo `sql_warehouse`
    THEN la matriz devuelve el conjunto de privilegios válidos para SQL
         warehouses (incluyendo al menos `CAN_USE`).
    """
    consultora = ConsultoraMatrizPrivilegios()

    privilegios = consultora.ObtenerPrivilegios(TipoObjeto.SQL_WAREHOUSE)

    assert "CAN_USE" in privilegios


def TestEscenarioConsultaDeUnTipoDeObjetoInexistenteEnLaMatriz():
    """Escenario: Consulta de un tipo de objeto inexistente en la matriz.

    WHEN se consulta la matriz por un tipo de objeto que no está declarado
    THEN la matriz responde que el tipo no tiene privilegios declarados, sin
         causar un error del sistema.
    """
    # Matriz parcial inyectada: el tipo TABLA_DELTA no está declarado.
    matriz_parcial = {
        tipo: privilegios
        for tipo, privilegios in MATRIZ_PRIVILEGIOS.items()
        if tipo is not TipoObjeto.TABLA_DELTA
    }
    consultora = ConsultoraMatrizPrivilegios(matriz=matriz_parcial)

    # Sin excepción del sistema: conjunto vacío y opciones vacías.
    assert consultora.ObtenerPrivilegios(TipoObjeto.TABLA_DELTA) == frozenset()
    assert consultora.ListarOpcionesParaUi(TipoObjeto.TABLA_DELTA) == []
    assert not consultora.EsCombinacionValida(
        "SELECT", TipoObjeto.TABLA_DELTA
    )


def TestEscenarioCombinacionValida():
    """Escenario: Combinación válida.

    WHEN se valida el privilegio `SELECT` contra el tipo `tabla_delta`
    THEN la matriz responde que la combinación es válida.
    """
    consultora = ConsultoraMatrizPrivilegios()

    assert consultora.EsCombinacionValida("SELECT", TipoObjeto.TABLA_DELTA)
    # Validar no lanza ninguna excepción.
    consultora.ValidarCombinacion("SELECT", TipoObjeto.TABLA_DELTA)


def TestEscenarioCombinacionInvalida():
    """Escenario: Combinación inválida.

    WHEN se valida el privilegio `CAN_USE` contra el tipo `catalogo`
    THEN la matriz responde que la combinación es inválida.
    """
    consultora = ConsultoraMatrizPrivilegios()

    assert not consultora.EsCombinacionValida("CAN_USE", TipoObjeto.CATALOGO)
    with pytest.raises(ErrorCombinacionInvalida):
        consultora.ValidarCombinacion("CAN_USE", TipoObjeto.CATALOGO)


def TestEscenarioMensajeConAlternativas():
    """Escenario: Mensaje con alternativas.

    WHEN se valida el privilegio `CAN_USE` contra el tipo `catalogo` y la
         combinación es inválida
    THEN el mensaje de error menciona el privilegio `CAN_USE`, el tipo
         `catalogo` y lista los privilegios válidos para catálogos.
    """
    consultora = ConsultoraMatrizPrivilegios()

    with pytest.raises(ErrorCombinacionInvalida) as error:
        consultora.ValidarCombinacion("CAN_USE", TipoObjeto.CATALOGO)

    mensaje = str(error.value)
    assert "CAN_USE" in mensaje
    assert TipoObjeto.CATALOGO.value in mensaje
    for privilegio_valido in MATRIZ_PRIVILEGIOS[TipoObjeto.CATALOGO]:
        assert privilegio_valido in mensaje


def TestEscenarioObtencionDeOpcionesParaUnTipo():
    """Escenario: Obtención de opciones para un tipo.

    WHEN se solicita la lista de privilegios seleccionables para el tipo
         `volumen`
    THEN la matriz devuelve exactamente los privilegios válidos para volúmenes,
         sin privilegios de otros tipos.
    """
    consultora = ConsultoraMatrizPrivilegios()

    opciones = consultora.ListarOpcionesParaUi(TipoObjeto.VOLUMEN)

    assert set(opciones) == MATRIZ_PRIVILEGIOS[TipoObjeto.VOLUMEN]
    # Ningún privilegio ajeno al tipo se cuela en las opciones.
    assert "SELECT" not in opciones
    assert "CAN_USE" not in opciones


def TestEscenarioExtensionConUnNuevoTipo():
    """Escenario: Extensión con un nuevo tipo.

    WHEN se agrega una nueva entrada tipo de objeto -> privilegios a la
         declaración de la matriz
    THEN las consultas y validaciones existentes siguen comportándose igual y
         el nuevo tipo responde a consultas y validaciones sin cambios
         adicionales en la lógica.
    """
    # Matriz parcial sin TABLA_DELTA: la validación existente funciona igual
    # para los demás tipos...
    matriz_parcial = {
        tipo: privilegios
        for tipo, privilegios in MATRIZ_PRIVILEGIOS.items()
        if tipo is not TipoObjeto.TABLA_DELTA
    }
    consultora = ConsultoraMatrizPrivilegios(matriz=matriz_parcial)
    assert consultora.EsCombinacionValida(
        "USE CATALOG", TipoObjeto.CATALOGO
    )
    assert not consultora.EsCombinacionValida(
        "SELECT", TipoObjeto.TABLA_DELTA
    )

    # ...y al agregar la nueva entrada (dato, no lógica), la misma consultora
    # responde a consultas y validaciones del tipo agregado sin ningún cambio
    # adicional en el código.
    matriz_ampliada = dict(matriz_parcial)
    matriz_ampliada[TipoObjeto.TABLA_DELTA] = frozenset({"SELECT", "MODIFY"})

    consultora_ampliada = ConsultoraMatrizPrivilegios(matriz=matriz_ampliada)
    assert consultora_ampliada.EsCombinacionValida(
        "SELECT", TipoObjeto.TABLA_DELTA
    )
    assert consultora_ampliada.ListarOpcionesParaUi(
        TipoObjeto.TABLA_DELTA
    ) == ["MODIFY", "SELECT"]
    # El comportamiento de los tipos preexistentes no cambió.
    assert consultora_ampliada.EsCombinacionValida(
        "USE CATALOG", TipoObjeto.CATALOGO
    )
