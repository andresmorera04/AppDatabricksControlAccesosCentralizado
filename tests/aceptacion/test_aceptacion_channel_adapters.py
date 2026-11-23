"""Pruebas de aceptación del capability `channel-adapters`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/specs/channel-adapters/spec.md`:

- Contrato unificado de ejecución por canal:
  - Otorgamiento exitoso por contrato
    -> TestEscenarioOtorgamientoExitosoPorContrato
  - Fallo reportado por contrato -> TestEscenarioFalloReportadoPorContrato
- Canal SQL para el plano de datos:
  - Instrucción de otorgamiento SQL
    -> TestEscenarioInstruccionDeOtorgamientoSql
  - Consulta de grants vigentes -> TestEscenarioConsultaDeGrantsVigentes
- Canal SDK/REST para el plano de control:
  - Permiso sobre objeto del plano de control
    -> TestEscenarioPermisoSobreObjetoDelPlanoDeControl
- Errores de privilegios insuficientes identificables:
  - Permiso denegado del sistema externo
    -> TestEscenarioPermisoDenegadoDelSistemaExterno
  - Error no relacionado con privilegios
    -> TestEscenarioErrorNoRelacionadoConPrivilegios
- Implementaciones simulables para testing:
  - Canal simulado que responde éxito
    -> TestEscenarioCanalSimuladoQueRespondeExito
  - Canal simulado que responde permiso denegado
    -> TestEscenarioCanalSimuladoQueRespondePermisoDenegado
- En este change no se ejecutan operaciones externas reales:
  - Ejecución de grant real fuera de alcance
    -> TestEscenarioEjecucionDeGrantRealFueraDeAlcance

En este change los canales son contratos + implementaciones simuladas: las
instrucciones SQL y las llamadas a la Permissions API reales se verifican en
las pruebas integrales de C4 en adelante (spec: "En este change no se ejecutan
operaciones externas reales").
"""

import sys

from control_accesos.canales.contratos import CanalControl, CanalDatos
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
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants


def CrearItemDeDatos(privilegio="SELECT"):
    """Construye un ítem del plano de datos para las pruebas de aceptación."""
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )


def CrearItemDeControl(privilegio="CAN_USE"):
    """Construye un ítem del plano de control para las pruebas de aceptación."""
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(
            identificador="a1b2c3d4e5f6", tipo=TipoObjeto.SQL_WAREHOUSE
        ),
    )


def TestEscenarioOtorgamientoExitosoPorContrato():
    """Escenario: Otorgamiento exitoso por contrato.

    WHEN un canal recibe un ítem válido y lo otorga sin errores
    THEN el canal devuelve un resultado por ítem con estado `otorgado`.
    """
    canal = CanalDatosSimulado()
    item = CrearItemDeDatos()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert resultado.item == item


def TestEscenarioFalloReportadoPorContrato():
    """Escenario: Fallo reportado por contrato.

    WHEN un canal recibe un ítem válido pero la ejecución falla (por ejemplo,
         el objeto no existe)
    THEN el canal devuelve un resultado por ítem con estado `fallido` y el
         detalle del error, sin propagar la excepción al llamador.
    """
    canal = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.OBJETO_INEXISTENTE
    )

    # No se propaga ninguna excepción al llamador: solo el resultado.
    resultado = canal.Otorgar(CrearItemDeDatos())

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle


def TestEscenarioInstruccionDeOtorgamientoSql():
    """Escenario: Instrucción de otorgamiento SQL.

    WHEN el canal SQL recibe un ítem cuyo objeto pertenece al plano de datos
    THEN el canal construye una instrucción de otorgamiento para ese objeto y
         la ejecuta por su mecanismo SQL.

    En C1 el mecanismo SQL es la implementación simulada (no se ejecutan
    operaciones externas reales); la construcción de la instrucción GRANT real
    se verifica en las pruebas integrales de C4.
    """
    canal = CanalDatosSimulado()
    item = CrearItemDeDatos()

    resultado = canal.Otorgar(item)

    # El ítem pasó por el mecanismo del canal de datos (contrato CanalDatos).
    assert isinstance(canal, CanalDatos)
    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.operaciones_ejecutadas[0].operacion == "otorgar"
    assert canal.operaciones_ejecutadas[0].item == item


