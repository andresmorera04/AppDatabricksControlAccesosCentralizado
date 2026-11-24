"""Modelos de la identidad del llamante (capability `caller-identity`).

Tres dataclasses, todas inmutables (`frozen`) y con validación fail-fast en
español, siguiendo la convención del dominio (design.md D1):

- `ContextoLlamante`: dictado que entrega el proveedor del contexto
  on-behalf-of. Es el dato *en bruto* que la plataforma reporta (tipo,
  identificador, nombre mostrable, App Id y grupos); no se interpreta aquí.
- `Grupo`: grupo de Databricks, con su identificador (el id numérico de SCIM,
  que es la forma en la que Unity Catalog identifica a un otorgatario grupo)
  y su nombre legible.
- `IdentidadLlamante`: identidad ya resuelta y validada, compuesta por el
  `Principal` del dominio, sus grupos y —solo para service principals— el
  App Id. Expone `ReferenciasDeIdentidad()`, el insumo único con el que la
  resolución de privilegios empareja los otorgamientos vigentes.

Los service principals son principales **independientes** de usuarios y
grupos: una identidad de usuario no incorpora App Id ni referencias de
ningún service principal (spec `caller-identity` - "Los service principals
son principales independientes").
"""

from dataclasses import dataclass, field
from typing import Optional

from control_accesos.autenticacion.errores import ErrorIdentidadLlamanteInvalida
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.dominio.modelos import Principal

# Tipo de principal con el que la identidad lleva App Id obligatorio. Se
# declara como dato para que la regla se lea en un solo sitio.
TIPO_QUE_REQUIERE_APP_ID = TipoPrincipal.SERVICE_PRINCIPAL


@dataclass(frozen=True)
class Grupo:
    """Grupo de Databricks del que el llamante es miembro.

    Attributes:
        identificador (str): identificador único del grupo (por ejemplo, el id
            numérico de SCIM, que es como Unity Catalog lo reporta en sus
            otorgamientos). Obligatorio y no vacío.
        nombre (Optional[str]): nombre legible del grupo (como lo reporta la
            Permissions API del plano de control). None cuando el origen no lo
            informa.
    """

    identificador: str
    nombre: Optional[str] = None

    def __post_init__(self):
        """Valida y normaliza el grupo al construirlo.

        Raises:
            ErrorIdentidadLlamanteInvalida: si el identificador es nulo, está
                vacío o no es texto.
        """
        object.__setattr__(self, "identificador", _ValidarTexto(
            self.identificador, "el identificador del grupo"
        ))
        nombre_recortado = _RecortarOPorNulo(self.nombre)
        object.__setattr__(self, "nombre", nombre_recortado)


@dataclass(frozen=True)
class ContextoLlamante:
    """Dictado del contexto on-behalf-of entregado por la plataforma.

    Es el dato en bruto que el puerto `ProveedorIdentidadLlamante` reporta; el
    servicio lo convierte en una `IdentidadLlamante` validada.

    Attributes:
        tipo (TipoPrincipal | str): tipo de principal del llamante.
        identificador (str): identificador del llamante reportado por la
            plataforma (correo del usuario, nombre del grupo o nombre del
            service principal).
        nombre_mostrable (Optional[str]): nombre para mostrar del llamante.
        app_id (Optional[str]): App Id del service principal que ejecuta la
            app; None para usuarios y grupos.
        grupos (tuple[Grupo, ...]): grupos de los que el llamante es miembro
            directo. Vacío explícito cuando no tiene.
    """

    tipo: TipoPrincipal
    identificador: str
    nombre_mostrable: Optional[str] = None
    app_id: Optional[str] = None
    grupos: tuple = field(default_factory=tuple)

    def __post_init__(self):
        """Normaliza grupos y textos del dictado, sin validar la identidad.

        La validación de coherencia (identificador no vacío, App Id solo para
        service principals) corresponde a `IdentidadLlamante`, que es el
        modelo ya resuelto: aquí se conserva lo que la plataforma reportó.

        Raises:
            ErrorIdentidadLlamanteInvalida: si `grupos` no es una colección de
                `Grupo`, o si algún miembro no es un grupo.
        """
        grupos_recibidos = tuple(self.grupos or ())
        for grupo in grupos_recibidos:
            if not isinstance(grupo, Grupo):
                raise ErrorIdentidadLlamanteInvalida(
                    "Los grupos del contexto deben ser instancias de Grupo; "
                    f"se recibió {type(grupo).__name__}."
                )
        object.__setattr__(self, "grupos", grupos_recibidos)
        object.__setattr__(
            self, "nombre_mostrable", _RecortarOPorNulo(self.nombre_mostrable)
        )
        object.__setattr__(self, "app_id", _RecortarOPorNulo(self.app_id))


