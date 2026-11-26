"""Proveedor real del contexto on-behalf-of para la Databricks App (C9).

Implementación de producción del puerto `ProveedorIdentidadLlamante` (C3,
capability `caller-identity`) que la UI de grants inyecta al
`ServicioIdentidadLlamante` (design.md D3).

Flujo de resolución, por invocación:

1. Lee el token OBO del header del request cuyo nombre declara la
   configuración (`nombre_encabezado_token_obo`, por defecto el header
   documentado por Databricks Apps para Streamlit). La búsqueda es
   insensible a mayúsculas para funcionar con mapas planos y con el multidict
   de `st.context.headers`.
2. Lee el host del workspace de la variable de entorno que la plataforma
   inyecta al runtime de la App (nombre declarado en la configuración:
   `variable_entorno_host_workspace`).
3. Construye un cliente del workspace EXPLÍCITAMENTE con ese host y ese
   token (fábrica inyectable; en producción `WorkspaceClient(host=...,
   token=...)`), sin heredar las credenciales del service principal de la
   App: quien llama es el usuario, no la App.
4. Verifica la identidad por SCIM (`current_user.me()`) y la traduce a un
   `ContextoLlamante`: usuario (userName/displayName/grupos) o service
   principal (con su App Id, referencia de emparejamiento de C3).

Fallos tipificados (nunca propagan el token en el mensaje; la causa original
queda encadenada para el diagnóstico que registra el servicio):

- header ausente o vacío -> `ErrorContextoLlamanteAusente`;
- host no informado, fallo de transporte, token inválido/expirado o SCIM sin
  identificador utilizable -> `ErrorAutenticacionLlamante`.

El token es un dato local de `ObtenerContexto`: no se guarda en atributos de
la instancia, no se serializa y no aparece en `__repr__` (design.md D11).
"""

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.modelos import ContextoLlamante, Grupo
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoPrincipal

# Nombres de los atributos de configuración que consume este módulo. Los
# VALORES viven en config/app_properties.json (regla No HardCoded); aquí solo
# se declaran los nombres, igual que hace `configuracion_app.py` con
# `ATRIBUTO_CATALOGO`.
ATRIBUTO_ENCABEZADO_TOKEN_OBO = "nombre_encabezado_token_obo"
ATRIBUTO_VARIABLE_ENTORNO_HOST = "variable_entorno_host_workspace"

# Identificador del módulo para trazas y mensajes (convención de los canales
# reales y de la bitácora).
MODULO_PROVEEDOR_IDENTIDAD_APP = "ui.proveedor_identidad_app"


def AccederEncabezadosStreamlit():
    """Acceso de producción a los headers del request actual de Streamlit.

    Se importa Streamlit de forma perezosa para que el módulo sea importable
    fuera del runtime de la App (pruebas unitarias, herramientas).

    Returns:
        Mapping: headers del request actual (multidict insensible a
            mayúsculas).

    Raises:
        Exception: si no hay contexto de request (fuera de Streamlit) o el
            runtime falla; el proveedor lo captura y lo traduce.
    """
    import streamlit as st

    return st.context.headers


def CrearClienteWorkspace(host, token):
    """Fábrica de producción del cliente del workspace con credencial OBO.

    Construcción explícita con host y token del llamante: NUNCA se deja que
    el SDK autoconfigure las credenciales del entorno de la App, porque
    entonces las operaciones saldrían con el service principal de la App y se
    rompería el modelo on-behalf-of (design.md D3).

    Args:
        host (str): URL del workspace (variable de entorno de la plataforma).
        token (str): token OBO del header del request.

    Returns:
        WorkspaceClient: cliente autenticado como el llamante.
    """
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(host=host, token=token)


