"""Helpers de integridad de llaves garantizada desde el código (capability `app-persistence`).

Delta Lake no enforcea llave primaria, llaves foráneas ni integridad
referencial, así que el estándar del proyecto exige garantizarlas desde el
código de la aplicación (README.md - Estándar de desarrollo; design.md D5).

Este módulo implementa esas validaciones con operaciones MASIVAS de PySpark
(groupBy + count, joins inner/left-anti sobre tablas delta), sin ciclos por
fila:

- **Unicidad de llave primaria**: dentro del lote a escribir y contra la tabla
  destino (una PK ya existente no puede repetirse).
- **Existencia de referencias foráneas**: cada valor no nulo de las columnas
  hijas debe existir en la tabla padre (semántica SQL estándar: las
  referencias nulas no son violaciones).

Toda violación lanza `ErrorIntegridad` con el detalle de las llaves
infractoras ANTES de escribir: ante una violación no se escribe ningún
registro del lote (el verificador se invoca siempre antes que la escritura).
"""

from dataclasses import dataclass

from control_accesos.persistencia.errores import ErrorIntegridad

# Límite de llaves infractoras incluidas en el mensaje de error: suficiente
# para diagnosticar sin desbordar la bitácora cuando un lote grande falla.
MAX_LLAVES_REPORTADAS = 10


@dataclass(frozen=True)
class ReferenciaForanea:
    """Declaración de una referencia de llave foránea entre tablas de la app.

    Attributes:
        tabla_padre (str): nombre de la tabla padre dentro del esquema dedicado.
        columnas_hija (tuple[str, ...]): columnas de la tabla hija que portan
            la referencia.
        columnas_padre (tuple[str, ...]): columnas de la tabla padre referidas,
            en el mismo orden que `columnas_hija`.

    Raises:
        ValueError: si las tuplas de columnas no tienen la misma longitud o
            están vacías (la referencia no sería verificable).
    """

    tabla_padre: str
    columnas_hija: tuple
    columnas_padre: tuple

    def __post_init__(self):
        """Valida la forma de la declaración al construir la referencia."""
        if not self.columnas_hija or not self.columnas_padre:
            raise ValueError(
                "Una referencia foránea debe declarar al menos una columna "
                "hija y una columna padre."
            )
        if len(self.columnas_hija) != len(self.columnas_padre):
            raise ValueError(
                "Las columnas hija y padre de una referencia foránea deben "
                f"tener la misma longitud: {self.columnas_hija} vs "
                f"{self.columnas_padre}."
            )