def TestEscenarioConsultaDeGrantsVigentes():
    """Escenario: Consulta de grants vigentes.

    WHEN se solicita al canal SQL los grants vigentes de un objeto
    THEN el canal devuelve la lista de grants vigentes del objeto tal como el
         sistema los reporta.
    """
    canal = CanalDatosSimulado()
    item_otorgado = CrearItemDeDatos()
    canal.Otorgar(item_otorgado)

    grants_vigentes = canal.ListarGrantsVigentes(item_otorgado.objeto)

    assert grants_vigentes == [item_otorgado]


def TestEscenarioPermisoSobreObjetoDelPlanoDeControl():
    """Escenario: Permiso sobre objeto del plano de control.

    WHEN el canal SDK o REST recibe un ítem cuyo objeto pertenece al plano de
         control
    THEN el canal otorga el permiso mediante la Permissions API y devuelve el
         resultado por ítem correspondiente.

    En C1 la Permissions API es simulada (spec: sin operaciones externas
    reales); la llamada real se verifica en las pruebas integrales de C7.
    """
    canal = CanalControlSimulado()
    item = CrearItemDeControl()

    resultado = canal.Otorgar(item)

    assert isinstance(canal, CanalControl)
    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(item.objeto) == [item]


def TestEscenarioPermisoDenegadoDelSistemaExterno():
    """Escenario: Permiso denegado del sistema externo.

    WHEN un canal ejecuta un otorgamiento y el sistema externo responde con un
         error de permiso denegado para el ejecutor
    THEN el canal devuelve el resultado del ítem con la marca de privilegios
         insuficientes, distinguible de un fallo genérico.
    """
    canal_denegado = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )
    canal_generico = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    item = CrearItemDeDatos()

    resultado_denegado = canal_denegado.Otorgar(item)
    resultado_generico = canal_generico.Otorgar(item)

    assert resultado_denegado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    # Distinguible del fallo genérico.
    assert resultado_generico.estado is EstadoItem.FALLIDO
    assert resultado_denegado.estado is not resultado_generico.estado


def TestEscenarioErrorNoRelacionadoConPrivilegios():
    """Escenario: Error no relacionado con privilegios.

    WHEN un canal ejecuta un otorgamiento y ocurre un error distinto a permiso
         denegado (por ejemplo, objeto inexistente)
    THEN el canal devuelve el resultado del ítem como `fallido`, sin la marca
         de privilegios insuficientes.
    """
    canal = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.OBJETO_INEXISTENTE
    )

    resultado = canal.Otorgar(CrearItemDeDatos())

    assert resultado.estado is EstadoItem.FALLIDO
    assert resultado.estado is not EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestEscenarioCanalSimuladoQueRespondeExito():
    """Escenario: Canal simulado que responde éxito.

    WHEN el pipeline ejecuta un ítem contra una implementación simulada
         configurada para éxito
    THEN el ítem se procesa y reporta `otorgado` sin que exista conexión a
         sistema externo alguno.
    """
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(
            escenario_por_defecto=EscenarioSimulacion.EXITO
        ),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO


def TestEscenarioCanalSimuladoQueRespondePermisoDenegado():
    """Escenario: Canal simulado que responde permiso denegado.

    WHEN el pipeline ejecuta un ítem contra una implementación simulada
         configurada para responder permiso denegado
    THEN el ítem se procesa y reporta `privilegios_insuficientes` sin conexión
         a sistema externo alguno.
    """
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(
            escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
        ),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    assert reporte.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestEscenarioEjecucionDeGrantRealFueraDeAlcance():
    """Escenario: Ejecución de grant real fuera de alcance.

    WHEN se procesa una solicitud completa del pipeline con canales simulados
    THEN ninguna instrucción SQL, llamada SDK ni llamada REST es enviada a un
         workspace real.
    """
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=canal_control
    )
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT", "CAN_USE"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    pipeline.Procesar(solicitud)

    # Ninguna biblioteca de conexión externa fue cargada por el flujo: ni el
    # SDK de Databricks (llamadas SDK/REST) ni clientes HTTP.
    modulos_de_conexion = [
        nombre
        for nombre in sys.modules
        if nombre.startswith("databricks")
        or nombre.startswith("requests")
        or nombre.startswith("urllib3")
    ]
    assert modulos_de_conexion == [], (
        "El flujo con canales simulados no debe cargar bibliotecas de "
        "conexión a sistemas externos"
    )
