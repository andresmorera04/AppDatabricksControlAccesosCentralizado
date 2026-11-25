"""Fábrica de fixtures autocontenidas para las integrales de grants-uc-externos.

Infraestructura EXCLUSIVA de la capa integral (tarea 5.1 del change
`grants-uc-externos`, C6): crea por corrida los objetos externos que el change
necesita probar y limpia TODO lo creado al final, de modo que ninguna prueba
deje estado residual en el workspace.

Perfil por tipo de objeto (decisiones del humano, design D6):

- **external location** contra `andresAzureDev`: se crea con el storage
  credential existente del workspace sobre el contenedor de pruebas `test`. Ni
  el credential ni la cuenta de almacenamiento se hardcodean (regla del
  proyecto): se descubren consultando la API de Unity Catalog del workspace y la
  URL del contenedor de pruebas se deriva de una external location existente.
- **connection** contra `andresFree`: se crea hacia el SQL Server de pruebas
  cuyos datos de conexión se leen de **variables de entorno** (decisión del
  humano: la contraseña nunca se versiona; plantilla sin secretos en
  `.env.example`, archivo local `.env` gitignoreado). Si el perfil Free presenta
  problemas, se intenta el mismo DDL contra `andresAzureDev` (fallback autorizado
  por el humano).

Ningún secreto queda registrado en texto alguno: el motor SQL devuelve los fallos
de DDL con la sentencia completa (`| SQL: CREATE CONNECTION ... password '...'`),
y esos textos alimentan el motivo del skip y los informes JUnit de `results/`,
que sí se versionan, por lo que `TextoSinSecretos` redacta la contraseña y el
usuario antes de guardarlos.

Cada tipo se puede crear por separado (`CrearExternalLocation`,
`CrearConnection`) porque cada módulo integral usa un perfil distinto, y la
external location admite varias instancias para ejercitar la cardinalidad 1 a N
del lote (spec - "Lote 1 a N sobre external locations").

Creación best-effort por tipo: si un objeto no puede crearse en ningún perfil
disponible, se registra el motivo en `no_creados` y la prueba que lo consuma se
salta con ese motivo documentado (spec - "Tipo no creable en ningún perfil").

Convención de nombres: infraestructura de pruebas con el mismo estándar del
proyecto (clases y funciones en PascalCase, constantes en MAYÚSCULAS,
comentarios en español).
"""

import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from adaptador_sql_databricks import (
    PERFIL_CLI_INTEGRAL,
    EjecutarComandoCli,
)
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.dominio.enumeraciones import TipoObjeto

# Perfil CLI del workspace de Azure Databricks (decisión del humano para la
# fixture de external location, design D6). Es también el perfil de respaldo
# autorizado para la fixture de connection si `andresFree` presenta problemas.
PERFIL_CLI_AZURE = "andresAzureDev"

# Rutas de la API de Unity Catalog usadas para descubrir, sin hardcodear, el
# storage credential y la cuenta de almacenamiento del workspace.
RUTA_API_EXTERNAL_LOCATIONS = "/api/2.1/unity-catalog/external-locations"
RUTA_API_STORAGE_CREDENTIALS = "/api/2.1/unity-catalog/storage-credentials"

# Contenedor de pruebas designado por el humano para las external locations.
CONTENEDOR_PRUEBAS = "test"

# Tipo de proveedor de la connection: dato declarativo del DDL, no sensible.
CONNECTION_TIPO_PROVEEDOR = "SQLSERVER"

