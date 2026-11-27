"""Pruebas unitarias de la sesión SQL remota OBO (design.md D3, corrección F2).

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Cubre el contrato de `SesionSqlRemota` (transporte del canal SQL del plano de
datos sobre la Statement Execution API) y de su fábrica de producción
`CrearSesionSqlRemota`:

- las sentencias SELECT, SHOW GRANT y GRANT se ejecutan a través del transporte
  inyectado (`StatementExecutionAPI` del cliente SDK), sin conexión externa;
- el sondeo de la operación asíncrona llama a `get_statement` con el id devuelto
  hasta alcanzar un estado terminal (SUCCEEDED para success, FAILED para fallo);
- las filas devueltas son listas de textos (`list[list[str]]`) compatibles con
  el puerto que consume `CanalSqlDatos` (mismas columnas que `SHOW GRANT`);
- la fábrica construye el cliente con `auth_type='pat'` para usar SOLO el token
  OBO del llamante (sin heredar el OAuth del service principal de la App);
- los errores de transporte y de sentencia se traducen a `ErrorEjecucionRemota`
  con el token redactado: ningún mensaje propaga el secreto.

Nota TDD: este módulo se escribe rojo (la sesión no existe aún) y la
implementación se verifica en verde en la tarea 2.1.
"""

from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.reales.sesion_sql_remota import SesionSqlRemota
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.ui.fabrica_contexto import CrearSesionSqlRemota

# Valores de prueba.
HOST_WORKSPACE = "https://adb-1234567890.1.azuredatabricks.net"
TOKEN_OBO = "datokenscreto_obo_0123456789"
WAREHOUSE_ID = "abcdef1234567890abcdef12"
MARCA_REDACCION = "<token_redactado>"


class EstadoFalso:
    """Estado de una respuesta falsa de la Statement Execution API."""

    def __init__(self, estado, mensaje_error=None):
        self.state = estado
        self.error = ErrorFalso(mensaje_error) if mensaje_error else None


class ErrorFalso:
    """Error de workspace de una respuesta falsa (campo `status.error`)."""

    def __init__(self, mensaje):
        self.message = mensaje


class ResultadoFalso:
    """Resultado de una respuesta falsa (campo `result` con `data_array`)."""

    def __init__(self, filas):
        self.data_array = filas


class RespuestaFalsa:
    """Respuesta falsa de la Statement Execution API.

    Incluye `statement_id`, `status` (con `state` y, opcionalmente, `error`) y,
    opcionalmente, `result` con `data_array`.
    """

    def __init__(self, estado, filas=None, mensaje_error=None, id_sentencia="stmt-1"):
        self.statement_id = id_sentencia
        self.status = EstadoFalso(estado, mensaje_error)
        self.result = ResultadoFalso(filas) if filas is not None else None


class ApiEjecucionFalsa:
    """Doble del transporte `StatementExecutionAPI`.

    Registra las instrucciones, los warehouses y los sondeos recibidos, y
    devuelve las respuestas configuradas: una inicial para `execute_statement` y
    una lista FIFO para las llamadas a `get_statement`. Puede lanzar errores
    preconfigurados para verificar la redacción del token.
    """

    def __init__(self, respuesta_inicial=None):
        self.respuesta_inicial = respuesta_inicial
        self.respuestas_de_sondeo = []
        self.error_de_transporte = None
        self.error_de_sondeo = None
        self.instrucciones_recibidas = []
        self.warehouse_ids_recibidos = []
        self.wait_timeouts_recibidos = []
        self.sondeos_realizados = []

    def execute_statement(self, statement=None, warehouse_id=None, wait_timeout=None, **extra):
        """Registra la petición y devuelve la respuesta inicial (o lanza)."""
        self.instrucciones_recibidas.append(statement)
        self.warehouse_ids_recibidos.append(warehouse_id)
        self.wait_timeouts_recibidos.append(wait_timeout)
        if self.error_de_transporte is not None:
            raise self.error_de_transporte
        return self.respuesta_inicial

    def get_statement(self, statement_id):
        """Registra el sondeo y devuelve la siguiente respuesta de la cola."""
        self.sondeos_realizados.append(statement_id)
        if self.error_de_sondeo is not None:
            raise self.error_de_sondeo
        if self.respuestas_de_sondeo:
            return self.respuestas_de_sondeo.pop(0)
        return self.respuesta_inicial


def CrearApiEjecucion(filas=None, estado="SUCCEEDED", mensaje_error=None):
    """Construye un transporte falso con una respuesta inicial exitosa.

    Args:
        filas (list[list[str]] | None): filas `data_array` de la respuesta.
        estado (str): estado inicial de la respuesta.
        mensaje_error (str | None): mensaje del error de workspace, si aplica.

    Returns:
        ApiEjecucionFalsa: transporte configurado con la respuesta inicial.
    """
    respuesta = RespuestaFalsa(
        estado=estado, filas=filas, mensaje_error=mensaje_error
    )
    return ApiEjecucionFalsa(respuesta)


