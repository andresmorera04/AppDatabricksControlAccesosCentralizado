"""Proveedores simulados del contexto on-behalf-of (capability `caller-identity`).

Permiten ejercitar la autenticación del llamante **sin conexión externa**,
igual que hacen los canales simulados de `channel-adapters`: las pruebas
unitarias y funcionales del split, de la resolución de privilegios y de la
bitácora necesitan una identidad determinista, y el contexto real de una
Databricks App solo existe dentro de la app desplegada.

Fábricas incluidas (una por escenario del spec):

- `IdentidadUsuarioConGrupos()` / `IdentidadUsuarioSinGrupos()`
- `IdentidadServicePrincipal(app_id, ...)`
- `IdentidadGrupo()`
- `ContextoAusente()` / `ContextoInvalido(...)`

Example:
    >>> proveedor = ProveedorIdentidadSimulado(
    ...     contexto=IdentidadUsuarioConGrupos()
    ... )
    >>> ServicioIdentidadLlamante(proveedor=proveedor).IdentidadResuelta
    True
"""

from control_accesos.autenticacion.errores import (
    ErrorAutenticacionLlamante,
    ErrorContextoLlamanteAusente,
)
from control_accesos.autenticacion.modelos import ContextoLlamante, Grupo
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.dominio.enumeraciones import TipoPrincipal

# Referencias usadas por las fábricas simuladas. Son valores de ejemplo,
# exclusivamente de pruebas: la configuración de la aplicación nunca se
# simula desde aquí (regla No HardCoded).
IDENTIFICADOR_USUARIO_DEMO = "usuario_demo@example.com"
NOMBRE_USUARIO_DEMO = "Usuario Demo"
ID_GRUPO_ADMINS_DEMO = "81065872484794"
NOMBRE_GRUPO_ADMINS_DEMO = "admins"
ID_GRUPO_USERS_DEMO = "83195513137921"
NOMBRE_GRUPO_USERS_DEMO = "users"
NOMBRE_SERVICE_PRINCIPAL_DEMO = "app-demo-la-app"
APP_ID_DEMO = "00000000-0000-0000-0000-000000000000"


class ProveedorIdentidadSimulado(ProveedorIdentidadLlamante):
    """Proveedor que devuelve el contexto configurado o lanza un fallo.

    Attributes:
        llamadas_recibidas (int): cuántas veces el servicio consultó el
            contexto; permite verificar el caché por invocación.
    """

    def __init__(self, contexto=None, excepcion=None):
        """Configura el contexto a devolver o la excepción a lanzar.

        Args:
            contexto (ContextoLlamante | None): dictado que devolverá
                `ObtenerContexto`; None reproduce el contexto ausente.
            excepcion (BaseException | None): excepción que lanzará el
                método, para simular token inválido o servicio no disponible.

        Raises:
            ErrorAutenticacionLlamante: si se configuran a la vez un contexto
                y una excepción, porque el resultado sería ambiguo.
        """
        if contexto is not None and excepcion is not None:
            raise ErrorAutenticacionLlamante(
                "Un proveedor simulado configura contexto o excepción, no "
                "ambas: el resultado de ObtenerContexto sería ambiguo."
            )
        self._contexto = contexto
        self._excepcion = excepcion
        self.llamadas_recibidas = 0

    def ObtenerContexto(self):
        """Devuelve el contexto configurado o lanza la excepción configurada.

        Returns:
            ContextoLlamante | None: el contexto programado en la prueba.

        Raises:
            BaseException: la excepción programada, si aplica.
        """
        self.llamadas_recibidas += 1
        if self._excepcion is not None:
            raise self._excepcion
        return self._contexto


def IdentidadUsuarioConGrupos():
    """Contexto de un usuario miembro de dos grupos (escenario positivo).

    Returns:
        ContextoLlamante: contexto de usuario con grupos `admins` y `users`.
    """
    return ContextoLlamante(
        tipo=TipoPrincipal.USUARIO,
        identificador=IDENTIFICADOR_USUARIO_DEMO,
        nombre_mostrable=NOMBRE_USUARIO_DEMO,
        grupos=(
            Grupo(identificador=ID_GRUPO_ADMINS_DEMO, nombre=NOMBRE_GRUPO_ADMINS_DEMO),
            Grupo(identificador=ID_GRUPO_USERS_DEMO, nombre=NOMBRE_GRUPO_USERS_DEMO),
        ),
    )


def IdentidadUsuarioSinGrupos():
    """Contexto de un usuario sin membresías (lista vacía explícita).

    Returns:
        ContextoLlamante: contexto de usuario con `grupos` vacío.
    """
    return ContextoLlamante(
        tipo=TipoPrincipal.USUARIO,
        identificador=IDENTIFICADOR_USUARIO_DEMO,
        nombre_mostrable=NOMBRE_USUARIO_DEMO,
        grupos=(),
    )


def IdentidadServicePrincipal(app_id=APP_ID_DEMO, nombre=NOMBRE_SERVICE_PRINCIPAL_DEMO):
    """Contexto de la app ejecutándose con su propio service principal.

    Args:
        app_id (str): App Id del service principal (referencia con la que
            Unity Catalog reporta sus otorgamientos).
        nombre (str): nombre del service principal (referencia del plano de
            control).

    Returns:
        ContextoLlamante: contexto de tipo `service_principal` con su App Id.
    """
    return ContextoLlamante(
        tipo=TipoPrincipal.SERVICE_PRINCIPAL,
        identificador=nombre,
        nombre_mostrable=nombre,
        app_id=app_id,
        grupos=(
            Grupo(identificador=ID_GRUPO_USERS_DEMO, nombre=NOMBRE_GRUPO_USERS_DEMO),
        ),
    )


def IdentidadGrupo(nombre=NOMBRE_GRUPO_ADMINS_DEMO):
    """Contexto de un llamante que es un grupo (principal de tipo grupo).

    Args:
        nombre (str): nombre del grupo llamante.

    Returns:
        ContextoLlamante: contexto de tipo `grupo`.
    """
    return ContextoLlamante(
        tipo=TipoPrincipal.GRUPO,
        identificador=nombre,
        nombre_mostrable=nombre,
        grupos=(),
    )


def ContextoAusente():
    """Proveedor simulado cuyo contexto on-behalf-of no está presente.

    Returns:
        ProveedorIdentidadSimulado: proveedor que reporta ausencia de contexto.
    """
    return ProveedorIdentidadSimulado(
        excepcion=ErrorContextoLlamanteAusente(
            "Invocación sin contexto de usuario on-behalf-of (simulado)."
        )
    )


def ContextoConFallo(msg="Fallo simulado del servicio de identidad."):
    """Proveedor simulado que falla al obtener el contexto.

    Args:
        msg (str): mensaje del error simulado.

    Returns:
        ProveedorIdentidadSimulado: proveedor que lanza `RuntimeError`.
    """
    return ProveedorIdentidadSimulado(excepcion=RuntimeError(msg))
