"""Descubrimiento de objetos de Unity Catalog con la credencial OBO (design.md D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Componente real de solo lectura que lista los objetos del plano de datos
(catálogos, esquemas y tablas) usando el cliente OBO del llamante. A diferencia
de los principals (SCIM, contexto broker), Unity Catalog es un listado OBO:
el token del llamante sí alcanza los scopes `catalog.*` (verificado GO en el
gate broker).

Contrato, alineado con el descubridor de principals (broker) y pensado para la
UI de grants:

- API expuesta: `ListarCatalogos`, `ListarEsquemas(catalogo)` y
  `ListarTablas(catalogo, esquema)`, cada una devolviendo una tupla de
  `ObjetoUcDescubierto` (tipo e identificador con **nombre calificado**);
- paginación transparente: se camina el iterador del SDK sin asumir una sola
  página, con un tope opcional (`limite`) desde la configuración;
- clasificación por metadatos: el `table_type` de las tablas se mapea a los
  cuatro tipos tabulares del dominio y se descartan los no soportados;
- orden estable: se conserva el orden del servicio;
- fallo distinguible del vacío: un error de listado se traduce a
  `ErrorListadoUc`; una lista auténticamente vacía se devuelve como tupla vacía.

El módulo NO importa `databricks-sdk` al importarse: recibe el cliente OBO ya
construido (la fábrica del llamante lo obtiene con `auth_type='pat'`). Ningún
valor de conexión ni id vive en el código.
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import TipoObjeto

# Identificador del módulo para la bitácora de errores (convención del proyecto).
MODULO_DESCUBRIMIENTO_UC = "canal_descubrimiento_uc"

# Clasificación del metadato `table_type` del SDK al dominio (design.md D6): los
# tipos MANAGED y EXTERNAL corresponden a TABLA_DELTA (tabla Delta estándar),
# VIEW a VISTA_SQL y MATERIALIZED_VIEW a VISTA_MATERIALIZADA; STREAMING_TABLE
# es directo. Cualquier otro valor se descarta (filtrado por metadatos).
TABLE_TYPE_A_TIPO_OBJETO = {
    "MANAGED": TipoObjeto.TABLA_DELTA,
    "EXTERNAL": TipoObjeto.TABLA_DELTA,
    "STREAMING_TABLE": TipoObjeto.STREAMING_TABLE,
    "VIEW": TipoObjeto.VISTA_SQL,
    "MATERIALIZED_VIEW": TipoObjeto.VISTA_MATERIALIZADA,
}


@dataclass(frozen=True)
class ObjetoUcDescubierto:
    """Objeto de Unity Catalog descubierto con la credencial OBO.

    Attributes:
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str): nombre calificado (`catalogo`, `catalogo.esquema`
            o `catalogo.esquema.tabla`), normalizado después por el dominio.
    """

    tipo: TipoObjeto
    identificador: str


class ErrorListadoUc(RuntimeError):
    """Fallo del listado UC con la credencial OBO, distinguible del vacío."""


class DescubridorUc:
    """Lista objetos de Unity Catalog con la credencial OBO del llamante.

    Attributes:
        cliente: cliente SDK (`WorkspaceClient`) OBO, con los servicios
            `catalogs`, `schemas` y `tables` (cada uno con `list(...)`).
    """

    def __init__(self, cliente, limite=None, registrador_errores=None):
        """Inicializa el descubridor con el cliente OBO inyectado.

        Args:
            cliente: `WorkspaceClient` OBO con `catalogs`, `schemas` y `tables`.
            limite (int | None): tope de elementos por listado; None no limita.
            registrador_errores (BitacoraErrores | None): bitácora opcional.

        Raises:
            ValueError: si el cliente no expone los servicios UC con `list`.
        """
        self._validar_cliente(cliente)
        self._cliente = cliente
        self._limite = limite
        self._registrador_errores = registrador_errores

    @staticmethod
    def _validar_cliente(cliente):
        """Valida que el cliente exponga los servicios UC con `list`."""
        if cliente is None:
            raise ValueError(
                "Se requiere un cliente (WorkspaceClient OBO) para listar "
                "objetos de Unity Catalog."
            )
        for nombre_servicio in ("catalogs", "schemas", "tables"):
            servicio = getattr(cliente, nombre_servicio, None)
            if servicio is None or not hasattr(servicio, "list"):
                raise ValueError(
                    f"El cliente debe exponer el servicio "
                    f"'{nombre_servicio}' con el método 'list()'."
                )

    def ListarCatalogos(self):
        """Lista los catálogos del workspace (nombre calificado de una parte).

        Returns:
            tuple[ObjetoUcDescubierto, ...]: catálogos, en el orden del servicio.
        """
        return self._Listar(
            lambda: self._cliente.catalogs.list(),
            _ObjetoDesdeCatalogo,
        )

    def ListarEsquemas(self, catalogo):
        """Lista los esquemas del catálogo indicado (nombre `catalogo.esquema`).

        Args:
            catalogo (str): nombre del catálogo que acota el listado.

        Returns:
            tuple[ObjetoUcDescubierto, ...]: esquemas, en el orden del servicio.
        """
        return self._Listar(
            lambda: self._cliente.schemas.list(catalog_name=catalogo),
            _ObjetoDesdeEsquema(catalogo),
        )

    def ListarTablas(self, catalogo, esquema):
        """Lista las tablas del par catálogo/esquema (`catalogo.esquema.tabla`).

        Args:
            catalogo (str): catálogo que acota el listado.
            esquema (str): esquema que acota el listado.

        Returns:
            tuple[ObjetoUcDescubierto, ...]: tablas tabulares soportadas, en el
                orden del servicio, clasificadas por `table_type`.
        """
        return self._Listar(
            lambda: self._cliente.tables.list(
                catalog_name=catalogo, schema_name=esquema
            ),
            _ObjetoDesdeTabla(catalogo, esquema),
        )

    def _Listar(self, operacion, traductor):
        """Materializa el listado caminando el iterador y lo acota por límite.

        Args:
            operacion (callable): invocación `list(...)` del servicio.
            traductor (callable): traduce cada registro a `ObjetoUcDescubierto`
                o None (para descartarlo).

        Returns:
            tuple[ObjetoUcDescubierto, ...]: registros válidos, en orden, sin
                exceder `limite`.

        Raises:
            ErrorListadoUc: si el listado falla (transporte/UC), con el detalle
                sin credenciales y causa encadenada.
        """
        try:
            registros = list(operacion())
        except Exception as excepcion:  # noqa: BLE001 - se traduce y tipifica
            self._RegistrarFallo(excepcion)
            raise ErrorListadoUc(
                f"[{MODULO_DESCUBRIMIENTO_UC}] No se pudo listar los objetos "
                f"de Unity Catalog con la credencial OBO: {excepcion}"
            ) from excepcion

        resultado = tuple(
            objeto
            for objeto in (traductor(registro) for registro in registros)
            if objeto is not None
        )
        if self._limite is not None:
            return resultado[: self._limite]
        return resultado

    def _RegistrarFallo(self, excepcion):
        """Registra el fallo del listado en la bitácora sin propagarlo."""
        if self._registrador_errores is None:
            return
        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_DESCUBRIMIENTO_UC,
                usuario=None,
                contexto="listado UC de objetos con la credencial OBO",
            )
        except Exception:  # noqa: BLE001 - la bitácora nunca propaga
            return


def _TextoONulo(valor):
    """Normaliza un texto opcional: recorta y convierte vacío en None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _ObjetoDesdeCatalogo(registro):
    """Traduce un catálogo a `ObjetoUcDescubierto` (o None)."""
    nombre = _TextoONulo(getattr(registro, "name", None))
    if nombre is None:
        return None
    return ObjetoUcDescubierto(tipo=TipoObjeto.CATALOGO, identificador=nombre)


