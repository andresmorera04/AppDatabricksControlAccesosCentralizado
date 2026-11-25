"""Pruebas de aceptación de la capability `uc-data-object-grants`.

Trazabilidad 1:1 con los escenarios del spec delta
`openspec/changes/grants-uc-datos/specs/uc-data-object-grants/spec.md`:

- Instrucción de otorgamiento por tipo de objeto:
  - Grant sobre un catálogo -> TestEscenarioGrantSobreCatalogo
  - Grant sobre un esquema calificado -> TestEscenarioGrantSobreEsquemaCalificado
  - Grant sobre una tabla delta calificada -> TestEscenarioGrantSobreTablaDeltaCalificada
  - Grant sobre un volumen -> TestEscenarioGrantSobreVolumen
  - Grant sobre un modelo de ML -> TestEscenarioGrantSobreModeloMl
  - ST, vista materializada y vista SQL comparten TABLE
    -> TestEscenarioStreamingVistaMaterializadaYVistaSqlUsanTable
- Instrucción de revocación por tipo de objeto:
  - Revocación sobre una tabla delta -> TestEscenarioRevocacionSobreTablaDelta
- Ejecución de instrucciones por una sesión SQL inyectada:
  - Instrucción enviada a la sesión inyectada -> TestEscenarioInstruccionEnviadaALaSesion
  - Canal ejercitado sin workspace -> TestEscenarioCanalEjercitadoSinWorkspace
- Errores del workspace traducidos a mensajes específicos por caso:
  - Permiso denegado al otorgar -> TestEscenarioPermisoDenegadoAlOtorgar
  - Objeto inexistente -> TestEscenarioObjetoInexistente
  - Principal inexistente -> TestEscenarioPrincipalInexistente
  - Cualquier otro fallo de la sesión -> TestEscenarioOtroFalloDeSesion
- Verificación posterior al grant con SHOW GRANTS:
  - Grant confirmado -> TestEscenarioGrantConfirmadoPorLaVerificacion
  - Grant no confirmado -> TestEscenarioGrantNoConfirmado
  - Filas traducidas a otorgamientos -> TestEscenarioFilasTraducidasAOtorgamientos
- Vertical slice de punta a punta con el canal SQL real:
  - Solicitud otorgada de punta a punta -> TestEscenarioSolicitudOtorgadaDePuntaAPunta
  - Ítem incompatible bloqueado antes de ejecutar
    -> TestEscenarioItemIncompatibleBloqueadoAntesDeEjecutar
  - Ítem sin privilegio efectivo del llamante
    -> TestEscenarioItemSinPrivilegioEfectivoDelLlamante
  - Fallo puntual no aborta la solicitud -> TestEscenarioFalloPuntualNoAborta
- Objetos fuera del alcance de este change (requisito modificado por el change
  `grants-uc-externos`, C6: el canal SQL soporta los diez tipos del plano de
  datos y solo el plano de control queda fuera):
  - External location y connection soportadas por el canal SQL
    -> TestEscenarioExternalLocationYConnectionSoportadas
  - Objeto del plano de control fuera del canal
    -> TestEscenarioObjetoDeControlFueraDelCanal
- Pruebas integrales autocontenidas sobre andresFree:
  - Fixtures creadas y destruidas por la propia prueba
    -> TestEscenarioFixturesCreadasYDestruidas
  - Sin dependencia del workspace de respaldo -> TestEscenarioSinWorkspaceDeRespaldo

Todo con el canal real sobre una sesión SQL simulada (y, donde aplica, identidad y
resolutor simulados): ninguna escritura llega a un workspace real.
"""

import sys
from pathlib import Path

# La fábrica de fixtures vive en la capa integral (no es un paquete); se agrega
# su directorio al sys.path para ejercitar su contrato de creación/limpieza en
# los escenarios de integrales autocontenidas (mismo criterio que conftest.py).
RAIZ_PRUEBAS = Path(__file__).resolve().parents[1]
if str(RAIZ_PRUEBAS / "integrales") not in sys.path:
    sys.path.insert(0, str(RAIZ_PRUEBAS / "integrales"))

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import ErrorCanal
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
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

from fixtures_uc_datos import FixturesUcDatos

