"""Pruebas de aceptación de la capability `uc-external-object-grants`.

Trazabilidad 1:1 con los escenarios del spec delta
`openspec/changes/grants-uc-externos/specs/uc-external-object-grants/spec.md`:

- Instrucción de otorgamiento para objetos externos:
  - Grant sobre una external location
    -> TestEscenarioGrantSobreUnaExternalLocation
  - Grant sobre una connection -> TestEscenarioGrantSobreUnaConnection
  - Privilegios según la matriz -> TestEscenarioPrivilegiosSegunLaMatriz
- Instrucción de revocación para objetos externos:
  - Revocación sobre una external location
    -> TestEscenarioRevocacionSobreUnaExternalLocation
  - Revocación sobre una connection
    -> TestEscenarioRevocacionSobreUnaConnection
- Ejecución de instrucciones por una sesión SQL inyectada:
  - Instrucción enviada a la sesión inyectada
    -> TestEscenarioInstruccionEnviadaALaSesionInyectada
  - Canal ejercitado sin workspace alguno
    -> TestEscenarioCanalEjercitadoSinWorkspaceAlguno
- Errores del workspace traducidos a mensajes específicos por caso:
  - Permiso denegado al otorgar -> TestEscenarioPermisoDenegadoAlOtorgar
  - External location o connection inexistente
    -> TestEscenarioExternalLocationOConnectionInexistente
  - Principal inexistente -> TestEscenarioPrincipalInexistente
  - Cualquier otro fallo de la sesión -> TestEscenarioCualquierOtroFalloDeSesion
- Verificación posterior al grant con SHOW GRANTS:
  - Grant confirmado por la verificación
    -> TestEscenarioGrantConfirmadoPorLaVerificacion
  - Grant no confirmado por la verificación
    -> TestEscenarioGrantNoConfirmadoPorLaVerificacion
  - Filas propias conservan el tipo consultado
    -> TestEscenarioFilasPropiasConservanElTipoConsultado
- Cardinalidades 1 a 1, 1 a N y N a 1:
  - Lote 1 a N sobre external locations
    -> TestEscenarioLoteUnoANSobreExternalLocations
  - Lote N a 1 sobre una connection -> TestEscenarioLoteNUnoASobreUnaConnection
  - Lote N a M rechazado -> TestEscenarioLoteNAMRechazado
- Cobertura completa del plano de datos:
  - Objeto del plano de control fuera del canal
    -> TestEscenarioObjetoDelPlanoDeControlFueraDelCanal
- Pruebas integrales autocontenidas con perfil por tipo de objeto:
  - Fixtures creadas y destruidas por la propia prueba
    -> TestEscenarioFixturesCreadasYDestruidasPorLaPropiaPrueba
  - Connection con fallback autorizado
    -> TestEscenarioConnectionConFallbackAutorizado
  - Tipo no creable en ningún perfil
    -> TestEscenarioTipoNoCreableEnNingunPerfil

Todo con el canal real de producción (`CanalSqlDatos`) sobre una sesión SQL
simulada que imita las respuestas del motor —incluidos los códigos de error
reales contrastados contra los workspaces (design D3)— y, para los escenarios de
integrales, la fábrica real de fixtures con el descubrimiento de Unity Catalog
imitado: ninguna escritura llega a un workspace real.
"""

import sys
from pathlib import Path

# La fábrica de fixtures vive en la capa integral (no es un paquete); se agrega
# su directorio al sys.path para ejercitar su contrato de creación/limpieza en
# los escenarios de integrales autocontenidas (mismo criterio que conftest.py y
# que la suite de aceptación de C4).
RAIZ_PRUEBAS = Path(__file__).resolve().parents[1]
if str(RAIZ_PRUEBAS / "integrales") not in sys.path:
    sys.path.insert(0, str(RAIZ_PRUEBAS / "integrales"))

import pytest

import fixtures_uc_externos
from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from fixtures_uc_externos import (
    CONTENEDOR_PRUEBAS,
    MARCADOR_SECRETO_OCULTO,
    NOMBRE_VARIABLE_ENTORNO_HOST_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_PASSWORD_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_PUERTO_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_USUARIO_SQLSERVER,
    NOMBRES_VARIABLES_ENTORNO_SQLSERVER,
    RUTA_API_EXTERNAL_LOCATIONS,
    RUTA_API_STORAGE_CREDENTIALS,
    FixturesUcExternos,
)

# Objetos externos de prueba: nombres simples, como los reporta Unity Catalog
# para estos securables del metastore (sin calificación por catálogo/esquema).
EXTERNAL_LOCATION = ObjetoSecurable(
    identificador="ubicacion_externa_pruebas",
    tipo=TipoObjeto.EXTERNAL_LOCATION,
)
CONNECTION = ObjetoSecurable(
    identificador="conexion_sqlserver_pruebas", tipo=TipoObjeto.CONNECTION
)

# Beneficiario de los ítems, con forma de correo (como reporta Unity Catalog).
BENEFICIARIO = "beneficiario@example.com"

# Datos del workspace imitado que la fábrica de fixtures descubre por API (no se
# hardcodean en producción: la fixture los deriva de la respuesta real).
CREDENCIAL_ALMACENAMIENTO = "credencial_almacenamiento_pruebas"
CUENTA_ALMACENAMIENTO = "cuentapruebas.dfs.core.windows.net"
URL_LOCATION_EXISTENTE = (
    f"abfss://datos@{CUENTA_ALMACENAMIENTO}/raw"
)

