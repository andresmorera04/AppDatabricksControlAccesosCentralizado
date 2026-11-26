"""Fábrica del contexto de operación OBO por acción (C9, design.md D3).

Punto único de composición de la UI de grants: para CADA acción del usuario
(descubrir, previsualizar, confirmar) construye un contexto nuevo con la
credencial on-behalf-of del llamante, sin singletons de módulo ni objetos
compartidos entre sesiones de Streamlit:

- proveedor OBO real (`ProveedorIdentidadDatabricksApp`, C9) y servicio de
  identidad de C3 (`ServicioIdentidadLlamante`), que resuelve y cachea la
  identidad por invocación;
- cliente del workspace (`WorkspaceClient` con host y token explícitos) para
  el canal SDK del plano de control y el descubrimiento de opciones;
- sesión Spark remota (Databricks Connect con la MISMA credencial OBO) para
  el canal SQL del plano de datos y la agregación masiva del reporte de lote;
- canales reales de ambos planos (`CanalSqlDatos` + `SesionSparkSql`,
  `CanalControlComputo` + `ClientePermisosSdk`), resolutor de privilegios
  efectivos (C3) y `PipelineGrants` completo con la identidad resuelta y las
  bitácoras inyectadas.

Reglas de seguridad que fija esta composición:

- el token OBO se lee del header del request (función compartida
  `LeerTokenObo`); el token del service principal propio de la App
  (`DATABRICKS_TOKEN` del entorno) NUNCA se usa para las operaciones del
  llamante: no existe fallback elevado;
- sin token OBO no se construye ningún cliente ni sesión
  (`ErrorContextoLlamanteAusente`);
- la identidad no resuelta (token expirado, SCIM inaccesible) no impide la
  composición: el contexto existe con `identidad=None`, el fallo queda
  registrado por el servicio de C3 y el controlador deshabilita
  previsualización y ejecución (spec `grant-management-ui`);
- las bitácoras de eventos/errores se inyectan desde fuera (composición de
  auditoría con identidad de App, design.md D10, tarea 5.2): esta fábrica no
  las construye ni decide su credencial.

`ContextoOperacionLlamante.Cerrar()` libera la sesión Spark de la acción de
forma idempotente y controlada.
"""

import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from control_accesos.autenticacion.errores import ErrorAutenticacionLlamante
from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.autenticacion.proveedores import ProveedorIdentidadLlamante
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.canal_sql_datos import (
    CanalSqlDatos,
    SesionSparkSql,
)
from control_accesos.canales.reales.cliente_permisos_sdk import (
    ClientePermisosSdk,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
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


def CrearSesionSparkObo(host, token):
    """Fábrica de producción de la sesión Spark remota con credencial OBO.

    Importa `databricks-connect` de forma perezosa: es una dependencia
    exclusiva del runtime de la App y NO se instala en el ~/.venv local
    (design.md D5); las pruebas unitarias inyectan dobles.

    Nota sobre `Config` (databricks-sdk >= 0.170): su inicialización hace un
    sondeo best-effort de metadatos del host (`/.well-known/databricks-config`)
    y ante cualquier fallo cae de vuelta a la configuración explícita
    (host/token), que es la única fuente usada aquí. Con el host real del
    workspace el sondeo es inmediato; el spike de la tarea 2.4 lo valida
    desplegado. Las pruebas unitarias parchean `Config` para no depender de
    la red.

    Usa `create()` y no `getOrCreate()`: cada acción obtiene una sesión
    nueva, de modo que dos llamantes nunca compartan contexto Spark
    (design.md D3). La conexión al cómputo serverless se valida contra el
    runtime real en el spike de la tarea 2.4.

    Args:
        host (str): host del workspace.
        token (str): token OBO del llamante.

    Returns:
        DatabricksSession: sesión remota autenticada como el llamante.

    Raises:
        Exception: cualquier fallo de Connect (transporte, cómputo,
            permisos); la fábrica lo captura y lo traduce.
    """
    from databricks.connect import DatabricksSession
    from databricks.sdk.config import Config

    configuracion_sdk = Config(host=host, token=token)
    return (
        DatabricksSession.builder.sdkConfig(configuracion_sdk)
        .serverless(True)
        .create()
    )


@dataclass(frozen=True)
class ContextoOperacionLlamante:
    """Composición OBO de una acción de la UI, lista para usar y cerrar.

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
        sesion_spark (Any): sesión Spark remota (Databricks Connect) con la
            misma credencial OBO.
        canal_datos (CanalSqlDatos): canal real del plano de datos.
        canal_control (CanalControlComputo): canal real del plano de control.
        resolutor (ResolutorPrivilegiosEfectivos): resolutor de C3 cableado
            con los canales OBO.
        pipeline (PipelineGrants): orquestador completo con identidad,
            resolutor, bitácoras y sesión para la agregación de lote.
        registrador_eventos (Any | None): bitácora de eventos inyectada.
        registrador_errores (Any | None): bitácora de errores inyectada.
    """

    proveedor: ProveedorIdentidadLlamante
    servicio_identidad: ServicioIdentidadLlamante
    identidad: Optional[IdentidadLlamante]
    cliente_workspace: Any
    sesion_spark: Any
    canal_datos: CanalSqlDatos
    canal_control: CanalControlComputo
    resolutor: ResolutorPrivilegiosEfectivos
    pipeline: PipelineGrants
    registrador_eventos: Any = None
    registrador_errores: Any = None

    # Marca interna de cierre idempotente (no participa en repr ni comparaciones).
    _sesion_cerrada: bool = field(default=False, repr=False, compare=False)

    def Cerrar(self):
        """Libera la sesión Spark de la acción, una sola vez.

        Idempotente: invocaciones repetidas (rerender, limpieza duplicada)
        no vuelven a detener la sesión. Un fallo de `stop()` se degrada de
        forma controlada —registro en la bitácora de errores cuando existe,
        salida de error local en caso contrario— y nunca se propaga al
        controlador.
        """
        if self._sesion_cerrada:
            return
        object.__setattr__(self, "_sesion_cerrada", True)

        if self.sesion_spark is None:
            return
        try:
            self.sesion_spark.stop()
        except Exception as excepcion:  # noqa: BLE001 - cierre controlado
            self._RegistrarFalloCierre(excepcion)

    def _RegistrarFalloCierre(self, excepcion):
        """Registra el fallo del cierre de sesión sin propagarlo.

        Args:
            excepcion (BaseException): fallo de `stop()` de la sesión Spark.
        """
        usuario = (
            self.identidad.usuario_bitacora
            if self.identidad is not None
            else None
        )
        if self.registrador_errores is None:
            print(
                f"[{MODULO_FABRICA_CONTEXTO}] No se pudo cerrar la sesión "
                f"Spark del llamante: {excepcion}",
                file=sys.stderr,
            )
            return
        try:
            self.registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_FABRICA_CONTEXTO,
                usuario=usuario,
                contexto="cierre de la sesión Spark OBO de la UI de grants",
            )
        except Exception as excepcion_registro:  # noqa: BLE001
            # La bitácora no puede convertirse en un punto de fallo en
            # cascada (convención de C2): se reporta en la salida local.
            print(
                f"[{MODULO_FABRICA_CONTEXTO}] El fallo de cierre de sesión "
                f"no pudo registrarse: {excepcion_registro}. Fallo original: "
                f"{excepcion}",
                file=sys.stderr,
            )


