"""Pruebas funcionales de la auditoría del canal de cómputo (capability
`compute-grants`, design D7).

Verifican con Spark local y los escritores reales de bitácora que, al procesar
una solicitud sobre objetos de cómputo por `CanalControlComputo`:

- el evento queda registrado en `bitacora_eventos` con el `usuario` del llamante
  on-behalf-of y el desglose de estados por ítem;
- un fallo del transporte durante la ejecución queda registrado en
  `bitacora_errores` con su detalle (STRUCT) y el módulo `canal_control`.

El transporte es un doble que imita la Permissions API; los escritores de
bitácora operan sobre las tablas delta locales creadas por el inicializador de
persistencia (C2).
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.bitacora.escritores import BitacoraErrores, BitacoraEventos
from control_accesos.canales.reales.canal_control_computo import (
    MODULO_BITACORA_ERRORES,
    CanalControlComputo,
)
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal, SolicitudGrant
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.pipeline.pipeline_grants import PipelineGrants

CATALOGO_LOCAL = "spark_catalog"
TABLA_EVENTOS = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_eventos"
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"

BENEFICIARIO = "beneficiario@example.com"


class TransportePermisosControlFalso:
    """Transporte que imita la Permissions API para las pruebas de auditoría."""

    def __init__(self):
        self._acl = {}
        self._inexistentes = set()

    def RegistrarObjeto(self, objeto, entradas=()):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._acl[(recurso, objeto.identificador)] = list(entradas)

    def MarcarInexistente(self, objeto):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._inexistentes.add((recurso, objeto.identificador))

    def LeerAcl(self, recurso, identificador):
        if (recurso, identificador) in self._inexistentes:
            from control_accesos.canales.errores import ErrorCanal

            raise ErrorCanal(
                f"[RESOURCE_DOES_NOT_EXIST] El objeto '{identificador}' no existe."
            )
        return tuple(self._acl.get((recurso, identificador), []))

    def EscribirAcl(self, recurso, identificador, entradas):
        self._acl[(recurso, identificador)] = list(entradas)


def CrearConfiguracionLocal(tmp_path):
    import json

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8")
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def PrepararBitacoras(sesion_spark, tmp_path):
    configuracion = CrearConfiguracionLocal(tmp_path)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return (
        BitacoraEventos(sesion=sesion_spark, capa=capa),
        BitacoraErrores(sesion=sesion_spark, capa=capa),
    )


def IdentidadUsuario():
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def CrearSolicitud(objeto, privilegios):
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=objeto,
    )


def ContarFilas(sesion_spark, tabla, condicion=""):
    sentencia = f"SELECT COUNT(*) AS total FROM {tabla}"
    if condicion:
        sentencia += f" WHERE {condicion}"
    return sesion_spark.sql(sentencia).collect()[0].total


OBJETO = ObjetoSecurable(identificador="ClusterAudit", tipo=TipoObjeto.COMPUTO_CLASICO)


def TestEventoRegistradoConUsuarioOboYDesglose(sesion_spark, tmp_path):
    """El evento de la solicitud de cómputo queda con el usuario OBO y el desglose."""
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    transporte = TransportePermisosControlFalso()
    transporte.RegistrarObjeto(OBJETO)
    canal_control = CanalControlComputo(
        transporte, registrador_errores=bitacora_errores
    )
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )
    eventos_otorgados_antes = ContarFilas(
        sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'"
    )

    reporte = pipeline.Procesar(CrearSolicitud(OBJETO, ["CAN_ATTACH_TO"]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert (
        ContarFilas(sesion_spark, TABLA_EVENTOS, "resultado = 'otorgado'")
        - eventos_otorgados_antes
        == 1
    ), "El evento de la solicitud debe quedar registrado"
    fila = sesion_spark.sql(
        f"SELECT usuario, detalle FROM {TABLA_EVENTOS} "
        "WHERE resultado = 'otorgado' ORDER BY marca_tiempo DESC LIMIT 1"
    ).collect()[0]
    assert fila.usuario == IDENTIFICADOR_USUARIO_DEMO
    assert "otorgado=1" in fila.detalle


def TestFalloDeTransporteRegistradoEnBitacoraErrores(sesion_spark, tmp_path):
    """Un fallo del transporte se registra en bitacora_errores con su detalle."""
    bitacora_eventos, bitacora_errores = PrepararBitacoras(sesion_spark, tmp_path)
    objeto = ObjetoSecurable(
        identificador="ClusterNoExiste", tipo=TipoObjeto.COMPUTO_CLASICO
    )
    transporte = TransportePermisosControlFalso()
    transporte.RegistrarObjeto(objeto)
    transporte.MarcarInexistente(objeto)
    canal_control = CanalControlComputo(
        transporte, registrador_errores=bitacora_errores
    )
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        registrador_eventos=bitacora_eventos,
        registrador_errores=bitacora_errores,
    )

    reporte = pipeline.Procesar(CrearSolicitud(objeto, ["CAN_ATTACH_TO"]))

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    filas = sesion_spark.sql(
        f"SELECT modulo, detalle FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}' "
        f"AND detalle.contexto LIKE '%{objeto.identificador}%'"
    ).collect()
    assert len(filas) == 1, "El fallo de ejecución debe quedar en la bitácora"
    assert filas[0].detalle.tipo_excepcion == "ErrorCanal"
    assert objeto.identificador in filas[0].detalle.contexto
