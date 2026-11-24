"""Cargador de la configuración de la aplicación (capability `app-configuration`).

Implementa la fuente única de configuración del proyecto, exigida por la regla
estricta "código NO hardcodeado" (README.md - Estándar de desarrollo): ningún
valor configurable se escribe en el código; todo se lee del archivo de
propiedades `config/app_properties.json`.

Contrato (ver spec `app-configuration`):

- **Carga única y validada**: el archivo se lee una sola vez al construir la
  instancia y los valores quedan en memoria (nunca se relee por acceso). Si el
  archivo no existe, no es un objeto JSON válido o le falta un atributo
  obligatorio, se lanza una excepción propia con mensaje explícito (fail-fast).
- **Acceso parametrizado y de solo lectura**: los atributos se exponen como
  propiedades sin setter y mediante `ObtenerAtributo(nombre)`, de modo que un
  atributo nuevo agregado al archivo en changes futuros se expone por el mismo
  mecanismo sin modificar este código.
- **Ruta derivada, no hardcodeada**: la ruta por defecto se construye a partir
  de la ubicación de este módulo (`__file__`), igual que hace el `conftest.py`
  de la raíz del proyecto.

Atributos actuales del archivo de propiedades:

- `catalogo`: catálogo de Unity Catalog donde la aplicación crea su esquema
  dedicado `control_acceso_app`. Valor distribuido por defecto: `control`.

Ver design.md D2 del change `persistencia-bitacora`.
"""

import json
from pathlib import Path
from types import MappingProxyType

from control_accesos.configuracion.errores import (
    ErrorArchivoPropiedadesInexistente,
    ErrorArchivoPropiedadesInvalido,
    ErrorAtributoConfiguracionAusente,
)

# Raíz del proyecto, derivada de la ubicación de este módulo
# (control_accesos/configuracion/configuracion_app.py -> raíz). Se calcula para
# no escribir rutas absolutas a mano (regla: nada hardcodeado).
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Ubicación relativa del archivo de propiedades respecto de la raíz.
DIRECTORIO_CONFIGURACION = "config"
NOMBRE_ARCHIVO_PROPIEDADES = "app_properties.json"

# Ruta por defecto del archivo de propiedades de la aplicación.
RUTA_ARCHIVO_PROPIEDADES_POR_DEFECTO = (
    RAIZ_PROYECTO / DIRECTORIO_CONFIGURACION / NOMBRE_ARCHIVO_PROPIEDADES
)

# Nombre del atributo que indica el catálogo de Unity Catalog donde vive el
# esquema dedicado de la aplicación (ver spec `app-configuration`).
ATRIBUTO_CATALOGO = "catalogo"

# Atributos obligatorios del archivo de propiedades. Se declaran como dato
# (tupla) para que un change futuro que agregue un atributo obligatorio solo
# extienda esta lista, sin tocar la lógica de validación. De momento la
# aplicación solo requiere el catálogo.
ATRIBUTOS_OBLIGATORIOS = (ATRIBUTO_CATALOGO,)


