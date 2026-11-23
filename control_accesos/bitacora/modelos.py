"""Modelos de registro de las bitácoras (capability `audit-logging`).

Dataclasses inmutables que fijan el contrato tipado de cada fila de bitácora
(design.md D6): los nombres de sus campos coinciden exactamente con las
columnas declaradas en el módulo DDL (`control_accesos/persistencia/ddl.py`),
de modo que el escritor puede convertir cualquier registro a fila de DataFrame
de forma genérica, sin mapas ni conversiones manuales.

Modelos (se agregan a lo largo del change):

- `EventoBitacora`: fila de `bitacora_eventos` (actividad de la aplicación con
  el usuario que la provoca; el usuario queda nulo hasta que exista identidad
  on-behalf-of en C3).
- `DetalleError` y `RegistroError`: fila y detalle STRUCT de `bitacora_errores`
  (tarea 4.2).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def GenerarIdentificadorUnico():
    """Genera el identificador único de un registro de bitácora.

    Las llaves primarias de ambas bitácoras (`id_evento`, `id_error`) son
    UUID en texto: únicos sin coordinación, estables entre reintentos y
    verificables por los helpers de integridad (design.md D5/D6).

    Returns:
        str: UUID versión 4 en su representación de texto.
    """
    return str(uuid.uuid4())


@dataclass(frozen=True)
class EventoBitacora:
    """Evento general de la actividad de la aplicación (tabla `bitacora_eventos`).

    Attributes:
        accion (str): acción realizada por la aplicación (por ejemplo,
            `otorgar_privilegios`). Obligatoria y no vacía.
        usuario (str | None): usuario que provoca el evento. Se alimenta con
            la identidad on-behalf-of cuando exista (change `auth-caller-obo`,
            C3); hasta entonces queda explícitamente `None` (el evento se
            registra igual, ver spec `audit-logging`).
        detalle (str | None): detalle libre del evento.
        resultado (str | None): resultado observable del evento (por ejemplo,
            `ok`, `otorgado`, `fallido`).
        id_evento (str): llave primaria; UUID generado por defecto.
        marca_tiempo (datetime): momento del evento; por defecto, ahora.

    Raises:
        ValueError: si la acción está vacía o es nula (un evento sin acción
            no describe ninguna actividad).
    """

    accion: str
    usuario: Optional[str] = None
    detalle: Optional[str] = None
    resultado: Optional[str] = None
    id_evento: str = field(default_factory=GenerarIdentificadorUnico)
    marca_tiempo: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Valida la forma del evento al construirlo (fail-fast, en español)."""
        if not self.accion or not str(self.accion).strip():
            raise ValueError(
                "La acción del evento de bitácora no puede estar vacía: "
                "todo evento debe describir la actividad realizada."
            )


@dataclass(frozen=True)
class DetalleError:
    """Detalle estructurado de un error (campo STRUCT de `bitacora_errores`).

    Sus cuatro campos son el contrato mínimo del estándar (README.md: "el
    campo de detalle del error es de tipo STRUCT<...>") y coinciden con la
    declaración `STRUCT<tipo_excepcion, mensaje, traza, contexto>` del DDL
    (design.md D6): al convertirse a fila de DataFrame, el escritor transforma
    esta dataclass en el diccionario que Spark materializa como STRUCT.

    Attributes:
        tipo_excepcion (str): nombre de la clase de la excepción capturada.
        mensaje (str): mensaje de la excepción.
        traza (str): traza completa del error (traceback formateado) o una
            marca explícita cuando la excepción nunca se lanzó.
        contexto (str): contexto de la operación que falló (qué se hacía y
            con qué datos), aportado por el punto de captura.
    """

    tipo_excepcion: str
    mensaje: str
    traza: str
    contexto: str


@dataclass(frozen=True)
class RegistroError:
    """Error controlado registrado en la tabla `bitacora_errores`.

    Attributes:
        modulo (str): módulo o componente donde se capturó el error.
            Obligatorio y no vacío: identifica dónde ocurrió el fallo.
        detalle (DetalleError): detalle estructurado (STRUCT) del error.
        usuario (str | None): usuario que provocaba la operación fallida;
            nulo cuando no hay identidad disponible (igual que en eventos).
        id_error (str): llave primaria; UUID generado por defecto.
        marca_tiempo (datetime): momento de la captura; por defecto, ahora.

    Raises:
        ValueError: si el módulo está vacío o el detalle no es un
            `DetalleError` (el contrato STRUCT es obligatorio).
    """

    modulo: str
    detalle: DetalleError
    usuario: Optional[str] = None
    id_error: str = field(default_factory=GenerarIdentificadorUnico)
    marca_tiempo: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Valida la forma del registro al construirlo (fail-fast)."""
        if not self.modulo or not str(self.modulo).strip():
            raise ValueError(
                "El módulo del registro de error no puede estar vacío: "
                "identifica dónde se capturó el error."
            )
        if not isinstance(self.detalle, DetalleError):
            raise ValueError(
                "El detalle del error debe ser un DetalleError (campos del "
                f"STRUCT declarados en el DDL); se recibió: "
                f"{type(self.detalle).__name__}."
            )
