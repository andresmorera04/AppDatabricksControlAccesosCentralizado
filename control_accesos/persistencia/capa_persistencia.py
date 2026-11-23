"""Capa de persistencia con escritura masiva (capability `app-persistence`).

Punto único de escritura en las tablas delta de la aplicación (design.md D3):
los escritores de bitácora y cualquier consumidor futuro persisten sus lotes a
través de esta clase, que usa operaciones masivas de PySpark (una escritura
`insertInto` por lote, nunca ciclos por fila), cumpliendo el estándar "PySpark
al máximo".

La sesión Spark se recibe por inyección (local en pruebas, provista por el
entorno en la Databricks App) y el catálogo proviene de la configuración de la
aplicación: esta clase no hardcodea ningún nombre (regla No HardCoded).

Todo fallo de escritura se controla con try/except y se traduce a
`ErrorEscrituraPersistencia` con mensaje explícito en español que conserva la
causa original encadenada, de modo que pueda registrarse en la bitácora de
errores (capability `audit-logging`).
"""

from control_accesos.persistencia.ddl import ConstructorDdl
from control_accesos.persistencia.errores import ErrorEscrituraPersistencia
from control_accesos.persistencia.integridad import VerificadorIntegridad


class CapaPersistencia:
    """Escribe lotes de registros en las tablas delta de la aplicación.

    Attributes:
        sesion: sesión Spark inyectada.
        configuracion (ConfiguracionApp): configuración de la aplicación.
        constructor_ddl (ConstructorDdl): se reutiliza para resolver los nombres
            calificados `<catalogo>.<esquema>.<tabla>` sin duplicar constantes.

    Example:
        >>> capa = CapaPersistencia(sesion=sesion, configuracion=configuracion)
        >>> capa.Escribir(marco_lote, "bitacora_eventos")
    """

    def __init__(self, sesion, configuracion):
        """Inicializa la capa con la sesión Spark y la configuración inyectadas.

        Args:
            sesion: sesión Spark que ejecuta las operaciones masivas.
            configuracion (ConfiguracionApp): configuración de la aplicación;
                se usa su atributo `catalogo` para calificar las tablas.

        Raises:
            ValueError: si no se recibe sesión o configuración.
        """
        if sesion is None:
            raise ValueError(
                "Se requiere una sesión Spark para la capa de persistencia."
            )
        if configuracion is None:
            raise ValueError(
                "Se requiere la configuración de la aplicación para conocer "
                "el catálogo donde viven las tablas."
            )

        self.sesion = sesion
        self.configuracion = configuracion
        # Se reutiliza el constructor de DDL solo como fuente de los nombres
        # calificados (catálogo + esquema dedicado), sin duplicar constantes.
        self.constructor_ddl = ConstructorDdl(catalogo=configuracion.catalogo)

    def NombreTablaCalificado(self, nombre_tabla):
        """Resuelve el nombre totalmente calificado de una tabla de la aplicación.

        Args:
            nombre_tabla (str): nombre de la tabla dentro del esquema dedicado.

        Returns:
            str: `<catalogo>.<esquema>.<tabla>`.
        """
        return (
            f"{self.constructor_ddl.nombre_calificado_esquema}.{nombre_tabla}"
        )

    def Escribir(self, marco_datos, nombre_tabla):
        """Escribe un lote de registros en una tabla delta existente (append).

        Operación masiva: el lote se inserta completo en una sola escritura
        `insertInto`, sin recorrer filas con ciclos. Antes de escribir se
        reordena el DataFrame a las columnas de la tabla destino (resolución
        temprana de la tabla y de sus columnas, que a la vez valida que la
        tabla exista).

        Args:
            marco_datos (pyspark.sql.DataFrame): lote de registros a escribir;
                sus columnas deben cubrir las de la tabla destino.
            nombre_tabla (str): nombre de la tabla dentro del esquema dedicado.

        Returns:
            str: nombre calificado de la tabla donde se escribió el lote.

        Raises:
            ErrorEscrituraPersistencia: si la tabla destino no existe, si el
                lote no cubre sus columnas o si la operación de escritura falla
                por cualquier causa externa. El mensaje indica la tabla y
                conserva la causa original.
        """
        nombre_calificado = self.NombreTablaCalificado(nombre_tabla)

        try:
            # Resolución de la tabla destino: lanza si no existe (se traduce a
            # error controlado) y aporta el orden canónico de sus columnas.
            columnas_destino = self.sesion.table(nombre_calificado).columns

            # Se reordena el lote al orden de la tabla para que la inserción
            # posicional de `insertInto` sea exacta (operación masiva, una sola
            # pasada; sin ciclos por fila).
            marco_ordenado = marco_datos.select(*columnas_destino)

            # Escritura masiva en append (INSERT INTO sobre la tabla delta).
            marco_ordenado.write.insertInto(nombre_calificado)
        except Exception as excepcion:
            # Cualquier fallo del motor se traduce a un error explícito y
            # controlado, registrable en la bitácora de errores.
            raise ErrorEscrituraPersistencia(
                f"No se pudo escribir el lote en la tabla "
                f"'{nombre_calificado}': {excepcion}"
            ) from excepcion

        return nombre_calificado

    def EscribirConIntegridad(
        self,
        marco_datos,
        nombre_tabla,
        claves_primarias=(),
        referencias_foraneas=(),
        verificador=None,
    ):
        """Verifica la integridad del lote y, si está íntegro, lo escribe.

        Delta no enforcea llaves (README.md - Estándar de desarrollo), así que
        la escritura de la aplicación pasa siempre por aquí: primero se validan
        la unicidad de la llave primaria y las referencias foráneas declaradas
        con operaciones masivas (design.md D5) y SOLO si el lote está íntegro
        se delega en `Escribir`. Ante cualquier violación se lanza
        `ErrorIntegridad` y no se escribe ningún registro del lote.

        Args:
            marco_datos (pyspark.sql.DataFrame): lote de registros a escribir.
            nombre_tabla (str): tabla destino dentro del esquema dedicado.
            claves_primarias (tuple[str, ...]): columnas de la llave primaria
                de la tabla destino; vacío omite la verificación de PK.
            referencias_foraneas (tuple[ReferenciaForanea, ...]): referencias
                foráneas declaradas de la tabla destino; vacío omite la
                verificación de FK.
            verificador (VerificadorIntegridad | None): verificador inyectado
                (las pruebas pueden sustituirlo); por defecto se construye uno
                con la sesión de esta capa.

        Returns:
            str: nombre calificado de la tabla donde se escribió el lote.

        Raises:
            ErrorIntegridad: si el lote viola la unicidad de PK o alguna
                referencia foránea (no se escribe nada).
            ErrorEscrituraPersistencia: si la escritura masiva falla.
        """
        if verificador is None:
            verificador = VerificadorIntegridad(sesion=self.sesion)

        # 1) Validaciones masivas ANTES de escribir: toda violación lanza y el
        #    lote completo queda sin escribir (spec `app-persistence`).
        if claves_primarias:
            verificador.ValidarClavePrimaria(
                marco_datos,
                self.NombreTablaCalificado(nombre_tabla),
                claves_primarias,
            )
        if referencias_foraneas:
            # La capa aporta el resolvedor de nombres calificados: el
            # verificador no conoce el catálogo ni el esquema dedicado.
            verificador.ValidarReferenciasForaneas(
                marco_datos,
                referencias_foraneas,
                self.NombreTablaCalificado,
            )

        # 2) Lote íntegro: escritura masiva en append.
        return self.Escribir(marco_datos, nombre_tabla)
