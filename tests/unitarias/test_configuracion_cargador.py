"""Prueba unitaria de la clase cargadora de la configuración de la aplicación.

Change C2 (`persistencia-bitacora`), capability `app-configuration`.

Cubre los escenarios del spec
(`openspec/changes/persistencia-bitacora/specs/app-configuration/spec.md`):

- carga exitosa con los valores del archivo de propiedades;
- archivo inexistente rechazado con un error explícito que indica la ruta
  esperada;
- JSON inválido (y raíz JSON que no es un objeto) rechazado con error explícito;
- atributo obligatorio `catalogo` ausente rechazado con error explícito;
- intento de modificación en tiempo de ejecución que deja la configuración
  inalterada (atributos de solo lectura);
- carga única: los valores quedan en memoria y no se relee el archivo;
- crecimiento del archivo: un atributo nuevo se expone por el mismo mecanismo
  parametrizado, sin modificar código.
"""

import json
from pathlib import Path

import pytest

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.configuracion.errores import (
    ErrorAtributoConfiguracionAusente,
    ErrorArchivoPropiedadesInexistente,
    ErrorArchivoPropiedadesInvalido,
)

# Nombre del atributo obligatorio y valor con el que se distribuye el archivo
# de propiedades en este change (ver design.md D2).
NOMBRE_ATRIBUTO_CATALOGO = "catalogo"
VALOR_CATALOGO_POR_DEFECTO = "control"

# Ruta del archivo de propiedades real del proyecto, derivada de este archivo
# de pruebas (tests/unitarias/ -> raíz), sin escribirla a mano.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RUTA_ARCHIVO_REAL = RAIZ_PROYECTO / "config" / "app_properties.json"


def EscribirPropiedades(ruta, propiedades):
    """Escribe un archivo de propiedades JSON en la ruta indicada.

    Utilitario de las pruebas: serializa `propiedades` (diccionario o texto ya
    formateado) en `ruta`, creando el directorio si hiciera falta.

    Args:
        ruta (Path): destino del archivo de propiedades.
        propiedades (dict | str): contenido a escribir; si es diccionario se
            serializa como JSON, si es texto se escribe tal cual (para poder
            provocar JSON inválido a propósito).

    Returns:
        Path: la ruta escrita.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = (
        propiedades
        if isinstance(propiedades, str)
        else json.dumps(propiedades, ensure_ascii=False)
    )
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def TestCargaExitosaDesdeArchivoDePropiedades():
    """La configuración del proyecto debe cargar con el catálogo distribuido."""
    configuracion = ConfiguracionApp.Cargar()

    assert configuracion.catalogo == VALOR_CATALOGO_POR_DEFECTO, (
        "El catálogo expuesto debe ser el valor definido en "
        f"{RUTA_ARCHIVO_REAL}"
    )
    assert configuracion.ObtenerAtributo(NOMBRE_ATRIBUTO_CATALOGO) == (
        VALOR_CATALOGO_POR_DEFECTO
    ), "El acceso parametrizado debe devolver el mismo valor del archivo"


def TestArchivoInexistenteRechazadoConRutaEsperada(tmp_path):
    """Un archivo de propiedades inexistente debe rechazarse con su ruta."""
    ruta_inexistente = tmp_path / "config" / "app_properties.json"

    with pytest.raises(ErrorArchivoPropiedadesInexistente) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta_inexistente)

    assert str(ruta_inexistente) in error.value.mensaje, (
        "El error explícito debe indicar la ruta esperada del archivo faltante"
    )


def TestJsonInvalidoRechazadoConErrorExplicito(tmp_path):
    """Un archivo con JSON inválido debe rechazarse con error explícito."""
    ruta = EscribirPropiedades(
        tmp_path / "app_properties.json", '{"catalogo": "control",,}'
    )

    with pytest.raises(ErrorArchivoPropiedadesInvalido) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert "JSON" in error.value.mensaje, (
        "El error explícito debe indicar que el archivo no es JSON válido"
    )


def TestRaizJsonQueNoEsObjetoRechazada(tmp_path):
    """Un JSON válido cuya raíz no es un objeto debe rechazarse."""
    ruta = EscribirPropiedades(tmp_path / "app_properties.json", '["catalogo"]')

    with pytest.raises(ErrorArchivoPropiedadesInvalido) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert "objeto" in error.value.mensaje.lower(), (
        "El error debe indicar que se esperaba un objeto JSON de pares "
        "atributo-valor"
    )


def TestAtributoCatalogoAusenteRechazado(tmp_path):
    """Un archivo sin el atributo obligatorio `catalogo` debe rechazarse."""
    ruta = EscribirPropiedades(tmp_path / "app_properties.json", {})

    with pytest.raises(ErrorAtributoConfiguracionAusente) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert NOMBRE_ATRIBUTO_CATALOGO in error.value.mensaje, (
        "El error explícito debe indicar el atributo obligatorio faltante"
    )


def TestIntentoDeModificacionNoAlteraLaConfiguracion(tmp_path):
    """La configuración es de solo lectura durante la ejecución."""
    ruta = EscribirPropiedades(
        tmp_path / "app_properties.json", {NOMBRE_ATRIBUTO_CATALOGO: "ventas"}
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    # Asignar el atributo expuesto debe fallar (propiedad sin setter).
    with pytest.raises(AttributeError):
        configuracion.catalogo = "otro_catalogo"

    # La vista de atributos debe ser inmutable.
    with pytest.raises(TypeError):
        configuracion.atributos[NOMBRE_ATRIBUTO_CATALOGO] = "otro_catalogo"

    assert configuracion.catalogo == "ventas", (
        "Tras los intentos de modificación la configuración debe permanecer "
        "inalterada con los valores originales del archivo"
    )


def TestCargaUnicaNoReleeElArchivo(tmp_path):
    """Los valores se leen una sola vez y quedan en memoria."""
    ruta = EscribirPropiedades(
        tmp_path / "app_properties.json", {NOMBRE_ATRIBUTO_CATALOGO: "ventas"}
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    # Se modifica el archivo en disco después de cargar la configuración.
    EscribirPropiedades(
        ruta, {NOMBRE_ATRIBUTO_CATALOGO: "otro_catalogo_en_disco"}
    )

    assert configuracion.catalogo == "ventas", (
        "La configuración cargada no debe releer el archivo: el valor en "
        "memoria es el que se cargó al iniciar"
    )


def TestAccesoParametrizadoPermiteCrecerElArchivo(tmp_path):
    """Un atributo nuevo del archivo se expone sin modificar código."""
    ruta = EscribirPropiedades(
        tmp_path / "app_properties.json",
        {NOMBRE_ATRIBUTO_CATALOGO: "control", "atributo_futuro": "valor_x"},
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert configuracion.ObtenerAtributo("atributo_futuro") == "valor_x", (
        "El mecanismo parametrizado debe exponer cualquier atributo presente "
        "en el archivo de propiedades"
    )

    with pytest.raises(ErrorAtributoConfiguracionAusente) as error:
        configuracion.ObtenerAtributo("atributo_que_no_existe")

    assert "atributo_que_no_existe" in error.value.mensaje, (
        "El error debe indicar el atributo solicitado que no existe"
    )