# Datos FICTICIOS del SQL Server de pruebas para la capa de aceptación: ninguna
# prueba usa credenciales reales, que viven en el entorno del humano y nunca en
# el código (decisión del humano: la contraseña no se versiona).
HOST_SQLSERVER_FICTICIO = "sqlserver.pruebas.invalid"
PUERTO_SQLSERVER_FICTICIO = "1433"
USUARIO_SQLSERVER_FICTICIO = "usuario_ficticio_pruebas"
PASSWORD_SQLSERVER_FICTICIO = "clave_ficticia_de_aceptacion"


class ErrorMotorSql(RuntimeError):
    """Excepción con la forma del error que reporta el motor SQL real."""


class SesionSqlDoble:
    """Sesión SQL que imita al motor real (filas de SHOW GRANT y errores).

    Attributes:
        sentencias (list[str]): sentencias recibidas, en orden.
    """

    def __init__(self):
        self.sentencias = []
        self._filas_show_grant = {}
        self._errores_por_prefijo = []

    def ConfigurarShowGrant(self, objeto, filas):
        """Fija las filas de SHOW GRANT para el objeto.

        Args:
            objeto (ObjetoSecurable): objeto externo consultado.
            filas (list[list[str]]): filas con las columnas de SHOW GRANT.
        """
        self._filas_show_grant[CanalSqlDatos.ConstruirShowGrant(objeto)] = (
            list(filas)
        )

    def ConfigurarErrorEn(self, prefijo, error):
        """Configura un error para las sentencias que empiezan por el prefijo.

        Args:
            prefijo (str): prefijo de la sentencia que debe fallar.
            error (Exception): excepción que la sesión lanzará.
        """
        self._errores_por_prefijo.append((prefijo, error))

    def sql(self, sentencia):
        """Registra la sentencia y responde según la configuración.

        Args:
            sentencia (str): sentencia SQL recibida.

        Returns:
            list[list[str]]: filas de la consulta (vacía para DDL).

        Raises:
            Exception: el error configurado por prefijo, si aplica.
        """
        self.sentencias.append(sentencia)
        for prefijo, error in self._errores_por_prefijo:
            if sentencia.startswith(prefijo):
                raise error
        if sentencia.startswith("SHOW GRANT"):
            return list(self._filas_show_grant.get(sentencia, []))
        return []

    def SentenciasDeEscritura(self):
        """Devuelve las sentencias GRANT/REVOKE/DDL (sin SHOW GRANT).

        Returns:
            list[str]: sentencias que no son de lectura, en orden.
        """
        return [s for s in self.sentencias if not s.startswith("SHOW GRANT")]


