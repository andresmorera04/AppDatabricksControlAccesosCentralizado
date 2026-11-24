"""Pruebas funcionales del canal SQL real integrado en el pipeline.

Cubren el requirement "Vertical slice de punta a punta con el canal SQL real"
del spec `uc-data-object-grants`, usando `CanalSqlDatos` (producción) sobre una
sesión SQL que imita las respuestas reales del motor de Unity Catalog: filas de
`SHOW GRANT` con otorgatario textual y errores con los códigos reales
(`SCHEMA_OR_OBJECT_NOT_FOUND`, `PERMISSION_DENIED`). No hay conexión externa.

Se ejercitan los cuatro caminos del flujo:

- solicitud 1 a 1 válida otorgada y verificada de punta a punta;
- ítem incompatible con la matriz bloqueado en pre-flight sin tocar la sesión;
- ítem sin privilegio efectivo del llamante bloqueado con
  `privilegios_insuficientes` sin llegar a la sesión (split de C3);
- fallo puntual de un ítem que no aborta el otorgamiento de los demás.
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Objeto del plano de datos sobre el que se otorga en todas las pruebas.
OBJETO = ObjetoSecurable(
    identificador="control.prod.ventas", tipo=TipoObjeto.TABLA_DELTA
)

# Beneficiario (recibe los privilegios) con forma de correo, como Databricks
# reporta a los usuarios en Unity Catalog.
BENEFICIARIO = "beneficiario@example.com"

# Palabra clave y clave con las que SHOW GRANT reporta las filas del objeto.
PALABRA_OBJETO = "TABLE"
CLAVE_OBJETO = "control.prod.ventas"


class ErrorMotorSql(RuntimeError):
    """Excepción con la forma del error que reporta el motor SQL real."""


class SesionSqlWorkspaceImitada:
    """Sesión SQL que imita al motor de Unity Catalog a nivel de instrucciones.

    Registra las sentencias recibidas y responde de forma determinista:

    - para las sentencias `SHOW GRANT` devuelve las filas configuradas para la
      consulta exacta;
    - para las sentencias `GRANT`/`REVOKE` lanza el error configurado (por
      prefijo) o simplemente registra el éxito.

    Attributes:
        sentencias_ejecutadas (list[str]): todas las sentencias recibidas.
    """

    def __init__(self):
        self.sentencias_ejecutadas = []
        self._filas_show_grant = {}
        self._errores_por_prefijo = []

    def ConfigurarShowGrant(self, objeto, filas):
        """Fija las filas que `SHOW GRANT` devuelve para el objeto.

        Args:
            objeto (ObjetoSecurable): objeto consultado.
            filas (list[list[str]]): filas con las columnas de SHOW GRANT.
        """
        sentencia = CanalSqlDatos.ConstruirShowGrant(objeto)
        self._filas_show_grant[sentencia] = list(filas)

    def ConfigurarErrorEn(self, prefijo, error):
        """Configura un error para las sentencias cuyo texto empieza por prefijo.

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
        self.sentencias_ejecutadas.append(sentencia)

        for prefijo, error in self._errores_por_prefijo:
            if sentencia.startswith(prefijo):
                raise error

        if sentencia.startswith("SHOW GRANT"):
            return list(self._filas_show_grant.get(sentencia, []))
        return []

    def SentenciasDeEscritura(self):
        """Devuelve las sentencias GRANT/REVOKE (sin las de lectura).

        Returns:
            list[str]: sentencias que escriben permisos, en orden.
        """
        return [
            sentencia
            for sentencia in self.sentencias_ejecutadas
            if not sentencia.startswith("SHOW GRANT")
        ]


def CrearSolicitud(privilegios):
    """Construye una solicitud 1 a 1 sobre el objeto de prueba.

    Args:
        privilegios (list[str]): privilegios a otorgar al beneficiario.

    Returns:
        SolicitudGrant: solicitud válida para procesar.
    """
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=OBJETO,
    )


