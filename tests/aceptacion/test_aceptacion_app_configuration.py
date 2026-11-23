"""Pruebas de aceptación del capability `app-configuration`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/changes/persistencia-bitacora/specs/app-configuration/spec.md`:

- Carga validada del archivo de propiedades:
  - Carga exitosa -> TestEscenarioCargaExitosa
  - Archivo de propiedades inexistente -> TestEscenarioArchivoDePropiedadesInexistente
  - Archivo con JSON inválido -> TestEscenarioArchivoConJsonInvalido
- Atributo catalogo:
  - Lectura del catálogo configurado -> TestEscenarioLecturaDelCatalogoConfigurado
  - Atributo catalogo ausente -> TestEscenarioAtributoCatalogoAusente
- Fuente única de configuración de solo lectura:
  - Intento de modificación en tiempo de ejecución -> TestEscenarioIntentoDeModificacionEnTiempoDeEjecucion
  - Crecimiento del archivo de propiedades -> TestEscenarioCrecimientoDelArchivoDePropiedades
"""

import json

import pytest

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.configuracion.errores import (
    ErrorArchivoPropiedadesInexistente,
    ErrorArchivoPropiedadesInvalido,
    ErrorAtributoConfiguracionAusente,
)


def EscribirArchivoPropiedades(ruta, contenido):
    """Escribe un archivo de propiedades de prueba (texto o diccionario JSON).

    Args:
        ruta (Path): destino del archivo.
        contenido (dict | str): si es diccionario se serializa como JSON; si
            es texto se escribe tal cual (para provocar JSON inválido).

    Returns:
        Path: la ruta escrita.
    """
    texto = (
        contenido if isinstance(contenido, str) else json.dumps(contenido)
    )
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def TestEscenarioCargaExitosa():
    """Escenario: Carga exitosa.

    WHEN la aplicación solicita la configuración y el archivo de propiedades
         existe y es JSON válido
    THEN la configuración queda disponible con los atributos y valores
         definidos en el archivo.
    """
    configuracion = ConfiguracionApp.Cargar()

    # El archivo distribuido del proyecto define el catálogo por defecto.
    assert configuracion.catalogo == "control"
    assert configuracion.ObtenerAtributo("catalogo") == "control"


def TestEscenarioArchivoDePropiedadesInexistente(tmp_path):
    """Escenario: Archivo de propiedades inexistente.

    WHEN la aplicación solicita la configuración y el archivo no existe
    THEN el sistema reporta un error explícito que indica la ruta esperada.
    """
    ruta_inexistente = tmp_path / "config" / "app_properties.json"

    with pytest.raises(ErrorArchivoPropiedadesInexistente) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta_inexistente)

    assert str(ruta_inexistente) in error.value.mensaje


def TestEscenarioArchivoConJsonInvalido(tmp_path):
    """Escenario: Archivo con JSON inválido.

    WHEN la aplicación solicita la configuración y el archivo no contiene
         JSON válido
    THEN el sistema reporta un error explícito que indica que el archivo no es
         JSON válido, sin usar valor alguno.
    """
    ruta = EscribirArchivoPropiedades(
        tmp_path / "app_properties.json", '{"catalogo": "control",,}'
    )

    with pytest.raises(ErrorArchivoPropiedadesInvalido) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert "JSON" in error.value.mensaje


def TestEscenarioLecturaDelCatalogoConfigurado(tmp_path):
    """Escenario: Lectura del catálogo configurado.

    WHEN un componente consulta el atributo `catalogo`
    THEN el sistema devuelve el valor definido en el archivo de propiedades.
    """
    ruta = EscribirArchivoPropiedades(
        tmp_path / "app_properties.json", {"catalogo": "ventas"}
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert configuracion.catalogo == "ventas", (
        "El catálogo leído debe ser exactamente el definido en el archivo"
    )


def TestEscenarioAtributoCatalogoAusente(tmp_path):
    """Escenario: Atributo catalogo ausente.

    WHEN el archivo de propiedades no define el atributo `catalogo`
    THEN el sistema reporta un error explícito que indica el atributo
         obligatorio faltante.
    """
    ruta = EscribirArchivoPropiedades(tmp_path / "app_properties.json", {})

    with pytest.raises(ErrorAtributoConfiguracionAusente) as error:
        ConfiguracionApp.Cargar(ruta_archivo=ruta)

    assert "catalogo" in error.value.mensaje


def TestEscenarioIntentoDeModificacionEnTiempoDeEjecucion(tmp_path):
    """Escenario: Intento de modificación en tiempo de ejecución.

    WHEN un componente intenta alterar un atributo de la configuración cargada
    THEN la configuración permanece inalterada con los valores originales.
    """
    ruta = EscribirArchivoPropiedades(
        tmp_path / "app_properties.json", {"catalogo": "ventas"}
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    with pytest.raises(AttributeError):
        configuracion.catalogo = "modificado"
    with pytest.raises(TypeError):
        configuracion.atributos["catalogo"] = "modificado"

    assert configuracion.catalogo == "ventas", (
        "Tras los intentos de modificación el valor original debe permanecer"
    )


def TestEscenarioCrecimientoDelArchivoDePropiedades(tmp_path):
    """Escenario: Crecimiento del archivo de propiedades.

    WHEN un change posterior agrega un nuevo atributo al archivo
    THEN el sistema lo expone parametrizado por el mismo mecanismo, sin
         modificar los atributos existentes.
    """
    ruta = EscribirArchivoPropiedades(
        tmp_path / "app_properties.json",
        {"catalogo": "control", "atributo_del_futuro": "valor_futuro"},
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)

    # El atributo nuevo se expone por el mismo mecanismo parametrizado...
    assert configuracion.ObtenerAtributo("atributo_del_futuro") == (
        "valor_futuro"
    )
    # ...sin modificar los existentes.
    assert configuracion.catalogo == "control"
