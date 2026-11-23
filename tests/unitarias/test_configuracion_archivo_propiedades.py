"""Prueba unitaria del archivo de propiedades de la aplicación.

Change C2 (`persistencia-bitacora`), capability `app-configuration`.

El estándar de desarrollo del proyecto impone la regla estricta "código NO
hardcodeado": todo valor configurable vive en un único archivo de propiedades
(`config/app_properties.json`). Esta prueba fija el contrato de ese archivo tal
como lo entrega este change:

- el archivo existe en la ruta esperada (derivada de la raíz del proyecto, sin
  escribir la ruta absoluta a mano);
- su contenido es JSON válido (un objeto plano de pares clave-valor);
- define el atributo obligatorio `catalogo` con el valor por defecto
  distribuido (`control`), que es el catálogo de Unity Catalog donde la
  aplicación crea su esquema dedicado.

Ver openspec/changes/persistencia-bitacora/specs/app-configuration/spec.md
(requisitos "Carga validada del archivo de propiedades" y "Atributo catalogo").
"""

import json
from pathlib import Path

# Raíz del proyecto, derivada de la ubicación de este archivo de pruebas
# (tests/unitarias/ -> raíz). Se calcula, no se escribe a mano, para cumplir la
# regla de no hardcodear rutas.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Ruta relativa del archivo de propiedades respecto de la raíz del proyecto.
DIRECTORIO_CONFIGURACION = "config"
NOMBRE_ARCHIVO_PROPIEDADES = "app_properties.json"
RUTA_ARCHIVO_PROPIEDADES = (
    RAIZ_PROYECTO / DIRECTORIO_CONFIGURACION / NOMBRE_ARCHIVO_PROPIEDADES
)

# Atributo obligatorio de la configuración y valor por defecto con el que se
# distribuye el archivo en este change (ver proposal.md y design.md D2).
NOMBRE_ATRIBUTO_CATALOGO = "catalogo"
VALOR_CATALOGO_POR_DEFECTO = "control"


def TestArchivoPropiedadesExiste():
    """El archivo de propiedades debe existir en la ruta esperada del proyecto."""
    assert RUTA_ARCHIVO_PROPIEDADES.is_file(), (
        f"El archivo de propiedades de la aplicación no existe en la ruta "
        f"esperada: {RUTA_ARCHIVO_PROPIEDADES}. La regla 'código NO "
        f"hardcodeado' exige que toda configuración viva en ese archivo."
    )


def TestArchivoPropiedadesEsJsonValido():
    """El contenido del archivo de propiedades debe ser un objeto JSON válido."""
    contenido = RUTA_ARCHIVO_PROPIEDADES.read_text(encoding="utf-8")

    # Debe parsear como JSON sin lanzar excepción...
    propiedades = json.loads(contenido)

    # ...y el resultado debe ser un objeto (diccionario), no una lista ni un
    # escalar, porque la configuración son pares atributo-valor.
    assert isinstance(propiedades, dict), (
        "El archivo de propiedades debe contener un objeto JSON "
        f"(pares atributo-valor); se encontró: {type(propiedades).__name__}"
    )


def TestCatalogoDefinidoConValorPorDefecto():
    """El atributo `catalogo` debe estar definido con el valor `control`."""
    contenido = RUTA_ARCHIVO_PROPIEDADES.read_text(encoding="utf-8")
    propiedades = json.loads(contenido)

    assert NOMBRE_ATRIBUTO_CATALOGO in propiedades, (
        f"El atributo obligatorio '{NOMBRE_ATRIBUTO_CATALOGO}' no está "
        f"definido en {RUTA_ARCHIVO_PROPIEDADES}"
    )
    assert propiedades[NOMBRE_ATRIBUTO_CATALOGO] == VALOR_CATALOGO_POR_DEFECTO, (
        f"El atributo '{NOMBRE_ATRIBUTO_CATALOGO}' debe distribuirse con el "
        f"valor por defecto '{VALOR_CATALOGO_POR_DEFECTO}'; se encontró: "
        f"{propiedades[NOMBRE_ATRIBUTO_CATALOGO]!r}"
    )
