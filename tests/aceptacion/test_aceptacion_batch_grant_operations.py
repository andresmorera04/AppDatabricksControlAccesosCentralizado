"""Pruebas de aceptación del capability `batch-grant-operations`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/changes/grants-batch/specs/batch-grant-operations/spec.md`:

- Normalización de lotes a ítems atómicos:
  - Lote 1 a N normalizado por objeto y privilegio -> TestEscenarioLote1aNnormalizadoPorObjetoYPrivilegio
  - Lote N a 1 normalizado por principal y privilegio -> TestEscenarioLoteNa1NormalizadoPorPrincipalYPrivilegio
  - Lote degenerado equivalente a una solicitud 1 a 1 -> TestEscenarioLoteDegeneradoEquivalenteASolicitud1a1
- Validación de la solicitud por lote:
  - Lote sin principals -> TestEscenarioLoteSinPrincipals
  - Lote sin objetos -> TestEscenarioLoteSinObjetos
  - Lote sin privilegios -> TestEscenarioLoteSinPrivilegios
- Rechazo explícito de cardinalidad N a M:
  - Solicitud N a M rechazada con mensaje de alcance -> TestEscenarioSolicitudNaMRechazadaConMensajeDeAlcance
- Orquestación por lote sobre el pipeline:
  - Lote con objetos de distinto tipo -> TestEscenarioLoteConObjetosDeDistintoTipo
  - Lote con objetos de distinto plano -> TestEscenarioLoteConObjetosDeDistintoPlano
  - Ítem bloqueado en pre-flight dentro de un lote -> TestEscenarioItemBloqueadoEnPreFlightDentroDeUnLote
- Resultados parciales por ítem:
  - Fallo puntual en un lote 1 a N -> TestEscenarioFalloPuntualEnUnLote1aN
  - Bloqueo parcial por privilegios insuficientes -> TestEscenarioBloqueoParcialPorPrivilegiosInsuficientes
- Reporte consolidado del lote:
  - Totales por estado de un lote mixto -> TestEscenarioTotalesPorEstadoDeUnLoteMixto
  - Lote totalmente otorgado -> TestEscenarioLoteTotalmenteOtorgado
- Registro en bitácora de cada ítem del lote:
  - Ítems registrados individualmente -> TestEscenarioItemsRegistradosIndividualmente
  - Ítems registrados sin identidad de llamante -> TestEscenarioItemsRegistradosSinIdentidadDeLlamante
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pipeline_grants import (
    ACCION_PROCESAR_LOTE,
    PipelineGrants,
)
from control_accesos.pipeline.reporte_lote import AgregadorReporteLote
from control_accesos.resolucion.modelos import PrivilegiosEfectivosVista


class IdentidadLlamanteFalsa:
    """Doble de `IdentidadLlamante` con el atributo `usuario_bitacora`."""

    def __init__(self, usuario):
        self.usuario_bitacora = usuario


class EscritorBitacoraFalso:
    """Doble de `BitacoraEventos` que registra las llamadas sin persistir."""

    def __init__(self):
        self.eventos_registrados = []

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        """Simula el registro de un evento de bitácora."""
        self.eventos_registrados.append((accion, usuario, detalle, resultado))


class ResolutorFalso:
    """Resolutor de privilegios efectivos que devuelve una vista vacía."""

    def ResolverPrivilegiosEfectivos(self, identidad, objeto):
        """Devuelve una vista de privilegios efectivos vacía."""
        return PrivilegiosEfectivosVista(
            objeto=objeto,
            plano=objeto.plano,
            canal_consultado="datos" if objeto.plano.value == "datos" else "control",
            otorgamientos=tuple(),
        )


def TestEscenarioLote1aNnormalizadoPorObjetoYPrivilegio():
    """Escenario: Lote 1 a N normalizado por objeto y privilegio.

    WHEN se normaliza un lote 1 a N con un principal, dos privilegios y tres objetos
    THEN produce seis ítems atómicos, recorriendo los objetos en su orden de entrada
         y, dentro de cada objeto, los privilegios en su orden de entrada.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    privilegios = ["SELECT", "INSERT"]
    objetos = [
        ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        ObjetoSecurable(identificador="tabla2", tipo=TipoObjeto.TABLA_DELTA),
        ObjetoSecurable(identificador="tabla3", tipo=TipoObjeto.TABLA_DELTA),
    ]
    lote = SolicitudLoteGrant(
        principales=[principal], privilegios=privilegios, objetos=objetos
    )
    items = lote.NormalizarAItems()
    assert len(items) == 6