# Objetos de prueba del plano de datos.
CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
ESQUEMA = ObjetoSecurable(
    identificador="control.finanzas", tipo=TipoObjeto.ESQUEMA
)
TABLA = ObjetoSecurable(
    identificador="control.prod.ventas", tipo=TipoObjeto.TABLA_DELTA
)
VOLUMEN = ObjetoSecurable(
    identificador="control.datos.raw", tipo=TipoObjeto.VOLUMEN
)
MODELO = ObjetoSecurable(
    identificador="control.ml.modelo_ventas", tipo=TipoObjeto.MODELO_ML
)

# Beneficiario de los ítems, con forma de correo (como reporta Unity Catalog).
BENEFICIARIO = "beneficiario@example.com"


class ErrorMotorSql(RuntimeError):
    """Excepción con la forma del error que reporta el motor SQL real."""


class SesionSqlDoble:
    """Sesión SQL que imita al motor real (filas de SHOW GRANT y errores)."""

    def __init__(self):
        self.sentencias = []
        self._filas_show_grant = {}
        self._errores_por_prefijo = []

    def ConfigurarShowGrant(self, objeto, filas):
        """Fija las filas de SHOW GRANT para el objeto."""
        self._filas_show_grant[CanalSqlDatos.ConstruirShowGrant(objeto)] = (
            list(filas)
        )

    def ConfigurarErrorEn(self, prefijo, error):
        """Configura un error para las sentencias que empiezan por el prefijo."""
        self._errores_por_prefijo.append((prefijo, error))

    def sql(self, sentencia):
        """Registra la sentencia y responde según la configuración."""
        self.sentencias.append(sentencia)
        for prefijo, error in self._errores_por_prefijo:
            if sentencia.startswith(prefijo):
                raise error
        if sentencia.startswith("SHOW GRANT"):
            return list(self._filas_show_grant.get(sentencia, []))
        return []

    def SentenciasDeEscritura(self):
        """Devuelve las sentencias GRANT/REVOKE (sin SHOW GRANT)."""
        return [s for s in self.sentencias if not s.startswith("SHOW GRANT")]


def CrearItem(privilegio, objeto=TABLA, principal=BENEFICIARIO):
    """Construye un ítem de solicitud de prueba."""
    return ItemGrant(
        principal=Principal(
            identificador=principal, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def IdentidadUsuario():
    """Resuelve la identidad simulada del usuario llamante."""
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def Fila(principal, privilegio, tipo_palabra="TABLE", clave=TABLA.identificador):
    """Construye una fila de SHOW GRANT."""
    return [principal, privilegio, tipo_palabra, clave]


# --- Instrucción de otorgamiento por tipo de objeto ------------------------


def TestEscenarioGrantSobreCatalogo():
    """Escenario: Grant sobre un catálogo.

    WHEN un ítem otorga un privilegio sobre un catálogo de nombre simple
    THEN la instrucción usa la palabra clave CATALOG con ese nombre simple.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("USE CATALOG", objeto=CATALOGO)
    )
    assert sentencia == "GRANT USE CATALOG ON CATALOG `control` TO `beneficiario@example.com`"


def TestEscenarioGrantSobreEsquemaCalificado():
    """Escenario: Grant sobre un esquema calificado.

    WHEN un ítem otorga un privilegio sobre un esquema `catalogo.esquema`
    THEN la instrucción usa SCHEMA y conserva las dos partes calificadas.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("USE SCHEMA", objeto=ESQUEMA)
    )
    assert sentencia == (
        "GRANT USE SCHEMA ON SCHEMA `control`.`finanzas` TO `beneficiario@example.com`"
    )


def TestEscenarioGrantSobreTablaDeltaCalificada():
    """Escenario: Grant sobre una tabla delta calificada.

    WHEN un ítem otorga sobre una tabla `catalogo.esquema.tabla`
    THEN la instrucción usa TABLE y conserva las tres partes calificadas.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("SELECT", objeto=TABLA)
    )
    assert sentencia == (
        "GRANT SELECT ON TABLE `control`.`prod`.`ventas` TO `beneficiario@example.com`"
    )


def TestEscenarioGrantSobreVolumen():
    """Escenario: Grant sobre un volumen.

    WHEN un ítem otorga un privilegio sobre un volumen
    THEN la instrucción usa la palabra clave VOLUME.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("READ VOLUME", objeto=VOLUMEN)
    )
    assert sentencia == (
        "GRANT READ VOLUME ON VOLUME `control`.`datos`.`raw` "
        "TO `beneficiario@example.com`"
    )


