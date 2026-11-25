"""Pruebas de aceptación de la capability `compute-grants`.

Trazabilidad 1:1 con los escenarios del spec delta
`openspec/changes/grants-compute/specs/compute-grants/spec.md`: cada
`#### Scenario` tiene su prueba, con el nombre del escenario en el docstring,
usando el canal real `CanalControlComputo` sobre un transporte que imita la
Permissions API (sin conexión externa) y la fábrica de fixtures
`fixtures_computo` para los escenarios de entorno. Ninguna escritura llega a un
workspace real.
"""

import sys
from pathlib import Path

# La fábrica de fixtures vive en la capa integral; se agrega su directorio al
# sys.path para ejercitar su contrato de datos/perfil sin conexión (mismo
# criterio que la suite de aceptación de C4/C6).
RAIZ_PRUEBAS = Path(__file__).resolve().parents[1]
if str(RAIZ_PRUEBAS / "integrales") not in sys.path:
    sys.path.insert(0, str(RAIZ_PRUEBAS / "integrales"))

import pytest

import fixtures_computo as fixtures
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
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.verificador import Verificador
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos


class TransporteControlFalso:
    """Transporte que imita la Permissions API para la aceptación (sin red)."""

    def __init__(self):
        self._acl = {}
        self._inexistentes = set()
        self._errores_lectura = {}
        self.error_escritura = None
        self.lecturas = []
        self.escrituras = []

    def RegistrarObjeto(self, objeto, entradas=()):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._acl[(recurso, objeto.identificador)] = list(entradas)

    def MarcarInexistente(self, objeto):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._inexistentes.add((recurso, objeto.identificador))

    def ConfigurarErrorLectura(self, objeto, error):
        recurso = CanalControlComputo.RecursoDeTipo(objeto.tipo)
        self._errores_lectura[(recurso, objeto.identificador)] = error

    def LeerAcl(self, recurso, identificador):
        self.lecturas.append((recurso, identificador))
        if (recurso, identificador) in self._errores_lectura:
            raise self._errores_lectura[(recurso, identificador)]
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


USUARIO = "usuario_demo@example.com"


def _Principal(email="beneficiario@example.com", tipo=TipoPrincipal.USUARIO):
    return Principal(identificador=email, tipo=tipo)


def _Canal(transporte):
    return CanalControlComputo(transporte)


def _Pipeline(transporte, identidad=None, resolutor=None, registrador=None):
    return PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=_Canal(transporte),
        identidad_llamante=identidad,
        resolutor_privilegios=resolutor,
        registrador_eventos=registrador,
    )


def _Objeto(tipo=TipoObjeto.COMPUTO_CLASICO, identificador="obj-1"):
    return ObjetoSecurable(identificador=identificador, tipo=tipo)


def _Solicitud(objeto, privilegios, principal=_Principal()):
    return SolicitudGrant.Crear(
        principal=principal, privilegios=list(privilegios), objeto=objeto
    )


def _IdentidadUsuario():
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


class RegistradorEventosFalso:
    """Registrador de eventos que acumula llamadas (sin Spark)."""

    def __init__(self):
        self.eventos = []

    def Registrar(self, **kwargs):
        self.eventos.append(kwargs)


# --- Cobertura de los tipos de cómputo del plano de control -------------

def TestEscenarioPermisoSobreUnClusterClasico():
    """Permiso sobre un cluster clásico."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal(), "CAN_MANAGE", objeto)
    )
    assert resultado.estado is EstadoItem.OTORGADO


def TestEscenarioPermisoSobreUnServerlessComputeObject():
    """Permiso sobre un serverless compute object."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_SERVERLESS, "sc-default")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal(), "CAN_USE", objeto)
    )
    assert resultado.estado is EstadoItem.OTORGADO


def TestEscenarioPermisoSobreUnSqlWarehouse():
    """Permiso sobre un SQL warehouse."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.SQL_WAREHOUSE, "wh-1")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal(), "CAN_USE", objeto)
    )
    assert resultado.estado is EstadoItem.OTORGADO


def TestEscenarioTipoDeObjetoNoSoportado():
    """Tipo de objeto no soportado por el canal."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.DATABRICK_APP, "mi-app")
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal(), "CAN_USE", objeto)
    )
    assert resultado.estado is EstadoItem.FALLIDO
    assert "no pertenece al plano de control" in resultado.detalle


