"""Definiciones declarativas y constructor de DDL idempotente (capability `app-persistence`).

Este módulo concentra TODO el DDL de la aplicación como dato declarativo,
siguiendo el estándar del proyecto (README.md - Estándar de desarrollo) y el
design.md D4 del change `persistencia-bitacora`:

- **Idempotente**: toda sentencia usa `IF NOT EXISTS`; re-ejecutar el DDL no
  falla ni altera los objetos existentes.
- **SQL en mayúsculas**: las palabras reservadas van en mayúsculas (estándar).
- **Sin hardcodeo**: el catálogo se parametriza (lo aporta la configuración,
  `config/app_properties.json`); el esquema dedicado y las propiedades delta
  son constantes de este módulo. Ninguna sentencia repite valores a mano.
- **Propiedades delta del estándar**: toda tabla se crea con liquid clustering
  (`CLUSTER BY`), change data feed, optimizeWrite y autoCompact.
- **Bitácora de errores con STRUCT**: el detalle del error se declara como
  `STRUCT<...>` (regla del estándar).

El DDL se genera aquí como texto; su ejecución contra la sesión Spark la hace
el inicializador (tarea 3.2), que recibe la sesión por inyección (design.md D3).
"""

from dataclasses import dataclass


# Esquema dedicado de la aplicación, creado idempotentemente en el catálogo
# configurado. Es una constante del proyecto (README.md - Persistencia), no un
# valor de entorno, por eso vive aquí y no en `config/app_properties.json`.
ESQUEMA_APLICACION = "control_acceso_app"

# Propiedades delta obligatorias en TODA tabla de la aplicación (README.md -
# Estándar de desarrollo). Se declaran como dato (tupla de pares nombre-valor)
# para que el constructor las inyecte sin repetirlas por sentencia y para que
# una prueba pueda verificar exactamente este conjunto.
PROPIEDADES_DELTA_OBLIGATORIAS = (
    ("delta.enableChangeDataFeed", "true"),
    ("delta.autoOptimize.optimizeWrite", "true"),
    ("delta.autoOptimize.autoCompact", "true"),
)

# Comentario del esquema dedicado (documentación en el propio catálogo).
COMENTARIO_ESQUEMA = (
    "Esquema dedicado de la aplicacion de control de accesos centralizado: "
    "tablas delta de bitacora y demas persistencia de la aplicacion."
)

# Tipo STRUCT del detalle de la bitácora de errores (design.md D6). Se declara
# como constante para que el contrato del STRUCT sea único y verificable.
TIPO_STRUCT_DETALLE_ERROR = (
    "STRUCT<tipo_excepcion: STRING, mensaje: STRING, traza: STRING, "
    "contexto: STRING>"
)


@dataclass(frozen=True)
class Columna:
    """Definición declarativa de una columna de tabla delta.

    Attributes:
        nombre (str): nombre de la columna (snake_case, estándar del proyecto).
        tipo (str): tipo SQL de la columna (por ejemplo, `STRING`, `TIMESTAMP`
            o un `STRUCT<...>`).
        nullable (bool): si la columna admite valores nulos. Las llaves
            primarias y campos obligatorios se declaran `nullable=False`
            (rendirán `NOT NULL` en el DDL).
    """

    nombre: str
    tipo: str
    nullable: bool = True

    def Ddl(self):
        """Renderiza la columna como fragmento de DDL (`nombre TIPO [NOT NULL]`).

        Returns:
            str: definición SQL de la columna, con un único espacio entre el
            nombre y el tipo (para mantener el DDL estable y legible).
        """
        sufijo_nulabilidad = "" if self.nullable else " NOT NULL"
        return f"{self.nombre} {self.tipo}{sufijo_nulabilidad}"


@dataclass(frozen=True)
class DefinicionTabla:
    """Definición declarativa de una tabla delta de la aplicación.

    Attributes:
        nombre (str): nombre de la tabla dentro del esquema dedicado.
        columnas (tuple[Columna, ...]): columnas en orden de declaración.
        cluster_por (tuple[str, ...]): columnas de liquid clustering
            (`CLUSTER BY`). En las bitácoras es la marca de tiempo, que es la
            columna dominante de consulta (design.md D6).
        comentario (str): comentario de la tabla (documentación en el catálogo).
        claves_primarias (tuple[str, ...]): columnas de la llave primaria de la
            tabla. Delta no la enforcea: la verifican los helpers de integridad
            antes de cada escritura (design.md D5).
    """

    nombre: str
    columnas: tuple
    cluster_por: tuple
    comentario: str
    claves_primarias: tuple = ()


# Bitácora de eventos generales: registra toda la actividad de la aplicación
# con el usuario que provoca cada evento (identidad OBO cuando exista, vacío
# explícito mientras tanto). Ver spec `audit-logging` y design.md D6.
DEFINICION_BITACORA_EVENTOS = DefinicionTabla(
    nombre="bitacora_eventos",
    columnas=(
        Columna("id_evento", "STRING", nullable=False),
        Columna("marca_tiempo", "TIMESTAMP", nullable=False),
        Columna("usuario", "STRING", nullable=True),
        Columna("accion", "STRING", nullable=False),
        Columna("detalle", "STRING", nullable=True),
        Columna("resultado", "STRING", nullable=True),
    ),
    cluster_por=("marca_tiempo",),
    comentario=(
        "Bitacora de eventos generales de la aplicacion: toda actividad con "
        "el usuario que la provoca."
    ),
    claves_primarias=("id_evento",),
)

