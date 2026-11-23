"""Excepciones propias del módulo de configuración (capability `app-configuration`).

El proyecto controla todo error con try/except y mensajes explícitos en
español (README.md - Estándar de desarrollo). La configuración es el primer
punto de fallo de la aplicación: si el archivo de propiedades falta, está
corrupto o le falta un atributo obligatorio, la aplicación no puede continuar
y debe reportarlo de forma explícita (fail-fast, ver design.md D2), nunca con
un error críptico en medio de una operación de grants.

Jerarquía:

- `ErrorConfiguracion`: error genérico de la configuración.
- `ErrorArchivoPropiedadesInexistente`: el archivo de propiedades no existe en
  la ruta esperada.
- `ErrorArchivoPropiedadesInvalido`: el archivo existe pero no contiene un
  objeto JSON válido.
- `ErrorAtributoConfiguracionAusente`: un atributo obligatorio (o solicitado)
  no está definido en el archivo de propiedades.
"""


class ErrorConfiguracion(Exception):
    """Error genérico de la carga o el acceso a la configuración.

    Attributes:
        mensaje (str): descripción explícita del error, en español.
    """

    def __init__(self, mensaje):
        """Inicializa el error con su mensaje explícito.

        Args:
            mensaje (str): descripción del error para el usuario o la
                bitácora de errores.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje

    def __str__(self):
        """Representación en texto del error (su mensaje explícito).

        Returns:
            str: el mensaje del error.
        """
        return self.mensaje


class ErrorArchivoPropiedadesInexistente(ErrorConfiguracion):
    """El archivo de propiedades de la aplicación no existe.

    Se lanza cuando la ruta esperada (`config/app_properties.json`, o la ruta
    explícitamente indicada) no apunta a un archivo. El mensaje siempre incluye
    la ruta esperada para que el operador pueda crearla o corregirla.
    """


class ErrorArchivoPropiedadesInvalido(ErrorConfiguracion):
    """El archivo de propiedades no contiene un objeto JSON válido.

    Se lanza tanto cuando el contenido no es JSON parseable como cuando el
    JSON es válido pero su raíz no es un objeto de pares atributo-valor.
    """


class ErrorAtributoConfiguracionAusente(ErrorConfiguracion):
    """Un atributo de configuración obligatorio o solicitado no está definido.

    Se lanza al cargar la configuración cuando falta alguno de los atributos
    obligatorios declarados, y al consultar por nombre un atributo que el
    archivo no define. El mensaje siempre indica el nombre del atributo y la
    ruta del archivo consultado.
    """