def Fila(principal, privilegio):
    """Construye una fila de SHOW GRANT del propio objeto.

    Args:
        principal (str): otorgatario referenciado por la fila.
        privilegio (str): privilegio vigente.

    Returns:
        list[str]: fila con las columnas Principal, ActionType, ObjectType,
            ObjectKey.
    """
    return [principal, privilegio, PALABRA_OBJETO, CLAVE_OBJETO]


def IdentidadUsuario():
    """Devuelve la identidad on-behalf-of del usuario llamante de prueba.

    Returns:
        IdentidadLlamante: identidad resuelta desde el proveedor simulado.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def TestSolicitudValidaOtorgadaYVerificada():
    """Una solicitud 1 a 1 válida se otorga y verifica de punta a punta.

    Escenario "Solicitud otorgada de punta a punta" del spec.
    """
    sesion = SesionSqlWorkspaceImitada()
    sesion.ConfigurarShowGrant(
        OBJETO,
        [
            Fila(BENEFICIARIO, "SELECT"),
            Fila(BENEFICIARIO, "MODIFY"),
        ],
    )
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.Procesar(CrearSolicitud(["SELECT", "MODIFY"]))

    assert len(reporte.lineas) == 2
    assert all(linea.estado is EstadoItem.OTORGADO for linea in reporte.lineas)
    # Dos grants ejecutados (SELECT y MODIFY) y verificación posterior con
    # SHOW GRANT por cada ítem otorgado.
    assert len(sesion.SentenciasDeEscritura()) == 2
    assert sesion.sentencias_ejecutadas[0].startswith("GRANT SELECT")


def TestItemIncompatibleBloqueadoEnPreFlight():
    """Un privilegio inválido para el tipo se bloquea sin tocar la sesión.

    Escenario "Ítem incompatible bloqueado antes de ejecutar" del spec.
    """
    sesion = SesionSqlWorkspaceImitada()
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.Procesar(CrearSolicitud(["CAN_USE"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "no es válido" in linea.detalle
    assert sesion.sentencias_ejecutadas == [], (
        "La matriz filtra antes: la sesión no recibe ninguna sentencia"
    )


def TestItemSinPrivilegioEfectivoBloqueado():
    """Sin el privilegio efectivo del llamante el ítem se bloquea en pre-flight.

    Escenario "Ítem sin privilegio efectivo del llamante" del spec.
    """
    sesion = SesionSqlWorkspaceImitada()
    # El llamante solo tiene SELECT; MODIFY no está entre sus efectivos.
    sesion.ConfigurarShowGrant(
        OBJETO, [Fila(IDENTIFICADOR_USUARIO_DEMO, "SELECT")]
    )
    canal_datos = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos,
            canal_control=CanalControlSimulado(),
        ),
    )

    reporte = pipeline.Procesar(CrearSolicitud(["MODIFY"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert sesion.SentenciasDeEscritura() == [], (
        "El bloqueo por privilegios no debe enviar ninguna instrucción GRANT"
    )
    # El resolutor sí consultó los grants vigentes una vez (lectura permitida).
    assert len(sesion.sentencias_ejecutadas) == 1
    assert sesion.sentencias_ejecutadas[0].startswith("SHOW GRANT")


def TestFalloPuntualNoAbortaElResto():
    """Un fallo de un ítem no cancela el otorgamiento de los demás.

    Escenario "Fallo puntual no aborta la solicitud" del spec.
    """
    sesion = SesionSqlWorkspaceImitada()
    # MODIFY falla por objeto inexistente; SELECT se otorga y se verifica.
    sesion.ConfigurarShowGrant(OBJETO, [Fila(BENEFICIARIO, "SELECT")])
    sesion.ConfigurarErrorEn(
        "GRANT MODIFY",
        ErrorMotorSql(
            "[SCHEMA_OR_OBJECT_NOT_FOUND] El objeto no existe en el metastore."
        ),
    )
    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.Procesar(CrearSolicitud(["SELECT", "MODIFY"]))

    estados = {linea.item.privilegio: linea.estado for linea in reporte.lineas}
    assert estados["SELECT"] is EstadoItem.OTORGADO
    assert estados["MODIFY"] is EstadoItem.FALLIDO
    assert "no existe" in reporte.lineas[1].detalle