def _TextoONulo(valor):
    """Normaliza un texto opcional: recorta y convierte vacío en None.

    Args:
        valor (str | None): texto recibido del entorno o de SCIM.

    Returns:
        str | None: texto recortado, o None si no existe o queda vacío.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _BuscarEncabezado(encabezados, nombre_encabezado):
    """Busca un header por nombre, sin distinguir mayúsculas.

    Funciona con mapas planos (pruebas) y con el multidict insensible de
    `st.context.headers` (producción).

    Args:
        encabezados (Mapping | None): mapa de headers del request.
        nombre_encabezado (str): nombre buscado.

    Returns:
        str | None: valor del header, o None si no aparece.
    """
    if not encabezados:
        return None
    nombre_buscado = str(nombre_encabezado).lower()
    for clave, valor in encabezados.items():
        if str(clave).lower() == nombre_buscado:
            return valor
    return None


def LeerTokenObo(acceso_encabezados, configuracion):
    """Lee el token OBO del header cuyo nombre declara la configuración.

    Función compartida por el proveedor de identidad y por la fábrica del
    contexto (design.md D3): una única implementación de la lectura del
    token para que ambos consumidores no diverjan.

    Args:
        acceso_encabezados (callable): función sin argumentos que devuelve el
            mapa de headers del request actual.
        configuracion (ConfiguracionApp): configuración con el atributo
            `nombre_encabezado_token_obo`.

    Returns:
        str: token tal como llegó en el header (no se altera).

    Raises:
        ErrorAutenticacionLlamante: si el mapa de headers no puede leerse.
        ErrorContextoLlamanteAusente: si el header no está o llega vacío.
    """
    nombre_encabezado = configuracion.ObtenerAtributo(
        ATRIBUTO_ENCABEZADO_TOKEN_OBO
    )

    try:
        encabezados = acceso_encabezados()
    except Exception as excepcion:  # noqa: BLE001 - fallo del runtime
        raise ErrorAutenticacionLlamante(
            f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] No se pudieron leer los "
            f"headers del request actual: la identidad del llamante queda "
            f"sin resolver."
        ) from excepcion

    token = _BuscarEncabezado(encabezados, nombre_encabezado)
    if _TextoONulo(token) is None:
        # Ausencia afirmable de contexto: el request no trae token OBO
        # (llamada sin autenticación de usuario habilitada).
        raise ErrorContextoLlamanteAusente(
            f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] La invocación no incluye "
            f"el token on-behalf-of en el header '{nombre_encabezado}': "
            f"no hay identidad de usuario que resolver."
        )
    return token


def LeerHostWorkspace(entorno, configuracion):
    """Lee el host del workspace de la variable de entorno de la plataforma.

    Args:
        entorno (Mapping): variables de entorno del runtime de la App.
        configuracion (ConfiguracionApp): configuración con el atributo
            `variable_entorno_host_workspace`.

    Returns:
        str: host del workspace recortado.

    Raises:
        ErrorAutenticacionLlamante: si la variable no está o llega vacía.
    """
    nombre_variable = configuracion.ObtenerAtributo(
        ATRIBUTO_VARIABLE_ENTORNO_HOST
    )
    host = _TextoONulo(entorno.get(nombre_variable))
    if host is None:
        raise ErrorAutenticacionLlamante(
            f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] El runtime de la App no "
            f"informa el host del workspace en la variable de entorno "
            f"'{nombre_variable}': revise el despliegue de la Databricks App."
        )
    return host


class ProveedorIdentidadDatabricksApp(ProveedorIdentidadLlamante):
    """Proveedor OBO real: header del request + host del entorno + SCIM.

    Todos los colaboradores son inyectables (headers, entorno, fábrica de
    clientes y configuración), de modo que las pruebas unitarias ejercitan el
    flujo completo sin red ni runtime de Streamlit, y la fábrica del contexto
    (design.md D3) compone una instancia nueva por acción.

    Example:
        >>> proveedor = ProveedorIdentidadDatabricksApp(
        ...     acceso_encabezados=AccederEncabezadosStreamlit,
        ...     fabrica_cliente=CrearClienteWorkspace,
        ... )
        >>> contexto = proveedor.ObtenerContexto()  # dentro de la App
    """

    def __init__(
        self,
        acceso_encabezados=None,
        fabrica_cliente=None,
        configuracion=None,
        entorno=None,
    ):
        """Inicializa el proveedor con sus colaboradores.

        Args:
            acceso_encabezados (callable | None): función sin argumentos que
                devuelve el mapa de headers del request; None usa el acceso de
                producción a Streamlit.
            fabrica_cliente (callable | None): función `(host=..., token=...)`
                que construye el cliente del workspace; None usa la fábrica de
                producción con el SDK.
            configuracion (ConfiguracionApp | None): configuración de la
                aplicación; None carga la del proyecto.
            entorno (Mapping | None): variables de entorno; None usa
                `os.environ` del runtime de la App.

        Raises:
            ErrorAutenticacionLlamante: si un colaborador inyectado no es del
                tipo esperado (fail-fast de cableado).
        """
        if acceso_encabezados is not None and not callable(acceso_encabezados):
            raise ErrorAutenticacionLlamante(
                "El acceso a los headers debe ser invocable (devuelve el mapa "
                f"de headers del request); se recibió "
                f"{type(acceso_encabezados).__name__}."
            )
        if fabrica_cliente is not None and not callable(fabrica_cliente):
            raise ErrorAutenticacionLlamante(
                "La fábrica de clientes debe ser invocable con "
                f"'host' y 'token'; se recibió {type(fabrica_cliente).__name__}."
            )

        self._acceso_encabezados = (
            acceso_encabezados or AccederEncabezadosStreamlit
        )
        self._fabrica_cliente = fabrica_cliente or CrearClienteWorkspace

        if configuracion is None:
            from control_accesos.configuracion.configuracion_app import (
                ConfiguracionApp,
            )

            configuracion = ConfiguracionApp.Cargar()
        self._configuracion = configuracion

        if entorno is None:
            import os

            entorno = os.environ
        self._entorno = entorno

        # Nota de seguridad: el token NO se almacena; es un dato local de
        # cada `ObtenerContexto` (design.md D3/D11).

    def ObtenerContexto(self):
        """Resuelve el contexto on-behalf-of de la invocación actual.

        Returns:
            ContextoLlamante: dictado validado con tipo, identificador,
                nombre mostrable, App Id (solo service principals) y grupos
                SCIM del llamante.

        Raises:
            ErrorContextoLlamanteAusente: si el request no trae el header del
                token OBO o llega vacío.
            ErrorAutenticacionLlamante: si el entorno no informa el host, si
                el cliente no puede construirse, si la verificación SCIM
                falla (token inválido o expirado) o si la identidad SCIM no
                reporta un identificador utilizable.
        """
        token = self._ObtenerTokenObo()
        host = self._ObtenerHostWorkspace()
        cliente = self._CrearClienteLlamante(host, token)
        registro_scim = self._VerificarIdentidadScim(cliente)
        return self._TraducirAContexto(registro_scim)

    def _ObtenerTokenObo(self):
        """Lee el token OBO del header declarado en la configuración.

        Delega en la función compartida `LeerTokenObo`, usada también por la
        fábrica del contexto (design.md D3).

        Returns:
            str: token tal como llegó en el header (no se altera).

        Raises:
            ErrorContextoLlamanteAusente: si el header no está o llega vacío.
            ErrorAutenticacionLlamante: si el mapa de headers no puede leerse.
        """
        return LeerTokenObo(self._acceso_encabezados, self._configuracion)

    def _ObtenerHostWorkspace(self):
        """Lee el host del workspace de la variable de entorno de la App.

        Delega en la función compartida `LeerHostWorkspace`.

        Returns:
            str: host del workspace recortado.

        Raises:
            ErrorAutenticacionLlamante: si la variable no está o llega vacía.
        """
        return LeerHostWorkspace(self._entorno, self._configuracion)

    def _CrearClienteLlamante(self, host, token):
        """Construye el cliente del workspace con la credencial del llamante.

        Args:
            host (str): host del workspace.
            token (str): token OBO del request.

        Returns:
            WorkspaceClient: cliente autenticado como el llamante.

        Raises:
            ErrorAutenticacionLlamante: si la fábrica falla (transporte,
                configuración del SDK).
        """
        try:
            return self._fabrica_cliente(host=host, token=token)
        except Exception as excepcion:  # noqa: BLE001 - fallo del transporte
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] No se pudo construir el "
                f"cliente del workspace con la credencial del llamante."
            ) from excepcion

    def _VerificarIdentidadScim(self, cliente):
        """Verifica el token y obtiene el registro SCIM del llamante.

        Args:
            cliente (WorkspaceClient): cliente con la credencial OBO.

        Returns:
            User | ServicePrincipal: registro SCIM del llamante.

        Raises:
            ErrorAutenticacionLlamante: si la llamada falla (token inválido,
                expirado o sin permiso de lectura de identidad).
        """
        try:
            return cliente.current_user.me()
        except Exception as excepcion:  # noqa: BLE001 - token no verificable
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] No se pudo verificar la "
                f"identidad del llamante en el workspace: el token "
                f"on-behalf-of es inválido, está expirado o carece de acceso "
                f"a la lectura de identidad."
            ) from excepcion

    def _TraducirAContexto(self, registro_scim):
        """Traduce el registro SCIM al dictado `ContextoLlamante`.

        Reglas (spec caller-identity):

        - un registro con `application_id` es un service principal y su App
          Id es obligatorio (referencia de emparejamiento de otorgamientos);
        - cualquier otro registro verificable es un usuario; `me()` nunca
          devuelve un grupo como llamante;
        - las membresías sin identificador SCIM (`value` vacío) se descartan:
          no son utilizables para emparejar otorgamientos.

        Args:
            registro_scim (User | ServicePrincipal): registro devuelto por
                `current_user.me()`.

        Returns:
            ContextoLlamante: dictado en bruto para el servicio de C3.

        Raises:
            ErrorAutenticacionLlamante: si el registro no reporta un
                identificador (userName) utilizable.
        """
        identificador = _TextoONulo(getattr(registro_scim, "user_name", None))
        if identificador is None:
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_PROVEEDOR_IDENTIDAD_APP}] La identidad SCIM del "
                f"llamante no reporta un identificador (userName) utilizable."
            )

        nombre_mostrable = _TextoONulo(
            getattr(registro_scim, "display_name", None)
        )
        app_id = _TextoONulo(
            getattr(registro_scim, "application_id", None)
        )

        if app_id is not None:
            tipo = TipoPrincipal.SERVICE_PRINCIPAL
        else:
            tipo = TipoPrincipal.USUARIO

        grupos = []
        for membresia in getattr(registro_scim, "groups", None) or ():
            identificador_grupo = _TextoONulo(getattr(membresia, "value", None))
            if identificador_grupo is None:
                # Membresía sin id SCIM: inutilizable para el emparejamiento
                # de la resolución de privilegios; se descarta.
                continue
            grupos.append(
                Grupo(
                    identificador=identificador_grupo,
                    nombre=_TextoONulo(getattr(membresia, "display", None)),
                )
            )

        return ContextoLlamante(
            tipo=tipo,
            identificador=identificador,
            nombre_mostrable=nombre_mostrable,
            app_id=app_id,
            grupos=tuple(grupos),
        )

    def __repr__(self):
        """Representación para trazas: solo nombres de colaboradores.

        Nunca incluye tokens, headers ni credenciales (design.md D11).

        Returns:
            str: clase y colaboradores del proveedor.
        """
        return (
            f"{type(self).__name__}("
            f"acceso_encabezados={type(self._acceso_encabezados).__name__}, "
            f"fabrica_cliente={type(self._fabrica_cliente).__name__})"
        )
