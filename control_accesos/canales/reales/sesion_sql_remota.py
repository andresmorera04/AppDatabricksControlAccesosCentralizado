"""Sesión SQL remota OBO sobre la Statement Execution API (design.md D3, F2).

Implementación de producción de la sesión que el canal `CanalSqlDatos` consume por
inyección en la Databricks App: adapta la Statement Execution API del
`databricks-sdk` al puerto `sql(sentencia) -> filas`, el mismo contrato que
entrega `SesionSparkSql` (Spark) y el transporte CLI de las pruebas integrales.

La corrección F2 (heredada del hallazgo de C9) sustituye a `databricks-connect`,
inviable en la imagen de la App (Python 3.11, sin `Builder.create()`): el SQL
del plano de datos se ejecuta por la Statement Execution API con la credencial
OBO del llamante (scope `sql`, verificado GO en el spike de C9), sin depender
de una SparkSession local.

El módulo sigue la regla del proyecto: NO importa `databricks-sdk` al importarse.
Recibe un transporte ya construido (el objeto `StatementExecutionAPI` del cliente
`WorkspaceClient`) inyectado; la credencial, el host y el warehouse se resuelven
en la capa de fábrica (`fabrica_contexto.CrearSesionSqlRemota`). Tampoco guarda
valores de conexión ni identificadores: solo consume el transporte y el
warehouse recibidos.

Errores controlados (spec - "errores controlados con redacción del token"): todo
fallo —de la sentencia (estado FAILED/CANCELED) o del transporte— se traduce a
`ErrorEjecucionRemota` con el token redactado (la marca `token_redactado`), para
que el secreto OBO jamás llegue a la bitácora ni al mensaje del reporte.
"""

# Sondeo síncrono de la operación asíncrona (parámetros operativos, no valores
# de conexión ni de negocio): la espera inicial se declara como la cadena que
# espera la API ("50s", máximo admitido) y el sondeo posterior acotado cubre el
# arranque en frío del warehouse serverless (mismo criterio del transporte CLI
# de integrales). La pausa entre sondeos es inyectable (opcional en pruebas).
TIEMPO_ESPERA_INICIAL = "50s"
SEGUNDOS_ENTRE_SONDEOS = 5
MAXIMO_SONDEOS = 60

# Estados de una sentencia: los dos primeros mantienen el sondeo; el término
# exitoso devuelve las filas; cualquier otro término es un fallo controlado.
ESTADOS_EN_CURSO = ("PENDING", "RUNNING")
ESTADO_EXITO = "SUCCEEDED"

# Marca que sustituye al token en cualquier mensaje de error (nunca se expone
# el secreto OBO, design.md D11).
MARCA_TOKEN_REDACTADO = "<token_redactado>"


class ErrorEjecucionRemota(RuntimeError):
    """Fallo controlado de la ejecución remota de una sentencia SQL.

    Se lanza ante una sentencia que no termina en éxito (FAILED/CANCELED) o ante
    un fallo del transporte; su mensaje NUNCA incluye el token OBO: la fábrica
    inyecta el token solo para redactarlo si aparece en el texto reportado por
    el workspace o por el SDK.
    """


def _EstadoDe(respuesta):
    """Normaliza el estado de una respuesta a texto en mayúsculas (o None).

    Acepta tanto el `StatementState` del SDK como una cadena simple (pruebas),
    igual que el criterio de `_NivelDePermiso` del adaptador de permisos.

    Args:
        respuesta: respuesta de la Statement Execution API (o doble).

    Returns:
        str | None: valor del estado en mayúsculas (`PENDING`, `RUNNING`,
            `SUCCEEDED`, `FAILED`, ...), o None si no hay estado informado.
    """
    estado = getattr(getattr(respuesta, "status", None), "state", None)
    if estado is None:
        return None
    valor = getattr(estado, "value", None)
    return str(valor).upper() if valor is not None else str(estado).upper()


def _FilasDe(respuesta):
    """Devuelve las filas `data_array` de una respuesta, o lista vacía.

    Args:
        respuesta: respuesta de la Statement Execution API (o doble).

    Returns:
        list[list[str]]: filas del resultado; vacía para sentencias sin
            resultado (GRANT/REVOKE y otras DDL).
    """
    filas = getattr(getattr(respuesta, "result", None), "data_array", None)
    return list(filas) if filas is not None else []


def _MensajeErrorDe(respuesta):
    """Extrae el mensaje de error del workspace de una respuesta, o None.

    Args:
        respuesta: respuesta de la Statement Execution API (o doble).

    Returns:
        str | None: texto del error informado por el workspace (`status.error`).
    """
    error = getattr(getattr(respuesta, "status", None), "error", None)
    if error is None:
        return None
    mensaje = getattr(error, "message", None)
    if mensaje is None:
        return None
    return str(mensaje).strip() or None