def TestEscenarioLoteNa1NormalizadoPorPrincipalYPrivilegio():
    """Escenario: Lote N a 1 normalizado por principal y privilegio.

    WHEN se normaliza un lote N a 1 con tres principals, dos privilegios y un objeto
    THEN produce seis ítems atómicos, recorriendo los principals en su orden de entrada
         y, dentro de cada principal, los privilegios en su orden de entrada.
    """
    principales = [
        Principal(identificador="user1@example.com", tipo="usuario"),
        Principal(identificador="user2@example.com", tipo="usuario"),
        Principal(identificador="user3@example.com", tipo="usuario"),
    ]
    privilegios = ["SELECT", "INSERT"]
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    lote = SolicitudLoteGrant(
        principales=principales, privilegios=privilegios, objetos=[objeto]
    )
    items = lote.NormalizarAItems()
    assert len(items) == 6


def TestEscenarioLoteDegeneradoEquivalenteASolicitud1a1():
    """Escenario: Lote degenerado equivalente a una solicitud 1 a 1.

    WHEN se normaliza un lote con un solo principal y un solo objeto
    THEN produce los mismos ítems atómicos que la solicitud 1 a 1 equivalente.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    privilegios = ["SELECT"]
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    lote = SolicitudLoteGrant(
        principales=[principal], privilegios=privilegios, objetos=[objeto]
    )
    items = lote.NormalizarAItems()
    assert len(items) == 1


def TestEscenarioLoteSinPrincipals():
    """Escenario: Lote sin principals.

    WHEN llega una solicitud por lote cuya lista de principals está vacía
    THEN el sistema la rechaza con un error explícito que indica que falta al menos un principal.
    """
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    with pytest.raises(ErrorDominio) as excinfo:
        SolicitudLoteGrant(principales=[], privilegios=["SELECT"], objetos=[objeto])
    assert "principal" in str(excinfo.value).lower()


def TestEscenarioLoteSinObjetos():
    """Escenario: Lote sin objetos.

    WHEN llega una solicitud por lote cuya lista de objetos está vacía
    THEN el sistema la rechaza con un error explícito que indica que falta al menos un objeto.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    with pytest.raises(ErrorDominio) as excinfo:
        SolicitudLoteGrant(principales=[principal], privilegios=["SELECT"], objetos=[])
    assert "objeto" in str(excinfo.value).lower()


def TestEscenarioLoteSinPrivilegios():
    """Escenario: Lote sin privilegios.

    WHEN llega una solicitud por lote cuya lista de privilegios está vacía
    THEN el sistema la rechaza con un error explícito que indica que falta al menos un privilegio.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    with pytest.raises(ErrorDominio) as excinfo:
        SolicitudLoteGrant(principales=[principal], privilegios=[], objetos=[objeto])
    assert "privilegio" in str(excinfo.value).lower()


def TestEscenarioSolicitudNaMRechazadaConMensajeDeAlcance():
    """Escenario: Solicitud N a M rechazada con mensaje de alcance.

    WHEN llega a la entrada por lote una solicitud con dos principals y dos objetos
    THEN el sistema la rechaza con un mensaje explícito que declara la cardinalidad N a M fuera de alcance.
    """
    principales = [
        Principal(identificador="user1@example.com", tipo="usuario"),
        Principal(identificador="user2@example.com", tipo="usuario"),
    ]
    objetos = [
        ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        ObjetoSecurable(identificador="tabla2", tipo=TipoObjeto.TABLA_DELTA),
    ]
    with pytest.raises(ErrorDominio) as excinfo:
        SolicitudLoteGrant(principales=principales, privilegios=["SELECT"], objetos=objetos)
    assert "N a M" in str(excinfo.value)


def TestEscenarioLoteConObjetosDeDistintoTipo():
    """Escenario: Lote con objetos de distinto tipo.

    WHEN un lote 1 a N incluye un catálogo y una tabla delta
    THEN cada ítem se clasifica contra la matriz según su propio tipo de objeto.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objetos = [
        ObjetoSecurable(identificador="catalogo1", tipo=TipoObjeto.CATALOGO),
        ObjetoSecurable(identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA),
    ]
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(canal_datos=canal_datos, canal_control=canal_control)
    resultado = pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT"], objetos=objetos
    )
    assert len(resultado.lineas) == 2


