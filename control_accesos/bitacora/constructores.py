"""Constructor compartido de registros de error (Spark-free, C9 D5/D10).

La conversión `excepción -> RegistroError` es lógica pura (sin PySpark). Se
extrae a este módulo para que:

- el escritor REST de la Databricks App (`BitacoraErroresRemota`) la reutilice
  SIN importar `escritores.py` (que arrastra `capa_persistencia` -> `integridad`
  -> `pyspark`, ausente en el runtime de la App);
- el escritor Spark (`BitacoraErrores` de `escritores.py`, ruta CLI/lote) la
  delegue al Mismo lugar, evitando duplicar la regla.

Regla D5: el runtime de la App no instala `pyspark`; ningún módulo alcanzable
desde `control_accesos.ui.composicion` debe importar `pyspark` a nivel de módulo.
"""

import traceback
from datetime import datetime

from control_accesos.bitacora.modelos import DetalleError, RegistroError

# Marca explícita del campo traza cuando la excepción capturada nunca se lanzó
# (no tiene traceback real). Constante compartida por ambos escritores.
MARCA_TRAZA_NO_DISPONIBLE = "(sin traza disponible: la excepcion no se lanzo)"


def ConstruirRegistroError(excepcion, modulo, usuario=None, contexto="",
                           marca_tiempo=None):
    """Construye el modelo `RegistroError` desde la excepción capturada.

    Extrae el detalle STRUCT con el máximo detalle: tipo de la excepción, su
    mensaje, la traza formateada (o la marca explícita de traza no disponible
    si la excepción se construyó sin lanzarse) y el contexto aportado.

    Args:
        excepcion (BaseException): excepción capturada por el try/except.
        modulo (str): módulo o componente donde se capturó.
        usuario (str | None): usuario que provocaba la operación fallida.
        contexto (str): contexto de la operación que falló.
        marca_tiempo (datetime | None): momento de la captura; por defecto,
            el instante de la construcción.

    Returns:
        RegistroError: modelo listo para registrarse (no escribe nada).
    """
    if excepcion.__traceback__ is not None:
        traza = "".join(
            traceback.format_exception(
                type(excepcion), excepcion, excepcion.__traceback__
            )
        )
    else:
        traza = MARCA_TRAZA_NO_DISPONIBLE

    detalle = DetalleError(
        tipo_excepcion=type(excepcion).__name__,
        mensaje=str(excepcion),
        traza=traza,
        contexto=str(contexto),
    )
    return RegistroError(
        modulo=modulo,
        detalle=detalle,
        usuario=usuario,
        marca_tiempo=marca_tiempo or datetime.now(),
    )
