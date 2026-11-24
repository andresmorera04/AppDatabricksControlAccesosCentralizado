"""Excepciones de la autenticación on-behalf-of del llamante.

Jerarquía propia del subpaquete (misma convención que `dominio.errores`,
`canales.errores` y `configuracion.errores`): todos los fallos de
autenticación se reportan en español y con mensaje explícito, y el servicio
los captura para degradar de forma controlada (spec `caller-identity` -
"Errores de autenticación visibles y controlados"), nunca los propaga.
"""


class ErrorAutenticacionLlamante(Exception):
    """Error de la autenticación o de la resolución de identidad del llamante.

    Attributes:
        mensaje (str): descripción explícita del fallo, en español.
    """

    def __init__(self, mensaje):
        """Inicializa el error con su mensaje.

        Args:
            mensaje (str): descripción del fallo de autenticación.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje

    def __str__(self):
        """Representación en texto del error (su mensaje)."""
        return self.mensaje


class ErrorContextoLlamanteAusente(ErrorAutenticacionLlamante):
    """La invocación no trae un contexto on-behalf-of verificable.

    Es el caso de una llamada de servicio no autenticada, o de una app en la
    que la autenticación de usuario todavía no está habilitada: la identidad
    del llamante queda explícitamente sin resolver.
    """


class ErrorIdentidadLlamanteInvalida(ErrorAutenticacionLlamante):
    """El contexto recibido describe una identidad que no puede construirse.

    Cubre identificador vacío o nulo, tipo fuera de la enumeración de
    principales, App Id ausente en un service principal o App Id informado
    para un principal que no lo es.
    """