def CrearItem(privilegio, objeto=EXTERNAL_LOCATION, principal=BENEFICIARIO):
    """Construye un ítem de solicitud de prueba sobre un objeto externo.

    Args:
        privilegio (str): privilegio a otorgar o revocar.
        objeto (ObjetoSecurable): external location o connection de prueba.
        principal (str): identificación del principal destinatario.

    Returns:
        ItemGrant: ítem listo para ejercitar el canal.
    """
    return ItemGrant(
        principal=Principal(
            identificador=principal, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def Fila(principal, privilegio, palabra_clave, clave):
    """Construye una fila de SHOW GRANT tal como la reporta el metastore.

    Args:
        principal (str): otorgatario referenciado por la fila.
        privilegio (str): privilegio vigente.
        palabra_clave (str): palabra clave SQL del tipo (`EXTERNAL LOCATION`,
            con sus dos tokens, o `CONNECTION`).
        clave (str): clave del securable en la fila.

    Returns:
        list[str]: fila con las columnas Principal, ActionType, ObjectType,
            ObjectKey.
    """
    return [principal, privilegio, palabra_clave, clave]


def FilaLocation(principal, privilegio, objeto=EXTERNAL_LOCATION):
    """Construye una fila propia de la external location consultada."""
    return Fila(principal, privilegio, "EXTERNAL LOCATION", objeto.identificador)


def FilaConnection(principal, privilegio, objeto=CONNECTION):
    """Construye una fila propia de la connection consultada."""
    return Fila(principal, privilegio, "CONNECTION", objeto.identificador)


def CrearSolicitud(objeto, privilegios):
    """Construye una solicitud 1 a 1 sobre un objeto externo de prueba.

    Args:
        objeto (ObjetoSecurable): external location o connection.
        privilegios (list[str]): privilegios a otorgar al beneficiario.

    Returns:
        SolicitudGrant: solicitud válida para procesar por el pipeline.
    """
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=objeto,
    )


def DescubrimientoUnityCatalogSimulado(comando, perfil):
    """Imita las respuestas de la API de Unity Catalog para la fábrica.

    La fábrica descubre el storage credential y la cuenta de almacenamiento del
    workspace sin hardcodearlos; aquí se imitan esas respuestas para ejercitar
    su contrato de creación/limpieza sin tocar ningún workspace real.

    Args:
        comando (list[str]): subcomando del CLI (`["get", <ruta>]`).
        perfil (str): perfil CLI que se consultaría.

    Returns:
        dict: respuesta imitada según la ruta consultada.
    """
    ruta = comando[1] if len(comando) > 1 else ""
    if ruta == RUTA_API_EXTERNAL_LOCATIONS:
        return {
            "external_locations": [
                {
                    "name": "location_existente_del_workspace",
                    "url": URL_LOCATION_EXISTENTE,
                    "credential_name": CREDENCIAL_ALMACENAMIENTO,
                }
            ]
        }
    if ruta == RUTA_API_STORAGE_CREDENTIALS:
        return {
            "storage_credentials": [{"name": CREDENCIAL_ALMACENAMIENTO}]
        }
    return {}


def DescubrimientoSinDatos(comando, perfil):
    """Imita un workspace que no expone external locations ni credentials.

    Args:
        comando (list[str]): subcomando del CLI.
        perfil (str): perfil CLI que se consultaría.

    Returns:
        dict: respuesta vacía para cualquier ruta.
    """
    return {}


def ExportarEntornoConexion(monkeypatch):
    """Exporta los datos ficticios del SQL Server de pruebas en el entorno.

    La fábrica de fixtures lee los datos de la connection de las variables de
    entorno (nunca del código); la aceptación los fija con valores ficticios para
    ejercitar el DDL sin credenciales reales.

    Args:
        monkeypatch: fixture de pytest para alterar el entorno de la prueba.

    Returns:
        dict[str, str]: los datos ficticios exportados, para las aserciones.
    """
    datos = {
        NOMBRE_VARIABLE_ENTORNO_HOST_SQLSERVER: HOST_SQLSERVER_FICTICIO,
        NOMBRE_VARIABLE_ENTORNO_PUERTO_SQLSERVER: PUERTO_SQLSERVER_FICTICIO,
        NOMBRE_VARIABLE_ENTORNO_USUARIO_SQLSERVER: USUARIO_SQLSERVER_FICTICIO,
        NOMBRE_VARIABLE_ENTORNO_PASSWORD_SQLSERVER: (
            PASSWORD_SQLSERVER_FICTICIO
        ),
    }
    for nombre, valor in datos.items():
        monkeypatch.setenv(nombre, valor)
    return datos


def BorrarEntornoConexion(monkeypatch):
    """Borra del entorno las variables con los datos del SQL Server de pruebas.

    Args:
        monkeypatch: fixture de pytest para alterar el entorno de la prueba.
    """
    for nombre in NOMBRES_VARIABLES_ENTORNO_SQLSERVER:
        monkeypatch.delenv(nombre, raising=False)


# --- Instrucción de otorgamiento para objetos externos ----------------------


def TestEscenarioGrantSobreUnaExternalLocation():
    """Escenario: Grant sobre una external location.

    WHEN un ítem otorga un privilegio sobre una external location identificada
         por su nombre
    THEN la instrucción construida usa la palabra clave `EXTERNAL LOCATION` con
         ese nombre.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("READ FILES")
    )

    assert sentencia == (
        "GRANT READ FILES ON EXTERNAL LOCATION `ubicacion_externa_pruebas` "
        f"TO `{BENEFICIARIO}`"
    )


def TestEscenarioGrantSobreUnaConnection():
    """Escenario: Grant sobre una connection.

    WHEN un ítem otorga un privilegio sobre una connection de Unity Catalog
    THEN la instrucción construida usa la palabra clave `CONNECTION`.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("USE CONNECTION", objeto=CONNECTION)
    )

    assert sentencia == (
        "GRANT USE CONNECTION ON CONNECTION `conexion_sqlserver_pruebas` "
        f"TO `{BENEFICIARIO}`"
    )


def TestEscenarioPrivilegiosSegunLaMatriz():
    """Escenario: Privilegios según la matriz.

    WHEN un ítem otorga un privilegio válido según la matriz de compatibilidad
    THEN la instrucción incluye ese privilegio en mayúsculas y el principal
         identificado por su identificador.
    """
    casos = (
        (EXTERNAL_LOCATION, "EXTERNAL USE LOCATION"),
        (EXTERNAL_LOCATION, "WRITE FILES"),
        (CONNECTION, "CREATE FOREIGN CATALOG"),
        (CONNECTION, "ALL PRIVILEGES"),
    )

    for objeto, privilegio in casos:
        sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
            CrearItem(privilegio, objeto=objeto)
        )
        assert f"GRANT {privilegio} ON " in sentencia
        assert f"TO `{BENEFICIARIO}`" in sentencia


# --- Instrucción de revocación para objetos externos ------------------------


def TestEscenarioRevocacionSobreUnaExternalLocation():
    """Escenario: Revocación sobre una external location.

    WHEN se revoca a un principal un privilegio sobre una external location
    THEN la instrucción revoca el privilegio con la palabra clave
         `EXTERNAL LOCATION`, el nombre de la location y el principal indicado.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem("WRITE FILES")
    )

    assert sentencia == (
        "REVOKE WRITE FILES ON EXTERNAL LOCATION `ubicacion_externa_pruebas` "
        f"FROM `{BENEFICIARIO}`"
    )


def TestEscenarioRevocacionSobreUnaConnection():
    """Escenario: Revocación sobre una connection.

    WHEN se revoca a un principal un privilegio sobre una connection
    THEN la instrucción construida usa la palabra clave `CONNECTION`.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem("USE CONNECTION", objeto=CONNECTION)
    )

    assert sentencia == (
        "REVOKE USE CONNECTION ON CONNECTION `conexion_sqlserver_pruebas` "
        f"FROM `{BENEFICIARIO}`"
    )


# --- Ejecución de instrucciones por una sesión SQL inyectada ----------------


