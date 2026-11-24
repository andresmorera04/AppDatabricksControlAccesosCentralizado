"""Modelos de la resolución de privilegios efectivos.

Dataclasses inmutables del subpaquete (design.md D2/D4):

- `OtorgamientoEfectivo`: un otorgamiento vigente del llamante sobre el objeto
  consultado, con su origen (directo, heredado o no determinado) y la
  referencia de identidad con la que coincidió.
- `PrivilegiosEfectivosVista`: la vista unificada por objeto que oculta las
  diferencias de formato entre el canal SQL y el canal SDK/REST.
- `MensajePrivilegiosInsuficientes`: el dato del bloqueo, con los cuatro
  campos que el spec exige poder consultar por separado.
"""

from dataclasses import dataclass, field
from typing import Optional

from control_accesos.dominio.enumeraciones import ListarValoresDeEnumeracion, Plano
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import NormalizarPrivilegio, ObjetoSecurable
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio

# Formas canónicas de los textos obligatorios de los modelos de este módulo.
_TEXTO_OBLIGATORIO = "no puede estar vacío ni ser nulo"

# Autoridad que necesita el llamante sobre un objeto para poder otorgarle a
# otro principal un privilegio de ese objeto, declarada por plano.
#
# - Plano de datos: en Unity Catalog quien puede seguir otorgando privilegios
#   sobre un securable es quien tiene `MANAGE` (o la misma opción de otorgar).
# - Plano de control: en la Permissions API el nivel que permite administrar
#   los permisos del objeto es `CAN_MANAGE`.
#
# Se declara como dato (no como if dispersos) para que un change futuro pueda
# ampliar el mapa sin tocar la lógica del split. Si un plano no está aquí, el
# split reporta como faltante el propio privilegio solicitado.
PRIVILEGIO_AUTORIZADOR_POR_PLANO = {
    Plano.DATOS: "MANAGE",
    Plano.CONTROL: "CAN_MANAGE",
}


@dataclass(frozen=True)
class OtorgamientoEfectivo:
    """Otorgamiento vigente que pertenece al llamante.

    Attributes:
        privilegio (str): privilegio otorgado, en forma canónica (MAYÚSCULAS).
        origen (OrigenPrivilegio): DIRECTO sobre el propio objeto, HEREDADO de
            un contenedor padre, o NO_DETERMINADO si el canal no lo informa.
        otorgatario (str): identificación del otorgatario tal como la reportó
            el canal (id opaco en el plano de datos, nombre en el de control).
        referencia_coincidente (str): referencia de la identidad del llamante
            con la que ese otorgatario coincidió, para trazabilidad.
        heredado_de (Optional[str]): identificación del securable padre cuando
            `origen` es HEREDADO; None en cualquier otro caso.
    """

    privilegio: str
    origen: OrigenPrivilegio
    otorgatario: str
    referencia_coincidente: str = ""
    heredado_de: Optional[str] = None

    def __post_init__(self):
        """Valida y normaliza el otorgamiento al construirlo.

        Raises:
            ErrorDominio: si el privilegio o el otorgatario están vacíos, o si
                el origen no pertenece a `OrigenPrivilegio`.
        """
        object.__setattr__(self, "privilegio", NormalizarPrivilegio(self.privilegio))
        object.__setattr__(
            self, "origen", _NormalizarOrigen(self.origen)
        )
        object.__setattr__(self, "otorgatario", _TextoObligatorio(
            self.otorgatario, "El otorgatario"
        ))
        object.__setattr__(
            self, "heredado_de", _TextoOPorNulo(self.heredado_de)
        )