class VerificadorIntegridad:
    """Verifica llave primaria y referencias foráneas con operaciones masivas.

    Recibe la sesión Spark por inyección (design.md D3). Sus métodos lanzan
    `ErrorIntegridad` ante cualquier violación, con el detalle de las llaves
    infractoras (acotado por `MAX_LLAVES_REPORTADAS`).

    Example:
        >>> verificador = VerificadorIntegridad(sesion=sesion)
        >>> verificador.ValidarClavePrimaria(lote, "catalogo.esquema.tabla",
        ...                                  ("id_evento",))
    """

    def __init__(self, sesion):
        """Inicializa el verificador con la sesión Spark inyectada.

        Args:
            sesion: sesión Spark que ejecuta las operaciones masivas.

        Raises:
            ValueError: si no se recibe sesión.
        """
        if sesion is None:
            raise ValueError(
                "Se requiere una sesión Spark para verificar la integridad."
            )
        self.sesion = sesion

    def ValidarClavePrimaria(self, marco_lote, nombre_tabla_destino, claves_primarias):
        """Verifica la unicidad de la llave primaria del lote.

        Comprueba, en este orden y con operaciones masivas:

        1. que el lote no contenga llaves primarias duplicadas entre sí
           (`groupBy` + `count`);
        2. que ninguna llave primaria del lote exista ya en la tabla destino
           (join `inner` del lote con la tabla por las columnas clave).

        Args:
            marco_lote (pyspark.sql.DataFrame): lote que se pretende escribir.
            nombre_tabla_destino (str): nombre calificado de la tabla destino.
            claves_primarias (tuple[str, ...]): columnas de la llave primaria.

        Raises:
            ErrorIntegridad: si hay llaves duplicadas en el lote o contra la
                tabla destino. El mensaje detalla las llaves infractoras.
        """
        if not claves_primarias:
            raise ValueError(
                "La verificación de llave primaria requiere al menos una "
                "columna clave."
            )

        columnas_clave = list(claves_primarias)

        # Import perezoso: pyspark no existe en el runtime de la App (D5).
        from pyspark.sql import functions as funciones_spark

        # 1) Unicidad DENTRO del lote: agrupar por la clave y contar; cualquier
        #    grupo con más de una fila es una llave duplicada.
        duplicadas_en_lote = (
            marco_lote.groupBy(*columnas_clave)
            .count()
            .where(funciones_spark.col("count") > 1)
            .select(*columnas_clave)
            .limit(MAX_LLAVES_REPORTADAS)
            .collect()
        )
        if duplicadas_en_lote:
            raise ErrorIntegridad(
                f"Violación de llave primaria en el lote destinado a "
                f"'{nombre_tabla_destino}': llaves duplicadas DENTRO del lote "
                f"{self._FormatearLlaves(duplicadas_en_lote, columnas_clave)}. "
                f"No se escribió ningún registro."
            )

        # 2) Unicidad CONTRA la tabla destino: join inner por la clave; toda
        #    fila resultante es una llave del lote que ya existe en la tabla.
        tabla_destino = self.sesion.table(nombre_tabla_destino)
        ya_existentes = (
            marco_lote.select(*columnas_clave)
            .join(
                tabla_destino.select(*columnas_clave),
                on=columnas_clave,
                how="inner",
            )
            .distinct()
            .limit(MAX_LLAVES_REPORTADAS)
            .collect()
        )
        if ya_existentes:
            raise ErrorIntegridad(
                f"Violación de llave primaria contra la tabla destino "
                f"'{nombre_tabla_destino}': llaves del lote que YA EXISTEN en "
                f"la tabla {self._FormatearLlaves(ya_existentes, columnas_clave)}. "
                f"No se escribió ningún registro."
            )

    def ValidarReferenciasForaneas(
        self, marco_lote, referencias_foraneas, resolvedor_nombre_tabla
    ):
        """Verifica la existencia de las referencias foráneas del lote.

        Para cada referencia declarada, aplica un join `left_anti` del lote
        (filas con referencia no nula) contra la tabla padre: las filas
        resultantes son referencias huérfanas (el valor no existe en el padre).
        Siguiendo la semántica SQL estándar, las referencias nulas NO son
        violaciones.

        Args:
            marco_lote (pyspark.sql.DataFrame): lote que se pretende escribir.
            referencias_foraneas (tuple[ReferenciaForanea, ...]): referencias
                declaradas de la tabla hija.
            resolvedor_nombre_tabla (Callable[[str], str]): función que
                resuelve el nombre calificado de la tabla padre (lo aporta la
                capa de persistencia, dueña del catálogo y el esquema).

        Raises:
            ErrorIntegridad: si alguna referencia del lote no existe en su
                tabla padre. El mensaje detalla los valores huérfanos.
        """
        for referencia in referencias_foraneas:
            columnas_hija = list(referencia.columnas_hija)
            columnas_padre = list(referencia.columnas_padre)

            # Import perezoso: pyspark no existe en el runtime de la App (D5).
            from pyspark.sql import functions as funciones_spark

            # Se conservan solo las filas con referencia no nula en TODAS las
            # columnas hijas (nulo = sin referencia, no es violación).
            con_referencia = marco_lote
            for columna in columnas_hija:
                con_referencia = con_referencia.where(
                    funciones_spark.col(columna).isNotNull()
                )

            # Tabla padre proyectada a sus columnas referidas y sin duplicados.
            nombre_padre = resolvedor_nombre_tabla(referencia.tabla_padre)
            padre = (
                self.sesion.table(nombre_padre)
                .select(*columnas_padre)
                .distinct()
                .alias("padre")
            )

            # Join left_anti por los pares hija/padre: devuelve las filas del
            # lote cuya referencia NO existe en el padre (huérfanas).
            condiciones = [
                funciones_spark.col(f"hija.{columna_hija}")
                == funciones_spark.col(f"padre.{columna_padre}")
                for columna_hija, columna_padre in zip(
                    columnas_hija, columnas_padre
                )
            ]
            huerfanas = (
                con_referencia.alias("hija")
                .join(padre, on=condiciones, how="left_anti")
                .select(*columnas_hija)
                .distinct()
                .limit(MAX_LLAVES_REPORTADAS)
                .collect()
            )
            if huerfanas:
                raise ErrorIntegridad(
                    f"Violación de integridad referencial en la tabla hija: "
                    f"las referencias {self._FormatearLlaves(huerfanas, columnas_hija)} "
                    f"de las columnas {columnas_hija} NO EXISTEN en la tabla "
                    f"padre '{nombre_padre}'. No se escribió ningún registro."
                )

    @staticmethod
    def _FormatearLlaves(filas, columnas):
        """Formatea las llaves infractoras para el mensaje de error.

        Args:
            filas (list[pyspark.sql.Row]): filas recolectadas con las llaves.
            columnas (list[str]): nombres de las columnas de la llave.

        Returns:
            str: representación legible de las llaves, por ejemplo
            `[('id_1',), ('id_2',)]`.
        """
        return str([tuple(fila[columna] for columna in columnas) for fila in filas])
