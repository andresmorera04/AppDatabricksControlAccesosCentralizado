"""Clase consultora de la matriz de privilegios (capability `privilege-matrix`).

Expone las operaciones declaradas en el spec sobre la matriz de datos
(`MATRIZ_PRIVILEGIOS`):

- `ObtenerPrivilegios`: privilegios válidos de un tipo de objeto.
- `EsCombinacionValida`: valida una combinación privilegio x tipo.
- `ValidarCombinacion`: valida y lanza el error preciso si no es válida.
- `ListarOpcionesParaUi`: opciones seleccionables y ordenadas para la UI.

La matriz se puede inyectar (por defecto se usa la declarada en el proyecto),
de modo que las pruebas y los cambios posteriores puedan ampliarla sin tocar
esta clase: agregar un tipo es agregar una entrada al diccionario (spec
`privilege-matrix` - "Declarativa y extensible").
"""

from typing import Optional

from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.matriz.errores import ErrorCombinacionInvalida
from control_accesos.matriz.matriz_privilegios import MATRIZ_PRIVILEGIOS


class ConsultoraMatrizPrivilegios:
    """Consultora de la matriz de compatibilidad privilegio x tipo de objeto."""

    def __init__(self, matriz: Optional[dict] = None):
        """Inicializa la consultora con la matriz a consultar.

        Args:
            matriz (dict | None): diccionario TipoObjeto -> frozenset de
                privilegios. Si es None, se usa la matriz declarada en
                `matriz_privilegios.py`. La consultora nunca la modifica.
        """
        # Se conserva la referencia (sin copiar ni mutar) a la matriz recibida.
        self._matriz = MATRIZ_PRIVILEGIOS if matriz is None else matriz

    def ObtenerPrivilegios(self, tipo_objeto):
        """Devuelve los privilegios válidos declarados para un tipo de objeto.

        Args:
            tipo_objeto (TipoObjeto | str): tipo de objeto a consultar; se
                acepta también su valor en texto (por ejemplo, "catalogo").

        Returns:
            frozenset[str]: privilegios válidos del tipo. Si la matriz no
                declara el tipo, devuelve un conjunto vacío en lugar de
                provocar un error del sistema (escenario del spec).

        Raises:
            ErrorDominio: si el tipo recibido no pertenece a la enumeración.
        """
        tipo_normalizado = self._NormalizarTipo(tipo_objeto)
        # .get evita el KeyError cuando la matriz no declara el tipo.
        return self._matriz.get(tipo_normalizado, frozenset())

    def EsCombinacionValida(self, privilegio, tipo_objeto):
        """Indica si un privilegio es válido para un tipo de objeto.

        Args:
            privilegio (str): privilegio a validar (se normaliza a mayúsculas).
            tipo_objeto (TipoObjeto | str): tipo de objeto sobre el que se
                pretende otorgar el privilegio.

        Returns:
            bool: True si la combinación está declarada en la matriz.
        """
        privilegio_normalizado = self._NormalizarPrivilegio(privilegio)
        if not privilegio_normalizado:
            # Un privilegio vacío nunca es una combinación válida.
            return False
        return privilegio_normalizado in self.ObtenerPrivilegios(tipo_objeto)

    def ValidarCombinacion(self, privilegio, tipo_objeto):
        """Valida una combinación y lanza el error preciso si es inválida.

        Args:
            privilegio (str): privilegio a validar.
            tipo_objeto (TipoObjeto | str): tipo de objeto de la solicitud.

        Raises:
            ErrorCombinacionInvalida: si la combinación no está declarada; el
                mensaje identifica el privilegio, el tipo de objeto y lista los
                privilegios válidos alternativos (spec: mensajes precisos).
        """
        if self.EsCombinacionValida(privilegio, tipo_objeto):
            return

        privilegio_normalizado = self._NormalizarPrivilegio(privilegio)
        tipo_normalizado = self._NormalizarTipo(tipo_objeto)
        privilegios_validos = self.ObtenerPrivilegios(tipo_normalizado)

        raise ErrorCombinacionInvalida(
            mensaje=self.MensajeCombinacionInvalida(
                privilegio_normalizado, tipo_normalizado
            ),
            privilegio=privilegio_normalizado,
            tipo_objeto=tipo_normalizado,
            privilegios_validos=privilegios_validos,
        )

    def MensajeCombinacionInvalida(self, privilegio, tipo_objeto):
        """Construye el mensaje de error preciso de una combinación inválida.

        Se expone por separado de `ValidarCombinacion` para que las fases del
        pipeline puedan usar el mensaje como motivo de bloqueo sin lanzar ni
        capturar excepciones (spec `grant-pipeline` - fase de pre-flight).

        Args:
            privilegio (str): privilegio solicitado (se normaliza).
            tipo_objeto (TipoObjeto | str): tipo de objeto de la solicitud.

        Returns:
            str: mensaje en español que identifica el privilegio, el tipo de
                objeto y lista los privilegios válidos alternativos.
        """
        privilegio_normalizado = self._NormalizarPrivilegio(privilegio)
        tipo_normalizado = self._NormalizarTipo(tipo_objeto)
        privilegios_validos = self.ObtenerPrivilegios(tipo_normalizado)

        alternativas = ", ".join(sorted(privilegios_validos)) or "(ninguno)"
        return (
            f"El privilegio {privilegio_normalizado!r} no es válido para el "
            f"tipo de objeto {tipo_normalizado.value}. Privilegios válidos "
            f"para {tipo_normalizado.value}: {alternativas}."
        )

    def ListarOpcionesParaUi(self, tipo_objeto):
        """Lista los privilegios seleccionables en la UI para un tipo de objeto.

        Args:
            tipo_objeto (TipoObjeto | str): tipo de objeto cuyas opciones se
                quieren presentar.

        Returns:
            list[str]: privilegios válidos del tipo, ordenados alfabéticamente
                para una presentación estable. Lista vacía si la matriz no
                declara el tipo.
        """
        return sorted(self.ObtenerPrivilegios(tipo_objeto))

    def _NormalizarTipo(self, tipo_recibido):
        """Convierte el tipo recibido en un miembro de `TipoObjeto`.

        Args:
            tipo_recibido (TipoObjeto | str): tipo recibido por la operación.

        Returns:
            TipoObjeto: miembro normalizado de la enumeración.

        Raises:
            ErrorDominio: si el tipo no pertenece a la enumeración.
        """
        if isinstance(tipo_recibido, TipoObjeto):
            return tipo_recibido

        try:
            return TipoObjeto(tipo_recibido)
        except ValueError:
            raise ErrorDominio(
                f"Tipo de objeto no soportado para la consulta de la matriz: "
                f"se recibió {tipo_recibido!r}."
            ) from None

    def _NormalizarPrivilegio(self, privilegio_recibido):
        """Normaliza un privilegio a su forma canónica (texto en mayúsculas).

        Args:
            privilegio_recibido (str | None): privilegio recibido.

        Returns:
            str: privilegio recortado y en mayúsculas; texto vacío si el valor
                recibido no es texto o está vacío.
        """
        if not isinstance(privilegio_recibido, str):
            return ""
        return privilegio_recibido.strip().upper()