def _RedactarToken(texto, token):
    """Sustituye el token por una marca de redacción dentro del texto.

    Si no hay token (la sesión lo desconoce, p. ej. en pruebas), el texto queda
    intacto; la marca garantiza que el secreto no llegue a mensajes ni bitácoras
    (design.md D11).

    Args:
        texto (str): texto donde redactar.
        token (str | None): token OBO a ocultar.

    Returns:
        str: texto con toda aparición del token sustituida por la marca.
    """
    if not token or not texto:
        return texto
    return texto.replace(token, MARCA_TOKEN_REDACTADO)


class SesionSqlRemota:
    """Adapta la Statement Execution API al puerto de sesión del canal SQL.

    Ejecuta la sentencia por el transporte inyectado, sondea la operación
    asíncrona hasta su estado terminal y devuelve las filas del resultado como
    listas de textos (compatibles con `CanalSqlDatos`). Cualquier fallo se
    traduce a `ErrorEjecucionRemota` con el token redactado.

    Attributes:
        api_ejecucion: objeto con `execute_statement(statement=...,
            warehouse_id=..., wait_timeout=...) -> respuesta` y
            `get_statement(statement_id) -> respuesta` (el `StatementExecutionAPI`
            del cliente sdk, o un doble en pruebas).
        warehouse_id (str): id del SQL warehouse contra el que se ejecuta.
        token (str | None): token OBO, conservado ÚNICAMENTE para redactarlo de
            los mensajes de error (nunca se reenvía ni se serializa).
    """

    def __init__(self, api_ejecucion, warehouse_id, token=None, espera=None):
        """Inicializa la sesión con el transporte y el warehouse inyectados.

        Args:
            api_ejecucion: transporte con `execute_statement` y `get_statement`.
            warehouse_id (str): id del SQL warehouse (descubierto en la fábrica,
                nunca embebido aquí).
            token (str | None): token OBO a redactar de los mensajes de error.
            espera (callable | None): función `(segundos)` de pausa entre
                sondeos; None usa `time.sleep` (solo las pruebas la sustituyen
                para no esperar de verdad).

        Raises:
            ValueError: si el transporte no expone los métodos requeridos o si
                el warehouse_id es vacío.
        """
        if api_ejecucion is None or not hasattr(api_ejecucion, "execute_statement") or not hasattr(api_ejecucion, "get_statement"):
            raise ValueError(
                "Se requiere un transporte con 'execute_statement' y "
                "'get_statement' (StatementExecutionAPI del databricks-sdk)."
            )
        warehouse = str(warehouse_id).strip() if warehouse_id is not None else ""
        if not warehouse:
            raise ValueError(
                "Se requiere el id de un SQL warehouse para ejecutar sentencias "
                "por la Statement Execution API."
            )

        self._api_ejecucion = api_ejecucion
        self._warehouse_id = warehouse
        self._token = token
        self._espera = espera if espera is not None else _EsperarReal

    def sql(self, sentencia):
        """Ejecuta una sentencia SQL y devuelve sus filas (listas de textos).

        Args:
            sentencia (str): sentencia SQL a ejecutar (SELECT, SHOW GRANT,
                GRANT/REVOKE).

        Returns:
            list[list[str]]: filas del resultado; vacía para sentencias sin
                resultado.

        Raises:
            ErrorEjecucionRemota: si la sentencia no termina en éxito o el
                transporte falla; el mensaje redacta el token OBO.
        """
        try:
            respuesta = self._api_ejecucion.execute_statement(
                statement=sentencia,
                warehouse_id=self._warehouse_id,
                wait_timeout=TIEMPO_ESPERA_INICIAL,
            )
        except Exception as excepcion:  # noqa: BLE001 - se traduce y redacta
            raise ErrorEjecucionRemota(
                _RedactarToken(
                    f"Fallo del transporte al ejecutar la sentencia remota: "
                    f"{excepcion}",
                    self._token,
                )
            )

        id_sentencia = getattr(respuesta, "statement_id", None)
        estado = _EstadoDe(respuesta)

        sondeos = 0
        try:
            while estado in ESTADOS_EN_CURSO and sondeos < MAXIMO_SONDEOS:
                self._espera(SEGUNDOS_ENTRE_SONDEOS)
                respuesta = self._api_ejecucion.get_statement(id_sentencia)
                estado = _EstadoDe(respuesta)
                sondeos += 1
        except Exception as excepcion:  # noqa: BLE001 - se traduce y redacta
            raise ErrorEjecucionRemota(
                _RedactarToken(
                    f"Fallo del sondeo de la sentencia remota: {excepcion}",
                    self._token,
                )
            )

        if estado != ESTADO_EXITO:
            detalle = _MensajeErrorDe(respuesta) or "sin detalle del workspace"
            raise ErrorEjecucionRemota(
                _RedactarToken(
                    f"La sentencia no terminó en éxito en el workspace "
                    f"(estado: {estado}): {detalle} | SQL: {sentencia}",
                    self._token,
                )
            )

        return _FilasDe(respuesta)


def _EsperarReal(segundos):
    """Pausa real entre sondeos (por defecto en producción).

    Args:
        segundos (float): segundos a esperar.
    """
    import time

    time.sleep(segundos)
