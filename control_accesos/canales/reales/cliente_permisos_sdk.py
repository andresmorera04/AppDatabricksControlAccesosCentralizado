"""Adaptador del puerto de permisos del canal de cómputo sobre `databricks-sdk`
(capability `compute-grants`).

Implementación de producción del transporte (design D3) que el canal
`CanalControlComputo` consume por inyección: traduce las operaciones del puerto
(`LeerAcl` y `EscribirAcl`) a llamadas de la Permissions API mediante el cliente
`WorkspaceClient`, y devuelve la ACL como una lista de `EntradaAcl` con los
tipos propios del dominio (el canal nunca depende de tipos del SDK).

Escritura por PUT del conjunto completo (contrastado contra el workspace, design
D3/D4): el SDK expone `permissions.update` como **PATCH**, que Databricks rechaza
con `NOT_IMPLEMENTED` en objetos con propietario (`IS_OWNER`), como los SQL
warehouses y los serverless compute objects — `PATCH requests for warehouse ...
with owner permissions are not supported, please use PUT with the full set of
permissions`. El canal ya compone la ACL mediante lectura-modificación-escritura
(design D4), así que la escritura envía el conjunto completo por
`PUT /api/2.0/permissions/<recurso>/<id>`. La lectura sigue usando
`cliente.permissions.get`. Este módulo NO importa `databricks-sdk` al importarse
(regla del proyecto de suites libres de SDK): solo usa el cliente ya inyectado,
sin credenciales ni valores de conexión.

Los errores del SDK se traducen a `ErrorCanal` con el código del error
antepuesto `[CODIGO]` y el detalle: la clasificación de dominio (permiso
denegado, objeto inexistente, principal inexistente) la decide el canal sobre
esos mensajes con sus patrones declarativos (design D6).
"""

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.dominio.modelos import Principal

# Campos con los que la Permissions API identifica al otorgatario, y el tipo de
# principal del dominio que corresponde a cada uno (idéntico criterio al usado
# en la capa integral de C3, `tests/integrales/adaptador_canales_reales.py`).
CAMPOS_PRINCIPAL_DE_ACL = (
    ("user_name", TipoPrincipal.USUARIO),
    ("group_name", TipoPrincipal.GRUPO),
    ("service_principal_name", TipoPrincipal.SERVICE_PRINCIPAL),
)

# Plantilla de la ruta de la Permissions API para la escritura por PUT.
PLANTILLA_RUTA_PERMISOS = "/api/2.0/permissions/{recurso}/{identificador}"


class ClientePermisosSdk:
    """Adaptador del puerto de permisos sobre la Permissions API del cliente SDK.

    Attributes:
        cliente: cliente SDK (`WorkspaceClient`) ya autenticado, con el servicio
            `permissions` (lectura de ACL) y `api_client` (escritura por PUT).
    """

    def __init__(self, cliente):
        """Inicializa el adaptador con el cliente inyectado.

        Args:
            cliente: `WorkspaceClient` (o implementación con `permissions` y
                `api_client`) ya autenticado. El adaptador no crea ni configura
                credenciales.

        Raises:
            ValueError: si no se recibe un cliente con `permissions` y `api_client`.
        """
        if cliente is None or not hasattr(cliente, "permissions"):
            raise ValueError(
                "Se requiere un cliente con el servicio 'permissions' "
                "(WorkspaceClient de databricks-sdk) para operar sobre la "
                "Permissions API."
            )
        if not hasattr(cliente, "api_client"):
            raise ValueError(
                "Se requiere un cliente con 'api_client' para escribir la ACL "
                "por PUT (WorkspaceClient de databricks-sdk)."
            )
        self.cliente = cliente

    def LeerAcl(self, recurso, identificador):
        """Lee la ACL del objeto y la devuelve como entradas directas.

        Args:
            recurso (str): recurso de la Permissions API (`clusters`,
                `serverless-compute`, `sql/warehouses`).
            identificador (str): id del objeto, con su escritura original.

        Returns:
            tuple[EntradaAcl, ...]: una entrada por nivel directo de cada
                otorgatario; vacía si la ACL no tiene entradas directas. Las
                entradas sin otorgatario identificable y los niveles heredados
                se omiten (no se inventa principal ni se escribe lo heredado).

        Raises:
            ErrorCanal: si el objeto no existe o el transporte falla, con el
                código del error antepuesto `[CODIGO]`.
        """
        try:
            objeto = self.cliente.permissions.get(recurso, identificador)
        except Exception as error:  # noqa: BLE001 - se traduce a canal
            raise self._TraducirExcepcion(error)

        entradas = []
        for acl in objeto.access_control_list or ():
            principal = _PrincipalDesdeEntrada(acl)
            if principal is None:
                # Entrada sin otorgatario identificable: se omite sin inventar.
                continue
            for permiso in acl.all_permissions or ():
                if getattr(permiso, "inherited", False):
                    # Solo se gestionan niveles directos (design D5).
                    continue
                nivel = _NivelDePermiso(permiso)
                if nivel is None:
                    continue
                entradas.append(EntradaAcl(principal=principal, nivel=nivel))
        return tuple(entradas)

    def EscribirAcl(self, recurso, identificador, entradas):
        """Escribe la ACL completa del objeto por PUT (conjunto completo).

        El canal compone las entradas mediante la lectura-modificación-escritura
        (nunca reemplaza la ACL sin conocer su estado previo); aquí se traduce la
        lista resultante al cuerpo que espera la Permissions API y se envía por
        PUT, que es la vía admitida para objetos con propietario (`IS_OWNER`).

        Args:
            recurso (str): recurso de la Permissions API.
            identificador (str): id del objeto.
            entradas (list[EntradaAcl]): ACL completa a aplicar, una entrada
                por otorgatario directo.

        Raises:
            ErrorCanal: si el objeto no existe o el transporte falla, con el
                código del error antepuesto `[CODIGO]`.
        """
        cuerpo = {
            "access_control_list": [
                _SolicitudDeEntrada(entrada) for entrada in entradas
            ]
        }
        try:
            self.cliente.api_client.do(
                "PUT",
                PLANTILLA_RUTA_PERMISOS.format(
                    recurso=recurso, identificador=identificador
                ),
                body=cuerpo,
                headers={"Content-Type": "application/json"},
            )
        except Exception as error:  # noqa: BLE001 - se traduce a canal
            raise self._TraducirExcepcion(error)

    @staticmethod
    def _TraducirExcepcion(error):
        """Traduce la excepción del SDK a `ErrorCanal` con código y detalle.

        Args:
            error (BaseException): excepción capturada del cliente SDK.

        Returns:
            ErrorCanal: error con el código antepuesto `[CODIGO]` cuando el SDK
                lo informa, y el detalle del mensaje; sin marca de privilegios
                (la clasificación la hace el canal, design D6).
        """
        codigo = _CodigoDeError(error)
        detalle = _DetalleDeError(error)
        if codigo:
            return ErrorCanal(f"[{codigo}] {detalle}")
        return ErrorCanal(detalle)


