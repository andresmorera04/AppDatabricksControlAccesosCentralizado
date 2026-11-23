"""Inicializador idempotente de la persistencia (capability `app-persistence`).

Ejecuta el DDL declarado en `ddl.py` contra la sesión Spark inyectada
(design.md D3/D4): crea el esquema dedicado `control_acceso_app` en el catálogo
configurado y, dentro de él, todas las tablas registradas.

La idempotencia no la implementa esta clase con lógica condicional propia: la
garantizan las sentencias `CREATE ... IF NOT EXISTS` del DDL. Por eso
re-ejecutar `Inicializar()` cuantas veces haga falta (en cada arranque de la
aplicación) es seguro y no altera los datos existentes, tal como exige el spec
`app-persistence`.

Todo fallo de la sesión o del catálogo se controla con try/except y se traduce
a `ErrorInicializacionPersistencia` con mensaje explícito en español, que
conserva la causa original encadenada (estándar del proyecto: errores
controlados y registrables en la bitácora de errores).
"""

from control_accesos.persistencia.ddl import (
    DEFINICIONES_TABLAS_APLICACION,
    ConstructorDdl,
)
from control_accesos.persistencia.errores import ErrorInicializacionPersistencia


class InicializadorPersistencia:
    """Crea de forma idempotente el esquema dedicado y sus tablas delta.

    Recibe la sesión Spark por inyección (nunca la crea: design.md D3) y la
    configuración de la aplicación, de donde toma el catálogo. El esquema
    dedicado y las propiedades delta provienen de las constantes del módulo
    `ddl.py`, de modo que aquí no se hardcodea ningún valor.

    Attributes:
        sesion: sesión Spark (local en pruebas, provista por el entorno en la
            Databricks App).
        configuracion (ConfiguracionApp): configuración cargada de la aplicación.
        constructor_ddl (ConstructorDdl): generador del DDL parametrizado con el
            catálogo configurado.
        definiciones (tuple[DefinicionTabla, ...]): tablas a crear.

    Example:
        >>> inicializador = InicializadorPersistencia(sesion, configuracion)
        >>> inicializador.Inicializar()
    """

    def __init__(
        self,
        sesion,
        configuracion,
        definiciones=DEFINICIONES_TABLAS_APLICACION,
    ):
        """Inicializa el creador de esquema y tablas.

        Args:
            sesion: sesión Spark inyectada que ejecutará el DDL.
            configuracion (ConfiguracionApp): configuración de la aplicación;
                se usa su atributo `catalogo` para calificar el esquema.
            definiciones (tuple[DefinicionTabla, ...]): tablas a crear; por
                defecto, el registro declarativo de las tablas de la aplicación.

        Raises:
            ValueError: si no se recibe sesión o configuración (no se puede
                inicializar la persistencia sin ambos colaboradores).
        """
        if sesion is None:
            raise ValueError(
                "Se requiere una sesión Spark para inicializar la persistencia."
            )
        if configuracion is None:
            raise ValueError(
                "Se requiere la configuración de la aplicación para conocer el "
                "catálogo donde crear el esquema dedicado."
            )

        self.sesion = sesion
        self.configuracion = configuracion
        # El DDL se parametriza con el catálogo de la configuración: ninguna
        # sentencia de este módulo lleva el catálogo escrito a mano.
        self.constructor_ddl = ConstructorDdl(catalogo=configuracion.catalogo)
        self.definiciones = definiciones

    def Inicializar(self):
        """Crea idempotentemente el esquema dedicado y todas sus tablas.

        Ejecuta primero el `CREATE SCHEMA IF NOT EXISTS` y luego el
        `CREATE TABLE IF NOT EXISTS` de cada tabla registrada. Es seguro
        llamarlo en cada arranque de la aplicación: las sentencias idempotentes
        no fallan si los objetos ya existen ni alteran sus datos.

        Returns:
            list[str]: nombres calificados de las tablas cuya creación se
            garantizó (útil para trazas y bitácora de eventos).

        Raises:
            ErrorInicializacionPersistencia: si la ejecución del DDL falla por
                una causa externa (catálogo inexistente o sin privilegios,
                sesión caída). El mensaje indica la sentencia que falló y
                conserva la causa original.
        """
        # Sentencias a ejecutar en orden: primero el esquema (contenedor),
        # luego cada tabla. Se construyen todas desde el DDL declarativo.
        sentencias = [self.constructor_ddl.DdlEsquema()]
        sentencias.extend(
            self.constructor_ddl.DdlTabla(definicion)
            for definicion in self.definiciones
        )

        for sentencia in sentencias:
            try:
                # Ejecución del DDL contra la sesión inyectada. La idempotencia
                # la aporta el `IF NOT EXISTS` de la propia sentencia.
                self.sesion.sql(sentencia)
            except Exception as excepcion:
                # Se traduce cualquier fallo del motor a un error explícito y
                # controlado, conservando la causa original encadenada.
                raise ErrorInicializacionPersistencia(
                    "No se pudo inicializar la persistencia en el catálogo "
                    f"'{self.configuracion.catalogo}'. Falló la ejecución del "
                    f"DDL: {excepcion}"
                ) from excepcion

        # Se devuelven los nombres calificados de las tablas garantizadas.
        return [
            self.constructor_ddl.NombreTablaCalificado(definicion)
            for definicion in self.definiciones
        ]