def TestEscenarioInstruccionEnviadaALaSesionInyectada():
    """Escenario: Instrucción enviada a la sesión inyectada.

    WHEN el canal ejecuta el otorgamiento de un ítem sobre una external location
         o una connection
    THEN la instrucción construida se envía tal cual a la sesión inyectada.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)

    canal.Otorgar(CrearItem("READ FILES"))
    canal.Otorgar(CrearItem("USE CONNECTION", objeto=CONNECTION))

    assert sesion.SentenciasDeEscritura() == [
        "GRANT READ FILES ON EXTERNAL LOCATION `ubicacion_externa_pruebas` "
        f"TO `{BENEFICIARIO}`",
        "GRANT USE CONNECTION ON CONNECTION `conexion_sqlserver_pruebas` "
        f"TO `{BENEFICIARIO}`",
    ]


def TestEscenarioCanalEjercitadoSinWorkspaceAlguno():
    """Escenario: Canal ejercitado sin workspace alguno.

    WHEN el canal se construye con una sesión simulada
    THEN el otorgamiento y la revocación sobre objetos externos se procesan y se
         reportan sin ninguna conexión externa.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)

    resultado_otorgar = canal.Otorgar(CrearItem("READ FILES"))
    resultado_revocar = canal.Revocar(
        CrearItem("USE CONNECTION", objeto=CONNECTION)
    )

    assert resultado_otorgar.estado is EstadoItem.OTORGADO
    assert resultado_revocar.estado is EstadoItem.OTORGADO
    # El doble no abre red alguna: solo registra las dos sentencias recibidas.
    assert len(sesion.sentencias) == 2


# --- Errores del workspace traducidos a mensajes específicos ----------------


def TestEscenarioPermisoDenegadoAlOtorgar():
    """Escenario: Permiso denegado al otorgar.

    WHEN el workspace responde con permiso denegado al ejecutar la instrucción
         del llamante sobre un objeto externo
    THEN el ítem se reporta `privilegios_insuficientes` con un mensaje que
         identifica el privilegio y el objeto y deja constancia de que el
         llamante no puede otorgarlo.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT",
        ErrorMotorSql(
            "[PERMISSION_DENIED] El ejecutor no puede otorgar READ FILES."
        ),
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("READ FILES"))

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "READ FILES" in resultado.detalle
    assert EXTERNAL_LOCATION.identificador in resultado.detalle


def TestEscenarioExternalLocationOConnectionInexistente():
    """Escenario: External location o connection inexistente.

    WHEN la instrucción falla porque la external location o la connection no
         existe en el metastore
    THEN el ítem se reporta `fallido` con un mensaje que identifica el objeto
         inexistente.

    Se ejercitan los códigos REALES contrastados contra los workspaces (design
    D3): `EXTERNAL_LOCATION_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST` y
    `RESOURCE_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST`.
    """
    casos = (
        (
            EXTERNAL_LOCATION,
            "READ FILES",
            "[ErrorClass=EXTERNAL_LOCATION_DOES_NOT_EXIST."
            "RESOURCE_DOES_NOT_EXIST] External Location "
            "'ubicacion_externa_pruebas' does not exist.",
            "external_location",
        ),
        (
            CONNECTION,
            "USE CONNECTION",
            "[ErrorClass=RESOURCE_DOES_NOT_EXIST.RESOURCE_DOES_NOT_EXIST] "
            "Connection 'conexion_sqlserver_pruebas' does not exist.",
            "connection",
        ),
    )

    for objeto, privilegio, mensaje_error, tipo_esperado in casos:
        sesion = SesionSqlDoble()
        sesion.ConfigurarErrorEn("GRANT", ErrorMotorSql(mensaje_error))
        canal = CanalSqlDatos(sesion)

        resultado = canal.Otorgar(CrearItem(privilegio, objeto=objeto))

        assert resultado.estado is EstadoItem.FALLIDO
        assert "no existe" in resultado.detalle
        assert tipo_esperado in resultado.detalle
        assert objeto.identificador in resultado.detalle


def TestEscenarioPrincipalInexistente():
    """Escenario: Principal inexistente.

    WHEN la instrucción falla porque el principal no existe en el workspace
    THEN el ítem se reporta `fallido` con un mensaje que identifica el principal
         inexistente.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT",
        ErrorMotorSql(
            "[PRINCIPAL_DOES_NOT_EXIST] El principal referido no existe en el "
            "workspace."
        ),
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("READ FILES"))

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert BENEFICIARIO in resultado.detalle


def TestEscenarioCualquierOtroFalloDeSesion():
    """Escenario: Cualquier otro fallo de la sesión.

    WHEN la sesión falla por una causa distinta (transporte, sentencia rechazada)
    THEN el ítem se reporta `fallido` con el detalle del error y sin la marca de
         privilegios insuficientes.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT", ErrorMotorSql("Fallo de transporte: timeout de conexión.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("USE CONNECTION", objeto=CONNECTION))

    assert resultado.estado is EstadoItem.FALLIDO
    assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "timeout" in resultado.detalle


# --- Verificación posterior al grant con SHOW GRANTS ------------------------


def TestEscenarioGrantConfirmadoPorLaVerificacion():
    """Escenario: Grant confirmado por la verificación.

    WHEN un otorgamiento exitoso sobre una external location o una connection se
         verifica y la consulta reporta el privilegio concedido al principal
    THEN el ítem se reporta con estado `otorgado`.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        EXTERNAL_LOCATION, [FilaLocation(BENEFICIARIO, "READ FILES")]
    )
    sesion.ConfigurarShowGrant(
        CONNECTION, [FilaConnection(BENEFICIARIO, "USE CONNECTION")]
    )
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte_location = pipeline.Procesar(
        CrearSolicitud(EXTERNAL_LOCATION, ["READ FILES"])
    )
    reporte_connection = pipeline.Procesar(
        CrearSolicitud(CONNECTION, ["USE CONNECTION"])
    )

    assert reporte_location.lineas[0].estado is EstadoItem.OTORGADO
    assert reporte_connection.lineas[0].estado is EstadoItem.OTORGADO
    # La verificación consultó cada objeto con su propia palabra clave.
    assert (
        "SHOW GRANT ON EXTERNAL LOCATION `ubicacion_externa_pruebas`"
        in sesion.sentencias
    )
    assert (
        "SHOW GRANT ON CONNECTION `conexion_sqlserver_pruebas`"
        in sesion.sentencias
    )


