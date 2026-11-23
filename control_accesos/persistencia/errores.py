"""Excepciones propias de la capa de persistencia (capability `app-persistence`).

El proyecto controla todo error con try/except y mensajes explícitos en
español (README.md - Estándar de desarrollo). La capa de persistencia traduce
los fallos de bajo nivel (sesión Spark caída, catálogo inaccesible, violación
de integridad) a excepciones propias con mensaje explícito, de modo que el
resto de la aplicación —y la bitácora de errores— reciban una causa clara y
estable, no una excepción críptica de Py4J o del motor.

Jerarquía:

- `ErrorPersistencia`: error genérico de la capa de persistencia.
- `ErrorInicializacionPersistencia`: fallo al crear esquema/tablas (DDL).
- `ErrorEscrituraPersistencia`: fallo al escribir un lote en una tabla.
- `ErrorIntegridad`: violación de llave primaria, foránea o integridad
  referencial detectada por los helpers antes de escribir.
"""


class ErrorPersistencia(Exception):
    """Error genérico de la capa de persistencia.

    Attributes:
        mensaje (str): descripción explícita del error, en español.
    """

    def __init__(self, mensaje):
        """Inicializa el error con su mensaje explícito.

        Args:
            mensaje (str): descripción del error para el usuario o la
                bitácora de errores.
        """
        super().__init__(mensaje)
        self.mensaje = mensaje

    def __str__(self):
        """Representación en texto del error (su mensaje explícito).

        Returns:
            str: el mensaje del error.
        """
        return self.mensaje


class ErrorInicializacionPersistencia(ErrorPersistencia):
    """Fallo al inicializar la persistencia (creación de esquema o tablas).

    Se lanza cuando la ejecución del DDL contra la sesión Spark falla (por
    ejemplo, catálogo inexistente o inaccesible, sesión caída). El mensaje
    incluye la causa original para trazabilidad.
    """


class ErrorEscrituraPersistencia(ErrorPersistencia):
    """Fallo al escribir un lote de registros en una tabla delta.

    Se lanza cuando la operación masiva de escritura falla por una causa
    externa (tabla inaccesible, esquema incompatible, sesión caída).
    """


class ErrorIntegridad(ErrorPersistencia):
    """Violación de integridad de llaves detectada antes de escribir.

    Se lanza cuando un lote incumple la unicidad de la llave primaria (dentro
    del lote o contra la tabla destino) o la existencia de una referencia de
    llave foránea. El mensaje detalla las llaves infractoras. Ante esta
    excepción no se escribe ningún registro del lote (design.md D5).
    """