class FabricaContextoLlamante:
    """Compone un contexto OBO nuevo por cada acción de la UI.

    Colaboradores inyectables (producción y pruebas): acceso a headers,
    fábrica de clientes del workspace, fábrica de sesiones Spark,
    configuración, entorno y bitácoras. La fábrica NO conserva estado por
    llamante: todo lo específico de la acción se construye en
    `CrearContexto()` y vive en el contexto devuelto.

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
        fabrica_sesion_spark=None,
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
            fabrica_sesion_spark (callable | None): función
                `(host=..., token=...)` que construye la sesión Spark remota;
                None usa `CrearSesionSparkObo` (Databricks Connect real).
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
        if fabrica_sesion_spark is not None and not callable(
            fabrica_sesion_spark
        ):
            raise ErrorAutenticacionLlamante(
                "La fábrica de sesiones Spark debe ser invocable con 'host' "
                f"y 'token'; se recibió {type(fabrica_sesion_spark).__name__}."
            )

        self._acceso_encabezados = (
            acceso_encabezados or AccederEncabezadosStreamlit
        )
        self._fabrica_cliente_workspace = (
            fabrica_cliente_workspace or CrearClienteWorkspace
        )
        self._fabrica_sesion_spark = fabrica_sesion_spark or CrearSesionSparkObo

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
        sesión Spark -> proveedor/servicio de identidad (resolución SCIM con
        degradación controlada) -> canales reales -> resolutor -> pipeline.

        Returns:
            ContextoOperacionLlamante: composición lista para descubrir,
                previsualizar y ejecutar con la identidad del llamante.

        Raises:
            ErrorContextoLlamanteAusente: si el request no trae token OBO (no
                se construye ningún cliente ni sesión).
            ErrorAutenticacionLlamante: si el entorno no informa el host o si
                falla la construcción del cliente o de la sesión remota.
        """
        token = LeerTokenObo(self._acceso_encabezados, self._configuracion)
        host = LeerHostWorkspace(self._entorno, self._configuracion)

        cliente_workspace = self._CrearClienteWorkspace(host, token)
        sesion_spark = self._CrearSesionSpark(host, token)

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

        # Canales reales de ambos planos con la credencial OBO (C4-C8).
        canal_datos = CanalSqlDatos(
            sesion_sql=SesionSparkSql(sesion_spark),
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
            sesion_spark=sesion_spark,
        )

        return ContextoOperacionLlamante(
            proveedor=proveedor,
            servicio_identidad=servicio_identidad,
            identidad=identidad,
            cliente_workspace=cliente_workspace,
            sesion_spark=sesion_spark,
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

    def _CrearSesionSpark(self, host, token):
        """Construye la sesión Spark remota con la credencial del llamante.

        Args:
            host (str): host del workspace.
            token (str): token OBO del request.

        Returns:
            DatabricksSession: sesión remota autenticada como el llamante.

        Raises:
            ErrorAutenticacionLlamante: si Connect falla (transporte,
                cómputo no disponible, credencial rechazada).
        """
        try:
            return self._fabrica_sesion_spark(host=host, token=token)
        except Exception as excepcion:  # noqa: BLE001 - fallo de Connect
            raise ErrorAutenticacionLlamante(
                f"[{MODULO_FABRICA_CONTEXTO}] No se pudo establecer la "
                f"sesión Spark remota (Databricks Connect) con la credencial "
                f"del llamante."
            ) from excepcion