@dataclass(frozen=True)
class IdentidadLlamante:
    """Identidad del llamante ya resuelta y validada.

    Attributes:
        principal (Principal): principal del dominio que representa al
            llamante (usuario, grupo o service principal).
        grupos (tuple[Grupo, ...]): grupos de los que el llamante es miembro
            directo; vacío explícito cuando no pertenece a ninguno.
        nombre_mostrable (Optional[str]): nombre para mostrar reportado por la
            plataforma, usado como referencia de emparejamiento.
        app_id (Optional[str]): App Id del service principal; obligatorio para
            un llamante de tipo `service_principal` y prohibido en cualquier
            otro tipo.
    """

    principal: Principal
    grupos: tuple = field(default_factory=tuple)
    nombre_mostrable: Optional[str] = None
    app_id: Optional[str] = None

    def __post_init__(self):
        """Valida la coherencia de la identidad al construirla (fail-fast).

        Reglas declaradas en el spec `caller-identity`:

        - el llamante es un `Principal` del dominio;
        - los grupos son instancias de `Grupo`;
        - el App Id solo existe para un service principal, y en ese caso es
          obligatorio.

        Raises:
            ErrorIdentidadLlamanteInvalida: si alguna regla se incumple.
        """
        if not isinstance(self.principal, Principal):
            raise ErrorIdentidadLlamanteInvalida(
                "La identidad del llamante debe llevar un Principal del "
                f"dominio; se recibió {type(self.principal).__name__}."
            )

        grupos_recibidos = tuple(self.grupos or ())
        for grupo in grupos_recibidos:
            if not isinstance(grupo, Grupo):
                raise ErrorIdentidadLlamanteInvalida(
                    "Los grupos de la identidad deben ser instancias de "
                    f"Grupo; se recibió {type(grupo).__name__}."
                )
        object.__setattr__(self, "grupos", grupos_recibidos)
        object.__setattr__(
            self, "nombre_mostrable", _RecortarOPorNulo(self.nombre_mostrable)
        )

        app_id_normalizado = _RecortarOPorNulo(self.app_id)
        if self.principal.tipo is TIPO_QUE_REQUIERE_APP_ID:
            if app_id_normalizado is None:
                raise ErrorIdentidadLlamanteInvalida(
                    "La identidad de un service principal requiere su App Id: "
                    "es la referencia con la que Unity Catalog reporta los "
                    "otorgamientos hechos a ese principal."
                )
        elif app_id_normalizado is not None:
            # Un usuario o un grupo NO pueden llevar App Id: los service
            # principals son principales independientes (spec).
            raise ErrorIdentidadLlamanteInvalida(
                "El App Id solo aplica a principales de tipo "
                f"service_principal; la identidad recibida es de tipo "
                f"{self.principal.tipo.value} y trajo App Id "
                f"{app_id_normalizado!r}."
            )
        object.__setattr__(self, "app_id", app_id_normalizado)

    def ReferenciasDeIdentidad(self):
        """Devuelve las referencias con las que se emparejan los otorgamientos.

        Es el insumo único de la resolución de privilegios efectivos: el
        otorgatario de un otorgamiento vigente coincide con el llamante si su
        identificación reporteda por el canal aparece en este conjunto
        (spec `caller-identity` - "Referencias de identidad para el
        emparejamiento de otorgamientos").

        El conjunto contiene, sin duplicados y en orden determinista:

        - el identificador del llamante y su nombre mostrable;
        - el App Id y el nombre, tratándose de un service principal;
        - el identificador y el nombre de cada uno de sus grupos.

        Returns:
            tuple[str, ...]: referencias de identidad del llamante.
        """
        referencias_ordenadas = [self.principal.identificador]

        if self.nombre_mostrable is not None:
            referencias_ordenadas.append(self.nombre_mostrable)

        if self.app_id is not None:
            referencias_ordenadas.append(self.app_id)

        for grupo in self.grupos:
            referencias_ordenadas.append(grupo.identificador)
            if grupo.nombre is not None:
                referencias_ordenadas.append(grupo.nombre)

        # Deduplicado conservando el orden de aparición.
        referencias_unicas = []
        for referencia in referencias_ordenadas:
            if referencia not in referencias_unicas:
                referencias_unicas.append(referencia)

        return tuple(referencias_unicas)

    @property
    def usuario_bitacora(self):
        """Identificador con el que la bitácora de eventos registra al llamante.

        Returns:
            str: `identificador` del principal; la ausencia de identidad se
                expresa registrando `None` (lo decide el llamador, que no
                construye esta identidad sin llamante).
        """
        return self.principal.identificador


def _ValidarTexto(valor, descripcion):
    """Valida que un campo obligatorio sea texto no vacío, y lo recorta.

    Args:
        valor (str | None): valor recibido.
        descripcion (str): descripción del campo para el mensaje de error.

    Returns:
        str: valor recortado.

    Raises:
        ErrorIdentidadLlamanteInvalida: si es nulo, no es texto o queda vacío.
    """
    if valor is None:
        raise ErrorIdentidadLlamanteInvalida(
            f"{descripcion.capitalize()} no puede ser nulo."
        )
    if not isinstance(valor, str):
        raise ErrorIdentidadLlamanteInvalida(
            f"{descripcion.capitalize()} debe ser texto; se recibió "
            f"{type(valor).__name__}."
        )
    valor_recortado = valor.strip()
    if not valor_recortado:
        raise ErrorIdentidadLlamanteInvalida(
            f"{descripcion.capitalize()} no puede estar vacío."
        )
    return valor_recortado


def _RecortarOPorNulo(valor):
    """Recorta un texto opcional y convierte el vacío en None explícito.

    Args:
        valor (str | None): texto opcional recibido.

    Returns:
        str | None: texto recortado, o None si no se informó o quedó vacío.
    """
    if valor is None:
        return None
    valor_recortado = str(valor).strip()
    return valor_recortado or None
