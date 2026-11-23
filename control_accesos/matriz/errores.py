"""Excepciones de la matriz de privilegios (capability `privilege-matrix`).

Derivan de `ErrorDominio` para que el pipeline y las fases superiores puedan
capturar cualquier error del dominio de forma uniforme, y a la vez distinguir
el error específico de compatibilidad privilegio-objeto.
"""

from control_accesos.dominio.errores import ErrorDominio


class ErrorCombinacionInvalida(ErrorDominio):
    """Combinación privilegio x tipo de objeto no válida según la matriz.

    Attributes:
        privilegio (str): privilegio solicitado, en su forma canónica.
        tipo_objeto (TipoObjeto): tipo de objeto sobre el que se solicitó.
        privilegios_validos (frozenset[str]): alternativas válidas para ese
            tipo de objeto, usadas para construir el mensaje preciso.
    """

    def __init__(self, mensaje, privilegio, tipo_objeto, privilegios_validos):
        """Inicializa el error con su mensaje y el contexto de la combinación.

        Args:
            mensaje (str): mensaje explícito en español con las alternativas.
            privilegio (str): privilegio solicitado (forma canónica).
            tipo_objeto (TipoObjeto): tipo de objeto de la solicitud.
            privilegios_validos (frozenset[str]): privilegios válidos del tipo.
        """
        super().__init__(mensaje)
        self.privilegio = privilegio
        self.tipo_objeto = tipo_objeto
        self.privilegios_validos = privilegios_validos