# --- Privilegios válidos por tipo de cómputo ----------------------------

def TestEscenarioNivelesDePermisoDeUnClusterClasico():
    """Niveles de permiso de un cluster clásico."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    canal = _Canal(transporte)
    for privilegio in ("CAN_ATTACH_TO", "CAN_RESTART", "CAN_MANAGE"):
        assert canal.Otorgar(ItemGrant(_Principal(), privilegio, objeto)).estado is EstadoItem.OTORGADO


def TestEscenarioNivelesDePermisoDelComputoServerless():
    """Niveles de permiso del cómputo serverless."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_SERVERLESS, "sc-default")
    transporte.RegistrarObjeto(objeto)
    canal = _Canal(transporte)
    for privilegio in ("CAN_USE", "CAN_MANAGE"):
        assert canal.Otorgar(ItemGrant(_Principal(), privilegio, objeto)).estado is EstadoItem.OTORGADO


def TestEscenarioNivelesDePermisoDeUnSqlWarehouse():
    """Niveles de permiso de un SQL warehouse."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.SQL_WAREHOUSE, "wh-1")
    transporte.RegistrarObjeto(objeto)
    canal = _Canal(transporte)
    for privilegio in ("CAN_USE", "CAN_MONITOR", "CAN_MANAGE"):
        assert canal.Otorgar(ItemGrant(_Principal(), privilegio, objeto)).estado is EstadoItem.OTORGADO


def TestEscenarioPrivilegioIncompatibleConElTipo():
    """Privilegio incompatible con el tipo de objeto."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    reporte = _Pipeline(transporte).Procesar(_Solicitud(objeto, ["CAN_USE"]))
    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert transporte.escrituras == []


# --- Otorgamiento mediante la Permissions API ---------------------------

def TestEscenarioOtorgamientoSinEntradaPrevia():
    """Otorgamiento a un otorgatario sin entrada previa."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto, [EntradaAcl(_Principal("otro@x.com"), "CAN_RESTART")])
    _Canal(transporte).Otorgar(ItemGrant(_Principal("nuevo@x.com"), "CAN_USE", objeto))
    (_, _, entradas) = transporte.escrituras[0]
    assert EntradaAcl(_Principal("nuevo@x.com"), "CAN_USE") in entradas
    assert EntradaAcl(_Principal("otro@x.com"), "CAN_RESTART") in entradas


def TestEscenarioOtorgamientoSobreEntradaExistente():
    """Otorgamiento sobre una entrada ya existente."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto, [EntradaAcl(_Principal("mismo@x.com"), "CAN_USE")])
    _Canal(transporte).Otorgar(ItemGrant(_Principal("mismo@x.com"), "CAN_MANAGE", objeto))
    (_, _, entradas) = transporte.escrituras[0]
    assert EntradaAcl(_Principal("mismo@x.com"), "CAN_MANAGE") in entradas