def TestEscenarioGrantSobreModeloMl():
    """Escenario: Grant sobre un modelo de ML.

    WHEN un ítem otorga un privilegio sobre un modelo de ML
    THEN la instrucción usa la palabra clave MODEL.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
        CrearItem("EXECUTE", objeto=MODELO)
    )
    assert sentencia == (
        "GRANT EXECUTE ON MODEL `control`.`ml`.`modelo_ventas` "
        "TO `beneficiario@example.com`"
    )


def TestEscenarioStreamingVistaMaterializadaYVistaSqlUsanTable():
    """Escenario: ST, vista materializada y vista SQL comparten TABLE.

    WHEN un ítem otorga sobre una streaming table, una vista materializada o
         una vista SQL
    THEN la instrucción usa la palabra clave TABLE, igual que una tabla delta.
    """
    casos = (
        (TipoObjeto.STREAMING_TABLE, "control.prod.st_ventas"),
        (TipoObjeto.VISTA_MATERIALIZADA, "control.prod.mv_ventas"),
        (TipoObjeto.VISTA_SQL, "control.prod.v_ventas"),
    )
    for tipo, identificador in casos:
        objeto = ObjetoSecurable(identificador=identificador, tipo=tipo)
        sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
            CrearItem("SELECT", objeto=objeto)
        )
        assert " ON TABLE " in sentencia


# --- Instrucción de revocación por tipo de objeto ---------------------------


def TestEscenarioRevocacionSobreTablaDelta():
    """Escenario: Revocación sobre una tabla delta.

    WHEN se revoca un privilegio sobre una tabla delta
    THEN la instrucción usa FROM, la palabra clave TABLE y el nombre calificado.
    """
    sentencia = CanalSqlDatos.ConstruirSentenciaRevocacion(
        CrearItem("SELECT", objeto=TABLA)
    )
    assert sentencia == (
        "REVOKE SELECT ON TABLE `control`.`prod`.`ventas` "
        "FROM `beneficiario@example.com`"
    )


# --- Ejecución por una sesión SQL inyectada ---------------------------------


def TestEscenarioInstruccionEnviadaALaSesion():
    """Escenario: Instrucción enviada a la sesión inyectada.

    WHEN el canal ejecuta el otorgamiento de un ítem
    THEN la instrucción construida se envía tal cual a la sesión inyectada.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)
    item = CrearItem("SELECT")

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert sesion.sentencias == [CanalSqlDatos.ConstruirSentenciaOtorgamiento(item)]


def TestEscenarioCanalEjercitadoSinWorkspace():
    """Escenario: Canal ejercitado sin workspace.

    WHEN el canal se construye con una sesión simulada
    THEN el otorgamiento y la revocación se procesan sin conexión externa.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)

    assert canal.Otorgar(CrearItem("SELECT")).estado is EstadoItem.OTORGADO
    assert canal.Revocar(CrearItem("SELECT")).estado is EstadoItem.OTORGADO
    assert len(sesion.sentencias) == 2, "Solo interactúa con la sesión simulada"


# --- Errores del workspace traducidos a mensajes específicos ----------------


def TestEscenarioPermisoDenegadoAlOtorgar():
    """Escenario: Permiso denegado al otorgar.

    WHEN el workspace responde permiso denegado
    THEN el ítem es `privilegios_insuficientes` e identifica privilegio y objeto.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT", ErrorMotorSql("[PERMISSION_DENIED] Denegado para el ejecutor.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("SELECT"))

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "SELECT" in resultado.detalle
    assert "control.prod.ventas" in resultado.detalle


def TestEscenarioObjetoInexistente():
    """Escenario: Objeto inexistente.

    WHEN la instrucción falla porque el objeto no existe
    THEN el ítem es `fallido` con un mensaje que identifica el objeto.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT", ErrorMotorSql("[SCHEMA_OR_OBJECT_NOT_FOUND] No existe.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("SELECT"))

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert "control.prod.ventas" in resultado.detalle


def TestEscenarioPrincipalInexistente():
    """Escenario: Principal inexistente.

    WHEN la instrucción falla porque el principal no existe
    THEN el ítem es `fallido` con un mensaje que identifica el principal.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT", ErrorMotorSql("[PRINCIPAL_NOT_FOUND] No existe el principal.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("SELECT"))

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle
    assert BENEFICIARIO in resultado.detalle