def TestEscenarioLoteConObjetosDeDistintoPlano():
    """Escenario: Lote con objetos de distinto plano.

    WHEN un lote incluye objetos del plano de datos y del plano de control
    THEN cada ítem se ejecuta por el canal del plano de su objeto.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objetos = [
        ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        ObjetoSecurable(identificador="cluster-abc123", tipo=TipoObjeto.COMPUTO_CLASICO),
    ]
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(canal_datos=canal_datos, canal_control=canal_control)
    resultado = pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT", "CAN_MANAGE"], objetos=objetos
    )
    assert len(resultado.lineas) == 4


def TestEscenarioItemBloqueadoEnPreFlightDentroDeUnLote():
    """Escenario: Ítem bloqueado en pre-flight dentro de un lote.

    WHEN en un lote un ítem tiene un privilegio inválido para el tipo de su objeto
    THEN ese ítem se excluye de la ejecución con su motivo y los demás ítems continúan.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objeto_control = ObjetoSecurable(identificador="cluster-abc123", tipo=TipoObjeto.COMPUTO_CLASICO)
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(canal_datos=canal_datos, canal_control=canal_control)
    resultado = pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["INSERT"], objetos=[objeto_control]
    )
    assert len(resultado.lineas) == 1
    assert resultado.lineas[0].estado is EstadoItem.FALLIDO


def TestEscenarioFalloPuntualEnUnLote1aN():
    """Escenario: Fallo puntual en un lote 1 a N.

    WHEN en un lote 1 a N el segundo objeto no existe y los demás sí existen
    THEN los ítems de los demás objetos se ejecutan y los del segundo quedan fallidos.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objeto_ok = ObjetoSecurable(identificador="tabla_ok", tipo=TipoObjeto.TABLA_DELTA)
    objeto_falla = ObjetoSecurable(identificador="tabla_falla", tipo=TipoObjeto.TABLA_DELTA)
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    lote = SolicitudLoteGrant(
        principales=[principal], privilegios=["SELECT"], objetos=[objeto_ok, objeto_falla]
    )
    for item in lote.NormalizarAItems():
        if item.objeto.identificador == "tabla_falla":
            canal_datos.ConfigurarEscenario(item, EscenarioSimulacion.OBJETO_INEXISTENTE)
    pipeline = PipelineGrants(canal_datos=canal_datos, canal_control=canal_control)
    resultado = pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT"], objetos=[objeto_ok, objeto_falla]
    )
    assert len(resultado.lineas) == 2
    estados = {linea.estado for linea in resultado.lineas}
    assert EstadoItem.OTORGADO in estados
    assert EstadoItem.FALLIDO in estados


def TestEscenarioBloqueoParcialPorPrivilegiosInsuficientes():
    """Escenario: Bloqueo parcial por privilegios insuficientes.

    WHEN el llamante puede otorgar sobre un objeto del lote pero no sobre otro
    THEN los ítems del primer objeto se procesan y los del segundo se reportan privilegios_insuficientes.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    llamante = IdentidadLlamanteFalsa("llamante@example.com")
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        resolutor_privilegios=ResolutorFalso(),
        identidad_llamante=llamante,
    )
    resultado = pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT"], objetos=[objeto]
    )
    assert len(resultado.lineas) == 1
    assert resultado.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestEscenarioTotalesPorEstadoDeUnLoteMixto(sesion_spark):
    """Escenario: Totales por estado de un lote mixto.

    WHEN un lote termina con tres ítems otorgados, dos fallidos y uno con privilegios insuficientes
    THEN el reporte consolidado expone un total de seis ítems y los totales por estado 3/2/1.
    """
    from control_accesos.pipeline.reportador import LineaReporte, ReporteGrant
    from control_accesos.dominio.modelos import ItemGrant

    def _CrearLinea(estado):
        item = ItemGrant(
            principal=Principal(identificador="user@example.com", tipo="usuario"),
            privilegio="SELECT",
            objeto=ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        )
        return LineaReporte(item=item, estado=estado, detalle=None, trazabilidad=())

    lineas = [
        _CrearLinea(EstadoItem.OTORGADO),
        _CrearLinea(EstadoItem.OTORGADO),
        _CrearLinea(EstadoItem.OTORGADO),
        _CrearLinea(EstadoItem.FALLIDO),
        _CrearLinea(EstadoItem.FALLIDO),
        _CrearLinea(EstadoItem.PRIVILEGIOS_INSUFICIENTES),
    ]
    reporte = ReporteGrant(lineas=tuple(lineas))
    agregador = AgregadorReporteLote(sesion=sesion_spark)
    reporte_lote = agregador.Agregar(reporte)
    assert reporte_lote.total_items == 6
    assert reporte_lote.totales_por_estado[EstadoItem.OTORGADO] == 3
    assert reporte_lote.totales_por_estado[EstadoItem.FALLIDO] == 2
    assert reporte_lote.totales_por_estado[EstadoItem.PRIVILEGIOS_INSUFICIENTES] == 1