def TestEscenarioOtorgamientoIdempotente():
    """Otorgamiento idempotente."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto, [EntradaAcl(_Principal("mismo@x.com"), "CAN_USE")])
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal("mismo@x.com"), "CAN_USE", objeto)
    )
    assert resultado.estado is EstadoItem.OTORGADO


# --- Revocación mediante la Permissions API -----------------------------

def TestEscenarioRevocacionDeUnPermisoVigente():
    """Revocación de un permiso vigente."""
    transporte = TransporteControlFalso()
    objetivo = _Principal("a-revocar@x.com")
    otro = EntradaAcl(_Principal("otro@x.com"), "CAN_RESTART")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto, [EntradaAcl(objetivo, "CAN_USE"), otro])
    _Canal(transporte).Revocar(ItemGrant(objetivo, "CAN_USE", objeto))
    (_, _, entradas) = transporte.escrituras[0]
    assert all(e.principal != objetivo for e in entradas)
    assert otro in entradas


def TestEscenarioRevocacionDeUnPermisoNoVigente():
    """Revocación de un permiso que no estaba vigente."""
    transporte = TransporteControlFalso()
    otro = EntradaAcl(_Principal("otro@x.com"), "CAN_RESTART")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto, [otro])
    _Canal(transporte).Revocar(ItemGrant(_Principal("ausente@x.com"), "CAN_USE", objeto))
    (_, _, entradas) = transporte.escrituras[0]
    assert entradas == [otro]


# --- Consulta de la ACL vigente -----------------------------------------

def TestEscenarioEntradasDeLaACLTraducidas():
    """Entradas de la ACL traducidas a otorgamientos."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(
        objeto,
        [EntradaAcl(_Principal("u@x.com"), "CAN_USE"), EntradaAcl(_Principal("g", TipoPrincipal.GRUPO), "CAN_MANAGE")],
    )
    grants = _Canal(transporte).ListarGrantsVigentes(objeto)
    assert {g.privilegio for g in grants} == {"CAN_USE", "CAN_MANAGE"}
    assert all(g.objeto == objeto for g in grants)


def TestEscenarioACLSinEntradas():
    """ACL sin entradas."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.SQL_WAREHOUSE, "wh-1")
    transporte.RegistrarObjeto(objeto, [])
    assert _Canal(transporte).ListarGrantsVigentes(objeto) == []


# --- Verificación posterior al otorgamiento -----------------------------

def TestEscenarioPermisoConfirmadoPorLaVerificacion():
    """Permiso confirmado por la verificación."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    item = ItemGrant(_Principal(), "CAN_USE", objeto)
    transporte.RegistrarObjeto(objeto, [EntradaAcl(_Principal(), "CAN_USE")])
    canal = _Canal(transporte)
    resultado = Verificador(canal_datos=CanalDatosSimulado(), canal_control=canal).Verificar(
        [_ResultadoOtorgado(item)]
    )
    assert resultado[0].estado is EstadoItem.OTORGADO


def _ResultadoOtorgado(item):
    from control_accesos.dominio.modelos import ResultadoItem

    return ResultadoItem.Otorgado(item)


def TestEscenarioPermisoNoConfirmadoPorLaVerificacion():
    """Permiso no confirmado por la verificación."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    item = ItemGrant(_Principal(), "CAN_USE", objeto)
    transporte.RegistrarObjeto(objeto, [])
    canal = _Canal(transporte)
    resultado = Verificador(canal_datos=CanalDatosSimulado(), canal_control=canal).Verificar(
        [_ResultadoOtorgado(item)]
    )
    assert resultado[0].estado is EstadoItem.FALLIDO
    assert "CAN_USE" in resultado[0].detalle


# --- Errores del canal traducidos por caso ------------------------------

def TestEscenarioPermisoDenegadoAlEjecutor():
    """Permiso denegado al ejecutor."""
    transporte = TransporteControlFalso()
    transporte.error_escritura = ErrorCanal("[PERMISSION_DENIED] denegado")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestEscenarioObjetoDeComputoInexistente():
    """Objeto de cómputo inexistente."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    transporte.MarcarInexistente(objeto)
    resultado = _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle


def TestEscenarioPrincipalInexistente():
    """Principal inexistente."""
    transporte = TransporteControlFalso()
    transporte.error_escritura = ErrorCanal("[PRINCIPAL_DOES_NOT_EXIST] no existe")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(
        ItemGrant(_Principal("no-existe@x.com"), "CAN_USE", objeto)
    )
    assert resultado.estado is EstadoItem.FALLIDO
    assert "no-existe@x.com" in resultado.detalle


def TestEscenarioCualquierOtroFalloDelCanal():
    """Cualquier otro fallo del canal."""
    transporte = TransporteControlFalso()
    transporte.error_escritura = ErrorCanal("fallo inesperado de red")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    resultado = _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.FALLIDO
    assert "fallo inesperado de red" in resultado.detalle


# --- Identidad del llamante y trazabilidad ------------------------------

