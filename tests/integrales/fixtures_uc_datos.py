"""Fábrica de fixtures autocontenidas para las integrales de grants-uc-datos.

Infraestructura EXCLUSIVA de la capa integral (marker `free`, tarea 5.1 del
change `grants-uc-datos`): crea, por corrida, un catálogo con nombre único y un
esquema dentro, con un objeto de cada tipo del plano de datos soportado por el
change (tabla delta, vista SQL, volumen, modelo ML, vista materializada y
streaming table), y limpia TODO lo creado al final con `DROP CATALOG ... CASCADE`
(que arrastra esquema, objetos y grants), de modo que ninguna prueba deje estado
residual en el workspace.

Creación best-effort por tipo: si Free Edition no puede crear un tipo (por
ejemplo, una vista materializada o una streaming table), se registra el motivo
en `no_creados` y la prueba que lo consuma lo omite; el humano confirmó que la
MV funciona con el SQL warehouse serverless (o Lakeflow Declarative Pipelines
con compute serverless) y que la streaming table se crea con cualquier compute,
y autorizó el fallback en `andresAzureDev` si Free Edition presentara error o
limitación (ver design - riesgos).

Convención de nombres: infraestructura de pruebas con el mismo estándar del
proyecto (clases y constantes en PascalCase/MAYÚSCULAS, comentarios en español).
"""

import uuid
from dataclasses import dataclass

from control_accesos.dominio.enumeraciones import TipoObjeto


@dataclass(frozen=True)
class FixtureObjeto:
    """Un objeto securable creado por la fábrica, listo para probar.

    Attributes:
        tipo (TipoObjeto): tipo del objeto dentro de `TipoObjeto`.
        nombre (str): nombre simple del objeto (última parte del calificado).
        privilegio (str): privilegio representativo a otorgar y verificar.
        calificado (str): identificador completo del objeto (catálogo/esquema/nombre).
    """

    tipo: TipoObjeto
    nombre: str
    privilegio: str
    calificado: str