# Bitácora de errores: registra todo error controlado vía try/except con el
# máximo detalle en un campo STRUCT (design.md D6). Ver spec `audit-logging`.
DEFINICION_BITACORA_ERRORES = DefinicionTabla(
    nombre="bitacora_errores",
    columnas=(
        Columna("id_error", "STRING", nullable=False),
        Columna("marca_tiempo", "TIMESTAMP", nullable=False),
        Columna("usuario", "STRING", nullable=True),
        Columna("modulo", "STRING", nullable=False),
        Columna("detalle", TIPO_STRUCT_DETALLE_ERROR, nullable=False),
    ),
    cluster_por=("marca_tiempo",),
    comentario=(
        "Bitacora de errores de la aplicacion: detalle del error en campo "
        "STRUCT (tipo, mensaje, traza y contexto)."
    ),
    claves_primarias=("id_error",),
)

# Registro declarativo de todas las tablas de la aplicación en este change. El
# inicializador (tarea 3.2) itera esta tupla para crearlas idempotentemente;
# agregar una tabla nueva en un change futuro es agregar una entrada aquí.
DEFINICIONES_TABLAS_APLICACION = (
    DEFINICION_BITACORA_EVENTOS,
    DEFINICION_BITACORA_ERRORES,
)


class ConstructorDdl:
    """Construye las sentencias SQL idempotentes de esquema y tablas delta.

    Recibe el catálogo por parámetro (lo aporta la configuración de la
    aplicación) y usa el esquema dedicado y las propiedades delta como
    constantes del módulo, de modo que ninguna sentencia hardcodea valores
    (regla estricta No HardCoded). Es una clase de lógica pura: genera texto
    SQL, no lo ejecuta (la ejecución es del inicializador, con la sesión
    Spark inyectada).

    Attributes:
        catalogo (str): catálogo de Unity Catalog configurado.
        esquema (str): esquema dedicado de la aplicación.

    Example:
        >>> constructor = ConstructorDdl(catalogo="control")
        >>> constructor.DdlEsquema()
        'CREATE SCHEMA IF NOT EXISTS control.control_acceso_app ...'
    """

    def __init__(self, catalogo, esquema=ESQUEMA_APLICACION):
        """Inicializa el constructor con el catálogo y el esquema dedicado.

        Args:
            catalogo (str): catálogo configurado (de `config/app_properties.json`).
            esquema (str): esquema dedicado; por defecto `control_acceso_app`.

        Raises:
            ValueError: si el catálogo o el esquema están vacíos o son nulos
                (no se puede construir un nombre calificado válido).
        """
        if not catalogo or not str(catalogo).strip():
            raise ValueError(
                "El catálogo de la configuración no puede estar vacío; se "
                "requiere para calificar el esquema dedicado de la aplicación."
            )
        if not esquema or not str(esquema).strip():
            raise ValueError(
                "El esquema dedicado no puede estar vacío."
            )
        self.catalogo = catalogo
        self.esquema = esquema

    @property
    def nombre_calificado_esquema(self):
        """Nombre totalmente calificado del esquema dedicado.

        Returns:
            str: `<catalogo>.<esquema>`.
        """
        return f"{self.catalogo}.{self.esquema}"

    def DdlEsquema(self):
        """Genera el `CREATE SCHEMA IF NOT EXISTS` idempotente del esquema.

        Returns:
            str: sentencia SQL en mayúsculas que crea el esquema dedicado en el
            catálogo configurado, sin fallar si ya existe.
        """
        return (
            f"CREATE SCHEMA IF NOT EXISTS {self.nombre_calificado_esquema}\n"
            f"COMMENT '{COMENTARIO_ESQUEMA}'"
        )

    def NombreTablaCalificado(self, definicion):
        """Nombre totalmente calificado de una tabla del esquema dedicado.

        Args:
            definicion (DefinicionTabla): definición de la tabla.

        Returns:
            str: `<catalogo>.<esquema>.<tabla>`.
        """
        return f"{self.nombre_calificado_esquema}.{definicion.nombre}"

    def DdlTabla(self, definicion):
        """Genera el `CREATE TABLE IF NOT EXISTS` idempotente de una tabla delta.

        La sentencia incluye: columnas declaradas, formato delta, comentario,
        liquid clustering (`CLUSTER BY`) y las tres propiedades delta del
        estándar (CDF, optimizeWrite, autoCompact).

        Args:
            definicion (DefinicionTabla): definición declarativa de la tabla.

        Returns:
            str: sentencia SQL en mayúsculas, idempotente, con liquid
            clustering y propiedades delta habilitadas desde la creación.
        """
        # Columnas renderizadas una por línea, indentadas para legibilidad.
        columnas_ddl = ",\n".join(
            f"  {columna.Ddl()}" for columna in definicion.columnas
        )

        # Liquid clustering: columnas declaradas en la definición.
        cluster_por = ", ".join(definicion.cluster_por)

        # Propiedades delta del estándar, como pares 'nombre'='valor'.
        propiedades = ", ".join(
            f"'{nombre}'='{valor}'"
            for nombre, valor in PROPIEDADES_DELTA_OBLIGATORIAS
        )

        nombre_calificado = self.NombreTablaCalificado(definicion)

        return (
            f"CREATE TABLE IF NOT EXISTS {nombre_calificado} (\n"
            f"{columnas_ddl}\n"
            f")\n"
            f"USING DELTA\n"
            f"COMMENT '{definicion.comentario}'\n"
            f"CLUSTER BY ({cluster_por})\n"
            f"TBLPROPERTIES ({propiedades})"
        )