# Nombres de las variables de entorno con los datos del SQL Server de pruebas
# (decisión del humano: la contraseña NUNCA se versiona). Los cuatro valores
# viven fuera del código —regla estricta "configuración no hardcodeada"— y se
# exportan en el entorno antes de correr la capa integral: la plantilla sin
# secretos está en `.env.example` (versionada) y el archivo local `.env` queda
# gitignoreado. Si falta alguna variable, la fixture de connection no se crea y
# el motivo queda documentado en `no_creados`, de modo que la prueba integral se
# salta con justificación (spec - "Tipo no creable en ningún perfil") en lugar de
# fallar.
NOMBRE_VARIABLE_ENTORNO_HOST_SQLSERVER = "CONTROL_ACCESOS_SQLSERVER_HOST"
NOMBRE_VARIABLE_ENTORNO_PUERTO_SQLSERVER = "CONTROL_ACCESOS_SQLSERVER_PORT"
NOMBRE_VARIABLE_ENTORNO_USUARIO_SQLSERVER = "CONTROL_ACCESOS_SQLSERVER_USER"
NOMBRE_VARIABLE_ENTORNO_PASSWORD_SQLSERVER = (
    "CONTROL_ACCESOS_SQLSERVER_PASSWORD"
)

# Las cuatro variables, en el orden en que se listan en los mensajes de falta de
# configuración (dato declarativo, no lógica dispersa).
NOMBRES_VARIABLES_ENTORNO_SQLSERVER = (
    NOMBRE_VARIABLE_ENTORNO_HOST_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_PUERTO_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_USUARIO_SQLSERVER,
    NOMBRE_VARIABLE_ENTORNO_PASSWORD_SQLSERVER,
)

# Marcador que sustituye a la contraseña en cualquier texto que se registre. El
# motor SQL devuelve los fallos de DDL con la sentencia completa
# (`| SQL: CREATE CONNECTION ... password '<secreto>'`), y ese texto termina en
# el motivo del skip y en los informes JUnit de `results/`, que SÍ se versionan:
# ningún secreto debe llegar ahí (decisión del humano).
MARCADOR_SECRETO_OCULTO = "***"

# Prefijos de los nombres de las fixtures, con sufijo único por corrida para no
# chocar con restos de ejecuciones anteriores (design - riesgos).
PREFIJO_NOMBRE_EXTERNAL_LOCATION = "c6_extloc_"
PREFIJO_NOMBRE_CONNECTION = "c6_conn_"

# Privilegios representativos que las integrales otorgan y verifican por tipo.
PRIVILEGIO_EXTERNAL_LOCATION = "READ FILES"
PRIVILEGIO_CONNECTION = "USE CONNECTION"


@dataclass(frozen=True)
class FixtureObjetoExterno:
    """Un objeto externo creado por la fábrica, listo para probar.

    Attributes:
        tipo (TipoObjeto): `EXTERNAL_LOCATION` o `CONNECTION`.
        nombre (str): nombre simple del objeto en el metastore.
        privilegio (str): privilegio representativo a otorgar y verificar.
        identificador (str): identificador del objeto para el dominio (igual al
            nombre simple: estos objetos no se califican por catálogo/esquema).
    """

    tipo: TipoObjeto
    nombre: str
    privilegio: str
    identificador: str


def DatosConexionPruebas():
    """Lee los datos del SQL Server de pruebas desde las variables de entorno.

    Ningún dato de conexión vive en el código (regla estricta "configuración no
    hardcodeada" y decisión del humano de no versionar la contraseña): los cuatro
    valores se toman del entorno y la plantilla sin secretos está en
    `.env.example`.

    Returns:
        dict[str, str]: mapa con las claves `host`, `port`, `user` y `password`,
            listo para el DDL de la connection.

    Raises:
        RuntimeError: si falta alguna variable de entorno, listando las ausentes
            y cómo declararlas; la fábrica convierte este fallo en un motivo
            documentado, nunca en un error de la prueba.
    """
    ausentes = [
        nombre
        for nombre in NOMBRES_VARIABLES_ENTORNO_SQLSERVER
        if not os.environ.get(nombre)
    ]
    if ausentes:
        raise RuntimeError(
            "Faltan las variables de entorno con los datos del SQL Server de "
            f"pruebas: {', '.join(ausentes)}. Expórtalas en el entorno antes de "
            "correr la capa integral (plantilla sin secretos en `.env.example`; "
            "el archivo local `.env` está gitignoreado)."
        )

    return {
        "host": os.environ[NOMBRE_VARIABLE_ENTORNO_HOST_SQLSERVER],
        "port": os.environ[NOMBRE_VARIABLE_ENTORNO_PUERTO_SQLSERVER],
        "user": os.environ[NOMBRE_VARIABLE_ENTORNO_USUARIO_SQLSERVER],
        "password": os.environ[NOMBRE_VARIABLE_ENTORNO_PASSWORD_SQLSERVER],
    }