def TestEscenarioOtroFalloDeSesion():
    """Escenario: Cualquier otro fallo de la sesión.

    WHEN la sesión falla por una causa distinta (transporte)
    THEN el ítem es `fallido` con el detalle y sin marca de privilegios.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarErrorEn(
        "GRANT", ErrorMotorSql("Fallo de transporte: timeout.")
    )
    canal = CanalSqlDatos(sesion)

    resultado = canal.Otorgar(CrearItem("SELECT"))

    assert resultado.estado is EstadoItem.FALLIDO
    assert "timeout" in resultado.detalle
    assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES


# --- Verificación posterior al grant con SHOW GRANTS ------------------------


def TestEscenarioGrantConfirmadoPorLaVerificacion():
    """Escenario: Grant confirmado por la verificación.

    WHEN un otorgamiento exitoso aparece en los grants vigentes
    THEN el ítem se reporta `otorgado`.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(TABLA, [Fila(BENEFICIARIO, "SELECT")])
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto=TABLA,
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO


def TestEscenarioGrantNoConfirmado():
    """Escenario: Grant no confirmado por la verificación.

    WHEN un otorgamiento ejecutado no aparece en los grants vigentes
    THEN el ítem es `fallido` con un detalle que menciona privilegio, principal
         y objeto.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(TABLA, [])  # la verificación no lo encuentra
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto=TABLA,
        )
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "SELECT" in linea.detalle
    assert BENEFICIARIO in linea.detalle


def TestEscenarioFilasTraducidasAOtorgamientos():
    """Escenario: Filas de SHOW GRANTS traducidas a otorgamientos.

    WHEN la consulta devuelve una fila por cada otorgamiento
    THEN cada fila se traduce a un otorgamiento con otorgatario y privilegio.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        TABLA,
        [
            Fila(BENEFICIARIO, "SELECT"),
            Fila("grupo_analistas", "MODIFY"),
        ],
    )
    canal = CanalSqlDatos(sesion)

    grants = canal.ListarGrantsVigentes(TABLA)

    assert len(grants) == 2
    assert grants[0].principal.identificador == BENEFICIARIO
    assert grants[0].privilegio == "SELECT"
    assert grants[1].principal.tipo is TipoPrincipal.GRUPO


# --- Vertical slice de punta a punta ----------------------------------------


def TestEscenarioSolicitudOtorgadaDePuntaAPunta():
    """Escenario: Solicitud otorgada de punta a punta.

    WHEN un llamante con privilegios suficientes procesa una solicitud válida
    THEN cada ítem se otorga y verifica, pasando por GRANT y SHOW GRANT.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        TABLA, [Fila(BENEFICIARIO, "SELECT"), Fila(BENEFICIARIO, "MODIFY")]
    )
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT", "MODIFY"],
            objeto=TABLA,
        )
    )

    assert all(linea.estado is EstadoItem.OTORGADO for linea in reporte.lineas)
    assert len(sesion.SentenciasDeEscritura()) == 2
    assert any(s.startswith("SHOW GRANT") for s in sesion.sentencias)


def TestEscenarioItemIncompatibleBloqueadoAntesDeEjecutar():
    """Escenario: Ítem incompatible bloqueado antes de ejecutar.

    WHEN la solicitud incluye un privilegio inválido para el tipo de objeto
    THEN el ítem se bloquea en pre-flight y no se ejecuta instrucción alguna.
    """
    sesion = SesionSqlDoble()
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["CAN_USE"],
            objeto=TABLA,
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert sesion.sentencias == []


def TestEscenarioItemSinPrivilegioEfectivoDelLlamante():
    """Escenario: Ítem sin privilegio efectivo del llamante.

    WHEN el llamante no tiene el privilegio autorizador sobre el objeto
    THEN el ítem se bloquea `privilegios_insuficientes` sin ejecutar instrucción.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(
        TABLA, [Fila(IDENTIFICADOR_USUARIO_DEMO, "SELECT")]
    )
    canal = CanalSqlDatos(sesion)
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal, canal_control=canal_control
        ),
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["MODIFY"],
            objeto=TABLA,
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert sesion.SentenciasDeEscritura() == []


