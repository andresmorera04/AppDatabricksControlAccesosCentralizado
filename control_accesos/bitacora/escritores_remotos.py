"""Escritores de bitácora por SQL remoto, para la Databricks App (design.md D10).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 5.2.

En la Databricks App no hay SparkSession (corrección F2); la persistencia de la
auditoría se hace por la Statement Execution API con la identidad propia de la
App. Estos escritores tienen el MISMO contrato que los escritores Spark
(`BitacoraEventos`/`BitacoraErrores` de `escritores.py`), de modo que el
pipeline los usa sin cambios: `Registrar(...)` y `RegistrarLote(registros)`.

La escritura emite sentencias `INSERT INTO ... VALUES` (una por lote) por la
sesión inyectada (puerto `.sql(sentencia)` de `SesionSqlRemota`), sin
reimplementar la declaración de columnas: se lee de las `DefinicionTabla` del
DDL. La degradación es la misma que en Spark (design.md D7): un fallo de
escritura NO se propaga ni se re-registra; se deja constancia en stderr y la
operación principal continúa (el reporte ya obtenido no se oculta).
"""

import sys
from dataclasses import asdict
from datetime import datetime

from control_accesos.bitacora.escritores import BitacoraErrores as _ErrorBase
from control_accesos.bitacora.modelos import EventoBitacora
from control_accesos.persistencia.ddl import (
    DEFINICION_BITACORA_ERRORES,
    DEFINICION_BITACORA_EVENTOS,
    ConstructorDdl,
)

# Identificador del módulo para trazas (convención del proyecto).
MODULO_ESCRITORES_REMOTOS = "ui.escritores_remotos"


def _LiteralSql(valor):
    """Renderiza un valor escalar como literal SQL con escape de comillas.

    Args:
        valor: valor a renderizar (None, str, datetime, bool o número).

    Returns:
        str: literal SQL en mayúsculas para palabras reservadas (`NULL`,
            `CAST(... AS TIMESTAMP)`, `TRUE`/`FALSE`, cadena entre comillas).
    """
    if valor is None:
        return "NULL"
    if isinstance(valor, datetime):
        return f"CAST('{valor.isoformat()}' AS TIMESTAMP)"
    if isinstance(valor, bool):
        return "TRUE" if valor else "FALSE"
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