@dataclass(frozen=True)
class PrivilegiosEfectivosVista:
    """Vista unificada de los privilegios efectivos sobre un objeto.

    Attributes:
        objeto (ObjetoSecurable): objeto consultado.
        plano (Plano): plano del objeto, derivado de su tipo por el dominio.
        canal_consultado (str): nombre del canal por el que se consultó
            (`datos` o `control`), según `NOMBRES_CANAL_POR_PLANO`.
        otorgamientos (tuple[OtorgamientoEfectivo, ...]): otorgamientos
            efectivos del llamante; vacío explícito cuando no tiene.
        fue_consulta_exitosa (bool): False cuando el canal denegó la lectura
            de los otorgamientos; en ese caso no se afirma ningún privilegio
            (fail-safe, nunca se autoriza a ciegas).
    """

    objeto: ObjetoSecurable
    plano: Plano
    canal_consultado: str
    otorgamientos: tuple = field(default_factory=tuple)
    fue_consulta_exitosa: bool = True

    def __post_init__(self):
        """Valida la vista y normaliza la colección de otorgamientos.

        Raises:
            ErrorDominio: si falta el objeto o el plano, si el nombre del
                canal está vacío, o si algún elemento no es un
                `OtorgamientoEfectivo`.
        """
        if not isinstance(self.objeto, ObjetoSecurable):
            raise ErrorDominio(
                "La vista de privilegios efectivos requiere un "
                f"ObjetoSecurable; se recibió {type(self.objeto).__name__}."
            )
        object.__setattr__(self, "plano", _NormalizarPlano(self.plano))
        object.__setattr__(
            self,
            "canal_consultado",
            _TextoObligatorio(self.canal_consultado, "El canal consultado"),
        )

        otorgamientos_recibidos = tuple(self.otorgamientos or ())
        for otorgamiento in otorgamientos_recibidos:
            if not isinstance(otorgamiento, OtorgamientoEfectivo):
                raise ErrorDominio(
                    "Los otorgamientos de la vista deben ser instancias de "
                    f"OtorgamientoEfectivo; se recibió "
                    f"{type(otorgamiento).__name__}."
                )
        object.__setattr__(self, "otorgamientos", otorgamientos_recibidos)

    @property
    def privilegios_efectivos(self):
        """Conjunto de privilegios efectivos del llamante sobre el objeto.

        Returns:
            frozenset[str]: privilegios en su forma canónica; vacío explícito
                cuando el llamante no tiene ninguno (distinguible de un fallo
                consultando `FueConsultaExitosa`).
        """
        return frozenset(
            otorgamiento.privilegio for otorgamiento in self.otorgamientos
        )

    @property
    def FueConsultaExitosa(self):
        """Indica si la consulta de otorgamientos se completó normalmente.

        Returns:
            bool: False si el canal denegó la lectura de los otorgamientos.
        """
        return bool(self.fue_consulta_exitosa)

    def TieneElPrivilegio(self, privilegio):
        """Indica si el llamante tiene el privilegio sobre el objeto.

        Args:
            privilegio (str): privilegio a comprobar; se normaliza a MAYÚSCULAS.

        Returns:
            bool: True si figura entre los privilegios efectivos.
        """
        return NormalizarPrivilegio(privilegio) in self.privilegios_efectivos

    def ObtenerOtorgamientoDelPrivilegio(self, privilegio):
        """Devuelve el otorgamiento efectivo del privilegio, si existe.

        Args:
            privilegio (str): privilegio buscado.

        Returns:
            OtorgamientoEfectivo | None: el otorgamiento, o None si el
                llamante no tiene ese privilegio sobre el objeto.
        """
        privilegio_normalizado = NormalizarPrivilegio(privilegio)
        for otorgamiento in self.otorgamientos:
            if otorgamiento.privilegio == privilegio_normalizado:
                return otorgamiento
        return None

    def ObtenerOrigenDelPrivilegio(self, privilegio):
        """Devuelve el origen (directo/heredado/no determinado) del privilegio.

        Args:
            privilegio (str): privilegio consultado.

        Returns:
            OrigenPrivilegio | None: origen del otorgamiento, o None si el
                privilegio no es efectivo para el llamante.
        """
        otorgamiento = self.ObtenerOtorgamientoDelPrivilegio(privilegio)
        return None if otorgamiento is None else otorgamiento.origen


