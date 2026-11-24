"""Excepciones de la resolución de privilegios efectivos.

Derivan de `ErrorDominio`, como las de la matriz y de los canales, para que
el pipeline pueda capturar cualquier fallo del dominio de forma uniforme.
La distinción importa porque el split reporta estados distintos según la
causa (spec `caller-privilege-resolution`):

- `ErrorIdentidadNoResuelta`: no hay llamante de quién resolver privilegios.
- `ErrorObjetivoInaccesible`: el canal no pudo leer los otorgamientos (objeto
  inexistente, fallo de transporte, respuesta inválida, plano sin canal).
  Los ítems afectados se clasifican como `fallido`, NO como
  `privilegios_insuficientes`.
"""

from control_accesos.dominio.errores import ErrorDominio


class ErrorResolucionPrivilegios(ErrorDominio):
    """Error base de la resolución de privilegios efectivos del llamante."""


class ErrorIdentidadNoResuelta(ErrorResolucionPrivilegios):
    """No se dispone de la identidad del llamante para resolver privilegios.

    Es el caso de un contexto on-behalf-of ausente o de un fallo de
    autenticación ya reportado por `caller-identity`: sin a quién mirar, no
    puede afirmarse ningún privilegio.
    """


class ErrorObjetivoInaccesible(ErrorResolucionPrivilegios):
    """Los otorgamientos del objeto no pudieron consultarse.

    Cubre objeto inexistente, fallo de transporte o respuesta inválida del
    sistema externo, y plano sin canal configurado. Se informa del objeto
    involucrado para que el reporte lo muestre.

    Attributes:
        objeto (object | None): objeto securable que no pudo consultarse.
    """

    def __init__(self, mensaje, objeto=None):
        """Inicializa el error con su mensaje y el objeto implicado.

        Args:
            mensaje (str): descripción explícita del fallo, en español.
            objeto (ObjetoSecurable | None): objeto cuya consulta falló.
        """
        super().__init__(mensaje)
        self.objeto = objeto
