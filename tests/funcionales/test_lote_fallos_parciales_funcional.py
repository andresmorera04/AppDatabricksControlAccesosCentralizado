"""Prueba funcional de lotes con fallos parciales.

Change `grants-batch` (C5), capability `batch-grant-operations` (spec -
"Resultados parciales por ítem"): un lote 1 a N con un objeto inexistente entre
objetos existentes termina parcial (otorgados + fallidos) con el reporte
consolidado correcto; un lote N a 1 con un principal inexistente reporta solo
sus ítems como fallidos; un ítem sin privilegio efectivo del llamante se bloquea
`privilegios_insuficientes` sin llegar a la sesión; un ítem incompatible no
produce sentencia alguna en la sesión.

Change `grants-uc-externos` (C6), capability `uc-external-object-grants` (spec -
"Cardinalidades 1 a 1, 1 a N y N a 1"): los lotes sobre external locations y
connections se normalizan a ítems atómicos con resultados parciales por ítem y
reporte consolidado, y la cardinalidad N a M se rechaza sin ejecutar instrucción
alguna (design D5: el pipeline y la normalización de C5 se reutilizan sin
cambios; solo el canal SQL admite los dos tipos nuevos).

Usa los canales simulados (patrones de C4) que imitan las respuestas reales del
workspace: `SCHEMA_OR_OBJECT_NOT_FOUND` para objetos inexistentes,
`PERMISSION_DENIED` para privilegios insuficientes. Los casos de C6 sobre el
canal SQL real (`CanalSqlDatos`) usan una sesión simulada que imita las filas de
`SHOW GRANT` y los códigos reales del motor.
"""

import pytest

from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
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


# --- Lotes sobre objetos externos (spec `uc-external-object-grants`, C6) ----


class SesionSqlImitadaLote:
    """Sesión SQL que imita al motor real para los lotes de objetos externos.

    Registra las sentencias recibidas y responde de forma determinista: para
    `SHOW GRANT` devuelve las filas configuradas por objeto; para `GRANT`/
    `REVOKE` lanza el error configurado por prefijo o registra el éxito.

    Attributes:
        sentencias_ejecutadas (list[str]): todas las sentencias recibidas.
    """

    def __init__(self):
        self.sentencias_ejecutadas = []
        self._filas_show_grant = {}
        self._errores_por_prefijo = []

    def ConfigurarShowGrant(self, objeto, filas):
        """Fija las filas que SHOW GRANT devuelve para el objeto.

        Args:
            objeto (ObjetoSecurable): objeto externo consultado.
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


def _CrearExternalLocation(identificador):
    """Construye una external location de prueba (nombre simple)."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.EXTERNAL_LOCATION
    )


def _CrearConnection(identificador="conexion_sqlserver_pruebas"):
    """Construye una connection de Unity Catalog de prueba."""
    return ObjetoSecurable(identificador=identificador, tipo=TipoObjeto.CONNECTION)


