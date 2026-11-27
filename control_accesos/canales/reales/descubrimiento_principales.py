"""Descubrimiento de principals por SCIM con la identidad del service principal.

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Componente real de solo lectura que lista los principals del workspace (usuarios,
grupos y service principals) usando el service principal de la App (design.md
D4/D6): en el modo broker la App descubre principals con el SP porque el token
OBO del llamante carece de los scopes SCIM necesarios (`iam.access-control`).

Contrato, pensado para la UI de grants y para el aislamiento de autorización:

- API expuesta: `ListarUsuarios`, `ListarGrupos`, `ListarServicePrincipals` y el
  agregado `ListarPrincipales`, cada una devolviendo una tupla de
  `PrincipalDescubierto` (tipo, identificador, nombre mostrable y, para los
  service principals, su App Id preservado);
- paginación transparente: se camina el iterador del SDK sin asumir una sola
  página, con un tope opcional de elementos (`limite`) inyectado desde la
  configuración (regla No HardCoded);
- orden estable: se conserva el orden del servicio (no se barajan las opciones
  entre invocaciones);
- fallo distinguible del vacío: un error del listado se traduce a
  `ErrorListadoPrincipales`; una lista auténticamente vacía se devuelve como
  tupla vacía, sin confundir ambos casos.

El módulo NO importa `databricks-sdk` al importarse: recibe el cliente SP ya
construido (la fábrica broker lo obtiene de la autoconfiguración del entorno de
la App). Ningún valor de conexión ni id vive en el código.
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import TipoPrincipal

# Identificador del módulo para la bitácora de errores (convención del proyecto).
MODULO_DESCUBRIMIENTO = "canal_descubrimiento_principales"


@dataclass(frozen=True)
class PrincipalDescubierto:
    """Principal del workspace descubierto por SCIM con el SP.

    Attributes:
        tipo (TipoPrincipal): usuario, grupo o service principal.
        identificador (str): referencia estable del principal: `user_name` para
            usuarios, `display_name` para grupos y el App Id/`application_id`
            para service principals (preservado, design.md D4).
        nombre_mostrable (str | None): nombre para la UI, si el servicio lo
            informa.
        app_id (str | None): App Id del service principal (solo ellos).
    """

    tipo: TipoPrincipal
    identificador: str
    nombre_mostrable: Optional[str] = None
    app_id: Optional[str] = None


class ErrorListadoPrincipales(RuntimeError):
    """Fallo del listado SCIM con el SP, distinguible de una lista vacía.

    El llamador (UI o aislamiento) no puede confundir "no hay principals" con
    "no pude listarlos": este error representa el segundo caso y se lanza con el
    detalle del transporte redactado (sin credenciales).
    """


class DescubridorPrincipales:
    """Lista principals del workspace por SCIM con la identidad del SP.

    Attributes:
        cliente: cliente SDK (`WorkspaceClient`) autenticado como el SP de la
            App, con los servicios `users`, `groups` y `service_principals`
            (cada uno con `list()`).
    """

    def __init__(self, cliente, limite=None, registrador_errores=None):
        """Inicializa el descubridor con el cliente SP inyectado.

        Args:
            cliente: `WorkspaceClient` del SP, con `users`, `groups` y
                `service_principals` (cada uno con `list()`).
            limite (int | None): tope de elementos por listado; None no limita.
                Lo lee la fábrica broker desde `limite_opciones_descubrimiento`.
            registrador_errores (BitacoraErrores | None): bitácora opcional.

        Raises:
            ValueError: si el cliente no expone los servicios SCIM con `list`.
        """
        self._validar_cliente(cliente)
        self._cliente = cliente
        self._limite = limite
        self._registrador_errores = registrador_errores

    @staticmethod
    def _validar_cliente(cliente):
        """Valida que el cliente exponga los tres servicios SCIM con `list`."""
        if cliente is None:
            raise ValueError(
                "Se requiere un cliente SCIM (WorkspaceClient del service "
                "principal) para listar principals."
            )
        for nombre_servicio in ("users", "groups", "service_principals"):
            servicio = getattr(cliente, nombre_servicio, None)
            if servicio is None or not hasattr(servicio, "list"):
                raise ValueError(
                    f"El cliente debe exponer el servicio SCIM "
                    f"'{nombre_servicio}' con el método 'list()'."
                )

    def ListarUsuarios(self):
        """Lista los usuarios del workspace (user_name y display_name).

        Returns:
            tuple[PrincipalDescubierto, ...]: usuarios, en el orden del servicio.
        """
        return self._Listar(self._cliente.users, _PrincipalDesdeUsuario)

    def ListarGrupos(self):
        """Lista los grupos del workspace (display_name).

        Returns:
            tuple[PrincipalDescubierto, ...]: grupos, en el orden del servicio.
        """
        return self._Listar(self._cliente.groups, _PrincipalDesdeGrupo)

    def ListarServicePrincipals(self):
        """Lista los service principals (application_id preservado).

        Returns:
            tuple[PrincipalDescubierto, ...]: service principals, en el orden
                del servicio, con su App Id preservado.
        """
        return self._Listar(
            self._cliente.service_principals, _PrincipalDesdeServicePrincipal
        )

    def ListarPrincipales(self):
        """Lista los tres tipos de principal en un único agregado estable.

        Returns:
            tuple[PrincipalDescubierto, ...]: usuarios, luego grupos y luego
                service principals, en el orden del servicio de cada tipo.
        """
        return (
            self.ListarUsuarios()
            + self.ListarGrupos()
            + self.ListarServicePrincipals()
        )

    def _Listar(self, servicio, traductor):
        """Materializa el listado caminando el iterador del servicio.

        Args:
            servicio: servicio SCIM con `list()` (iterador paginado del SDK).
            traductor (callable): traduce cada registro a `PrincipalDescubierto`.

        Returns:
            tuple[PrincipalDescubierto, ...]: registros válidos, en orden,
                acotados por `limite` cuando se configuró.

        Raises:
            ErrorListadoPrincipales: si el listado falla (transporte/SCIM), con
                el detalle sin credenciales y causa encadenada.
        """
        try:
            registros = list(servicio.list())
        except Exception as excepcion:  # noqa: BLE001 - se traduce y tipifica
            self._RegistrarFallo(excepcion)
            raise ErrorListadoPrincipales(
                f"[{MODULO_DESCUBRIMIENTO}] No se pudo listar los principals "
                f"del workspace por SCIM con el service principal: {excepcion}"
            ) from excepcion

        resultado = tuple(
            principal
            for principal in (traductor(registro) for registro in registros)
            if principal is not None
        )
        if self._limite is not None:
            return resultado[: self._limite]
        return resultado

    def _RegistrarFallo(self, excepcion):
        """Registra el fallo del listado en la bitácora sin propagarlo.

        Args:
            excepcion (BaseException): excepción capturada del servicio SCIM.
        """
        if self._registrador_errores is None:
            return
        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_DESCUBRIMIENTO,
                usuario=None,
                contexto="listado SCIM de principals con el service principal",
            )
        except Exception:  # noqa: BLE001 - la bitácora nunca propaga
            return


def _TextoONulo(valor):
    """Normaliza un texto opcional: recorta y convierte vacío en None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _PrincipalDesdeUsuario(registro):
    """Traduce un registro SCIM de usuario a `PrincipalDescubierto` (o None)."""
    identificador = _TextoONulo(getattr(registro, "user_name", None))
    if identificador is None:
        return None
    return PrincipalDescubierto(
        tipo=TipoPrincipal.USUARIO,
        identificador=identificador,
        nombre_mostrable=_TextoONulo(getattr(registro, "display_name", None)),
    )


def _PrincipalDesdeGrupo(registro):
    """Traduce un registro SCIM de grupo a `PrincipalDescubierto` (o None)."""
    identificador = _TextoONulo(getattr(registro, "display_name", None))
    if identificador is None:
        return None
    return PrincipalDescubierto(
        tipo=TipoPrincipal.GRUPO,
        identificador=identificador,
        nombre_mostrable=identificador,
    )


def _PrincipalDesdeServicePrincipal(registro):
    """Traduce un service principal conservando su App Id (o None)."""
    app_id = _TextoONulo(getattr(registro, "application_id", None))
    if app_id is None:
        return None
    return PrincipalDescubierto(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL,
        identificador=app_id,
        nombre_mostrable=_TextoONulo(getattr(registro, "display_name", None)),
        app_id=app_id,
    )
