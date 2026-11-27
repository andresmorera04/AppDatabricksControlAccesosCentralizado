"""Fábrica del contexto de operación OBO por acción (C9, design.md D3; F2).

Punto único de composición de la UI de grants: para CADA acción del usuario
(descubrir, previsualizar, confirmar) construye un contexto nuevo con la
credencial on-behalf-of del llamante, sin singletons de módulo ni objetos
compartidos entre sesiones de Streamlit:

- proveedor OBO real (`ProveedorIdentidadDatabricksApp`, C9) y servicio de
  identidad de C3 (`ServicioIdentidadLlamante`), que resuelve y cachea la
  identidad por invocación;
- cliente del workspace (`WorkspaceClient` con host y token explícitos) para
  el canal SDK del plano de control, el descubrimiento de opciones y la
  sesión SQL remota;
- sesión SQL remota OBO (`SesionSqlRemota` sobre la Statement Execution API,
  corrección F2 de C9) para el canal SQL del plano de datos —la imagen de la
  App no admite `databricks-connect`, de modo que no hay SparkSession—;
- canales reales de ambos planos (`CanalSqlDatos` + `SesionSqlRemota`,
  `CanalControlComputo` + `ClientePermisosSdk`), resolutor de privilegios
  efectivos (C3) y `PipelineGrants` completo con la identidad resuelta, el
  agregador de lote en Python (`AgregadorReporteLotePython`) y las bitácoras
  inyectadas.

Reglas de seguridad que fija esta composición:

- el token OBO se lee del header del request (función compartida
  `LeerTokenObo`); el token del service principal propio de la App
  (`DATABRICKS_TOKEN` del entorno) NUNCA se usa para las operaciones del
  llamante: no existe fallback elevado;
- sin token OBO no se construye ningún cliente (`ErrorContextoLlamanteAusente`);
- la identidad no resuelta (token expirado, SCIM inaccesible) no impide la
  composición: el contexto existe con `identidad=None`, el fallo queda
  registrado por el servicio de C3 y el controlador deshabilita
  previsualización y ejecución (spec `grant-management-ui`);
- el warehouse para el SQL OBO se resuelve por orden: la propiedad
  `IdWarehouse` de la configuración (decisión humana 2026-11-27, dinámica por
  entorno), la variable de entorno correspondiente y, como último recurso, el
  descubrimiento con la credencial del llamante (design.md D3, precondición
  operativa); sin warehouse usable la composición falla con error controlado
  y sin el token;
- las bitácoras de eventos/errores se inyectan desde fuera (composición de
  auditoría con identidad de App, design.md D10, tarea 5.2): esta fábrica no
  las construye ni decide su credencial.

Al no existir SparkSession, `ContextoOperacionLlamante.Cerrar()` queda como una
operación idempotente sin recurso que liberar, conservada por compatibilidad
con el controlador de C9.
"""

from dataclasses import dataclass
from typing import Any, Optional

from control_accesos.autenticacion.errores import ErrorAutenticacionLlamante
from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.canales.reales.sesion_sql_remota import SesionSqlRemota
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.reporte_lote import AgregadorReporteLotePython
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos
from control_accesos.ui.proveedor_identidad_app import (
    AccederEncabezadosStreamlit,
    CrearClienteWorkspace,
    LeerHostWorkspace,
    LeerTokenObo,
    ProveedorIdentidadDatabricksApp,
)

# Identificador del módulo para trazas, mensajes y bitácora de errores
# (convención de los canales reales y del proveedor OBO).
MODULO_FABRICA_CONTEXTO = "ui.fabrica_contexto"

# Atributos de configuración del warehouse del SQL OBO (decisión humana
# 2026-11-27, design.md D13): `id_warehouse` es el id dinámico por entorno y
# `variable_entorno_id_warehouse` el nombre de la variable de entorno que lo
# suple cuando la propiedad está vacía.
NOMBRE_ATRIBUTO_ID_WAREHOUSE = "id_warehouse"
NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_ID_WAREHOUSE = "variable_entorno_id_warehouse"


def DescubrirWarehouseServerless(cliente):
    """Descubre el id de un SQL warehouse con cómputo serverless (OBO).

    El identificador NO se hardcodea (regla del proyecto): se consulta la API
    de warehouses del cliente ya autenticado y se toma el primero con cómputo
    serverless habilitado (en Free Edition el warehouse serverless arranca bajo
    demanda aunque figure STOPPED). Es la precondición operativa del SQL OBO
    (design.md D3): el llamante necesita CAN USE sobre un warehouse.

    Args:
        cliente (WorkspaceClient): cliente con la credencial OBO del llamante.

    Returns:
        str | None: id del primer warehouse serverless, o None si no hay
            ninguno disponible para el llamante.
    """
    servicio_warehouses = getattr(cliente, "warehouses", None)
    if servicio_warehouses is None or not hasattr(servicio_warehouses, "list"):
        return None
    for warehouse in servicio_warehouses.list() or ():
        if getattr(warehouse, "enable_serverless_compute", False):
            return getattr(warehouse, "id", None)
    return None