def TestEscenarioGrantNoConfirmadoPorLaVerificacion():
    """Escenario: Grant no confirmado por la verificación.

    WHEN un otorgamiento reportado como exitoso no aparece en los grants
         vigentes del objeto externo
    THEN el ítem se reporta `fallido` con un detalle que menciona el privilegio,
         el principal y el objeto.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(CONNECTION, [])  # la verificación no lo encuentra
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(CrearSolicitud(CONNECTION, ["USE CONNECTION"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "USE CONNECTION" in linea.detalle
    assert BENEFICIARIO in linea.detalle
    assert CONNECTION.identificador in linea.detalle


def TestEscenarioFilasPropiasConservanElTipoConsultado():
    """Escenario: Filas propias conservan el tipo consultado.

    WHEN la consulta de grants vigentes devuelve la fila del propio objeto
         consultado
    THEN esa fila se traduce a un otorgamiento con el tipo consultado, y
         cualquier fila con palabra no mapeable (p. ej. un contenedor padre como
         `METASTORE`) se omite sin inventar objeto.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        EXTERNAL_LOCATION,
        [
            FilaLocation(BENEFICIARIO, "READ FILES"),
            Fila("propietario", "OWN", "METASTORE", "metastore_root"),
        ],
    )
    sesion.ConfigurarShowGrant(
        CONNECTION, [FilaConnection("grupo_analistas", "USE CONNECTION")]
    )
    canal = CanalSqlDatos(sesion)

    grants_location = canal.ListarGrantsVigentes(EXTERNAL_LOCATION)
    grants_connection = canal.ListarGrantsVigentes(CONNECTION)

    # La fila del contenedor metastore se omite: queda solo la fila propia.
    assert len(grants_location) == 1
    assert grants_location[0].objeto.tipo is TipoObjeto.EXTERNAL_LOCATION
    assert grants_location[0].objeto.identificador == (
        EXTERNAL_LOCATION.identificador
    )
    assert grants_location[0].privilegio == "READ FILES"
    assert len(grants_connection) == 1
    assert grants_connection[0].objeto.tipo is TipoObjeto.CONNECTION
    assert grants_connection[0].principal.tipo is TipoPrincipal.GRUPO


# --- Cardinalidades 1 a 1, 1 a N y N a 1 ------------------------------------


def TestEscenarioLoteUnoANSobreExternalLocations():
    """Escenario: Lote 1 a N sobre external locations.

    WHEN un principal recibe privilegios sobre varias external locations en un
         lote
    THEN cada combinación privilegio-objeto se procesa como ítem atómico con su
         resultado parcial, y el lote se consolida en el reporte.
    """
    location_1 = ObjetoSecurable(
        identificador="ubicacion_lote_1", tipo=TipoObjeto.EXTERNAL_LOCATION
    )
    location_2 = ObjetoSecurable(
        identificador="ubicacion_lote_2", tipo=TipoObjeto.EXTERNAL_LOCATION
    )
    privilegios = ["READ FILES", "WRITE FILES"]

    sesion = SesionSqlDoble()
    for location in (location_1, location_2):
        sesion.ConfigurarShowGrant(
            location,
            [
                FilaLocation(BENEFICIARIO, privilegio, objeto=location)
                for privilegio in privilegios
            ],
        )
    # WRITE FILES falla sobre la segunda location: resultado parcial real.
    sesion.ConfigurarErrorEn(
        "GRANT WRITE FILES ON EXTERNAL LOCATION `ubicacion_lote_2`",
        ErrorMotorSql("[PERMISSION_DENIED] Denegado para el ejecutor."),
    )
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.ProcesarLoteDesdeEntradas(
        principales=[
            Principal(identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO)
        ],
        privilegios=privilegios,
        objetos=[location_1, location_2],
    )

    # 4 ítems atómicos (2 privilegios x 2 objetos), con resultados parciales.
    assert len(reporte.lineas) == 4
    estados = [linea.estado for linea in reporte.lineas]
    assert estados.count(EstadoItem.OTORGADO) == 3
    assert estados.count(EstadoItem.PRIVILEGIOS_INSUFICIENTES) == 1
    # Cada ítem emitió su propia instrucción con la palabra clave de dos tokens.
    assert all(
        "ON EXTERNAL LOCATION `" in sentencia
        for sentencia in sesion.SentenciasDeEscritura()
    )