def TestEscenarioFalloPuntualNoAborta():
    """Escenario: Fallo puntual no aborta la solicitud.

    WHEN de varios ítems ejecutables uno falla durante la ejecución
    THEN los demás se otorgan y se reportan, sin cancelar la operación.
    """
    sesion = SesionSqlDoble()
    sesion.ConfigurarShowGrant(TABLA, [Fila(BENEFICIARIO, "SELECT")])
    sesion.ConfigurarErrorEn(
        "GRANT MODIFY",
        ErrorMotorSql("[SCHEMA_OR_OBJECT_NOT_FOUND] No existe."),
    )
    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT", "MODIFY"],
            objeto=TABLA,
        )
    )

    estados = {linea.item.privilegio: linea.estado for linea in reporte.lineas}
    assert estados["SELECT"] is EstadoItem.OTORGADO
    assert estados["MODIFY"] is EstadoItem.FALLIDO


# --- Objetos fuera del alcance de este change -------------------------------


def TestEscenarioExternalLocationYConnectionSoportadas():
    """Escenario: External location y connection soportadas por el canal SQL.

    Requisito modificado por el change `grants-uc-externos` (C6):

    WHEN llega al canal un ítem sobre una external location o una connection
    THEN se procesa con la palabra clave SQL de su tipo, sin rechazo.
    """
    casos = (
        (TipoObjeto.EXTERNAL_LOCATION, "ruta_externa", "EXTERNAL LOCATION"),
        (TipoObjeto.CONNECTION, "conexion_lakehouse", "CONNECTION"),
    )
    for tipo, nombre, palabra_clave in casos:
        objeto = ObjetoSecurable(identificador=nombre, tipo=tipo)
        sentencia = CanalSqlDatos.ConstruirSentenciaOtorgamiento(
            CrearItem("ALL PRIVILEGES", objeto=objeto)
        )
        assert f"ON {palabra_clave} `{nombre}`" in sentencia


def TestEscenarioObjetoDeControlFueraDelCanal():
    """Escenario: Objeto del plano de control fuera de este canal.

    WHEN llega al canal SQL un ítem cuyo objeto pertenece al plano de control
    THEN se rechaza con error controlado y no se ejecuta instrucción alguna.
    """
    objeto = ObjetoSecurable(
        identificador="a1b2c3d4", tipo=TipoObjeto.COMPUTO_CLASICO
    )
    with pytest.raises(ErrorCanal):
        CanalSqlDatos.ConstruirSentenciaOtorgamiento(
            CrearItem("CAN_MANAGE", objeto=objeto)
        )


# --- Pruebas integrales autocontenidas sobre andresFree ---------------------


def TestEscenarioFixturesCreadasYDestruidas():
    """Escenario: Fixtures creadas y destruidas por la propia prueba.

    WHEN corre la fábrica de fixtures integrales
    THEN crea su catálogo/esquema/objetos con nombre único y, al limpiar,
         emite DROP CATALOG ... CASCADE que arrastra todo sin dejar residuo.
    """
    sesion = SesionSqlDoble()
    fixtures = FixturesUcDatos(sesion)

    fixtures.Crear()

    sentencias_creacion = "\n".join(sesion.sentencias)
    assert f"CREATE CATALOG `{fixtures.catalogo}`" in sentencias_creacion
    assert "CREATE SCHEMA" in sentencias_creacion
    assert "CREATE TABLE" in sentencias_creacion

    fixtures.Limpiar()

    assert f"DROP CATALOG IF EXISTS `{fixtures.catalogo}` CASCADE" in (
        sesion.sentencias[-1]
    )


def TestEscenarioSinWorkspaceDeRespaldo():
    """Escenario: Sin dependencia del workspace de respaldo.

    WHEN corre la suite integral de este change, la fábrica solo opera a través
         de la sesión inyectada
    THEN ninguna instrucción ni atributo depende del workspace de respaldo
         (`andresAzureDev`).
    """
    sesion = SesionSqlDoble()
    fixtures = FixturesUcDatos(sesion)

    fixtures.Crear()
    fixtures.Limpiar()

    assert all(
        "azur" not in sentencia.lower() for sentencia in sesion.sentencias
    ), "La fábrica no menciona ningún workspace de respaldo"
    assert isinstance(fixtures.catalogo, str) and fixtures.catalogo