class EscritorBitacoraSqlRemoto:
    """Base común de los escritores de bitácora por SQL remoto.

    Attributes:
        sesion: sesión con el puerto `.sql(sentencia)` (una `SesionSqlRemota`
            con la identidad de la App, o un doble en pruebas).
        constructor_ddl: generador del nombre calificado a partir del catálogo
            configurado (sin hardcodear).
        definicion: `DefinicionTabla` de la tabla destino (fijada por subclase).
    """

    definicion = None

    def __init__(self, sesion, configuracion):
        """Inicializa el escritor con la sesión SQL y la configuración.

        Args:
            sesion: objeto con `.sql(sentencia)`.
            configuracion (ConfiguracionApp): configuración de la aplicación.

        Raises:
            ValueError: si no se recibe sesión con `.sql` o configuración.
        """
        if sesion is None or not callable(getattr(sesion, "sql", None)):
            raise ValueError(
                "Se requiere una sesión con el puerto '.sql(sentencia)' para "
                "escribir la bitácora por la Statement Execution API."
            )
        if configuracion is None:
            raise ValueError(
                "Se requiere la configuración de la aplicación para calificar "
                "las tablas de bitácora."
            )
        self.sesion = sesion
        self.constructor_ddl = ConstructorDdl(catalogo=configuracion.catalogo)
        self.definicion = type(self).definicion

    @property
    def nombre_tabla(self):
        """Nombre calificado de la tabla destino (`catalogo.esquema.tabla`)."""
        return self.constructor_ddl.NombreTablaCalificado(self.definicion)

    def RegistrarLote(self, registros):
        """Escribe un lote de registros con una única sentencia INSERT.

        Args:
            registros (Iterable): modelos de registro (EventoBitacora o
                RegistroError) a persistir.

        Returns:
            tuple: los registros procesados. Se devuelven aunque la escritura
                falle: la bitácora degrada de forma controlada (design.md D7).
        """
        lote = tuple(registros)
        if not lote:
            return ()

        try:
            self.sesion.sql(self._SentenciaInsert(lote))
        except Exception as excepcion:  # noqa: BLE001 - degradación controlada
            self._ReportarFalloLocal(excepcion, len(lote))

        return lote

    def _SentenciaInsert(self, registros):
        """Construye el `INSERT INTO ... VALUES` del lote.

        Args:
            registros (tuple): modelos a persistir.

        Returns:
            str: sentencia SQL en mayúsculas con una fila `VALUES` por registro.
        """
        columnas = ", ".join(
            columna.nombre for columna in self.definicion.columnas
        )
        filas = ", ".join(self._FilaDeRegistro(r) for r in registros)
        return (
            f"INSERT INTO {self.nombre_tabla} "
            f"({columnas}) VALUES {filas}"
        )

    def _FilaDeRegistro(self, registro):
        """Renderiza una fila `VALUES` de un modelo de registro.

        Args:
            registro: modelo cuyos campos coinciden con las columnas del DDL.

        Returns:
            str: `(literal, literal, ...)` en el orden de las columnas.
        """
        valores = []
        for columna in self.definicion.columnas:
            valor = getattr(registro, columna.nombre)
            if columna.tipo.startswith("STRUCT"):
                valores.append(self._StructSql(valor))
            else:
                valores.append(_LiteralSql(valor))
        return "(" + ", ".join(valores) + ")"

    @staticmethod
    def _StructSql(valor):
        """Renderiza un dataclass (detalle) como `NAMED_STRUCT` literal.

        Args:
            valor: dataclass cuyos campos y orden coinciden con el STRUCT.

        Returns:
            str: `NAMED_STRUCT('campo', literal, ...)`.
        """
        argumentos = []
        for nombre, valor_campo in asdict(valor).items():
            argumentos.append(f"'{nombre}'")
            argumentos.append(_LiteralSql(valor_campo))
        return "NAMED_STRUCT(" + ", ".join(argumentos) + ")"

    def _ReportarFalloLocal(self, excepcion, cantidad_registros):
        """Deja constancia visible en stderr del fallo de escritura.

        La bitácora nunca es un punto único de fallo: no se propaga ni se
        re-registra (anti-recursión); el reporte ya calculado se conserva.
        """
        print(
            f"[BITÁCORA REMOTA] No se pudieron escribir {cantidad_registros} "
            f"registro(s) en '{self.nombre_tabla}': {excepcion}. La ejecución "
            f"continúa; el fallo queda reportado solo en la salida local.",
            file=sys.stderr,
        )


class BitacoraEventosRemota(EscritorBitacoraSqlRemoto):
    """Escritor remoto de la bitácora de eventos (tabla `bitacora_eventos`)."""

    definicion = DEFINICION_BITACORA_EVENTOS

    def Registrar(
        self,
        accion,
        usuario=None,
        detalle=None,
        resultado=None,
        marca_tiempo=None,
    ):
        """Construye y registra un evento por la Statement Execution API."""
        evento = EventoBitacora(
            accion=accion,
            usuario=usuario,
            detalle=detalle,
            resultado=resultado,
            marca_tiempo=marca_tiempo or datetime.now(),
        )
        self.RegistrarLote((evento,))
        return evento


class BitacoraErroresRemota(EscritorBitacoraSqlRemoto):
    """Escritor remoto de la bitácora de errores (tabla `bitacora_errores`)."""

    definicion = DEFINICION_BITACORA_ERRORES

    def Registrar(self, excepcion, modulo, usuario=None, contexto="",
                  marca_tiempo=None):
        """Construye y registra un error capturado por la Statement Execution API."""
        registro = _ErrorBase.ConstruirRegistro(
            excepcion=excepcion,
            modulo=modulo,
            usuario=usuario,
            contexto=contexto,
            marca_tiempo=marca_tiempo,
        )
        self.RegistrarLote((registro,))
        return registro