def TestSelectDevuelveFilasCompatiblesConCanalSqlDatos():
    """El SELECT devuelve las filas del `data_array` como listas de textos."""
    api = CrearApiEjecucion(
        filas=[
            ["usuario@correo.com", "SELECT", "TABLE", "control.prod.ventas"],
            ["grupo_analistas", "SELECT", "TABLE", "control.prod.ventas"],
        ]
    )
    sesion = SesionSqlRemota(api, WAREHOUSE_ID)

    filas = sesion.sql("SHOW GRANT ON TABLE `control`.`prod`.`ventas`")

    assert filas == [
        ["usuario@correo.com", "SELECT", "TABLE", "control.prod.ventas"],
        ["grupo_analistas", "SELECT", "TABLE", "control.prod.ventas"],
    ]
    # El canal consume estas filas sin modificación alguna (compatibilidad).
    assert api.instrucciones_recibidas == [
        "SHOW GRANT ON TABLE `control`.`prod`.`ventas`"
    ]


def TestFilasCompatiblesConCanalSqlDatosListarGrants():
    """CanalSqlDatos consume la sesión remota y traduce SHOW GRANT a ítems.

    La compatibilidad se demuestra de extremo a extremo en la unidad: la sesión
    remota alimenta `ListarGrantsVigentes` y devuelve los otorgamientos con el
    tipo de principal inferido de la referencia textual.
    """
    api = CrearApiEjecucion(
        filas=[
            ["usuario@correo.com", "SELECT", "TABLE", "control.prod.ventas"],
        ]
    )
    canal = CanalSqlDatos(SesionSqlRemota(api, WAREHOUSE_ID))
    objeto = ObjetoSecurable(
        identificador="control.prod.ventas", tipo=TipoObjeto.TABLA_DELTA
    )

    grants = canal.ListarGrantsVigentes(objeto)

    assert len(grants) == 1
    assert grants[0].principal == Principal(
        identificador="usuario@correo.com", tipo=TipoPrincipal.USUARIO
    )
    assert grants[0].privilegio == "SELECT"


def TestGrantSinResultadoDevuelveListaVacia():
    """Una GRANT (DDL) exitosa sin `data_array` devuelve una lista vacía."""
    api = CrearApiEjecucion(estado="SUCCEEDED")
    sesion = SesionSqlRemota(api, WAREHOUSE_ID)

    filas = sesion.sql("GRANT SELECT ON TABLE `control`.`prod`.`ventas` TO `u`")

    assert filas == []
    assert api.instrucciones_recibidas[0].startswith("GRANT SELECT")


def TestEjecucionEnviaWarehouseYTimeoutAlTransporte():
    """La sesión reenvía el warehouse_id y el tiempo de espera iniciales."""
    api = CrearApiEjecucion(estado="SUCCEEDED")
    sesion = SesionSqlRemota(api, WAREHOUSE_ID)

    sesion.sql("SELECT 1")

    assert api.warehouse_ids_recibidos == [WAREHOUSE_ID]
    assert api.wait_timeouts_recibidos and api.wait_timeouts_recibidos[0]


def TestSondeoDeOperacionAsincronaHastaEstadoTerminal():
    """Sondea con get_statement hasta que la operación termina en éxito."""
    api = ApiEjecucionFalsa(RespuestaFalsa(estado="PENDING"))
    api.respuestas_de_sondeo = [
        RespuestaFalsa(estado="RUNNING"),
        RespuestaFalsa(
            estado="SUCCEEDED",
            filas=[["done", "SELECT", "TABLE", "c.s.t"]],
        ),
    ]
    sesion = SesionSqlRemota(api, WAREHOUSE_ID, espera=lambda segundos: None)

    filas = sesion.sql("SELECT 1")

    assert filas == [["done", "SELECT", "TABLE", "c.s.t"]]
    # Dos sondeos: RUNNING y SUCCEEDED, ambos con el id de la sentencia inicial.
    assert api.sondeos_realizados == ["stmt-1", "stmt-1"]


def TestFalloDeSentenciaLanzaErrorRedactado():
    """Una sentencia FAILED se traduce a ErrorEjecucionRemota sin el token."""
    api = ApiEjecucionFalsa(
        RespuestaFalsa(
            estado="FAILED",
            mensaje_error=f"PERMISSION_DENIED with credential {TOKEN_OBO}",
        )
    )
    sesion = SesionSqlRemota(api, WAREHOUSE_ID, token=TOKEN_OBO)

    try:
        sesion.sql("GRANT SELECT ON TABLE `c`.`s`.`t` TO `u`")
    except Exception as excepcion:  # noqa: BLE001 - se verifica la traducción
        mensaje = str(excepcion)
        assert "ErrorEjecucionRemota" in type(excepcion).__name__
        assert TOKEN_OBO not in mensaje
        assert MARCA_REDACCION in mensaje
        assert "PERMISSION_DENIED" in mensaje
    else:
        raise AssertionError("Se esperaba un ErrorEjecucionRemota por FAILED.")