def TestEscenarioEventoConElUsuarioDelLlamante():
    """Evento con el usuario del llamante."""
    registrador = RegistradorEventosFalso()
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=_Canal(transporte),
        identidad_llamante=_IdentidadUsuario(),
        registrador_eventos=registrador,
    )
    reporte = pipeline.Procesar(_Solicitud(objeto, ["CAN_MANAGE"]))
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert registrador.eventos
    assert registrador.eventos[-1]["usuario"] == USUARIO


class RegistradorErroresFalso:
    def __init__(self, falla=False):
        self.registros = []
        self.falla = falla

    def Registrar(self, *args, **kwargs):
        if self.falla:
            raise RuntimeError("bitácora caída")
        self.registros.append((args, kwargs))


def TestEscenarioFalloDeEjecucionRegistrado():
    """Fallo de ejecución registrado."""
    registrador = RegistradorErroresFalso()
    transporte = TransporteControlFalso()
    transporte.error_escritura = ErrorCanal("fallo de red")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    canal = CanalControlComputo(transporte, registrador_errores=registrador)
    canal.Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert len(registrador.registros) == 1


def TestEscenarioLaAuditoriaNoIntroduceFallos():
    """La auditoría no introduce fallos en cascada."""
    transporte = TransporteControlFalso()
    transporte.error_escritura = ErrorCanal("fallo de red")
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    canal = CanalControlComputo(
        transporte, registrador_errores=RegistradorErroresFalso(falla=True)
    )
    resultado = canal.Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.FALLIDO


# --- Alcance del control serverless -------------------------------------

def TestEscenarioObjetosDefaultSoloPermisos():
    """Objetos default tratados solo como objetivo de permisos."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_SERVERLESS, "Default Interactive Compute")
    transporte.RegistrarObjeto(objeto)
    canal = _Canal(transporte)
    canal.Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    # Solo escribe la ACL: el canal no expone métodos de crear/renombrar/eliminar.
    assert len(transporte.escrituras) == 1
    assert not hasattr(canal, "Crear")
    assert not hasattr(canal, "Eliminar")


def TestEscenarioActivacionDelFeatureFueraDeLaApp():
    """Activación del feature fuera de la app."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_SERVERLESS, "sc")
    transporte.RegistrarObjeto(objeto)
    transporte.ConfigurarErrorLectura(
        objeto, ErrorCanal("Serverless access control is not enabled for this workspace.")
    )
    resultado = _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.FALLIDO
    assert "not enabled" in resultado.detalle
    assert transporte.escrituras == []


# --- Credenciales y destino inyectados ----------------------------------

def TestEscenarioCanalEjercitadoSinWorkspaceAlguno():
    """Canal ejercitado sin workspace alguno."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_CLASICO, "ClusterA")
    transporte.RegistrarObjeto(objeto)
    canal = _Canal(transporte)
    assert canal.Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto)).estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(objeto)


def TestEscenarioOperacionEnviadaAlTransporteInyectado():
    """Operación enviada al transporte inyectado."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.SQL_WAREHOUSE, "Wh-Mixto")
    transporte.RegistrarObjeto(objeto)
    _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    (recurso, identificador, _) = transporte.escrituras[0]
    assert recurso == "sql/warehouses"
    assert identificador == "Wh-Mixto"


# --- Cardinalidades y resultados parciales ------------------------------

def TestEscenarioLoteUnoANSobreObjetosDeComputo():
    """Lote 1 a N sobre varios objetos de cómputo."""
    transporte = TransporteControlFalso()
    o1 = _Objeto(TipoObjeto.COMPUTO_CLASICO, "C1")
    o2 = _Objeto(TipoObjeto.SQL_WAREHOUSE, "W1")
    transporte.RegistrarObjeto(o1)
    transporte.RegistrarObjeto(o2)
    reporte = _Pipeline(transporte).ProcesarLoteDesdeEntradas(
        principales=[_Principal()], privilegios=["CAN_MANAGE"], objetos=[o1, o2]
    )
    assert len(reporte.lineas) == 2
    assert all(l.estado is EstadoItem.OTORGADO for l in reporte.lineas)