def TextoSinSecretos(texto, datos_conexion):
    """Sustituye los datos sensibles por un marcador en un texto de error.

    El motor SQL incluye la sentencia completa en sus fallos de DDL, y esos
    textos se registran en `no_creados`, en el motivo del skip de la prueba
    integral y en los informes JUnit de `results/` (versionados). Se redactan la
    contraseña y el usuario para que ningún secreto llegue al repositorio.

    Args:
        texto (str): texto original del error o motivo.
        datos_conexion (dict[str, str] | None): datos leídos del entorno; si es
            None no hay nada que redactar.

    Returns:
        str: texto con los valores sensibles sustituidos por
            `MARCADOR_SECRETO_OCULTO`.
    """
    if not datos_conexion:
        return texto

    texto_redactado = texto
    for clave in ("password", "user"):
        valor = datos_conexion.get(clave)
        if valor:
            texto_redactado = texto_redactado.replace(
                valor, MARCADOR_SECRETO_OCULTO
            )
    return texto_redactado


class FixturesUcExternos:
    """Crea y destruye las external locations y la connection de pruebas.

    Attributes:
        locations (list[FixtureObjetoExterno]): external locations creadas.
        objetos (dict[TipoObjeto, FixtureObjetoExterno]): primera fixture de
            cada tipo creado (acceso rápido por tipo).
        no_creados (dict[str, str]): tipos no creados y avisos, con el motivo.
    """

    def __init__(
        self,
        sesion_location=None,
        sesion_connection=None,
        sesion_connection_respaldo=None,
        perfil_location=PERFIL_CLI_AZURE,
    ):
        """Inicializa la fábrica con las sesiones reales por tipo de objeto.

        Args:
            sesion_location (SesionSqlDatabricks | None): sesión del perfil de
                Azure, donde se crean las external locations.
            sesion_connection (SesionSqlDatabricks | None): sesión del perfil
                primario (`andresFree`), donde se intenta crear la connection.
            sesion_connection_respaldo (SesionSqlDatabricks | None): sesión del
                perfil de respaldo autorizado para la connection; si es None, no
                hay fallback y un fallo del perfil primario se documenta.
            perfil_location (str): perfil CLI usado para descubrir el storage
                credential y la cuenta de almacenamiento del workspace.
        """
        self.sesion_location = sesion_location
        self.sesion_connection = sesion_connection
        self.sesion_connection_respaldo = sesion_connection_respaldo
        self.perfil_location = perfil_location

        # Sufijo único por corrida: los nombres no chocan con restos viejos.
        self.sufijo_corrida = uuid.uuid4().hex[:8]
        self.nombre_connection = (
            f"{PREFIJO_NOMBRE_CONNECTION}{self.sufijo_corrida}"
        )

        self.locations = []
        self.objetos = {}
        self.no_creados = {}

        # Sesión que realmente creó la connection (primaria o de respaldo): las
        # pruebas la necesitan para otorgar, verificar y revocar sobre ella.
        self._sesion_efectiva_connection = sesion_connection

        # Grants otorgados por las pruebas, para revocarlos en la limpieza.
        self._grants_otorgados = []

    def Crear(self):
        """Crea ambas fixtures best-effort (los dos perfiles disponibles)."""
        self.CrearExternalLocation()
        self.CrearConnection()

    def CrearExternalLocation(self, cantidad=1):
        """Crea una o varias external locations de pruebas sobre el contenedor.

        Varias instancias comparten el contenedor de pruebas con subrutas
        distintas (la URL de una external location debe ser única en el
        metastore), lo que permite ejercitar la cardinalidad 1 a N del lote.

        Args:
            cantidad (int): número de external locations a crear.
        """
        for indice in range(cantidad):
            nombre = self._NombreLocation(indice)
            try:
                credencial = self._DescubrirStorageCredential()
                url = self._DerivarUrlContenedorPruebas(nombre, credencial)
                self.sesion_location.sql(
                    f"CREATE EXTERNAL LOCATION `{nombre}` "
                    f"URL '{url}' "
                    f"WITH (STORAGE CREDENTIAL `{credencial}`)"
                )
                fixture = FixtureObjetoExterno(
                    tipo=TipoObjeto.EXTERNAL_LOCATION,
                    nombre=nombre,
                    privilegio=PRIVILEGIO_EXTERNAL_LOCATION,
                    identificador=nombre,
                )
                self.locations.append(fixture)
                self.objetos.setdefault(TipoObjeto.EXTERNAL_LOCATION, fixture)
            except Exception as error:  # noqa: BLE001 - best-effort por tipo
                self.no_creados[TipoObjeto.EXTERNAL_LOCATION.value] = (
                    f"{type(error).__name__}: {error}"
                )
                return

    def CrearConnection(self):
        """Crea la connection de pruebas, con el fallback autorizado.

        Los datos del SQL Server de pruebas se leen del entorno (nunca del
        código): si faltan las variables, la fixture no se crea y el motivo queda
        documentado, igual que si el DDL fallara. Intenta el DDL contra el perfil
        primario (`andresFree`); si falla y hay sesión de respaldo, lo intenta
        contra `andresAzureDev` (autorización del humano, design D6). Si ambos
        fallan, el motivo queda registrado —con los datos sensibles redactados— y
        la prueba correspondiente se salta.
        """
        sesiones = [sesion for sesion in (
            self.sesion_connection, self.sesion_connection_respaldo
        ) if sesion is not None]

        try:
            datos_conexion = DatosConexionPruebas()
            sentencia = self._SentenciaCrearConnection(datos_conexion)
        except RuntimeError as error:
            # Falta de configuración del entorno: se documenta como tipo no
            # creado (skip justificado), no como fallo de la prueba.
            self.no_creados[TipoObjeto.CONNECTION.value] = (
                f"{type(error).__name__}: {error}"
            )
            return

        motivos = []
        for indice, sesion in enumerate(sesiones):
            try:
                sesion.sql(sentencia)
                self._sesion_efectiva_connection = sesion
                fixture = FixtureObjetoExterno(
                    tipo=TipoObjeto.CONNECTION,
                    nombre=self.nombre_connection,
                    privilegio=PRIVILEGIO_CONNECTION,
                    identificador=self.nombre_connection,
                )
                self.objetos[TipoObjeto.CONNECTION] = fixture
                if indice > 0:
                    # Constancia del fallback autorizado: la connection se creó
                    # en el perfil de respaldo, no en el primario.
                    self.no_creados["_connection_fallback_usado"] = (
                        f"El perfil primario ({PERFIL_CLI_INTEGRAL}) falló; la "
                        f"connection se creó en {PERFIL_CLI_AZURE}."
                    )
                return
            except Exception as error:  # noqa: BLE001 - best-effort con fallback
                # El motor devuelve la sentencia completa en el error: se
                # redactan los datos sensibles antes de registrar el motivo.
                motivos.append(
                    TextoSinSecretos(
                        f"{type(error).__name__}: {error}", datos_conexion
                    )
                )

        self.no_creados[TipoObjeto.CONNECTION.value] = " | ".join(motivos)

    def Objeto(self, tipo):
        """Devuelve la primera fixture de un tipo, o None si no se creó.

        Args:
            tipo (TipoObjeto): tipo buscado.

        Returns:
            FixtureObjetoExterno | None: fixture del tipo, o None.
        """
        return self.objetos.get(tipo)

    def SesionConnection(self):
        """Devuelve la sesión donde vive la connection creada.

        Returns:
            SesionSqlDatabricks: la sesión del perfil primario, o la del perfil
                de respaldo si el fallback autorizado se usó.
        """
        return self._sesion_efectiva_connection

    def RegistrarGrant(self, item):
        """Anota un grant otorgado por una prueba, para revocarlo al limpiar.

        Args:
            item (ItemGrant): ítem cuyo privilegio quedó vigente en el workspace.
        """
        self._grants_otorgados.append(item)

    def Limpiar(self):
        """Revoca los grants otorgados y elimina las fixtures creadas.

        La revocación se construye con el propio canal de producción
        (`CanalSqlDatos.ConstruirSentenciaRevocacion`), de modo que la limpieza
        ejercita la misma ruta que las pruebas, y se ejecuta por la sesión del
        perfil donde vive cada objeto (la external location en Azure, la
        connection en el perfil que la creó). Cada paso es best-effort: un fallo
        de limpieza se registra en `no_creados` sin abortar los siguientes,
        porque el objetivo es no dejar estado residual en el workspace.
        """
        for item in self._grants_otorgados:
            sesion = self._SesionPorTipo(item.objeto.tipo)
            if sesion is None:
                continue
            try:
                sesion.sql(CanalSqlDatos.ConstruirSentenciaRevocacion(item))
            except Exception as error:  # noqa: BLE001 - limpieza best-effort
                self.no_creados["_revocacion"] = f"{type(error).__name__}: {error}"

        for fixture in self.locations:
            try:
                self.sesion_location.sql(
                    f"DROP EXTERNAL LOCATION IF EXISTS `{fixture.nombre}`"
                )
            except Exception as error:  # noqa: BLE001 - limpieza best-effort
                self.no_creados[f"_limpieza_{fixture.nombre}"] = (
                    f"{type(error).__name__}: {error}"
                )

        if TipoObjeto.CONNECTION in self.objetos:
            try:
                self._sesion_efectiva_connection.sql(
                    f"DROP CONNECTION IF EXISTS `{self.nombre_connection}`"
                )
            except Exception as error:  # noqa: BLE001 - limpieza best-effort
                self.no_creados["_limpieza_connection"] = (
                    f"{type(error).__name__}: {error}"
                )

    def _SesionPorTipo(self, tipo):
        """Devuelve la sesión del perfil donde vive un tipo de objeto externo.

        Args:
            tipo (TipoObjeto): tipo del objeto a limpiar.

        Returns:
            SesionSqlDatabricks | None: sesión correspondiente, o None si este
                módulo no creó objetos de ese tipo.
        """
        if tipo is TipoObjeto.CONNECTION:
            return self._sesion_efectiva_connection
        return self.sesion_location

    def _NombreLocation(self, indice):
        """Devuelve el nombre único de una external location de la corrida.

        Args:
            indice (int): posición de la location dentro del lote de fixtures.

        Returns:
            str: nombre con el sufijo de corrida y, si hay varias, su índice.
        """
        nombre = f"{PREFIJO_NOMBRE_EXTERNAL_LOCATION}{self.sufijo_corrida}"
        return nombre if indice == 0 else f"{nombre}_{indice}"

    def _DescubrirStorageCredential(self):
        """Descubre el storage credential que usan las external locations.

        Prioriza el credential de una external location existente (es el que ya
        tiene permisos sobre la cuenta); si ninguna lo declara, toma el primero
        del workspace.

        Returns:
            str: nombre del storage credential a usar.

        Raises:
            RuntimeError: si el workspace no expone ningún storage credential.
        """
        for location in self._ExternalLocationsDelWorkspace():
            if location.get("credential_name"):
                return location["credential_name"]

        credenciales = EjecutarComandoCli(
            ["get", RUTA_API_STORAGE_CREDENTIALS], self.perfil_location
        ).get("storage_credentials", [])
        if credenciales:
            return credenciales[0]["name"]

        raise RuntimeError(
            "El workspace no expone ningún storage credential ni external "
            "location de la que derivarlo; no se puede crear la fixture."
        )

    def _DerivarUrlContenedorPruebas(self, nombre, credencial):
        """Deriva la URL del contenedor de pruebas desde una location existente.

        Sustituye el contenedor de la URL de una external location del workspace
        por el contenedor de pruebas designado, conservando el esquema y la
        cuenta de almacenamiento, y agrega una subruta con el nombre de la
        fixture (la URL de cada external location debe ser única).

        Args:
            nombre (str): nombre de la fixture, usado como subruta única.
            credencial (str): storage credential descubierto (para el mensaje).

        Returns:
            str: URL del contenedor de pruebas, lista para el DDL.

        Raises:
            RuntimeError: si ninguna external location existente tiene una URL
                con la forma esperada de la que derivar la cuenta.
        """
        for location in self._ExternalLocationsDelWorkspace():
            base = self._UrlConContenedorSustituido(location.get("url") or "")
            if base is not None:
                return f"{base}{nombre}/"

        raise RuntimeError(
            "Ninguna external location del workspace expone una URL con la "
            f"forma esperada (contenedor@cuenta) para derivar el contenedor "
            f"'{CONTENEDOR_PRUEBAS}' con el credential '{credencial}'."
        )

    def _ExternalLocationsDelWorkspace(self):
        """Lista las external locations del workspace del perfil configurado.

        Returns:
            list[dict]: entradas reportadas por la API de Unity Catalog.
        """
        return EjecutarComandoCli(
            ["get", RUTA_API_EXTERNAL_LOCATIONS], self.perfil_location
        ).get("external_locations", [])

    @staticmethod
    def _UrlConContenedorSustituido(url_existente):
        """Sustituye el contenedor de una URL de almacenamiento conocida.

        Solo reconoce la forma delegada de Azure (`esquema://contenedor@cuenta/`),
        que es la del workspace de pruebas. Cualquier otra forma (p. ej. un bucket
        de S3) devuelve None: la fábrica no inventa URLs (fail-safe).

        Args:
            url_existente (str): URL reportada por el workspace.

        Returns:
            str | None: URL base del contenedor de pruebas (terminada en `/`), o
                None si la forma no es reconocible.
        """
        if not url_existente:
            return None
        partes = urlparse(url_existente)
        if "@" not in partes.netloc:
            return None
        cuenta = partes.netloc.split("@", 1)[1]
        if not cuenta:
            return None
        return f"{partes.scheme}://{CONTENEDOR_PRUEBAS}@{cuenta}/"

    def _SentenciaCrearConnection(self, datos_conexion):
        """Construye el DDL de la connection hacia el SQL Server de pruebas.

        Args:
            datos_conexion (dict[str, str]): datos leídos del entorno por
                `DatosConexionPruebas` (`host`, `port`, `user`, `password`);
                ninguno vive en el código.

        Returns:
            str: sentencia `CREATE CONNECTION ... TYPE SQLSERVER OPTIONS (...)`
                en mayúsculas (estándar del proyecto).
        """
        return (
            f"CREATE CONNECTION `{self.nombre_connection}` "
            f"TYPE {CONNECTION_TIPO_PROVEEDOR} "
            f"OPTIONS ("
            f"host '{datos_conexion['host']}', "
            f"port '{datos_conexion['port']}', "
            f"user '{datos_conexion['user']}', "
            f"password '{datos_conexion['password']}')"
        )