class FixturesUcDatos:
    """Crea y destruye el catálogo/esquema/objetos de pruebas del change.

    Attributes:
        catalogo (str): nombre único del catálogo de la corrida.
        esquema_calificado (str): `catalogo.esquema`.
        objetos (dict[TipoObjeto, FixtureObjeto]): objetos creados con éxito.
        no_creados (dict[TipoObjeto, str]): tipos no creados, con el motivo.
    """

    # Nombre simple del esquema de trabajo dentro del catálogo de la corrida.
    NOMBRE_ESQUEMA = "esq_grants"

    def __init__(self, sesion):
        """Inicializa la fábrica con la sesión SQL real del workspace.

        Args:
            sesion (SesionSqlDatabricks): sesión que ejecuta el DDL real.
        """
        self.sesion = sesion
        self.catalogo = f"c4_grants_{uuid.uuid4().hex[:8]}"
        self.esquema_calificado = f"{self.catalogo}.{self.NOMBRE_ESQUEMA}"
        self.objetos = {}
        self.no_creados = {}

    def Crear(self):
        """Crea el catálogo, el esquema y un objeto por cada tipo soportable."""
        # Catálogo y esquema: son a la vez contenedores y objetivos de prueba.
        self.sesion.sql(f"CREATE CATALOG `{self.catalogo}`")
        self.objetos[TipoObjeto.CATALOGO] = FixtureObjeto(
            tipo=TipoObjeto.CATALOGO,
            nombre=self.catalogo,
            privilegio="USE CATALOG",
            calificado=self.catalogo,
        )
        self.sesion.sql(f"CREATE SCHEMA `{self.catalogo}`.`{self.NOMBRE_ESQUEMA}`")
        self.objetos[TipoObjeto.ESQUEMA] = FixtureObjeto(
            tipo=TipoObjeto.ESQUEMA,
            nombre=self.NOMBRE_ESQUEMA,
            privilegio="USE SCHEMA",
            calificado=self.esquema_calificado,
        )

        # La tabla delta se crea primero: las vistas materializadas y el modelo
        # la referencian en sus SELECT.
        self._Crear(
            TipoObjeto.TABLA_DELTA,
            "tabla_grant",
            "SELECT",
            # CDF habilitada: sirve como origen de la streaming table (STREAM()).
            f"CREATE TABLE {self._Sql('tabla_grant')} (id INT, nombre STRING) "
            "TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')",
        )
        self._Crear(
            TipoObjeto.VISTA_SQL,
            "vista_grant",
            "SELECT",
            f"CREATE VIEW {self._Sql('vista_grant')} "
            "AS SELECT 1 AS id, 'a' AS nombre",
        )
        self._Crear(
            TipoObjeto.VOLUMEN,
            "vol_grant",
            "READ VOLUME",
            f"CREATE VOLUME {self._Sql('vol_grant')}",
        )
        self._Crear(
            TipoObjeto.VISTA_MATERIALIZADA,
            "mv_grant",
            "SELECT",
            f"CREATE MATERIALIZED VIEW {self._Sql('mv_grant')} "
            f"AS SELECT id, nombre FROM {self._Sql('tabla_grant')}",
        )
        self._Crear(
            TipoObjeto.STREAMING_TABLE,
            "st_grant",
            "SELECT",
            # Una streaming table se crea SIEMPRE desde una consulta de
            # streaming (`FROM STREAM(<origen>)` con CDF en el origen); el motor
            # rechaza el DDL sin consulta y la CTAS sin STREAM (códigos
            # STREAMING_TABLE_OPERATION_NOT_ALLOWED / STREAMING_TABLE_QUERY_INVALID).
            f"CREATE STREAMING TABLE {self._Sql('st_grant')} "
            f"AS SELECT id, nombre FROM STREAM({self._Sql('tabla_grant')})",
        )
        # Los modelos de ML (registered models) se registran vía MLflow/ML, no
        # con SQL `CREATE MODEL` (inexistente en un SQL warehouse): este fixture
        # se omite y su grant queda cubierto por las pruebas unitarias y
        # funcionales (construcción y parseo de MODEL).
        self._Crear(
            TipoObjeto.MODELO_ML,
            "modelo_grant",
            "EXECUTE",
            f"CREATE MODEL {self._Sql('modelo_grant')} "
            f"AS SELECT id FROM {self._Sql('tabla_grant')}",
        )

    def _Sql(self, nombre):
        """Devuelve el nombre calificado de un objeto con cada parte entre backticks.

        Args:
            nombre (str): nombre simple del objeto dentro del esquema.

        Returns:
            str: `catálogo`.`esquema`.`nombre`, listo para una instrucción SQL.
        """
        return f"`{self.catalogo}`.`{self.NOMBRE_ESQUEMA}`.`{nombre}`"

    def _Crear(self, tipo, nombre, privilegio, sentencia):
        """Crea un objeto best-effort y registra el resultado.

        Args:
            tipo (TipoObjeto): tipo del objeto.
            nombre (str): nombre simple dentro del esquema.
            privilegio (str): privilegio representativo a probar.
            sentencia (str): DDL de creación del objeto.
        """
        calificado = f"{self.esquema_calificado}.{nombre}"
        try:
            self.sesion.sql(sentencia)
            self.objetos[tipo] = FixtureObjeto(
                tipo=tipo, nombre=nombre, privilegio=privilegio,
                calificado=calificado,
            )
        except Exception as error:  # noqa: BLE001 - best-effort por tipo
            self.no_creados[tipo] = f"{type(error).__name__}: {error}"

    def Objeto(self, tipo):
        """Devuelve el fixture de un tipo, o None si no se creó.

        Args:
            tipo (TipoObjeto): tipo buscado.

        Returns:
            FixtureObjeto | None: fixture del tipo, o None.
        """
        return self.objetos.get(tipo)

    def Limpiar(self):
        """Elimina el catálogo y todo lo que contiene (esquema, objetos, grants).

        `DROP CATALOG ... CASCADE` arrastra esquema, tablas, vistas, volúmenes,
        modelos y streaming tables, y con ellos los grants vigentes sobre esos
        securables: no queda estado residual en el workspace.
        """
        try:
            self.sesion.sql(f"DROP CATALOG IF EXISTS `{self.catalogo}` CASCADE")
        except Exception as error:  # noqa: BLE001 - limpieza best-effort
            self.no_creados["_limpieza"] = f"{type(error).__name__}: {error}"