def _SolicitudDeEntrada(entrada):
    """Traduce una entrada a la forma de solicitud de la Permissions API.

    Args:
        entrada (EntradaAcl): entrada a traducir.

    Returns:
        dict: solicitud con el campo del principal correspondiente a su tipo
            (`user_name`, `group_name` o `service_principal_name`) y su nivel.
    """
    return {
        _CampoDePrincipal(entrada.principal.tipo): entrada.principal.identificador,
        "permission_level": entrada.nivel,
    }


def _NivelDePermiso(permiso):
    """Devuelve el nivel de permiso directo como texto, o None si no lo hay.

    Args:
        permiso: objeto `Permission` del SDK con `permission_level`.

    Returns:
        str | None: nivel en su forma canónica (`CAN_*`), o None.
    """
    nivel = getattr(permiso, "permission_level", None)
    if nivel is None:
        return None
    valor = getattr(nivel, "value", None)
    if valor is None:
        valor = str(nivel)
    return str(valor).strip() or None


def _CampoDePrincipal(tipo):
    """Devuelve el campo de la ACL que identifica al principal según su tipo.

    Args:
        tipo (TipoPrincipal): tipo del principal.

    Returns:
        str: nombre del campo (`user_name`, `group_name` o
            `service_principal_name`).
    """
    for campo, tipo_asociado in CAMPOS_PRINCIPAL_DE_ACL:
        if tipo is tipo_asociado:
            return campo
    # Por defensa: un tipo fuera de los tres se identifica por usuario (el
    # dominio ya restringe los tipos a USUARIO, GRUPO y SERVICE_PRINCIPAL).
    return "user_name"


def _PrincipalDesdeEntrada(acl):
    """Construye el `Principal` del dominio desde una entrada de la ACL.

    Args:
        acl: entrada de la ACL del SDK (con `user_name`, `group_name` o
            `service_principal_name`).

    Returns:
        Principal | None: principal del dominio, o None si la entrada no trae
            otorgatario identificable.
    """
    for campo, tipo in CAMPOS_PRINCIPAL_DE_ACL:
        valor = getattr(acl, campo, None)
        if valor:
            return Principal(identificador=str(valor), tipo=tipo)
    return None


def _CodigoDeError(error):
    """Extrae el código de error del SDK, en mayúsculas, o None.

    Args:
        error (BaseException): excepción del SDK.

    Returns:
        str | None: código del error (por ejemplo `RESOURCE_DOES_NOT_EXIST`).
    """
    codigo = getattr(error, "error_code", None)
    if isinstance(codigo, str) and codigo.strip():
        return codigo.strip().upper()
    return None


def _DetalleDeError(error):
    """Devuelve el detalle del error como texto no vacío.

    Args:
        error (BaseException): excepción del SDK.

    Returns:
        str: mensaje del error; si no lo trae, el nombre de su tipo.
    """
    detalle = str(error).strip()
    if detalle:
        return detalle
    return f"Error sin mensaje del tipo {type(error).__name__}."