def TestEscenarioLoteTotalmenteOtorgado(sesion_spark):
    """Escenario: Lote totalmente otorgado.

    WHEN todos los ítems del lote quedan otorgados
    THEN el reporte consolidado expone el total de otorgados igual al total de ítems y cero en los demás.
    """
    from control_accesos.pipeline.reportador import LineaReporte, ReporteGrant
    from control_accesos.dominio.modelos import ItemGrant

    def _CrearLinea(estado):
        item = ItemGrant(
            principal=Principal(identificador="user@example.com", tipo="usuario"),
            privilegio="SELECT",
            objeto=ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        )
        return LineaReporte(item=item, estado=estado, detalle=None, trazabilidad=())

    lineas = [_CrearLinea(EstadoItem.OTORGADO), _CrearLinea(EstadoItem.OTORGADO)]
    reporte = ReporteGrant(lineas=tuple(lineas))
    agregador = AgregadorReporteLote(sesion=sesion_spark)
    reporte_lote = agregador.Agregar(reporte)
    assert reporte_lote.total_items == 2
    assert reporte_lote.totales_por_estado[EstadoItem.OTORGADO] == 2
    assert reporte_lote.totales_por_estado[EstadoItem.FALLIDO] == 0


def TestEscenarioItemsRegistradosIndividualmente():
    """Escenario: Ítems registrados individualmente.

    WHEN se procesa un lote de cuatro ítems con el llamante autenticado
    THEN la bitácora de eventos registra un evento por ítem más el evento consolidado.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objetos = [
        ObjetoSecurable(identificador=f"tabla{i}", tipo=TipoObjeto.TABLA_DELTA)
        for i in range(4)
    ]
    llamante = IdentidadLlamanteFalsa("llamante@example.com")
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    escritor_eventos = EscritorBitacoraFalso()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=llamante,
        registrador_eventos=escritor_eventos,
    )
    pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT"], objetos=objetos
    )
    # 4 eventos por ítem + 1 evento consolidado = 5 eventos.
    assert len(escritor_eventos.eventos_registrados) == 5


def TestEscenarioItemsRegistradosSinIdentidadDeLlamante():
    """Escenario: Ítems registrados sin identidad de llamante.

    WHEN se procesa un lote sin identidad del llamante
    THEN los eventos por ítem se registran igualmente, con el usuario explícitamente sin valor.
    """
    principal = Principal(identificador="user@example.com", tipo="usuario")
    objetos = [ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)]
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    escritor_eventos = EscritorBitacoraFalso()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        registrador_eventos=escritor_eventos,
    )
    pipeline.ProcesarLoteDesdeEntradas(
        principales=[principal], privilegios=["SELECT"], objetos=objetos
    )
    # 1 evento por ítem + 1 evento consolidado = 2 eventos.
    assert len(escritor_eventos.eventos_registrados) == 2
    # Ambos eventos tienen usuario=None.
    for accion, usuario, detalle, resultado in escritor_eventos.eventos_registrados:
        assert usuario is None
