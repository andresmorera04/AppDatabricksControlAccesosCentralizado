"""Prueba funcional de lotes con fallos parciales.

Change `grants-batch` (C5), capability `batch-grant-operations` (spec -
"Resultados parciales por ítem"): un lote 1 a N con un objeto inexistente entre
objetos existentes termina parcial (otorgados + fallidos) con el reporte
consolidado correcto; un lote N a 1 con un principal inexistente reporta solo
sus ítems como fallidos; un ítem sin privilegio efectivo del llamante se bloquea
`privilegios_insuficientes` sin llegar a la sesión; un ítem incompatible no
produce sentencia alguna en la sesión.

Usa los canales simulados (patrones de C4) que imitan las respuestas reales del
workspace: `SCHEMA_OR_OBJECT_NOT_FOUND` para objetos inexistentes,
`PERMISSION_DENIED` para privilegios insuficientes.
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.modelos import PrivilegiosEfectivosVista


class IdentidadLlamanteFalsa:
    """Doble de `IdentidadLlamante` con el atributo `usuario_bitacora`."""

    def __init__(self, usuario):
        self.usuario_bitacora = usuario


class ResolutorFalso:
    """Resolutor de privilegios efectivos que devuelve una vista vacía."""

    def ResolverPrivilegiosEfectivos(self, identidad, objeto):
        """Devuelve una vista de privilegios efectivos vacía (sin otorgamientos)."""
        return PrivilegiosEfectivosVista(
            objeto=objeto,
            plano=objeto.plano,
            canal_consultado="datos" if objeto.plano.value == "datos" else "control",
            otorgamientos=tuple(),
        )


def _CrearPrincipal(email="user@example.com"):
    """Construye un principal de prueba."""
    return Principal(identificador=email, tipo="usuario")


def _CrearObjetoTabla(identificador="catalogo1.schema1.tabla1"):
    """Construye un objeto de prueba del plano de datos."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.TABLA_DELTA
    )


class TestLoteFallosParciales:
    """Verifica los resultados parciales por ítem en lotes con fallos."""

    def TestLote1aNConObjetoInexistenteTerminaParcial(self):
        """Un lote 1 a N con un objeto inexistente termina parcial.

        WHEN un lote 1 a N incluye objetos existentes y uno inexistente THEN
        los ítems de los objetos existentes se otorgan y los del inexistente
        quedan fallidos, con el reporte consolidado correcto.
        """
        principal = _CrearPrincipal()
        objeto_ok1 = _CrearObjetoTabla("catalogo1.schema1.tabla_ok1")
        objeto_ok2 = _CrearObjetoTabla("catalogo1.schema1.tabla_ok2")
        objeto_inexistente = _CrearObjetoTabla("catalogo1.schema1.tabla_inexistente")

        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()

        # Configurar el objeto inexistente para fallar.
        lote = SolicitudLoteGrant(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto_ok1, objeto_inexistente, objeto_ok2],
        )
        for item in lote.NormalizarAItems():
            if item.objeto.identificador == "catalogo1.schema1.tabla_inexistente":
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )

        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto_ok1, objeto_inexistente, objeto_ok2],
        )

        # 3 ítems: 2 otorgados, 1 fallido.
        assert len(resultado.lineas) == 3
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in resultado.lineas if l.estado is EstadoItem.FALLIDO]
        assert len(otorgados) == 2
        assert len(fallidos) == 1
        # El ítem fallido es del objeto inexistente.
        assert fallidos[0].item.objeto.identificador == "catalogo1.schema1.tabla_inexistente"

    def TestLoteNa1ConPrincipalInexistenteReportaSoloSusItemsComoFallidos(self):
        """Un lote N a 1 con un principal inexistente reporta solo sus ítems como fallidos.

        WHEN un lote N a 1 incluye principals existentes y uno inexistente THEN
        los ítems del principal inexistente quedan fallidos y los demás se
        otorgan.
        """
        principal_ok1 = _CrearPrincipal("user1@example.com")
        principal_ok2 = _CrearPrincipal("user2@example.com")
        principal_inexistente = _CrearPrincipal("inexistente@example.com")
        objeto = _CrearObjetoTabla()

        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()

        # Configurar el principal inexistente para fallar.
        lote = SolicitudLoteGrant(
            principales=[principal_ok1, principal_inexistente, principal_ok2],
            privilegios=["SELECT"],
            objetos=[objeto],
        )
        for item in lote.NormalizarAItems():
            if item.principal.identificador == "inexistente@example.com":
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )

        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=canal_control
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal_ok1, principal_inexistente, principal_ok2],
            privilegios=["SELECT"],
            objetos=[objeto],
        )

        # 3 ítems: 2 otorgados, 1 fallido.
        assert len(resultado.lineas) == 3
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in resultado.lineas if l.estado is EstadoItem.FALLIDO]
        assert len(otorgados) == 2
        assert len(fallidos) == 1
        # El ítem fallido es del principal inexistente.
        assert fallidos[0].item.principal.identificador == "inexistente@example.com"

    def TestItemSinPrivilegioEfectivoSeBloqueaSinLlegarALaSesion(self):
        """Un ítem sin privilegio efectivo del llamante se bloquea sin llegar a la sesión.

        WHEN el llamante carece del privilegio autorizador sobre un objeto THEN
        el ítem se bloquea con `privilegios_insuficientes` y no se ejecuta
        ninguna sentencia en la sesión.
        """
        principal = _CrearPrincipal()
        objeto = _CrearObjetoTabla()
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
            principales=[principal],
            privilegios=["SELECT"],
            objetos=[objeto],
        )

        # El ítem se bloquea con privilegios insuficientes.
        assert len(resultado.lineas) == 1
        assert resultado.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
        # No se ejecutó ninguna sentencia en la sesión.
        assert not canal_datos.operaciones_ejecutadas

    def TestItemIncompatibleNoProduceSentenciaAlgunaEnLaSesion(self):
        """Un ítem incompatible no produce sentencia alguna en la sesión.

        WHEN un ítem tiene un privilegio inválido para el tipo de su objeto THEN
        se bloquea en pre-flight y no se ejecuta ninguna sentencia en la sesión.
        """
        principal = _CrearPrincipal()
        # INSERT no es válido para COMPUTO_CLASICO (plano de control).
        objeto_control = ObjetoSecurable(
            identificador="cluster-abc123", tipo=TipoObjeto.COMPUTO_CLASICO
        )

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
        # No se ejecutó ninguna sentencia en la sesión.
        assert not canal_control.operaciones_ejecutadas
