"""Pruebas unitarias de la orquestación por lote sobre el pipeline.

Trazabilidad:
- spec `batch-grant-operations` - "Orquestación por lote sobre el pipeline"
- spec `batch-grant-operations` - "Resultados parciales por ítem"
- spec `batch-grant-operations` - "Validación de la solicitud por lote"

Convención del proyecto (README.md): clases, funciones y métodos en PascalCase
(pytest.ini registra `python_functions = Test*`); errores del dominio como
`ErrorDominio` con mensaje explícito en español.
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.modelos import PrivilegiosEfectivosVista


def _CrearPrincipal(email="user@example.com"):
    """Construye un principal de prueba."""
    return Principal(identificador=email, tipo=TipoPrincipal.USUARIO)


def _CrearObjetoTabla(identificador="catalogo1.schema1.tabla1"):
    """Construye un objeto de prueba del plano de datos (tabla delta)."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.TABLA_DELTA
    )


def _CrearObjetoControl(identificador="cluster-abc123"):
    """Construye un objeto de prueba del plano de control (cómputo clásico)."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.COMPUTO_CLASICO
    )


class ResolutorFalso:
    """Resolutor de privilegios efectivos que devuelve una vista vacía.

    Simula un llamante sin privilegios efectivos sobre ningún objeto, de modo
    que los ítems se bloquean con `privilegios_insuficientes` en pre-flight
    (spec `batch-grant-operations` - "Ítem bloqueado en pre-flight").
    """

    def ResolverPrivilegiosEfectivos(self, identidad, objeto):
        """Devuelve una vista de privilegios efectivos vacía (sin otorgamientos)."""
        return PrivilegiosEfectivosVista(
            objeto=objeto,
            plano=objeto.plano,
            canal_consultado="datos" if objeto.plano.value == "datos" else "control",
            otorgamientos=tuple(),
        )


class TestOrquestacionPorLote:
    """Verifica la orquestación por lote sobre las fases del pipeline."""

    def TestLote1aNConObjetosDeDistintoTipoProcesaTodosLosItems(self):
        """Scenario: Lote 1 a N con objetos de distinto tipo.

        WHEN un lote 1 a N incluye objetos de distintos tipos THEN cada ítem
        se clasifica contra la matriz según su propio tipo de objeto y se
        ejecuta con la instrucción que le corresponde.
        """
        principal = _CrearPrincipal()
        objetos = [
            _CrearObjetoTabla("catalogo1.schema1.tabla1"),
            _CrearObjetoTabla("catalogo1.schema1.tabla2"),
        ]
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=objetos,
        )
        # Cada ítem produce su resultado; ninguno se aborta.
        assert len(resultado.lineas) == 2
        assert all(
            linea.estado is EstadoItem.OTORGADO for linea in resultado.lineas
        )

    def TestLoteConObjetosDeAmbosPlanosEjecutaPorCanalDelPlano(self):
        """Scenario: Lote con objetos de distinto plano.

        WHEN un lote incluye objetos del plano de datos y del plano de control
        THEN cada ítem se ejecuta por el canal del plano de su objeto.

        Nota: la lista de privilegios incluye SELECT (válido para datos) y
        CAN_MANAGE (válido para control). Cada objeto produce ítems con ambos
        privilegios; los incompatibles se bloquean en pre-flight, pero los
        compatibles se enrutan al canal correcto, demostrando el enrutamiento
        por plano.
        """
        principal = _CrearPrincipal()
        objetos = [
            _CrearObjetoTabla("catalogo1.schema1.tabla1"),
            _CrearObjetoControl("cluster-abc123"),
        ]
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT", "CAN_MANAGE"],
            objetos=objetos,
        )
        # 4 ítems: tabla×SELECT (otorgado), tabla×CAN_MANAGE (bloqueado),
        # cluster×SELECT (bloqueado), cluster×CAN_MANAGE (otorgado).
        assert len(resultado.lineas) == 4
        # Ambos canales fueron invocados (uno por cada plano).
        assert canal_datos.operaciones_ejecutadas  # ítem de datos
        assert canal_control.operaciones_ejecutadas  # ítem de control

    def TestItemIncompatibleConLaMatrizSeBloqueaEnPreFlight(self):
        """Scenario: Ítem incompatible con la matriz se bloquea en pre-flight.

        WHEN un ítem tiene un privilegio inválido para el tipo de su objeto
        THEN se bloquea en pre-flight sin llegar al canal de ejecución.
        """
        principal = _CrearPrincipal()
        # INSERT no es válido para COMPUTO_CLASICO (plano de control)
        objeto_control = _CrearObjetoControl()
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["INSERT"],
            objetos=[objeto_control],
        )
        # El ítem se bloquea en pre-flight con estado FALLIDO.
        assert len(resultado.lineas) == 1
        assert resultado.lineas[0].estado is EstadoItem.FALLIDO
        # No se invocó el canal de control (el ítem se bloqueó en pre-flight).
        assert not canal_control.operaciones_ejecutadas

    def TestItemSinPrivilegioEfectivoSeBloquea(self):
        """Scenario: Ítem sin privilegio efectivo del llamante se bloquea.

        WHEN el llamante carece del privilegio autorizador sobre un objeto
        THEN el ítem se bloquea con `privilegios_insuficientes` sin llegar a
        la sesión.
        """
        principal = _CrearPrincipal()
        objeto = _CrearObjetoTabla()
        llamante = Principal(
            identificador="llamante@example.com", tipo=TipoPrincipal.USUARIO
        )
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            resolutor_privilegios=ResolutorFalso(),
            identidad_llamante=llamante,
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto],
        )
        # El ítem se bloquea con privilegios insuficientes.
        assert len(resultado.lineas) == 1
        assert (
            resultado.lineas[0].estado
            is EstadoItem.PRIVILEGIOS_INSUFICIENTES
        )
        # No se invocó el canal (el ítem se bloqueó en pre-flight).
        assert not canal_datos.operaciones_ejecutadas

    def TestFalloPuntualNoAbortaElRestoDelLote(self):
        """Scenario: El fallo puntual de un ítem no aborta el resto del lote.

        WHEN un lote 1 a N tiene un ítem que falla y otro que se otorga THEN
        el reporte incluye ambos resultados sin abortar la operación.
        """
        principal = _CrearPrincipal()
        objeto_ok = _CrearObjetoTabla("catalogo1.schema1.tabla_ok")
        objeto_falla = _CrearObjetoTabla("catalogo1.schema1.tabla_falla")
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        # Configurar el segundo objeto para fallar con objeto inexistente.
        lote = SolicitudLoteGrant(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto_ok, objeto_falla],
        )
        for item in lote.NormalizarAItems():
            if item.objeto.identificador == "catalogo1.schema1.tabla_falla":
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto_ok, objeto_falla],
        )
        # Ambos ítems producen resultado; uno otorgado, uno fallido.
        assert len(resultado.lineas) == 2
        estados = {linea.estado for linea in resultado.lineas}
        assert EstadoItem.OTORGADO in estados
        assert EstadoItem.FALLIDO in estados


class TestValidacionFormaLote:
    """Verifica que ProcesarLoteDesdeEntradas valida la forma antes de generar ítems."""

    def TestLoteNaMRechazadoSinInvocarCanal(self):
        """Scenario: ProcesarLoteDesdeEntradas valida la forma antes de generar ítems.

        WHEN se invoca con cardinalidad N a M THEN se rechaza con ErrorDominio
        sin generar ítems ni invocar canal alguno.
        """
        principal1 = _CrearPrincipal("user1@example.com")
        principal2 = _CrearPrincipal("user2@example.com")
        objeto1 = _CrearObjetoTabla("catalogo1.schema1.tabla1")
        objeto2 = _CrearObjetoTabla("catalogo1.schema1.tabla2")
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        with pytest.raises(ErrorDominio) as excinfo:
            pipeline.ProcesarLoteDesdeEntradas(
                principales=[principal1, principal2],
                privilegios=["SELECT"],
                objetos=[objeto1, objeto2],
            )
        assert "N a M" in str(excinfo.value)
        # No se invocó ningún canal.
        assert not canal_datos.operaciones_ejecutadas
        assert not canal_control.operaciones_ejecutadas

    def TestLoteSinPrincipalesRechazado(self):
        """Scenario: Lote sin principals rechazado antes de generar ítems.

        WHEN se invoca con lista de principales vacía THEN se rechaza con
        ErrorDominio sin generar ítems ni invocar canal alguno.
        """
        objeto = _CrearObjetoTabla()
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        with pytest.raises(ErrorDominio) as excinfo:
            pipeline.ProcesarLoteDesdeEntradas(
                principales=[],
                privilegios=["SELECT"],
                objetos=[objeto],
            )
        assert "principal" in str(excinfo.value).lower()
        assert not canal_datos.operaciones_ejecutadas
