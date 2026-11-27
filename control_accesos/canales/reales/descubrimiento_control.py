"""Descubrimiento de objetos del plano de control (design.md D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Componente real de solo lectura que lista los objetos del plano de control
usando DOS contextos, por la restricción de scopes verificada en el gate broker:

- clusters all-purpose (`COMPUTO_CLASICO`) y serverless compute objects
  (`COMPUTO_SERVERLESS`) se listan con el **service principal** (el token OBO
  del llamante carece del scope `clusters`);
- SQL warehouses (`SQL_WAREHOUSE`) y Databricks Apps (`DATABRICK_APP`) se listan
  con la **credencial OBO** del llamante (scopes `sql` y `apps`);
- `USO_TOKEN` es singleton del workspace: no se lista por API; se expone un
  único objeto con el **identificador lógico configurado**
  (`identificador_logico_uso_token`), que el canal de ACL omite en la ruta real.

Contrato, alineado con los descubridores de principals y UC: tuplas de
`ObjetoControlDescubierto` (tipo e identificador), orden estable, límite
configurable y fallo (`ErrorListadoControl`) distinguible de una lista vacía
(cero clusters all-purpose es un vacío legítimo, p. ej. en Free Edition).

El módulo NO importa `databricks-sdk` al importarse: recibe los clientes ya
construidos (el SP por autoconfiguración del entorno de la App y el OBO por la
fábrica del llamante). Ningún valor de conexión ni id vive en el código.
"""

from dataclasses import dataclass
from typing import Optional

from control_accesos.dominio.enumeraciones import TipoObjeto

# Identificador del módulo para la bitácora de errores (convención del proyecto).
MODULO_DESCUBRIMIENTO_CONTROL = "canal_descubrimiento_control"


@dataclass(frozen=True)
class ObjetoControlDescubierto:
    """Objeto del plano de control descubierto.

    Attributes:
        tipo (TipoObjeto): tipo del objeto (de cómputo, warehouse, app o token).
        identificador (str): id real del objeto; para `USO_TOKEN`, el
            identificador lógico configurado (singleton).
    """

    tipo: TipoObjeto
    identificador: str


class ErrorListadoControl(RuntimeError):
    """Fallo del listado del plano de control, distinguible del vacío."""