def TestEscenarioFalloPuntualNoAbortaLote():
    """Fallo puntual no aborta el lote."""
    transporte = TransporteControlFalso()
    o1 = _Objeto(TipoObjeto.COMPUTO_CLASICO, "C1")
    o2 = _Objeto(TipoObjeto.COMPUTO_CLASICO, "C-inexistente")
    transporte.RegistrarObjeto(o1)
    transporte.RegistrarObjeto(o2)
    transporte.MarcarInexistente(o2)
    reporte = _Pipeline(transporte).ProcesarLoteDesdeEntradas(
        principales=[_Principal()], privilegios=["CAN_MANAGE"], objetos=[o1, o2]
    )
    estados = {l.item.objeto.identificador: l.estado for l in reporte.lineas}
    assert estados["C1"] is EstadoItem.OTORGADO
    assert estados["C-inexistente"] is EstadoItem.FALLIDO


def TestEscenarioCardinalidadNAMRechazada():
    """Cardinalidad N a M rechazada."""
    transporte = TransporteControlFalso()
    with pytest.raises(ErrorDominio):
        _Pipeline(transporte).ProcesarLoteDesdeEntradas(
            principales=[_Principal("a@x.com"), _Principal("b@x.com")],
            privilegios=["CAN_MANAGE"],
            objetos=[_Objeto(TipoObjeto.COMPUTO_CLASICO, "C1"), _Objeto(TipoObjeto.COMPUTO_CLASICO, "C2")],
        )
    assert transporte.escrituras == []


# --- Pruebas por entorno con restauración -------------------------------

def TestEscenarioACLRestauradaTrasLaPrueba():
    """ACL restaurada tras la prueba."""
    original = [EntradaAcl(_Principal("u@x.com"), "CAN_USE")]
    transporte = TransporteControlFalso()
    transporte.RegistrarObjeto(_Objeto(TipoObjeto.SQL_WAREHOUSE, "wh-1"), original)
    canal = _Canal(transporte)

    with fixtures.ACLRestaurada(canal, "sql/warehouses", "wh-1"):
        transporte.EscribirAcl("sql/warehouses", "wh-1", original + [EntradaAcl(_Principal("extra@x.com"), "CAN_USE")])

    assert tuple(transporte.LeerAcl("sql/warehouses", "wh-1")) == tuple(original)


def TestEscenarioComputoClasicoFueraDeFreeEdition():
    """Cómputo clásico fuera de Free Edition."""
    assert fixtures.PerfilDeTipo(TipoObjeto.COMPUTO_CLASICO) == fixtures.PERFIL_AZURE
    assert fixtures.PerfilDeTipo(TipoObjeto.SQL_WAREHOUSE) == fixtures.PERFIL_FREE


def TestEscenarioFeatureServerlessNoDisponible():
    """Feature serverless no disponible en el workspace."""
    transporte = TransporteControlFalso()
    objeto = _Objeto(TipoObjeto.COMPUTO_SERVERLESS, "sc")
    transporte.RegistrarObjeto(objeto)
    transporte.ConfigurarErrorLectura(
        objeto, ErrorCanal("[FEATURE_DISABLED] serverless accesos no habilitados")
    )
    resultado = _Canal(transporte).Otorgar(ItemGrant(_Principal(), "CAN_USE", objeto))
    assert resultado.estado is EstadoItem.FALLIDO
    assert transporte.escrituras == []


def TestEscenarioPermisoDenegadoConIdentidadEjecutoraRestringida():
    """Permiso denegado con identidad ejecutora restringida.

    El comportamiento real se verifica en la integral `free`
    (`TestPermisoDenegadoConIdentidadRestringida` de
    `test_grants_computo_andresfree.py`), que ejecuta el grant autenticada como el
    service principal restringido. Aquí, sin conexión, se afirma el contrato de la
    fábrica: el ejecutor restringido usa el App Id aprobado y su secret se inyecta
    por variable de entorno (nunca en el código).
    """
    assert fixtures.APP_ID_SP_EJECUTOR_RESTRINGIDO == fixtures.APP_ID_SP_FREE
    assert fixtures.VARIABLE_SECRET_EJECUTOR == "CONTROL_ACCESOS_SP_CLIENT_SECRET"