def TestEscenarioLoteNUnoASobreUnaConnection():
    """Escenario: Lote N a 1 sobre una connection.

    WHEN varios principals reciben privilegios sobre una misma connection en un
         lote
    THEN cada combinación principal-privilegio se procesa como ítem atómico con
         su resultado parcial.
    """
    principal_1 = "usuario_uno@example.com"
    principal_2 = "usuario_dos@example.com"
    principal_inexistente = "inexistente@example.com"

    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        CONNECTION,
        [
            FilaConnection(principal_1, "USE CONNECTION"),
            FilaConnection(principal_2, "USE CONNECTION"),
        ],
    )
    sesion.ConfigurarErrorEn(
        f"GRANT USE CONNECTION ON CONNECTION "
        f"`conexion_sqlserver_pruebas` TO `{principal_inexistente}`",
        ErrorMotorSql(
            "[PRINCIPAL_DOES_NOT_EXIST] El principal referido no existe."
        ),
    )
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.ProcesarLoteDesdeEntradas(
        principales=[
            Principal(identificador=principal_1, tipo=TipoPrincipal.USUARIO),
            Principal(
                identificador=principal_inexistente,
                tipo=TipoPrincipal.USUARIO,
            ),
            Principal(identificador=principal_2, tipo=TipoPrincipal.USUARIO),
        ],
        privilegios=["USE CONNECTION"],
        objetos=[CONNECTION],
    )

    # 3 ítems atómicos (3 principals x 1 privilegio x 1 objeto).
    assert len(reporte.lineas) == 3
    estados_por_principal = {
        linea.item.principal.identificador: linea.estado
        for linea in reporte.lineas
    }
    assert estados_por_principal[principal_1] is EstadoItem.OTORGADO
    assert estados_por_principal[principal_2] is EstadoItem.OTORGADO
    assert (
        estados_por_principal[principal_inexistente] is EstadoItem.FALLIDO
    ), "El fallo de un principal no debe abortar los demás ítems del lote"


def TestEscenarioLoteNAMRechazado():
    """Escenario: Lote N a M rechazado.

    WHEN una solicitud sobre objetos externos declara varios principals y varios
         objetos
    THEN se rechaza con el mensaje explícito de cardinalidad N a M no soportada,
         sin ejecutar instrucción alguna.
    """
    sesion = SesionSqlDoble()
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    with pytest.raises(ErrorDominio) as error:
        pipeline.ProcesarLoteDesdeEntradas(
            principales=[
                Principal(
                    identificador="usuario_uno@example.com",
                    tipo=TipoPrincipal.USUARIO,
                ),
                Principal(
                    identificador="usuario_dos@example.com",
                    tipo=TipoPrincipal.USUARIO,
                ),
            ],
            privilegios=["READ FILES"],
            objetos=[EXTERNAL_LOCATION, CONNECTION],
        )

    assert "N a M" in str(error.value)
    assert "fuera de alcance" in str(error.value)
    assert sesion.sentencias == [], (
        "El rechazo de la cardinalidad ocurre antes de cualquier ejecución"
    )


# --- Cobertura completa del plano de datos ----------------------------------


