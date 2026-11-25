"""Pruebas funcionales del canal real de cómputo integrado en el pipeline
(capability `compute-grants`).

Cubren los cuatro caminos del flujo sobre objetos de cómputo usando
`CanalControlComputo` (producción) sobre un transporte que imita la Permissions
API: ACL directa con otorgatario y nivel, error de objeto inexistente
(`RESOURCE_DOES_NOT_EXIST`) y tipos fuera de alcance. No hay conexión externa.

- solicitud 1 a 1 válida sobre cada tipo otorgada y verificada de punta a punta;
- ítem incompatible con la matriz bloqueado en pre-flight sin tocar el transporte;
- ítem sin privilegio efectivo del llamante bloqueado `privilegios_insuficientes`;
- tipo fuera de alcance (app o token de C8) rechazado sin llamada alguna.
"""

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_control_computo import (
    CanalControlComputo,
)
from control_accesos.canales.reales.entrada_acl import EntradaAcl
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos


class TransportePermisosControlFalso:
    """Transporte que imita la Permissions API: ACL en memoria y errores."""

    def __init__(self):
        self._acl = {}
        self._inexistentes = set()
        self.error_escritura = None
        self.lecturas = []
        self.escrituras = []

    def RegistrarObjeto(self, objeto, entradas=()):
        """Registra un objeto existente con su ACL inicial."""
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._acl[(recurso, objeto.identificador)] = list(entradas)

    def MarcarInexistente(self, objeto):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._inexistentes.add((recurso, objeto.identificador))

    def LeerAcl(self, recurso, identificador):
        self.lecturas.append((recurso, identificador))
        if (recurso, identificador) in self._inexistentes:
            raise ErrorCanal(
                f"[RESOURCE_DOES_NOT_EXIST] El objeto '{identificador}' no existe."
            )
        return tuple(self._acl.get((recurso, identificador), []))

    def EscribirAcl(self, recurso, identificador, entradas):
        self.escrituras.append((recurso, identificador, list(entradas)))
        if self.error_escritura is not None:
            raise self.error_escritura
        self._acl[(recurso, identificador)] = list(entradas)


BENEFICIARIO = "beneficiario@example.com"


def CrearPrincipal():
    return Principal(identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO)


def CrearSolicitud(objeto, privilegios):
    return SolicitudGrant.Crear(
        principal=CrearPrincipal(), privilegios=list(privilegios), objeto=objeto
    )


def IdentidadUsuario():
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def CrearPipeline(transporte, identidad=None, resolutor=None):
    canal_control = CanalControlComputo(transporte)
    return (
        PipelineGrants(
            canal_datos=CanalDatosSimulado(),
            canal_control=canal_control,
            identidad_llamante=identidad,
            resolutor_privilegios=resolutor,
        ),
        canal_control,
    )


CASOS_POR_TIPO = [
    (TipoObjeto.COMPUTO_CLASICO, "CAN_ATTACH_TO"),
    (TipoObjeto.COMPUTO_SERVERLESS, "CAN_USE"),
    (TipoObjeto.SQL_WAREHOUSE, "CAN_USE"),
]


@pytest.mark.parametrize("tipo,privilegio", CASOS_POR_TIPO)
def TestSolicitudValidaOtorgadaYVerificada(tipo, privilegio):
    """Una solicitud 1 a 1 válida se otorga y verifica de punta a punta."""
    objeto = ObjetoSecurable(identificador=f"obj-{tipo.value}", tipo=tipo)
    transporte = TransportePermisosControlFalso()
    transporte.RegistrarObjeto(objeto)
    pipeline, _ = CrearPipeline(transporte)

    reporte = pipeline.Procesar(CrearSolicitud(objeto, [privilegio]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert len(transporte.escrituras) == 1
    (recurso, identificador, entradas) = transporte.escrituras[0]
    assert identificador == objeto.identificador
    assert EntradaAcl(principal=CrearPrincipal(), nivel=privilegio) in entradas


def TestItemIncompatibleBloqueadoEnPreFlight():
    """Un privilegio inválido para el tipo se bloquea sin tocar el transporte."""
    objeto = ObjetoSecurable(identificador="ClusterA", tipo=TipoObjeto.COMPUTO_CLASICO)
    transporte = TransportePermisosControlFalso()
    transporte.RegistrarObjeto(objeto)
    pipeline, _ = CrearPipeline(transporte)

    reporte = pipeline.Procesar(CrearSolicitud(objeto, ["SELECT"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "no es válido" in linea.detalle
    assert transporte.escrituras == []
    assert transporte.lecturas == []


def TestItemSinPrivilegioEfectivoBloqueado():
    """Sin el privilegio efectivo del llamante el ítem se bloquea en pre-flight."""
    objeto = ObjetoSecurable(identificador="Wh-1", tipo=TipoObjeto.SQL_WAREHOUSE)
    transporte = TransportePermisosControlFalso()
    transporte.RegistrarObjeto(objeto)  # ACL vacía: el llamante no tiene nada.
    canal_control = CanalControlComputo(transporte)
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=CanalDatosSimulado(), canal_control=canal_control
        ),
    )

    reporte = pipeline.Procesar(CrearSolicitud(objeto, ["CAN_MANAGE"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert transporte.escrituras == [], (
        "El bloqueo por privilegios no debe escribir la ACL"
    )


@pytest.mark.parametrize("tipo_objeto", [TipoObjeto.DATABRICK_APP, TipoObjeto.USO_TOKEN])
def TestTipoFueraDeAlcanceRechazadoSinLlamada(tipo_objeto):
    """Un tipo ajeno al cómputo (app o token de C8) se rechaza sin llamada."""
    objeto = ObjetoSecurable(identificador="fuera-de-alcance", tipo=tipo_objeto)
    transporte = TransportePermisosControlFalso()
    pipeline, _ = CrearPipeline(transporte)

    reporte = pipeline.Procesar(CrearSolicitud(objeto, ["CAN_USE"]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "no pertenece al plano de control" in linea.detalle
    assert transporte.lecturas == [] and transporte.escrituras == []