def TestFalloDeTransporteLanzaErrorRedactado():
    """Un fallo del transporte se traduce con el token redactado."""
    api = ApiEjecucionFalsa()
    api.error_de_transporte = RuntimeError(f"OAuth rejected token {TOKEN_OBO}")
    sesion = SesionSqlRemota(api, WAREHOUSE_ID, token=TOKEN_OBO)

    try:
        sesion.sql("SELECT 1")
    except Exception as excepcion:  # noqa: BLE001 - se verifica la redacción
        mensaje = str(excepcion)
        assert "ErrorEjecucionRemota" in type(excepcion).__name__
        assert TOKEN_OBO not in mensaje
        assert MARCA_REDACCION in mensaje
    else:
        raise AssertionError("Se esperaba un error redactado del transporte.")


def TestFalloDeSondeoLanzaErrorRedactado():
    """Un fallo durante el sondeo también llega redactado al llamador."""
    api = ApiEjecucionFalsa(RespuestaFalsa(estado="RUNNING"))
    api.error_de_sondeo = RuntimeError(f"Sondeo rechazado con {TOKEN_OBO}")
    sesion = SesionSqlRemota(api, WAREHOUSE_ID, token=TOKEN_OBO, espera=lambda s: None)

    try:
        sesion.sql("SELECT 1")
    except Exception as excepcion:  # noqa: BLE001 - se verifica la redacción
        mensaje = str(excepcion)
        assert TOKEN_OBO not in mensaje
        assert MARCA_REDACCION in mensaje
    else:
        raise AssertionError("Se esperaba un error redactado del sondeo.")


def TestConstructorRechazaTransporteSinPuerto():
    """Sin un transporte con execute_statement/get_statement se falla pronto."""
    class SinPuerto:
        """Objeto sin los métodos del transporte."""

    try:
        SesionSqlRemota(SinPuerto(), WAREHOUSE_ID)
    except ValueError as excepcion:
        assert "execute_statement" in str(excepcion)
    else:
        raise AssertionError("Se esperaba un ValueError por transporte inválido.")


def TestConstructorRechazaWarehouseVacio():
    """Sin warehouse_id no hay contra quién ejecutar: error explícito."""
    api = CrearApiEjecucion(estado="SUCCEEDED")
    try:
        SesionSqlRemota(api, "")
    except ValueError as excepcion:
        assert "warehouse" in str(excepcion)
    else:
        raise AssertionError("Se esperaba un ValueError por warehouse vacío.")


class WorkspaceClientFalso:
    """Doble de `WorkspaceClient` que registra su construcción OBO."""

    ultima_instancia = None

    def __init__(self, host=None, token=None, **extra):
        self.host = host
        self.token = token
        self.extra = extra
        self.statement_execution = ApiEjecucionFalsa(RespuestaFalsa("SUCCEEDED"))
        WorkspaceClientFalso.ultima_instancia = self


def _InstalarWorkspaceClientFalso(monkeypatch):
    """Parchea `databricks.sdk.WorkspaceClient` con el doble registrador."""
    import databricks.sdk

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", WorkspaceClientFalso)


def TestFabricaConstruyeClienteConAuthTypePat(monkeypatch):
    """CrearSesionSqlRemota fija auth_type='pat' (solo token OBO, sin OAuth)."""
    _InstalarWorkspaceClientFalso(monkeypatch)

    sesion = CrearSesionSqlRemota(HOST_WORKSPACE, TOKEN_OBO, WAREHOUSE_ID)

    cliente = WorkspaceClientFalso.ultima_instancia
    assert cliente is not None
    assert cliente.extra.get("auth_type") == "pat", (
        "El cliente de la sesión remota debe fijar auth_type='pat' para usar "
        "solo el token OBO del llamante (design.md D3), no el OAuth del "
        "service principal de la App presente en el entorno."
    )
    assert cliente.token == TOKEN_OBO
    assert isinstance(sesion, SesionSqlRemota)


def TestFabricaEntregaElTransporteDelCliente():
    """La sesión devuelta ejecuta a través del statement_execution del cliente."""
    # Sin patchear la red: se usa la fábrica con un cliente inyectado.
    api = ApiEjecucionFalsa(RespuestaFalsa("SUCCEEDED"))

    # CrearSesionSqlRemota delega en la fábrica de clientes por defecto; se
    # inyecta una que devuelve un cliente cuyo statement_execution es el doble.
    class ClienteConTransporte:
        statement_execution = api

    clase_fabrica = lambda host=None, token=None: ClienteConTransporte()  # noqa: E731

    sesion = CrearSesionSqlRemota(
        HOST_WORKSPACE,
        TOKEN_OBO,
        WAREHOUSE_ID,
        fabrica_cliente=clase_fabrica,
    )

    sesion.sql("SELECT 1")

    assert api.instrucciones_recibidas == ["SELECT 1"]
    assert api.warehouse_ids_recibidos == [WAREHOUSE_ID]