class ConfiguracionApp:
    """Configuración de la aplicación cargada desde el archivo de propiedades.

    Instancia inmutable de solo lectura: se construye con `ConfiguracionApp.Cargar()`
    (o directamente con el constructor), que lee el archivo una sola vez, valida
    su contenido y conserva los atributos en memoria.

    Attributes:
        catalogo (str): catálogo de Unity Catalog configurado (atributo
            `catalogo` del archivo de propiedades).

    Example:
        >>> configuracion = ConfiguracionApp.Cargar()
        >>> configuracion.catalogo
        'control'
        >>> configuracion.ObtenerAtributo('catalogo')
        'control'
    """

    def __init__(self, ruta_archivo=None):
        """Carga y valida la configuración desde el archivo de propiedades.

        La lectura ocurre exactamente una vez aquí; los atributos quedan en
        memoria y los accesos posteriores no vuelven a tocar el disco.

        Args:
            ruta_archivo (str | Path | None): ruta del archivo de propiedades.
                Si es `None`, se usa la ruta por defecto del proyecto
                (`config/app_properties.json`, derivada de este módulo).

        Raises:
            ErrorArchivoPropiedadesInexistente: si la ruta no apunta a un
                archivo existente.
            ErrorArchivoPropiedadesInvalido: si el archivo no contiene un
                objeto JSON válido.
            ErrorAtributoConfiguracionAusente: si falta algún atributo
                obligatorio declarado en `ATRIBUTOS_OBLIGATORIOS`.
        """
        # Se acepta str o Path y se normaliza a Path (sin hardcodear la ruta:
        # por defecto se usa la derivada de este módulo).
        ruta = (
            Path(ruta_archivo)
            if ruta_archivo is not None
            else RUTA_ARCHIVO_PROPIEDADES_POR_DEFECTO
        )

        # Atributo privado con la ruta efectiva leída, para trazabilidad de
        # errores y pruebas.
        self._ruta_archivo = ruta

        # Lectura única + validación fail-fast (design.md D2).
        self._atributos = self._LeerYValidarArchivo(ruta)

    @classmethod
    def Cargar(cls, ruta_archivo=None):
        """Fábrica explícita de la configuración (lectura única del archivo).

        Args:
            ruta_archivo (str | Path | None): ruta del archivo de propiedades;
                `None` usa la ruta por defecto del proyecto.

        Returns:
            ConfiguracionApp: instancia cargada y validada, de solo lectura.

        Raises:
            ErrorArchivoPropiedadesInexistente: si el archivo no existe.
            ErrorArchivoPropiedadesInvalido: si el JSON es inválido.
            ErrorAtributoConfiguracionAusente: si falta un atributo obligatorio.
        """
        return cls(ruta_archivo=ruta_archivo)

    @property
    def catalogo(self):
        """Catálogo de Unity Catalog configurado (atributo `catalogo`).

        Propiedad de solo lectura (sin setter): cualquier intento de asignación
        lanza `AttributeError`, garantizando que la configuración no se altera
        en tiempo de ejecución (ver spec "Fuente única de configuración de
        solo lectura").

        Returns:
            str: nombre del catálogo donde vive el esquema dedicado de la app.
        """
        return self._atributos[ATRIBUTO_CATALOGO]

    @property
    def atributos(self):
        """Vista inmutable de todos los atributos del archivo de propiedades.

        Se devuelve un `MappingProxyType`, que es de solo lectura: intentar
        asignar una clave lanza `TypeError`. Así se exponen también los
        atributos futuros del archivo sin modificar esta clase.

        Returns:
            MappingProxyType: mapa atributo -> valor, inmutable.
        """
        return MappingProxyType(self._atributos)

    @property
    def ruta_archivo(self):
        """Ruta efectiva del archivo de propiedades leído.

        Returns:
            Path: ruta absoluta del archivo cargado.
        """
        return self._ruta_archivo

    def ObtenerAtributo(self, nombre_atributo):
        """Acceso parametrizado a cualquier atributo del archivo de propiedades.

        Es el mecanismo genérico de la configuración: permite que changes
        futuros agreguen atributos al archivo y los consuman por nombre sin
        modificar esta clase (ver spec "Crecimiento del archivo de
        propiedades").

        Args:
            nombre_atributo (str): nombre del atributo a consultar.

        Returns:
            Any: valor del atributo tal como está definido en el archivo.

        Raises:
            ErrorAtributoConfiguracionAusente: si el atributo no está definido
                en el archivo de propiedades. El mensaje indica el nombre
                solicitado y la ruta del archivo.
        """
        if nombre_atributo not in self._atributos:
            raise ErrorAtributoConfiguracionAusente(
                f"El atributo '{nombre_atributo}' no está definido en el "
                f"archivo de propiedades {self._ruta_archivo}. Atributos "
                f"disponibles: {', '.join(sorted(self._atributos))}."
            )
        return self._atributos[nombre_atributo]

    @staticmethod
    def _LeerYValidarArchivo(ruta):
        """Lee el archivo de propiedades y valida su contenido (fail-fast).

        Args:
            ruta (Path): ruta del archivo de propiedades a leer.

        Returns:
            dict: copia de los atributos leídos (objeto JSON de pares
            atributo-valor).

        Raises:
            ErrorArchivoPropiedadesInexistente: si la ruta no es un archivo.
            ErrorArchivoPropiedadesInvalido: si el contenido no es JSON válido
                o su raíz no es un objeto.
            ErrorAtributoConfiguracionAusente: si falta un atributo obligatorio.
        """
        # 1) Existencia del archivo: error explícito con la ruta esperada.
        if not ruta.is_file():
            raise ErrorArchivoPropiedadesInexistente(
                f"El archivo de propiedades de la aplicación no existe en la "
                f"ruta esperada: {ruta}. La regla 'código NO hardcodeado' "
                f"exige que toda configuración viva en ese archivo "
                f"(ver README.md - Estándar de desarrollo)."
            )

        # 2) Lectura del contenido.
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except OSError as excepcion:
            # Un archivo ilegible (permisos, disco) se reporta como
            # configuración inválida, con la causa encadenada.
            raise ErrorArchivoPropiedadesInvalido(
                f"No se pudo leer el archivo de propiedades {ruta}: "
                f"{excepcion}"
            ) from excepcion

        # 3) Parseo del JSON: error explícito que indica que no es JSON válido.
        try:
            datos = json.loads(contenido)
        except json.JSONDecodeError as excepcion:
            raise ErrorArchivoPropiedadesInvalido(
                f"El archivo de propiedades {ruta} no contiene JSON válido: "
                f"{excepcion}"
            ) from excepcion

        # 4) La raíz debe ser un objeto JSON (pares atributo-valor), no una
        #    lista ni un escalar.
        if not isinstance(datos, dict):
            raise ErrorArchivoPropiedadesInvalido(
                f"El archivo de propiedades {ruta} debe contener un objeto "
                f"JSON de pares atributo-valor; se encontró: "
                f"{type(datos).__name__}."
            )

        # 5) Presencia de los atributos obligatorios declarados como dato.
        for nombre_atributo in ATRIBUTOS_OBLIGATORIOS:
            if nombre_atributo not in datos:
                raise ErrorAtributoConfiguracionAusente(
                    f"El atributo obligatorio '{nombre_atributo}' no está "
                    f"definido en el archivo de propiedades {ruta}. "
                    f"Atributos presentes: "
                    f"{', '.join(sorted(datos)) or '(ninguno)'}."
                )

        # 6) Se devuelve una copia para que la instancia sea la única dueña de
        #    sus datos (inmutabilidad efectiva desde fuera).
        return dict(datos)

    def __repr__(self):
        """Representación legible de la configuración para trazas y bitácoras.

        Returns:
            str: clase, ruta del archivo y nombres de atributos cargados.
        """
        nombres = ", ".join(sorted(self._atributos))
        return (
            f"{type(self).__name__}(ruta_archivo={self._ruta_archivo}, "
            f"atributos=[{nombres}])"
        )