def _ObjetoDesdeEsquema(catalogo):
    """Devuelve el traductor de esquemas acotado a un catálogo."""

    def traducir(registro):
        nombre = _TextoONulo(getattr(registro, "name", None))
        if nombre is None:
            return None
        return ObjetoUcDescubierto(
            tipo=TipoObjeto.ESQUEMA,
            identificador=f"{catalogo}.{nombre}",
        )

    return traducir


def _ObjetoDesdeTabla(catalogo, esquema):
    """Devuelve el traductor de tablas acotado a catálogo/esquema, por table_type."""

    def traducir(registro):
        nombre = _TextoONulo(getattr(registro, "name", None))
        if nombre is None:
            return None
        tipo = _TipoTabla(registro)
        if tipo is None:
            return None
        return ObjetoUcDescubierto(
            tipo=tipo,
            identificador=f"{catalogo}.{esquema}.{nombre}",
        )

    return traducir


def _TipoTabla(registro):
    """Clasifica el `table_type` del SDK al dominio, o None si no es tabular.

    Args:
        registro: registro de tabla del SDK con atributo `table_type`.

    Returns:
        TipoObjeto | None: tipo tabular del dominio, o None para descartarlo.
    """
    table_type = getattr(registro, "table_type", None)
    if table_type is None:
        return None
    valor = getattr(table_type, "value", None)
    if valor is None:
        valor = table_type
    return TABLE_TYPE_A_TIPO_OBJETO.get(str(valor).upper())