def _ValorNoVacio(valor):
    """Normaliza un valor de configuración/entorno a texto útil o None.

    Args:
        valor: valor leído de configuración o del entorno (str o None).

    Returns:
        str | None: el texto sin espacios, o None si está vacío.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def CrearSesionSqlRemota(host, token, warehouse_id, fabrica_cliente=None):
    """Fábrica de producción de la sesión SQL remota OBO (Statement Execution).

    Construye el cliente del workspace con la credencial OBO del llamante
    (auth_type='pat' fijado por `CrearClienteWorkspace`) y adapta su
    `statement_execution` al puerto de sesión que consume `CanalSqlDatos`. Es la
    vía del SQL del plano de datos en la Databricks App (corrección F2 de C9,
    design.md D3): la imagen de la App no admite `databricks-connect`, de modo
    que el SQL se ejecuta por la Statement Execution API con el scope `sql`.

    Args:
        host (str): host del workspace.
        token (str): token OBO del llamante (se conserva solo para redactarlo
            de los mensajes de error; nunca se reenvía a otro destino).
        warehouse_id (str): id del SQL warehouse descubierto con la credencial
            OBO (no embebido en código).
        fabrica_cliente (callable | None): fábrica `(host=..., token=...)` que
            construye el cliente del workspace; None usa `CrearClienteWorkspace`
            (SDK real con auth_type='pat').

    Returns:
        SesionSqlRemota: sesión lista para `CanalSqlDatos`, con el transporte
            `statement_execution` del cliente OBO.
    """
    fabrica = fabrica_cliente or CrearClienteWorkspace
    cliente = fabrica(host=host, token=token)
    return SesionSqlRemota(
        api_ejecucion=cliente.statement_execution,
        warehouse_id=warehouse_id,
        token=token,
    )


@dataclass(frozen=True)
class ContextoOperacionLlamante:
    """Composición OBO de una acción de la UI, lista para usarse.

    Atributos inmutables desde fuera (dataclass frozen): la composición se
    construye completa en `FabricaContextoLlamante.CrearContexto` y se usa
    durante una única acción.

    Attributes:
        proveedor (ProveedorIdentidadLlamante): proveedor OBO real de la App.
        servicio_identidad (ServicioIdentidadLlamante): servicio de C3 con su
            caché por invocación; expone `IdentidadResuelta`.
        identidad (IdentidadLlamante | None): identidad resuelta del llamante;
            None cuando el token no pudo verificarse (degradación de C3).
        cliente_workspace (Any): `WorkspaceClient` con credencial OBO para el
            canal del plano de control y el descubrimiento.
        warehouse_id (str): id del SQL warehouse serverless descubierto con la
            credencial OBO (precondición del SQL OBO).
        canal_datos (CanalSqlDatos): canal real del plano de datos.
        canal_control (CanalControlComputo): canal real del plano de control.
        resolutor (ResolutorPrivilegiosEfectivos): resolutor de C3 cableado
            con los canales OBO.
        pipeline (PipelineGrants): orquestador completo con identidad,
            resolutor, bitácoras y agregador de lote en Python.
        registrador_eventos (Any | None): bitácora de eventos inyectada.
        registrador_errores (Any | None): bitácora de errores inyectada.
    """

    proveedor: ProveedorIdentidadLlamante
    servicio_identidad: ServicioIdentidadLlamante
    identidad: Optional[IdentidadLlamante]
    cliente_workspace: Any
    warehouse_id: str
    canal_datos: CanalSqlDatos
    canal_control: CanalControlComputo
    resolutor: ResolutorPrivilegiosEfectivos
    pipeline: PipelineGrants
    registrador_eventos: Any = None
    registrador_errores: Any = None

    def Cerrar(self):
        """Cierra el contexto; sin recurso Spark que liberar, es un no-op.

        Se conserva por compatibilidad con el controlador de C9, que lo invoca
        en un `finally`. Idempotente por construcción: no hay sesión ni recurso
        externo retenido por el contexto (la sesión SQL remota es stateless y
        el cliente SDK no exige cierre explícito).
        """


class FabricaContextoLlamante:
    """Compone un contexto OBO nuevo por cada acción de la UI.

    Colaboradores inyectables (producción y pruebas): acceso a headers, fábrica
    de clientes del workspace, descubridor del warehouse serverless,
    configuración, entorno y bitácoras. La fábrica NO conserva estado por
    llamante: todo lo específico de la acción se construye en `CrearContexto()`
    y vive en el contexto devuelto.

    Example:
        >>> fabrica = FabricaContextoLlamante()  # producción: Streamlit/SDK
        >>> contexto = fabrica.CrearContexto()
        >>> try:
        ...     reporte = contexto.pipeline.ProcesarDesdeEntradas(...)
        ... finally:
        ...     contexto.Cerrar()
    """

    def __init__(
        self,
        acceso_encabezados=None,
        fabrica_cliente_workspace=None,
        descubridor_warehouse=None,
        configuracion=None,
        entorno=None,
        registrador_eventos=None,
        registrador_errores=None,
        consultora=None,
    ):
        """Inicializa la fábrica con sus colaboradores.

        Args:
            acceso_encabezados (callable | None): función que devuelve los
                headers del request actual; None usa el acceso de Streamlit.
            fabrica_cliente_workspace (callable | None): función
                `(host=..., token=...)` que construye el cliente SDK; None
                usa `CrearClienteWorkspace` (SDK real).
            descubridor_warehouse (callable | None): función `(cliente)` que
                devuelve el id de un SQL warehouse serverless (o None); None usa
                `DescubrirWarehouseServerless` (SDK real).
            configuracion (ConfiguracionApp | None): configuración de la
                aplicación; None carga la del proyecto.
            entorno (Mapping | None): variables de entorno; None usa
                `os.environ`.
            registrador_eventos (BitacoraEventos | None): bitácora de eventos
                de la composición de auditoría (design.md D10).
            registrador_errores (BitacoraErrores | None): bitácora de errores
                de la composición de auditoría.
            consultora (ConsultoraMatrizPrivilegios | None): consultora de la
                matriz; None usa la matriz declarativa del proyecto.

        Raises:
            ErrorAutenticacionLlamante: si un colaborador invocable no lo es
                (fail-fast de cableado).
        """
        if acceso_encabezados is not None and not callable(acceso_encabezados):
            raise ErrorAutenticacionLlamante(
                "El acceso a los headers debe ser invocable; se recibió "
                f"{type(acceso_encabezados).__name__}."
            )
        if fabrica_cliente_workspace is not None and not callable(
            fabrica_cliente_workspace
        ):
            raise ErrorAutenticacionLlamante(
                "La fábrica de clientes del workspace debe ser invocable con "
                f"'host' y 'token'; se recibió "
                f"{type(fabrica_cliente_workspace).__name__}."
            )
        if descubridor_warehouse is not None and not callable(
            descubridor_warehouse
        ):
            raise ErrorAutenticacionLlamante(
                "El descubridor del warehouse debe ser invocable con el "
                f"cliente; se recibió {type(descubridor_warehouse).__name__}."
            )

        self._acceso_encabezados = (
            acceso_encabezados or AccederEncabezadosStreamlit
        )
        self._fabrica_cliente_workspace = (
            fabrica_cliente_workspace or CrearClienteWorkspace
        )
        self._descubridor_warehouse = (
            descubridor_warehouse or DescubrirWarehouseServerless
        )

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

        self._registrador_eventos = registrador_eventos
        self._registrador_errores = registrador_errores
        self._consultora = consultora

        # Nota de seguridad: la fábrica no guarda tokens ni identidades; cada
        # acción los lee del request y los entrega solo al contexto (D3/D11).

    def CrearContexto(self):
        """Compone el contexto OBO completo para una acción de la UI.

        Orden de composición: credencial (token/host) -> cliente SDK ->
        descubrimiento del warehouse serverless -> proveedor/servicio de
        identidad (resolución SCIM con degradación controlada) -> canales
        reales -> resolutor -> pipeline con agregador de lote en Python.

        Returns:
            ContextoOperacionLlamante: composición lista para descubrir,
                previsualizar y ejecutar con la identidad del llamante.

        Raises:
            ErrorContextoLlamanteAusente: si el request no trae token OBO (no
                se construye ningún cliente).
            ErrorAutenticacionLlamante: si el entorno no informa el host, si
                falla la construcción del cliente, si el warehouse serverless no
                puede descubrirse (precondición del SQL OBO) o si falla la
                sesión remota.
        """
        token = LeerTokenObo(self._acceso_encabezados, self._configuracion)
        host = LeerHostWorkspace(self._entorno, self._configuracion)

        cliente_workspace = self._CrearClienteWorkspace(host, token)
        warehouse_id = self._ResolverWarehouse(cliente_workspace)

        # Proveedor y servicio de C3: la identidad se resuelve una vez por
        # acción y queda cacheada en el servicio del contexto.
        proveedor = ProveedorIdentidadDatabricksApp(
            acceso_encabezados=self._acceso_encabezados,
            fabrica_cliente=self._fabrica_cliente_workspace,
            configuracion=self._configuracion,
            entorno=self._entorno,
        )
        servicio_identidad = ServicioIdentidadLlamante(
            proveedor=proveedor, registrador_errores=self._registrador_errores
        )
        identidad = servicio_identidad.ObtenerIdentidadLlamante()

        # Canales reales de ambos planos con la credencial OBO (C4-C8). El
        # plano de datos usa la sesión SQL remota (Statement Execution, F2) y,
        # para el reporte de lote, el agregador en Python (sin SparkSession).
        sesion_sql_remota = SesionSqlRemota(
            api_ejecucion=cliente_workspace.statement_execution,
            warehouse_id=warehouse_id,
            token=token,
        )
        canal_datos = CanalSqlDatos(
            sesion_sql=sesion_sql_remota,
            registrador_errores=self._registrador_errores,
        )
        canal_control = CanalControlComputo(
            transporte=ClientePermisosSdk(cliente_workspace),
            registrador_errores=self._registrador_errores,
        )
        resolutor = ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_errores=self._registrador_errores,
        )
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            consultora=self._consultora,
            identidad_llamante=identidad,
            resolutor_privilegios=resolutor,
            registrador_eventos=self._registrador_eventos,
            registrador_errores=self._registrador_errores,
            agregador_lote=AgregadorReporteLotePython(),
        )

        return ContextoOperacionLlamante(
            proveedor=proveedor,
            servicio_identidad=servicio_identidad,
            identidad=identidad,
            cliente_workspace=cliente_workspace,
            warehouse_id=warehouse_id,
            canal_datos=canal_datos,
            canal_control=canal_control,
            resolutor=resolutor,
            pipeline=pipeline,
            registrador_eventos=self._registrador_eventos,
            registrador_errores=self._registrador_errores,
        )

    def _CrearClienteWorkspace(self, host, token):
        """Construye el cliente SDK con la credencial del llamante.

        Args:
            host (str): host del workspace.
            token (str): token OBO del request.

        Returns:
            WorkspaceClient: cliente autenticado como el llamante.

        Raises:
            ErrorAutenticacionLlamante: si la fábrica de clientes falla.
        """
        try:
            return self._fabrica_cliente_workspace(host=host, token=token)
        except Exception as excepcion:  # noqa: BLE001 - fallo del transporte
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_FABRICA_CONTEXTO}] No se pudo construir el cliente "
                f"del workspace con la credencial del llamante."
            ) from excepcion

    def _ResolverWarehouse(self, cliente):
        """Resuelve el id del SQL warehouse para el SQL OBO (design.md D13).

        Orden de resolución (decisión humana 2026-11-27): la propiedad
        `IdWarehouse` de la configuración; si está vacía, la variable de
        entorno `variable_entorno_id_warehouse`; y, como último recurso
        dinámico, el descubrimiento con la credencial del llamante (conserva
        el arranque de Free Edition sin id preconfigurado).

        Args:
            cliente (WorkspaceClient): cliente OBO del contexto (solo se usa
                en el último recurso de descubrimiento).

        Returns:
            str: id del warehouse a usar para el SQL OBO.

        Raises:
            ErrorAutenticacionLlamante: si ninguna fuente aporta un warehouse
                usable (precondición operativa) o el descubrimiento falla; el
                mensaje nunca expone el token.
        """
        id_configuracion = _ValorNoVacio(
            self._configuracion.ObtenerAtributo(NOMBRE_ATRIBUTO_ID_WAREHOUSE)
        )
        if id_configuracion:
            return id_configuracion

        nombre_variable = self._configuracion.ObtenerAtributo(
            NOMBRE_ATRIBUTO_VARIABLE_ENTORNO_ID_WAREHOUSE
        )
        id_entorno = _ValorNoVacio(self._entorno.get(nombre_variable))
        if id_entorno:
            return id_entorno

        try:
            warehouse_id = _ValorNoVacio(self._descubridor_warehouse(cliente))
        except Exception as excepcion:  # noqa: BLE001 - fallo del transporte
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_FABRICA_CONTEXTO}] No se pudo descubrir un SQL "
                f"warehouse serverless con la credencial del llamante."
            ) from excepcion

        if not warehouse_id:
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_FABRICA_CONTEXTO}] No hay un SQL warehouse usable "
                f"para el SQL OBO del llamante: configure la propiedad "
                f"'IdWarehouse' o su variable de entorno, o disponga de un "
                f"warehouse serverless descubrible (precondición operativa, "
                f"design.md D3/D13)."
            )
        return warehouse_id
