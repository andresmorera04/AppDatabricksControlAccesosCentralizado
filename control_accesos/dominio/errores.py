"""Excepciones propias del modelo de dominio (capability `grant-domain-model`).

El proyecto controla todo error con try/except y mensajes explícitos en
español (README.md - Estándar de desarrollo). Estas excepciones son la base de
los errores de dominio; las excepciones de canales (por ejemplo,
`ErrorPrivilegiosInsuficientes`) derivan de ellas en su propio subpaquete.
"""


class ErrorDominio(Exception):
    """Error de validación o de consistencia del modelo de dominio.

    Se lanza cuando una entidad del dominio recibe datos inválidos (tipo fuera
    de la enumeración, identificador vacío, cardinalidad no soportada, etc.).
    El mensaje siempre indica qué se recibió y qué se esperaba, en español.

    Attributes:
        mensaje (str): descripción explícita del error, en español.
    """

    def __init__(self, mensaje):
        """Inicializa el error con su mensaje explícito.

        Args:
            mensaje (str): descripción del error para el usuario o la bitácora.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje

    def __str__(self):
        """Representación en texto del error (su mensaje explícito)."""
        return self.mensaje
