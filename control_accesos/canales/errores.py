"""Excepciones de los canales de ejecución (capability `channel-adapters`).

Los canales traducen las respuestas del sistema externo a estas excepciones,
que el contrato convierte en resultados por ítem (nunca se propagan al
llamador). La jerarquía permite distinguir el error de privilegios
insuficientes de cualquier otro fallo de ejecución (spec `channel-adapters` -
"Errores de privilegios insuficientes identificables").
"""


class ErrorCanal(Exception):
    """Error de ejecución de un canal (SQL, SDK o REST).

    Cubre cualquier fallo del sistema externo que no sea falta de privilegios:
    objeto inexistente, error de red, sintaxis rechazada, etc.

    Attributes:
        mensaje (str): descripción explícita del error, en español o el texto
            reportado por el sistema externo.
    """

    def __init__(self, mensaje):
        """Inicializa el error con su mensaje.

        Args:
            mensaje (str): descripción del fallo ocurrido en el canal.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje

    def __str__(self):
        """Representación en texto del error (su mensaje)."""
        return self.mensaje


class ErrorPrivilegiosInsuficientes(ErrorCanal):
    """El ejecutor no tiene privilegios para otorgar o revocar el ítem.

    Corresponde a la respuesta de permiso denegado del sistema externo (por
    ejemplo, `PERMISSION_DENIED` en Unity Catalog o el 403 de la Permissions
    API). El pipeline la reporta como estado `privilegios_insuficientes`,
    distinguible de un fallo genérico.
    """