class DescubridorControl:
    """Lista objetos del plano de control con los contextos SP y OBO.

    Attributes:
        cliente_sp: cliente SDK del service principal, con `clusters` y
            `serverless_compute_service` (cada uno con `list()`).
        cliente_obo: cliente SDK OBO, con `warehouses` y `apps`.
        identificador_logico_token (str): identificador lógico del singleton
            `USO_TOKEN` (configurable; no se consulta a la API).
    """

    def __init__(
        self,
        cliente_sp,
        cliente_obo,
        limite=None,
        identificador_logico_token="workspace",
        registrador_errores=None,
    ):
        """Inicializa el descubridor con los dos clientes inyectados.

        Args:
            cliente_sp: cliente del SP (clusters y serverless compute).
            cliente_obo: cliente OBO (warehouses y apps).
            limite (int | None): tope de elementos por listado; None no limita.
            identificador_logico_token (str): id lógico del singleton USO_TOKEN.
            registrador_errores (BitacoraErrores | None): bitácora opcional.

        Raises:
            ValueError: si falta algún servicio con `list()` o el identificador
                lógico del token es vacío.
        """
        self._validar(cliente_sp, cliente_obo, identificador_logico_token)
        self._cliente_sp = cliente_sp
        self._cliente_obo = cliente_obo
        self._limite = limite
        self._identificador_logico_token = identificador_logico_token
        self._registrador_errores = registrador_errores

    @staticmethod
    def _validar(cliente_sp, cliente_obo, identificador_logico_token):
        """Valida los colaboradores (fail-fast de cableado)."""
        if identificador_logico_token is None or not str(
            identificador_logico_token
        ).strip():
            raise ValueError(
                "Se requiere un identificador lógico no vacío para el "
                "singleton USO_TOKEN (configurable, nunca embebido)."
            )
        for nombre_cliente in ("sp", "obo"):
            cliente = cliente_sp if nombre_cliente == "sp" else cliente_obo
            if cliente is None:
                raise ValueError(
                    f"Se requiere el cliente {nombre_cliente.upper()} para "
                    f"listar objetos del plano de control."
                )
        for nombre_servicio in (
            "clusters",
            "serverless_compute_service",
        ):
            if not _TieneList(cliente_sp, nombre_servicio):
                raise ValueError(
                    f"El cliente del SP debe exponer '{nombre_servicio}' con list()."
                )
        for nombre_servicio in ("warehouses", "apps"):
            if not _TieneList(cliente_obo, nombre_servicio):
                raise ValueError(
                    f"El cliente OBO debe exponer '{nombre_servicio}' con list()."
                )

    def ListarClusters(self):
        """Lista los clusters all-purpose con el SP (identificador: cluster_id)."""
        return self._Listar(
            lambda: self._cliente_sp.clusters.list(),
            lambda registro: getattr(registro, "cluster_id", None),
            TipoObjeto.COMPUTO_CLASICO,
        )

    def ListarServerless(self):
        """Lista los serverless compute objects con el SP (serverless_compute_id)."""
        return self._Listar(
            lambda: self._cliente_sp.serverless_compute_service.list(),
            lambda registro: getattr(registro, "serverless_compute_id", None),
            TipoObjeto.COMPUTO_SERVERLESS,
        )

    def ListarWarehouses(self):
        """Lista los SQL warehouses con OBO (identificador: id)."""
        return self._Listar(
            lambda: self._cliente_obo.warehouses.list(),
            lambda registro: getattr(registro, "id", None),
            TipoObjeto.SQL_WAREHOUSE,
        )

    def ListarApps(self):
        """Lista las Databricks Apps con OBO (identificador: nombre)."""
        return self._Listar(
            lambda: self._cliente_obo.apps.list(),
            lambda registro: getattr(registro, "name", None),
            TipoObjeto.DATABRICK_APP,
        )

    def ListarUsoTokens(self):
        """Devuelve el singleton USO_TOKEN con el identificador lógico.

        Returns:
            tuple[ObjetoControlDescubierto, ...]: exactamente un objeto
                `USO_TOKEN` (singleton del workspace).
        """
        return (
            ObjetoControlDescubierto(
                tipo=TipoObjeto.USO_TOKEN,
                identificador=self._identificador_logico_token,
            ),
        )

    def _Listar(self, operacion, traductor, tipo):
        """Materializa un listado acotándolo al límite y tipificando el fallo.

        Args:
            operacion (callable): invocación `list()` del servicio.
            traductor (callable): `obtener_id(registro)` -> id o None.
            tipo (TipoObjeto): tipo del objeto a construir.

        Returns:
            tuple[ObjetoControlDescubierto, ...]: registros válidos, en orden.

        Raises:
            ErrorListadoControl: si el listado falla (denegación/transporte),
                con causa encadenada.
        """
        try:
            registros = list(operacion())
        except Exception as excepcion:  # noqa: BLE001 - se traduce y tipifica
            self._RegistrarFallo(excepcion)
            raise ErrorListadoControl(
                f"[{MODULO_DESCUBRIMIENTO_CONTROL}] No se pudo listar los "
                f"objetos del plano de control ({tipo.value}): {excepcion}"
            ) from excepcion

        resultado = tuple(
            ObjetoControlDescubierto(tipo=tipo, identificador=identificador)
            for registro in registros
            for identificador in [_TextoONulo(traductor(registro))]
            if identificador
        )
        if self._limite is not None:
            return resultado[: self._limite]
        return resultado

    def _RegistrarFallo(self, excepcion):
        """Registra el fallo del listado en la bitácora sin propagarlo."""
        if self._registrador_errores is None:
            return
        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_DESCUBRIMIENTO_CONTROL,
                usuario=None,
                contexto="listado de objetos del plano de control",
            )
        except Exception:  # noqa: BLE001 - la bitácora nunca propaga
            return


def _TieneList(cliente, nombre_servicio):
    """Devuelve True si el cliente expone el servicio con `list()`."""
    servicio = getattr(cliente, nombre_servicio, None)
    return servicio is not None and hasattr(servicio, "list")


def _TextoONulo(valor):
    """Normaliza un texto opcional: recorta y convierte vacío en None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None
