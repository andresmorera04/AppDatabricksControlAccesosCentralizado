"""Redacción de secretos y manejo controlado de errores para la UI (design.md D11).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 5.3.

Componente que purga de un texto todo material sensible antes de mostrarlo o
registrarlo: tokens (prefijo `dapi...`), headers `Authorization` y
`x-forwarded-access-token`, `DATABRICKS_CLIENT_SECRET`/`client_secret`, y
cualquier valor con prefijo `CONTROL_ACCESOS_`. No interpreta el contenido:
solo sustituye coincidencias por marcas, de modo que el mensaje se pueda
mostrar en la UI sin filtrar secretos ni stack traces.

El manejo controlado de errores (`MensajeDeErrorControlado`) devuelve SOLO el
mensaje redactado de la excepción (sin `Traceback` ni rutas), listo para la
interfaz o la bitácora.
"""

import re

# Identificador del módulo para trazas (convención del proyecto).
MODULO_REDACCION = "ui.redaccion"

# Marcas que sustituyen al material sensible en el texto redactado.
MARCA_TOKEN = "<token_redactado>"
MARCA_AUTHORIZATION = "<authorization_redactado>"
MARCA_SECRETO = "<secreto_redactado>"

# Patrones de redacción, en el orden que se aplican (los específicos de
# clave-valor primero; el patrón de token desnudo al final como cierre).
_PATRONES_CLAVE_VALOR = (
    re.compile(
        r"x-forwarded-access-token\s*[:=]\s*\S+", re.IGNORECASE
    ),
    re.compile(
        r"client_secret\s*[:=]\s*\S+", re.IGNORECASE
    ),
    re.compile(
        r"DATABRICKS_CLIENT_SECRET\s*[:=]\s*\S+", re.IGNORECASE
    ),
    re.compile(
        r"\bCONTROL_ACCESOS_[A-Z0-9_]+\s*[:=]\s*\S+", re.IGNORECASE
    ),
)

_PATRON_AUTHORIZATION = re.compile(
    r"Authorization\s*[:=]\s*\S+", re.IGNORECASE
)
_PATRON_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_PATRON_TOKEN = re.compile(r"\bdapi[a-zA-Z0-9]{8,}")


class RedactorSecretos:
    """Purga secretos y datos sensibles de un texto para UI y bitácora."""

    def Redactar(self, texto):
        """Sustituye todo material sensible del texto por marcas.

        Args:
            texto (str): texto a redactar (mensaje, detalle o traza).

        Returns:
            str: texto con tokens, headers de autorización y secretos
                sustituidos por marcas. El contenido inocuo queda intacto.
        """
        if not texto:
            return texto

        redactado = texto
        for patron in _PATRONES_CLAVE_VALOR:
            redactado = patron.sub(MARCA_SECRETO, redactado)
        redactado = _PATRON_AUTHORIZATION.sub(
            f"Authorization: {MARCA_AUTHORIZATION}", redactado
        )
        redactado = _PATRON_BEARER.sub(f"Bearer {MARCA_TOKEN}", redactado)
        redactado = _PATRON_TOKEN.sub(MARCA_TOKEN, redactado)
        return redactado

    def MensajeDeErrorControlado(self, excepcion):
        """Devuelve solo el mensaje redactado de una excepción (sin traza).

        Args:
            excepcion (BaseException): excepción capturada por try/except.

        Returns:
            str: mensaje redactado, sin `Traceback` ni rutas, apto para la
                interfaz o la bitácora (design.md D11).
        """
        return self.Redactar(str(excepcion))