@dataclass(frozen=True)
class MensajePrivilegiosInsuficientes:
    """Bloqueo de un ítem por falta de privilegios del llamante.

    Se representa como dato y no como cadena concatenada, para que el reporte
    del pipeline y la interfaz (change C9) consulten cada elemento por su
    nombre (spec `caller-privilege-resolution` - "Mensaje estructurado de
    privilegios insuficientes").

    Attributes:
        objeto (ObjetoSecurable): objeto objetivo del ítem bloqueado.
        plano (Plano): plano del objeto (`datos` o `control`).
        privilegio_requerido (str): privilegio que la solicitud pretendía
            otorgar, en su forma canónica.
        privilegio_faltante (str): privilegio que le hace falta al llamante
            para poder otorgarlo, en su forma canónica.
    """

    objeto: ObjetoSecurable
    plano: Plano
    privilegio_requerido: str
    privilegio_faltante: str

    def __post_init__(self):
        """Valida los cuatro elementos obligatorios del bloqueo.

        Raises:
            ErrorDominio: si falta el objeto, el plano o alguno de los dos
                privilegios.
        """
        if not isinstance(self.objeto, ObjetoSecurable):
            raise ErrorDominio(
                "El mensaje de privilegios insuficientes requiere el objeto "
                f"objetivo; se recibió {type(self.objeto).__name__}."
            )
        object.__setattr__(self, "plano", _NormalizarPlano(self.plano))
        object.__setattr__(
            self,
            "privilegio_requerido",
            NormalizarPrivilegio(self.privilegio_requerido),
        )
        object.__setattr__(
            self,
            "privilegio_faltante",
            NormalizarPrivilegio(self.privilegio_faltante),
        )

    def ComoTexto(self):
        """Construye el texto legible del bloqueo para el reporte.

        Returns:
            str: mensaje en español que identifica el objeto, su plano, el
                privilegio requerido y el privilegio faltante.
        """
        return (
            f"Privilegios insuficientes: el llamante no puede otorgar "
            f"{self.privilegio_requerido} sobre "
            f"{self.objeto.tipo.value} '{self.objeto.identificador}' "
            f"(plano {self.plano.value}) porque le falta el privilegio "
            f"{self.privilegio_faltante}."
        )


def _NormalizarPlano(plano_recibido):
    """Convierte el plano recibido en un miembro de `Plano`.

    Acepta el miembro de la enumeración o su valor en texto, igual que hacen
    los modelos del dominio.

    Args:
        plano_recibido (Plano | str): plano recibido.

    Returns:
        Plano: miembro normalizado.

    Raises:
        ErrorDominio: si no pertenece a la enumeración.
    """
    if isinstance(plano_recibido, Plano):
        return plano_recibido
    try:
        return Plano(plano_recibido)
    except ValueError:
        valores_validos = ", ".join(ListarValoresDeEnumeracion(Plano))
        raise ErrorDominio(
            f"Plano no soportado: se recibió {plano_recibido!r}. Los planos "
            f"válidos son: {valores_validos}."
        ) from None


def _NormalizarOrigen(origen_recibido):
    """Convierte el origen recibido en un miembro de `OrigenPrivilegio`.

    Args:
        origen_recibido (OrigenPrivilegio | str): origen recibido.

    Returns:
        OrigenPrivilegio: miembro normalizado.

    Raises:
        ErrorDominio: si no pertenece a la enumeración.
    """
    if isinstance(origen_recibido, OrigenPrivilegio):
        return origen_recibido
    try:
        return OrigenPrivilegio(origen_recibido)
    except ValueError:
        valores_validos = ", ".join(
            ListarValoresDeEnumeracion(OrigenPrivilegio)
        )
        raise ErrorDominio(
            f"Origen de privilegio no soportado: se recibió "
            f"{origen_recibido!r}. Los orígenes válidos son: {valores_validos}."
        ) from None


def _TextoObligatorio(valor, descripcion):
    """Valida que un texto obligatorio no esté vacío y lo recorta.

    Args:
        valor (str | None): texto recibido.
        descripcion (str): descripción del campo para el mensaje de error.

    Returns:
        str: texto recortado.

    Raises:
        ErrorDominio: si es nulo, no es texto o queda vacío.
    """
    if valor is None or not str(valor).strip():
        raise ErrorDominio(f"{descripcion} {_TEXTO_OBLIGATORIO}.")
    if not isinstance(valor, str):
        raise ErrorDominio(
            f"{descripcion} debe ser texto; se recibió {type(valor).__name__}."
        )
    return valor.strip()


def _TextoOPorNulo(valor):
    """Recorta un texto opcional, convirtiendo el vacío en None.

    Args:
        valor (str | None): texto opcional.

    Returns:
        str | None: texto recortado o None.
    """
    if valor is None:
        return None
    valor_recortado = str(valor).strip()
    return valor_recortado or None