def TestEscenarioObjetoDelPlanoDeControlFueraDelCanal():
    """Escenario: Objeto del plano de control fuera del canal.

    WHEN llega al canal SQL un ítem cuyo objeto pertenece al plano de control
    THEN el ítem se reporta `fallido` con el mensaje explícito de tipo no
         soportado por este canal y no se ejecuta ninguna instrucción SQL.

    El pipeline enruta por plano (design D5 de C2), de modo que este escenario
    cubre la defensa del propio canal: si un ítem de control llegara a él, la
    construcción de la sentencia lo rechaza con `ErrorCanal` y el contrato base
    lo convierte en resultado `fallido` por ítem, sin propagar la excepción ni
    tocar la sesión.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)
    objetos_de_control = (
        ObjetoSecurable(
            identificador="a1b2c3d4", tipo=TipoObjeto.COMPUTO_CLASICO
        ),
        ObjetoSecurable(
            identificador="b2c3d4e5", tipo=TipoObjeto.COMPUTO_SERVERLESS
        ),
        ObjetoSecurable(
            identificador="c3d4e5f6", tipo=TipoObjeto.SQL_WAREHOUSE
        ),
        ObjetoSecurable(
            identificador="d4e5f6a7", tipo=TipoObjeto.DATABRICK_APP
        ),
        ObjetoSecurable(
            identificador="e5f6a7b8", tipo=TipoObjeto.USO_TOKEN
        ),
    )

    for objeto in objetos_de_control:
        # La construcción de la sentencia rechaza el tipo ajeno al canal.
        with pytest.raises(ErrorCanal):
            CanalSqlDatos.ConstruirSentenciaOtorgamiento(
                CrearItem("CAN_MANAGE", objeto=objeto)
            )
        # Y por la vía del contrato, el ítem se reporta fallido con el mensaje
        # explícito de tipo no soportado, sin ejecutar instrucción alguna.
        resultado = canal.Otorgar(CrearItem("CAN_MANAGE", objeto=objeto))
        assert resultado.estado is EstadoItem.FALLIDO
        assert "no está soportado" in resultado.detalle
        assert "plano de control" in resultado.detalle

    assert sesion.SentenciasDeEscritura() == [], (
        "Ningún ítem del plano de control debe producir una instrucción SQL"
    )


# --- Pruebas integrales autocontenidas con perfil por tipo ------------------


def TestEscenarioFixturesCreadasYDestruidasPorLaPropiaPrueba(monkeypatch):
    """Escenario: Fixtures creadas y destruidas por la propia prueba.

    WHEN corre una prueba integral de otorgamiento y verificación sobre objetos
         externos
    THEN la prueba crea su external location (perfil `andresAzureDev`) o su
         connection (perfil `andresFree`), ejecuta el grant, lo verifica y
         destruye todo lo creado, sin dejar grants ni objetos residuales.

    Se ejercita la fábrica real con sesiones simuladas y el descubrimiento de
    Unity Catalog imitado: la external location se crea con el credential y la
    cuenta descubiertos (nunca hardcodeados) sobre el contenedor de pruebas, y
    la connection con los datos del SQL Server de pruebas declarados en la
    fixture.
    """
    monkeypatch.setattr(
        fixtures_uc_externos,
        "EjecutarComandoCli",
        DescubrimientoUnityCatalogSimulado,
    )
    ExportarEntornoConexion(monkeypatch)
    sesion_location = SesionSqlDoble()
    sesion_connection = SesionSqlDoble()
    fabrica = FixturesUcExternos(
        sesion_location=sesion_location,
        sesion_connection=sesion_connection,
    )

    fabrica.Crear()

    location = fabrica.Objeto(TipoObjeto.EXTERNAL_LOCATION)
    connection = fabrica.Objeto(TipoObjeto.CONNECTION)
    assert location is not None, f"Motivo: {fabrica.no_creados}"
    assert connection is not None, f"Motivo: {fabrica.no_creados}"

    # La external location se crea con lo descubierto en el workspace y sobre el
    # contenedor de pruebas designado por el humano.
    sentencia_location = sesion_location.sentencias[0]
    assert sentencia_location.startswith(
        f"CREATE EXTERNAL LOCATION `{location.nombre}`"
    )
    assert f"{CONTENEDOR_PRUEBAS}@{CUENTA_ALMACENAMIENTO}" in sentencia_location
    assert CREDENCIAL_ALMACENAMIENTO in sentencia_location
    # La connection se crea con los datos del SQL Server de pruebas leídos del
    # entorno: ningún dato de conexión vive en el código (decisión del humano).
    sentencia_connection = sesion_connection.sentencias[0]
    assert sentencia_connection.startswith(
        f"CREATE CONNECTION `{connection.nombre}` TYPE SQLSERVER"
    )
    assert f"host '{HOST_SQLSERVER_FICTICIO}'" in sentencia_connection
    assert f"port '{PUERTO_SQLSERVER_FICTICIO}'" in sentencia_connection
    assert f"user '{USUARIO_SQLSERVER_FICTICIO}'" in sentencia_connection
    assert f"password '{PASSWORD_SQLSERVER_FICTICIO}'" in sentencia_connection

    # Se otorga y verifica sobre cada fixture, como hace la prueba integral.
    canal_location = CanalSqlDatos(sesion_location)
    canal_connection = CanalSqlDatos(sesion_connection)
    objeto_location = ObjetoSecurable(
        identificador=location.identificador, tipo=location.tipo
    )
    objeto_connection = ObjetoSecurable(
        identificador=connection.identificador, tipo=connection.tipo
    )
    sesion_location.ConfigurarShowGrant(
        objeto_location,
        [FilaLocation(BENEFICIARIO, location.privilegio, objeto=objeto_location)],
    )
    sesion_connection.ConfigurarShowGrant(
        objeto_connection,
        [
            FilaConnection(
                BENEFICIARIO, connection.privilegio, objeto=objeto_connection
            )
        ],
    )
    item_location = CrearItem(location.privilegio, objeto=objeto_location)
    item_connection = CrearItem(connection.privilegio, objeto=objeto_connection)
    assert canal_location.Otorgar(item_location).estado is EstadoItem.OTORGADO
    assert (
        canal_connection.Otorgar(item_connection).estado is EstadoItem.OTORGADO
    )
    assert canal_location.ListarGrantsVigentes(objeto_location)
    assert canal_connection.ListarGrantsVigentes(objeto_connection)

    # Limpieza total: REVOKE de lo otorgado y DROP de todo lo creado, cada uno
    # por la sesión del perfil donde vive el objeto.
    fabrica.RegistrarGrant(item_location)
    fabrica.RegistrarGrant(item_connection)
    fabrica.Limpiar()

    assert (
        f"REVOKE {location.privilegio} ON EXTERNAL LOCATION "
        f"`{location.nombre}` FROM `{BENEFICIARIO}`" in sesion_location.sentencias
    )
    assert (
        f"DROP EXTERNAL LOCATION IF EXISTS `{location.nombre}`"
        in sesion_location.sentencias
    )
    assert (
        f"REVOKE {connection.privilegio} ON CONNECTION `{connection.nombre}` "
        f"FROM `{BENEFICIARIO}`" in sesion_connection.sentencias
    )
    assert (
        f"DROP CONNECTION IF EXISTS `{connection.nombre}`"
        in sesion_connection.sentencias
    )


def TestEscenarioConnectionConFallbackAutorizado(monkeypatch):
    """Escenario: Connection con fallback autorizado.

    WHEN el perfil `andresFree` presenta un problema para crear la fixture de
         connection
    THEN la fixture se intenta contra `andresAzureDev`, autorización otorgada por
         el humano.
    """
    monkeypatch.setattr(
        fixtures_uc_externos,
        "EjecutarComandoCli",
        DescubrimientoUnityCatalogSimulado,
    )
    ExportarEntornoConexion(monkeypatch)
    sesion_free = SesionSqlDoble()
    sesion_free.ConfigurarErrorEn(
        "CREATE CONNECTION",
        ErrorMotorSql(
            "[FEATURE_NOT_SUPPORTED] Lakehouse Federation no disponible en "
            "Free Edition."
        ),
    )
    sesion_azure = SesionSqlDoble()
    fabrica = FixturesUcExternos(
        sesion_connection=sesion_free,
        sesion_connection_respaldo=sesion_azure,
    )

    fabrica.CrearConnection()

    connection = fabrica.Objeto(TipoObjeto.CONNECTION)
    assert connection is not None, (
        f"El fallback autorizado debió crear la connection: {fabrica.no_creados}"
    )
    # La connection vive en el perfil de respaldo y así lo usa la limpieza.
    assert fabrica.SesionConnection() is sesion_azure
    assert any(
        sentencia.startswith(f"CREATE CONNECTION `{connection.nombre}`")
        for sentencia in sesion_azure.sentencias
    )
    assert "_connection_fallback_usado" in fabrica.no_creados, (
        "El uso del fallback debe quedar documentado en la fábrica"
    )


def TestEscenarioTipoNoCreableEnNingunPerfil(monkeypatch):
    """Escenario: Tipo no creable en ningún perfil.

    WHEN ni `andresFree` ni `andresAzureDev` permiten crear la fixture de un tipo
         externo
    THEN la prueba integral de ese tipo queda marcada con skip explícito que
         documenta la limitación, y el comportamiento se cubre en las capas
         unitaria y funcional.

    Se verifican las tres condiciones que alimentan ese skip: la connection que
    falla en ambos perfiles, la connection que no puede intentarse porque faltan
    las variables de entorno con sus datos, y la external location que el
    workspace no permite crear (sin datos que descubrir). Los motivos quedan
    registrados en `no_creados`, que es lo que la prueba integral reporta al
    saltarse, y en ningún caso contienen la contraseña ni el usuario: el motor
    devuelve la sentencia completa en sus fallos y esos textos se versionan en
    los informes JUnit (decisión del humano).
    """
    # Caso 1: la connection falla en el perfil primario y en el de respaldo, y el
    # error del motor incluye la sentencia completa con los datos sensibles.
    ExportarEntornoConexion(monkeypatch)
    sesion_free = SesionSqlDoble()
    sesion_free.ConfigurarErrorEn(
        "CREATE CONNECTION",
        ErrorMotorSql(
            "[INVALID_CREDENTIALS] Login failed for user. | SQL: CREATE "
            "CONNECTION `c6_conn_demo` TYPE SQLSERVER OPTIONS (host "
            f"'{HOST_SQLSERVER_FICTICIO}', port '{PUERTO_SQLSERVER_FICTICIO}', "
            f"user '{USUARIO_SQLSERVER_FICTICIO}', "
            f"password '{PASSWORD_SQLSERVER_FICTICIO}')"
        ),
    )
    sesion_azure = SesionSqlDoble()
    sesion_azure.ConfigurarErrorEn(
        "CREATE CONNECTION", ErrorMotorSql("[FEATURE_NOT_SUPPORTED] Azure.")
    )
    fabrica_connection = FixturesUcExternos(
        sesion_connection=sesion_free,
        sesion_connection_respaldo=sesion_azure,
    )

    fabrica_connection.CrearConnection()

    assert fabrica_connection.Objeto(TipoObjeto.CONNECTION) is None
    motivo_connection = fabrica_connection.no_creados[
        TipoObjeto.CONNECTION.value
    ]
    assert "INVALID_CREDENTIALS" in motivo_connection
    assert "FEATURE_NOT_SUPPORTED" in motivo_connection
    assert "Azure" in motivo_connection, (
        "El motivo debe incluir el fallo de ambos perfiles"
    )
    # Redacción de secretos: ni la contraseña ni el usuario llegan al motivo.
    assert PASSWORD_SQLSERVER_FICTICIO not in motivo_connection
    assert USUARIO_SQLSERVER_FICTICIO not in motivo_connection
    assert MARCADOR_SECRETO_OCULTO in motivo_connection

    # Caso 2: faltan las variables de entorno con los datos del SQL Server, de
    # modo que la connection no puede intentarse en ningún perfil.
    BorrarEntornoConexion(monkeypatch)
    sesion_sin_datos = SesionSqlDoble()
    fabrica_sin_entorno = FixturesUcExternos(sesion_connection=sesion_sin_datos)

    fabrica_sin_entorno.CrearConnection()

    assert fabrica_sin_entorno.Objeto(TipoObjeto.CONNECTION) is None
    motivo_falta_entorno = fabrica_sin_entorno.no_creados[
        TipoObjeto.CONNECTION.value
    ]
    for nombre_variable in NOMBRES_VARIABLES_ENTORNO_SQLSERVER:
        assert nombre_variable in motivo_falta_entorno, (
            "El motivo debe listar cada variable de entorno ausente"
        )
    assert ".env.example" in motivo_falta_entorno
    assert sesion_sin_datos.sentencias == [], (
        "Sin datos de conexión no debe ejecutarse ningún DDL"
    )

    # Caso 3: la external location no se puede crear porque el workspace no
    # expone credential ni URL de la que derivar el contenedor de pruebas.
    monkeypatch.setattr(
        fixtures_uc_externos,
        "EjecutarComandoCli",
        DescubrimientoSinDatos,
    )
    fabrica_location = FixturesUcExternos(sesion_location=SesionSqlDoble())

    fabrica_location.CrearExternalLocation()

    assert fabrica_location.Objeto(TipoObjeto.EXTERNAL_LOCATION) is None
    assert not fabrica_location.locations
    motivo_location = fabrica_location.no_creados[
        TipoObjeto.EXTERNAL_LOCATION.value
    ]
    assert "storage credential" in motivo_location