class TestLoteObjetosExternos:
    """Verifica las cardinalidades 1 a N y N a 1 sobre objetos externos (C6)."""

    def TestLote1aNSobreExternalLocationsConResultadosParciales(self):
        """Un lote 1 a N sobre external locations reporta resultados parciales.

        WHEN un principal recibe dos privilegios sobre dos external locations y
        una de ellas no existe THEN cada combinación privilegio-objeto es un
        ítem atómico con su resultado parcial: los de la location existente se
        otorgan y los de la inexistente quedan fallidos.
        """
        principal = _CrearPrincipal()
        location_ok = _CrearExternalLocation("ubicacion_pruebas_ok")
        location_inexistente = _CrearExternalLocation("ubicacion_pruebas_inexistente")
        privilegios = ["READ FILES", "WRITE FILES"]

        canal_datos = CanalDatosSimulado()
        lote = SolicitudLoteGrant(
            principales=[principal],
            privilegios=privilegios,
            objetos=[location_ok, location_inexistente],
        )
        for item in lote.NormalizarAItems():
            if item.objeto.identificador == location_inexistente.identificador:
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )

        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=CanalControlSimulado()
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=privilegios,
            objetos=[location_ok, location_inexistente],
        )

        # 4 ítems (2 privilegios x 2 objetos): 2 otorgados, 2 fallidos.
        assert len(resultado.lineas) == 4
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in resultado.lineas if l.estado is EstadoItem.FALLIDO]
        assert len(otorgados) == 2
        assert len(fallidos) == 2
        assert all(
            linea.item.objeto.identificador == location_ok.identificador
            for linea in otorgados
        )
        assert all(
            linea.item.objeto.identificador == location_inexistente.identificador
            for linea in fallidos
        )

    def TestLoteNa1SobreConnectionConResultadosParciales(self):
        """Un lote N a 1 sobre una connection reporta resultados parciales.

        WHEN tres principals reciben `USE CONNECTION` sobre una misma connection
        y uno de ellos no existe THEN cada combinación principal-privilegio es un
        ítem atómico: los de los principals existentes se otorgan y los del
        inexistente quedan fallidos.
        """
        principal_ok1 = _CrearPrincipal("user1@example.com")
        principal_ok2 = _CrearPrincipal("user2@example.com")
        principal_inexistente = _CrearPrincipal("inexistente@example.com")
        connection = _CrearConnection()

        canal_datos = CanalDatosSimulado()
        lote = SolicitudLoteGrant(
            principales=[principal_ok1, principal_inexistente, principal_ok2],
            privilegios=["USE CONNECTION"],
            objetos=[connection],
        )
        for item in lote.NormalizarAItems():
            if item.principal.identificador == "inexistente@example.com":
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )

        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=CanalControlSimulado()
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal_ok1, principal_inexistente, principal_ok2],
            privilegios=["USE CONNECTION"],
            objetos=[connection],
        )

        # 3 ítems (3 principals x 1 privilegio): 2 otorgados, 1 fallido.
        assert len(resultado.lineas) == 3
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in resultado.lineas if l.estado is EstadoItem.FALLIDO]
        assert len(otorgados) == 2
        assert len(fallidos) == 1
        assert fallidos[0].item.principal.identificador == "inexistente@example.com"

    def TestLoteNaMSobreObjetosExternosSeRechazaSinEjecutar(self):
        """La cardinalidad N a M sobre objetos externos se rechaza sin ejecutar.

        WHEN una solicitud declara varios principals y varias external locations
        THEN se rechaza con el mensaje explícito de cardinalidad N a M no
        soportada y no se ejecuta instrucción alguna.
        """
        principales = [_CrearPrincipal("user1@example.com"), _CrearPrincipal()]
        objetos = [
            _CrearExternalLocation("ubicacion_pruebas_1"),
            _CrearExternalLocation("ubicacion_pruebas_2"),
        ]

        canal_datos = CanalDatosSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos, canal_control=CanalControlSimulado()
        )

        with pytest.raises(ErrorDominio) as error:
            pipeline.ProcesarLoteDesdeEntradas(
                principales=principales,
                privilegios=["READ FILES"],
                objetos=objetos,
            )

        assert "N a M" in str(error.value)
        assert "fuera de alcance" in str(error.value)
        assert not canal_datos.operaciones_ejecutadas, (
            "El rechazo de la cardinalidad ocurre antes de cualquier ejecución"
        )

    def TestReporteConsolidadoDeLoteSobreExternalLocations(self, sesion_spark):
        """El lote sobre external locations se consolida con totales por estado.

        Con la sesión Spark inyectada, el reporte del lote expone `total_items`
        y `totales_por_estado` agregados con funciones masivas de PySpark
        (design D3 de C5), igual que para los objetos de C4.
        """
        principal = _CrearPrincipal()
        location_ok = _CrearExternalLocation("ubicacion_consolidada_ok")
        location_inexistente = _CrearExternalLocation("ubicacion_consolidada_mala")
        privilegios = ["READ FILES", "WRITE FILES"]

        canal_datos = CanalDatosSimulado()
        lote = SolicitudLoteGrant(
            principales=[principal],
            privilegios=privilegios,
            objetos=[location_ok, location_inexistente],
        )
        for item in lote.NormalizarAItems():
            if item.objeto.identificador == location_inexistente.identificador:
                canal_datos.ConfigurarEscenario(
                    item, EscenarioSimulacion.OBJETO_INEXISTENTE
                )

        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=CanalControlSimulado(),
            sesion_spark=sesion_spark,
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=privilegios,
            objetos=[location_ok, location_inexistente],
        )

        assert resultado.total_items == 4
        assert resultado.totales_por_estado[EstadoItem.OTORGADO] == 2
        assert resultado.totales_por_estado[EstadoItem.FALLIDO] == 2

    def TestLote1aNConCanalSqlRealConstruyeInstruccionesDeExternalLocation(self):
        """El lote sobre external locations usa el canal SQL real de producción.

        Design D5: la normalización de C5 y el pre-flight de C3 se reutilizan sin
        cambios; al admitir el canal los tipos externos, cada ítem del lote se
        ejecuta con su instrucción `GRANT ... ON EXTERNAL LOCATION ...` y se
        verifica con `SHOW GRANT` sobre la propia location.
        """
        principal = _CrearPrincipal()
        location_1 = _CrearExternalLocation("ubicacion_lote_1")
        location_2 = _CrearExternalLocation("ubicacion_lote_2")
        privilegios = ["READ FILES", "WRITE FILES"]

        sesion = SesionSqlImitadaLote()
        for location in (location_1, location_2):
            # Las filas de SHOW GRANT se configuran en una sola llamada por
            # objeto: cada configuración sustituye las filas anteriores del
            # mismo objeto, igual que una consulta real devuelve todas sus filas.
            sesion.ConfigurarShowGrant(
                location,
                [
                    [
                        principal.identificador,
                        privilegio,
                        "EXTERNAL LOCATION",
                        location.identificador,
                    ]
                    for privilegio in privilegios
                ],
            )
        # WRITE FILES falla sobre la segunda location: resultado parcial.
        sesion.ConfigurarErrorEn(
            "GRANT WRITE FILES ON EXTERNAL LOCATION `ubicacion_lote_2`",
            RuntimeError(
                "[PERMISSION_DENIED] El ejecutor no puede otorgar WRITE FILES."
            ),
        )

        pipeline = PipelineGrants(
            canal_datos=CanalSqlDatos(sesion),
            canal_control=CanalControlSimulado(),
        )
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=privilegios,
            objetos=[location_1, location_2],
        )

        assert len(resultado.lineas) == 4
        estados = [linea.estado for linea in resultado.lineas]
        assert estados.count(EstadoItem.OTORGADO) == 3
        assert estados.count(EstadoItem.PRIVILEGIOS_INSUFICIENTES) == 1
        # Las cuatro instrucciones del lote usan la palabra clave de dos tokens.
        escrituras = sesion.SentenciasDeEscritura()
        assert len(escrituras) == 4
        assert all("ON EXTERNAL LOCATION `" in sentencia for sentencia in escrituras)
        assert (
            "GRANT READ FILES ON EXTERNAL LOCATION `ubicacion_lote_1` TO "
            f"`{principal.identificador}`" in escrituras
        )
