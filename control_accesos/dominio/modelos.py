"""Modelos (dataclasses) del dominio de grants (capability `grant-domain-model`).

Este módulo crecerá a lo largo del change con las entidades del dominio
(`Principal`, `ObjetoSecurable`, `SolicitudGrant`, `ItemGrant`,
`ResultadoItem`). Todas son dataclasses inmutables con validación en su
constructor, y todo error se lanza como `ErrorDominio` con mensaje explícito
en español (ver design.md D2 y el spec `grant-domain-model`).
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    ListarValoresDeEnumeracion,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio

# Mapa declarativo TipoObjeto -> Plano (design.md D2): el plano de un objeto se
# deriva de su tipo consultando este mapa, sin lógica if dispersa en el código.
# Cubre los 15 tipos del README: 10 del plano de datos (Unity Catalog, canal
# SQL) y 5 del plano de control (workspace, canal SDK/REST Permissions API).
MAPA_TIPO_OBJETO_A_PLANO = {
    # Plano de datos (Unity Catalog).
    TipoObjeto.CATALOGO: Plano.DATOS,
    TipoObjeto.ESQUEMA: Plano.DATOS,
    TipoObjeto.TABLA_DELTA: Plano.DATOS,
    TipoObjeto.STREAMING_TABLE: Plano.DATOS,
    TipoObjeto.VISTA_MATERIALIZADA: Plano.DATOS,
    TipoObjeto.VISTA_SQL: Plano.DATOS,
    TipoObjeto.VOLUMEN: Plano.DATOS,
    TipoObjeto.MODELO_ML: Plano.DATOS,
    TipoObjeto.EXTERNAL_LOCATION: Plano.DATOS,
    TipoObjeto.CONNECTION: Plano.DATOS,
    # Plano de control (workspace).
    TipoObjeto.COMPUTO_CLASICO: Plano.CONTROL,
    TipoObjeto.COMPUTO_SERVERLESS: Plano.CONTROL,
    TipoObjeto.SQL_WAREHOUSE: Plano.CONTROL,
    TipoObjeto.DATABRICK_APP: Plano.CONTROL,
    TipoObjeto.USO_TOKEN: Plano.CONTROL,
}

# Política declarativa de normalización de identificadores por plano: los
# nombres de Unity Catalog (plano de datos) no distinguen mayúsculas y
# minúsculas, mientras que los identificadores del plano de control (ids de
# clusters, warehouses, apps y tokens) sí los distinguen. Se declara como dato
# para que el requisito de normalización del spec se cumpla sin ramificaciones
# dispersas en el código.
NORMALIZAR_A_MINUSCULAS_POR_PLANO = {
    Plano.DATOS: True,
    Plano.CONTROL: False,
}


@dataclass(frozen=True)
class Principal:
    """Entidad que recibe o pierde privilegios: usuario, grupo o service principal.

    Attributes:
        identificador (str): identificador único del principal (por ejemplo, el
            nombre de usuario, el nombre del grupo o el id del service
            principal). No puede estar vacío ni ser nulo.
        tipo (TipoPrincipal): tipo del principal dentro de la enumeración
            soportada. Se acepta también su valor en texto (por ejemplo,
            "usuario") y se normaliza al miembro de la enumeración.
    """

    identificador: str
    tipo: TipoPrincipal

    def __post_init__(self):
        """Valida y normaliza los datos del principal al construirlo.

        Raises:
            ErrorDominio: si el identificador está vacío o es nulo, o si el
                tipo no pertenece a la enumeración `TipoPrincipal`.
        """
        # La dataclass es inmutable (frozen), por lo que la normalización de
        # los campos se aplica con object.__setattr__ dentro del constructor.
        object.__setattr__(self, "tipo", self._NormalizarTipo(self.tipo))
        object.__setattr__(
            self, "identificador", self._NormalizarIdentificador(self.identificador)
        )

    def _NormalizarTipo(self, tipo_recibido):
        """Convierte el tipo recibido en un miembro de `TipoPrincipal`.

        Acepta un miembro de la enumeración o su valor en texto (español).

        Args:
            tipo_recibido (TipoPrincipal | str): tipo recibido por el constructor.

        Returns:
            TipoPrincipal: miembro normalizado de la enumeración.

        Raises:
            ErrorDominio: si el tipo recibido no pertenece a la enumeración;
                el mensaje indica el tipo recibido y los tipos válidos.
        """
        # Caso 1: ya es un miembro de la enumeración -> se usa tal cual.
        if isinstance(tipo_recibido, TipoPrincipal):
            return tipo_recibido

        # Caso 2: es el valor en texto de un miembro -> se convierte.
        try:
            return TipoPrincipal(tipo_recibido)
        except ValueError:
            # Caso 3: fuera de la enumeración -> error explícito (spec:
            # "indica el tipo recibido y los tipos válidos").
            valores_validos = ", ".join(ListarValoresDeEnumeracion(TipoPrincipal))
            raise ErrorDominio(
                f"Tipo de principal no soportado: se recibió {tipo_recibido!r}. "
                f"Los tipos válidos son: {valores_validos}."
            ) from None

    def _NormalizarIdentificador(self, identificador_recibido):
        """Valida y recorta el identificador del principal.

        Args:
            identificador_recibido (str | None): identificador recibido.

        Returns:
            str: identificador recortado (sin espacios en los extremos).

        Raises:
            ErrorDominio: si el identificador es nulo, vacío o solo espacios.
        """
        if identificador_recibido is None:
            raise ErrorDominio(
                "El identificador del principal no puede ser nulo."
            )

        if not isinstance(identificador_recibido, str):
            raise ErrorDominio(
                "El identificador del principal debe ser texto; "
                f"se recibió {type(identificador_recibido).__name__}."
            )

        identificador_recortado = identificador_recibido.strip()
        if not identificador_recortado:
            raise ErrorDominio(
                "El identificador del principal no puede estar vacío."
            )

        return identificador_recortado


@dataclass(frozen=True)
class ObjetoSecurable:
    """Objeto de Databricks sobre el que se otorgan o revocan privilegios.

    El plano (datos o control) no se declara en el constructor: se deriva del
    tipo consultando `MAPA_TIPO_OBJETO_A_PLANO`, de modo que no haya lógica
    dispersa ni posibilidad de inconsistencia entre tipo y plano.

    Attributes:
        identificador (str): identificación completa del objeto (nombre
            calificado en el plano de datos, por ejemplo
            `catalogo.esquema.tabla`; id del objeto en el plano de control).
            Se normaliza según la política declarada por plano.
        tipo (TipoObjeto): tipo del objeto dentro de la enumeración soportada.
            Se acepta también su valor en texto y se normaliza al miembro.
    """

    identificador: str
    tipo: TipoObjeto

    @property
    def plano(self):
        """Plano de autorización del objeto, derivado de su tipo.

        Returns:
            Plano: DATOS si el objeto es de Unity Catalog; CONTROL si es del
                workspace (Permissions API).
        """
        return MAPA_TIPO_OBJETO_A_PLANO[self.tipo]

    def __post_init__(self):
        """Valida y normaliza los datos del objeto al construirlo.

        Raises:
            ErrorDominio: si el tipo no pertenece a la enumeración
                `TipoObjeto`, o si el identificador está vacío o es nulo.
        """
        # La dataclass es inmutable (frozen): la normalización se aplica con
        # object.__setattr__ dentro del constructor.
        tipo_normalizado = self._NormalizarTipo(self.tipo)
        object.__setattr__(self, "tipo", tipo_normalizado)
        object.__setattr__(
            self,
            "identificador",
            self._NormalizarIdentificador(self.identificador, tipo_normalizado),
        )

    def _NormalizarTipo(self, tipo_recibido):
        """Convierte el tipo recibido en un miembro de `TipoObjeto`.

        Args:
            tipo_recibido (TipoObjeto | str): tipo recibido por el constructor.

        Returns:
            TipoObjeto: miembro normalizado de la enumeración.

        Raises:
            ErrorDominio: si el tipo recibido no pertenece a la enumeración;
                el mensaje indica el tipo recibido y los tipos soportados.
        """
        if isinstance(tipo_recibido, TipoObjeto):
            return tipo_recibido

        try:
            return TipoObjeto(tipo_recibido)
        except ValueError:
            valores_validos = ", ".join(ListarValoresDeEnumeracion(TipoObjeto))
            raise ErrorDominio(
                f"Tipo de objeto no soportado: se recibió {tipo_recibido!r}. "
                f"Los tipos soportados son: {valores_validos}."
            ) from None

    def _NormalizarIdentificador(self, identificador_recibido, tipo_normalizado):
        """Valida y normaliza la identificación del objeto securable.

        La normalización sigue la política declarada por plano
        (`NORMALIZAR_A_MINUSCULAS_POR_PLANO`): en el plano de datos dos
        referencias con distinta escritura resuelven al mismo objeto; en el
        plano de control el identificador conserva su escritura original.

        Args:
            identificador_recibido (str | None): identificación recibida.
            tipo_normalizado (TipoObjeto): tipo ya validado, del que se deriva
                el plano para aplicar la política de normalización.

        Returns:
            str: identificador recortado y normalizado según el plano.

        Raises:
            ErrorDominio: si el identificador es nulo, vacío o solo espacios.
        """
        if identificador_recibido is None:
            raise ErrorDominio(
                "El identificador del objeto securable no puede ser nulo."
            )

        if not isinstance(identificador_recibido, str):
            raise ErrorDominio(
                "El identificador del objeto securable debe ser texto; "
                f"se recibió {type(identificador_recibido).__name__}."
            )

        identificador_recortado = identificador_recibido.strip()
        if not identificador_recortado:
            raise ErrorDominio(
                "El identificador del objeto securable no puede estar vacío."
            )

        # Política declarativa por plano: sin ramificaciones dispersas.
        plano_del_objeto = MAPA_TIPO_OBJETO_A_PLANO[tipo_normalizado]
        normalizar_a_minusculas = NORMALIZAR_A_MINUSCULAS_POR_PLANO[
            plano_del_objeto
        ]
        if normalizar_a_minusculas:
            return identificador_recortado.lower()

        return identificador_recortado


def NormalizarPrivilegio(privilegio_recibido, posicion=None):
    """Valida y normaliza un privilegio a su forma canónica en mayúsculas.

    Los privilegios de Databricks se escriben en mayúsculas (por ejemplo,
    `SELECT`, `USE CATALOG`, `CAN_USE`), por lo que se recortan y se
    normalizan para que la misma solicitud no se trate como distinta por su
    escritura.

    Args:
        privilegio_recibido (str): privilegio a normalizar.
        posicion (int | None): posición del privilegio en la lista, para
            construir un mensaje de error preciso cuando hay varios.

    Returns:
        str: privilegio recortado y en mayúsculas.

    Raises:
        ErrorDominio: si el privilegio no es texto o está vacío.
    """
    referencia = "" if posicion is None else f" en la posición {posicion + 1}"

    if not isinstance(privilegio_recibido, str):
        raise ErrorDominio(
            f"El privilegio{referencia} debe ser texto; "
            f"se recibió {type(privilegio_recibido).__name__}."
        )

    privilegio_normalizado = privilegio_recibido.strip().upper()
    if not privilegio_normalizado:
        raise ErrorDominio(f"El privilegio{referencia} no puede estar vacío.")

    return privilegio_normalizado


@dataclass(frozen=True)
class ItemGrant:
    """Unidad atómica de procesamiento: un principal, un privilegio, un objeto.

    El pipeline trabaja ítem por ítem (ver spec `grant-pipeline`): cada ítem se
    clasifica en pre-flight, se ejecuta por su canal, se verifica y se reporta
    de forma independiente, de modo que un fallo puntual no aborte la
    operación completa.

    Attributes:
        principal (Principal): entidad que recibe el privilegio.
        privilegio (str): privilegio en su forma canónica (mayúsculas).
        objeto (ObjetoSecurable): objeto sobre el que se otorga el privilegio.
    """

    principal: Principal
    privilegio: str
    objeto: ObjetoSecurable

    def __post_init__(self):
        """Valida los campos del ítem al construirlo.

        Raises:
            ErrorDominio: si el principal o el objeto no son del tipo esperado,
                o si el privilegio está vacío.
        """
        if not isinstance(self.principal, Principal):
            raise ErrorDominio(
                "El principal del ítem debe ser una instancia de Principal; "
                f"se recibió {type(self.principal).__name__}."
            )
        if not isinstance(self.objeto, ObjetoSecurable):
            raise ErrorDominio(
                "El objeto del ítem debe ser una instancia de ObjetoSecurable; "
                f"se recibió {type(self.objeto).__name__}."
            )
        # La dataclass es inmutable (frozen): se normaliza con __setattr__.
        object.__setattr__(
            self, "privilegio", NormalizarPrivilegio(self.privilegio)
        )


@dataclass(frozen=True)
class SolicitudGrant:
    """Solicitud de otorgamiento de privilegios con cardinalidad 1 a 1.

    Forma aceptada (spec `grant-domain-model`): exactamente un principal, uno
    o más privilegios y un objeto. La cardinalidad N a M está fuera de alcance
    en esta versión y se rechaza con mensaje explícito; las cardinalidades
    1 a N y N a 1 (change `grants-batch`, C5) se expresan como varias
    solicitudes 1 a 1 independientes.

    Attributes:
        principal (Principal): entidad que recibe los privilegios.
        privilegios (tuple[str, ...]): privilegios en forma canónica
            (mayúsculas), en el orden recibido.
        objeto (ObjetoSecurable): objeto sobre el que se otorgan.
    """

    principal: Principal
    privilegios: tuple
    objeto: ObjetoSecurable

    def __post_init__(self):
        """Valida la forma de la solicitud al construirla.

        Raises:
            ErrorDominio: si el principal o el objeto no son del tipo
                esperado, o si la lista de privilegios está vacía o contiene
                un privilegio inválido.
        """
        if not isinstance(self.principal, Principal):
            raise ErrorDominio(
                "El principal de la solicitud debe ser una instancia de "
                f"Principal; se recibió {type(self.principal).__name__}."
            )
        if not isinstance(self.objeto, ObjetoSecurable):
            raise ErrorDominio(
                "El objeto de la solicitud debe ser una instancia de "
                f"ObjetoSecurable; se recibió {type(self.objeto).__name__}."
            )

        privilegios_recibidos = list(self.privilegios)
        if not privilegios_recibidos:
            raise ErrorDominio(
                "La solicitud de grant requiere al menos un privilegio; "
                "se recibió una lista de privilegios vacía."
            )

        privilegios_normalizados = tuple(
            NormalizarPrivilegio(privilegio, posicion)
            for posicion, privilegio in enumerate(privilegios_recibidos)
        )
        # La dataclass es inmutable (frozen): se normaliza con __setattr__.
        object.__setattr__(self, "privilegios", privilegios_normalizados)

    @classmethod
    def Crear(cls, principal, privilegios, objeto):
        """Fábrica de una solicitud 1 a 1 con validación de forma.

        Args:
            principal (Principal): entidad que recibe los privilegios.
            privilegios (list[str] | tuple[str, ...]): uno o más privilegios.
            objeto (ObjetoSecurable): objeto sobre el que se otorgan.

        Returns:
            SolicitudGrant: solicitud validada y lista para procesar.

        Raises:
            ErrorDominio: si la forma de la solicitud es inválida.
        """
        return cls(
            principal=principal, privilegios=tuple(privilegios), objeto=objeto
        )

    @classmethod
    def CrearDesdeConjuntos(cls, principales, privilegios, objetos):
        """Valida la cardinalidad recibida y crea la solicitud 1 a 1.

        Esta fábrica es el punto de entrada explícito de validación de
        cardinalidad (spec: rechazo antes de cualquier ejecución):

        - N a M (varios principals y varios objetos): fuera de alcance en esta
          versión; se rechaza con mensaje explícito.
        - 1 a N o N a 1: no son una solicitud 1 a 1; se rechazan indicando que
          cada combinación se expresa como una solicitud independiente
          (change `grants-batch`, C5).
        - 1 a 1: se acepta y se devuelve la solicitud.

        Args:
            principales (list[Principal]): principals recibidos.
            privilegios (list[str]): privilegios recibidos.
            objetos (list[ObjetoSecurable]): objetos recibidos.

        Returns:
            SolicitudGrant: solicitud 1 a 1 validada.

        Raises:
            ErrorDominio: si la cardinalidad no es 1 a 1, o si los conjuntos
                recibidos están vacíos.
        """
        lista_principales = list(principales)
        lista_objetos = list(objetos)

        if not lista_principales:
            raise ErrorDominio(
                "La solicitud de grant requiere al menos un principal; "
                "se recibió una lista de principales vacía."
            )
        if not lista_objetos:
            raise ErrorDominio(
                "La solicitud de grant requiere al menos un objeto; "
                "se recibió una lista de objetos vacía."
            )

        varios_principales = len(lista_principales) > 1
        varios_objetos = len(lista_objetos) > 1

        # Cardinalidad N a M: fuera de alcance en esta versión (decisión D6).
        if varios_principales and varios_objetos:
            raise ErrorDominio(
                "La cardinalidad N a M (varios principals y varios objetos a "
                "la vez) está fuera de alcance en esta versión. Procese cada "
                "combinación como una solicitud independiente."
            )

        # Cardinalidades 1 a N y N a 1: se procesan en C5 (grants-batch) como
        # varias solicitudes 1 a 1, no como una sola solicitud.
        if varios_principales or varios_objetos:
            raise ErrorDominio(
                "La cardinalidad de una solicitud de grant es 1 a 1 (un "
                "principal, uno o más privilegios, un objeto). Las "
                "cardinalidades 1 a N y N a 1 se procesan como varias "
                "solicitudes 1 a 1 independientes (change grants-batch, C5)."
            )

        return cls.Crear(
            principal=lista_principales[0],
            privilegios=privilegios,
            objeto=lista_objetos[0],
        )


@dataclass(frozen=True)
class ResultadoItem:
    """Resultado del procesamiento de un ítem de grant (spec `grant-domain-model`).

    Cada ítem procesado produce exactamente un resultado con su estado final
    (otorgado, fallido o privilegios insuficientes) y, cuando aplica, el
    detalle del error o la causa que lo provocó. Es la unidad del reporte del
    pipeline (ver spec `grant-pipeline`).

    Attributes:
        item (ItemGrant): ítem procesado al que pertenece este resultado.
        estado (EstadoItem): estado final del ítem.
        detalle (str | None): detalle del error (FALLIDO) o causa
            (PRIVILEGIOS_INSUFICIENTES); None cuando el ítem fue otorgado.
    """

    item: ItemGrant
    estado: EstadoItem
    detalle: Optional[str]

    def __post_init__(self):
        """Valida el resultado al construirlo.

        Raises:
            ErrorDominio: si el ítem no es un `ItemGrant`, si el estado no
                pertenece a `EstadoItem`, o si falta el detalle obligatorio de
                un estado FALLIDO o PRIVILEGIOS_INSUFICIENTES.
        """
        if not isinstance(self.item, ItemGrant):
            raise ErrorDominio(
                "El resultado por ítem debe referenciar una instancia de "
                f"ItemGrant; se recibió {type(self.item).__name__}."
            )

        # La dataclass es inmutable (frozen): se normaliza con __setattr__.
        object.__setattr__(self, "estado", self._NormalizarEstado(self.estado))
        object.__setattr__(self, "detalle", self._NormalizarDetalle(self.detalle))

        # El detalle es obligatorio en los estados que explican un problema.
        if self.estado is EstadoItem.FALLIDO and not self.detalle:
            raise ErrorDominio(
                "Un resultado FALLIDO requiere el detalle del error ocurrido."
            )
        if self.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES and not self.detalle:
            raise ErrorDominio(
                "Un resultado PRIVILEGIOS_INSUFICIENTES requiere la causa que "
                "lo provocó."
            )

    def _NormalizarEstado(self, estado_recibido):
        """Convierte el estado recibido en un miembro de `EstadoItem`.

        Args:
            estado_recibido (EstadoItem | str): estado recibido.

        Returns:
            EstadoItem: miembro normalizado de la enumeración.

        Raises:
            ErrorDominio: si el estado no pertenece a la enumeración.
        """
        if isinstance(estado_recibido, EstadoItem):
            return estado_recibido

        try:
            return EstadoItem(estado_recibido)
        except ValueError:
            valores_validos = ", ".join(ListarValoresDeEnumeracion(EstadoItem))
            raise ErrorDominio(
                f"Estado de resultado no soportado: se recibió "
                f"{estado_recibido!r}. Los estados válidos de EstadoItem son: "
                f"{valores_validos}."
            ) from None

    def _NormalizarDetalle(self, detalle_recibido):
        """Normaliza el detalle del resultado a texto recortado o None.

        Args:
            detalle_recibido (str | None): detalle recibido.

        Returns:
            str | None: detalle recortado, o None si no se informó detalle.
        """
        if detalle_recibido is None:
            return None

        if not isinstance(detalle_recibido, str):
            raise ErrorDominio(
                "El detalle del resultado debe ser texto; "
                f"se recibió {type(detalle_recibido).__name__}."
            )

        detalle_recortado = detalle_recibido.strip()
        return detalle_recortado or None

    @classmethod
    def Otorgado(cls, item, detalle=None):
        """Fábrica de un resultado de ítem otorgado.

        Args:
            item (ItemGrant): ítem otorgado.
            detalle (str | None): detalle opcional (por ejemplo, la
                confirmación de la verificación posterior al grant).

        Returns:
            ResultadoItem: resultado con estado OTORGADO.
        """
        return cls(item=item, estado=EstadoItem.OTORGADO, detalle=detalle)

    @classmethod
    def Fallido(cls, item, detalle):
        """Fábrica de un resultado de ítem fallido.

        Args:
            item (ItemGrant): ítem que falló.
            detalle (str): detalle del error ocurrido (obligatorio).

        Returns:
            ResultadoItem: resultado con estado FALLIDO y su detalle.

        Raises:
            ErrorDominio: si el detalle está vacío.
        """
        if detalle is None or not str(detalle).strip():
            raise ErrorDominio(
                "Un resultado fallido requiere el detalle del error ocurrido "
                "(detalle vacío)."
            )
        return cls(item=item, estado=EstadoItem.FALLIDO, detalle=detalle)

    @classmethod
    def PrivilegiosInsuficientes(cls, item, causa):
        """Fábrica de un resultado por privilegios insuficientes del ejecutor.

        Args:
            item (ItemGrant): ítem que no se pudo otorgar.
            causa (str): causa del bloqueo (obligatoria), por ejemplo la
                respuesta PERMISSION_DENIED del sistema externo.

        Returns:
            ResultadoItem: resultado con estado PRIVILEGIOS_INSUFICIENTES.

        Raises:
            ErrorDominio: si la causa está vacía.
        """
        if causa is None or not str(causa).strip():
            raise ErrorDominio(
                "Un resultado por privilegios insuficientes requiere la causa "
                "que lo provocó (causa vacía)."
            )
        return cls(
            item=item,
            estado=EstadoItem.PRIVILEGIOS_INSUFICIENTES,
            detalle=causa,
        )
