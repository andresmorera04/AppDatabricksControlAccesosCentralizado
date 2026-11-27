"""Fábrica del contexto broker del service principal (design.md D4/D6).

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Compone, por acción, un contexto de EJECUCIÓN con la identidad del service
principal de la Databricks App —nunca con la credencial OBO del llamante— para
las superficies donde el token del usuario no alcanza (SCIM y ACL del plano de
control). Es el segundo contexto del modelo broker (design.md D4); el primero
(`FabricaContextoLlamante`) conserva la identidad OBO para autorización y el
SQL UC.

Qué compone este contexto:

- `cliente_sp`: `WorkspaceClient` del SP obtenido de la AUTOCONFIGURACIÓN del
  entorno de la App (OAuth M2M). Jamás se construye con host/token del llamante
  ni se usa para evaluar autorización ni para la ruta CLI;
- `canal_control`: `CanalControlComputo` + `ClientePermisosSdk` con el SP, para
  leer y escribir ACLs de los cinco tipos del plano de control (warehouses,
  clusters, serverless compute objects, Databricks Apps y uso de tokens);
- `descubridor_principales`: `DescubridorPrincipales` con el SP, para listar
  usuarios, grupos y service principals por SCIM (el OBO no tiene ese scope).

Regla de seguridad (spec `app-broker-grants`): este contexto NO valida autoridad
alguna por sí mismo. La autorización se resuelve aparte con la identidad del
llamante (D2); toda escritura broker exige esa validación previa y su
revalidación al confirmar. El SP habilita la EJECUCIÓN, no el permiso.
"""

from dataclasses import dataclass
from typing import Any, Optional

from control_accesos.autenticacion.errores import ErrorAutenticacionLlamante
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.canales.reales.descubrimiento_principales import (
    DescubridorPrincipales,
)

# Identificador del módulo para trazas y bitácora.
MODULO_FABRICA_BROKER = "ui.fabrica_contexto_broker"

# Atributo de configuración con el tope de principals que devuelve el
# descubrimiento (regla No HardCoded: el valor vive en app_properties.json).
ATRIBUTO_LIMITE_OPCIONES = "limite_opciones_descubrimiento"

# Atributo de configuración con el tamaño de página de descubrimiento (leído por
# la UI; aquí se conserva como dato de trazabilidad del despliegue broker).
ATRIBUTO_TAMANO_PAGINA = "tamano_pagina_descubrimiento"


def CrearClienteWorkspaceSp():
    """Fábrica de producción del cliente del workspace con la identidad del SP.

    NO recibe host ni token: el SDK autodetecta las credenciales OAuth M2M del
    service principal propio de la App desde el entorno del runtime. Es la vía
    exclusiva del modo broker (SCIM y ACL del plano de control); nunca se usa
    para la identidad OBO del llamante ni para la ruta CLI.

    Returns:
        WorkspaceClient: cliente autenticado como el service principal de la App.
    """
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


@dataclass(frozen=True)
class ContextoOperacionBroker:
    """Composición broker (SP) de una acción, lista para usarse.

    Attributes:
        cliente_sp (Any): `WorkspaceClient` con la identidad del SP (autoconfig).
        canal_control (CanalControlComputo): canal real del plano de control
            para leer/escribir ACLs con el SP.
        descubridor_principales (DescubridorPrincipales): descubrimiento SCIM
            con el SP (usuarios, grupos, service principals).
        limite_opciones (int | None): tope de principals del descubrimiento,
            leído de la configuración.
    """

    cliente_sp: Any
    canal_control: CanalControlComputo
    descubridor_principales: DescubridorPrincipales
    limite_opciones: Optional[int]


class FabricaContextoBroker:
    """Compone un contexto broker (SP) nuevo por cada acción.

    Colaboradores inyectables (producción y pruebas): fábrica del cliente SP,
    configuración y bitácoras. La fábrica NO conserva estado: todo lo específico
    de la acción se construye en `CrearContexto()`.

    Example:
        >>> fabrica = FabricaContextoBroker()  # producción: App/autoconfig
        >>> contexto = fabrica.CrearContexto()
        >>> principals = contexto.descubridor_principales.ListarPrincipales()
    """

    def __init__(
        self,
        fabrica_cliente_sp=None,
        configuracion=None,
        registrador_eventos=None,
        registrador_errores=None,
    ):
        """Inicializa la fábrica con sus colaboradores.

        Args:
            fabrica_cliente_sp (callable | None): función SIN argumentos que
                construye el cliente del SP; None usa `CrearClienteWorkspaceSp`
                (autoconfiguración OAuth M2M del entorno).
            configuracion (ConfiguracionApp | None): configuración; None carga
                la del proyecto.
            registrador_eventos (BitacoraEventos | None): bitácora de eventos.
            registrador_errores (BitacoraErrores | None): bitácora de errores.

        Raises:
            ErrorAutenticacionLlamante: si un colaborador invocable no lo es.
        """
        if fabrica_cliente_sp is not None and not callable(fabrica_cliente_sp):
            raise ErrorAutenticacionLlamante(
                "La fábrica del cliente del service principal debe ser invocable "
                f"(sin argumentos); se recibió "
                f"{type(fabrica_cliente_sp).__name__}."
            )

        self._fabrica_cliente_sp = fabrica_cliente_sp or CrearClienteWorkspaceSp

        if configuracion is None:
            from control_accesos.configuracion.configuracion_app import (
                ConfiguracionApp,
            )

            configuracion = ConfiguracionApp.Cargar()
        self._configuracion = configuracion

        self._registrador_eventos = registrador_eventos
        self._registrador_errores = registrador_errores

    def CrearContexto(self):
        """Compone el contexto broker completo para una acción.

        Returns:
            ContextoOperacionBroker: cliente SP, canal de control (ACL) y
                descubrimiento SCIM, listos para ejecutar en modo broker.

        Raises:
            ErrorAutenticacionLlamante: si el cliente SP no puede construirse.
        """
        cliente_sp = self._CrearClienteSp()

        canal_control = CanalControlComputo(
            transporte=ClientePermisosSdk(cliente_sp),
            registrador_errores=self._registrador_errores,
        )
        limite_opciones = self._configuracion.ObtenerAtributo(
            ATRIBUTO_LIMITE_OPCIONES
        )
        descubridor_principales = DescubridorPrincipales(
            cliente=cliente_sp,
            limite=limite_opciones,
            registrador_errores=self._registrador_errores,
        )

        return ContextoOperacionBroker(
            cliente_sp=cliente_sp,
            canal_control=canal_control,
            descubridor_principales=descubridor_principales,
            limite_opciones=limite_opciones,
        )

    def _CrearClienteSp(self):
        """Construye el cliente del SP desde la autoconfiguración del entorno.

        Returns:
            WorkspaceClient: cliente autenticado como el SP de la App.

        Raises:
            ErrorAutenticacionLlamante: si la fábrica del SP falla.
        """
        try:
            return self._fabrica_cliente_sp()
        except Exception as excepcion:  # noqa: BLE001 - fallo de autoconfig
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_FABRICA_BROKER}] No se pudo construir el cliente del "
                f"service principal desde la autoconfiguración del entorno de "
                f"la App (OAuth M2M)."
            ) from excepcion
