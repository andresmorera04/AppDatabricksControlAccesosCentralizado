"""Pruebas unitarias de los canales simulados (capability `channel-adapters`).

Cubren el requirement "Implementaciones simulables para testing" del spec: los
fakes reproducen respuestas exitosas y de error (permiso denegado, objeto
inexistente) y permiten configurar los grants vigentes, sin interactuar con
ningún sistema externo.
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
)


def CrearItem(privilegio="SELECT", tipo=TipoObjeto.TABLA_DELTA, identificador=None):
    """Construye un ítem de prueba con el plano que corresponde al tipo.

    Args:
        privilegio (str): privilegio del ítem.
        tipo (TipoObjeto): tipo de objeto (define el plano).
        identificador (str | None): identificación del objeto.

    Returns:
        ItemGrant: ítem listo para ejercitar los canales simulados.
    """
    if identificador is None:
        identificador = "control.produccion.ventas"
    return ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=ObjetoSecurable(identificador=identificador, tipo=tipo),
    )


def TestCanalSimuladoExitosoOtorgaYDejaElGrantVigente():
    """Escenario éxito: el ítem se otorga y queda consultable como vigente."""
    canal = CanalDatosSimulado()
    item = CrearItem()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(item.objeto) == [item]


def TestCanalSimuladoConPermisoDenegado():
    """Escenario permiso denegado: resultado de privilegios insuficientes."""
    canal = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )

    resultado = canal.Otorgar(CrearItem())

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "PERMISSION_DENIED" in resultado.detalle


def TestCanalSimuladoConObjetoInexistente():
    """Escenario objeto inexistente: resultado fallido con el detalle."""
    canal = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.OBJETO_INEXISTENTE
    )

    resultado = canal.Otorgar(CrearItem())

    assert resultado.estado is EstadoItem.FALLIDO
    assert "no existe" in resultado.detalle


def TestEscenarioConfigurablePorItem():
    """Cada ítem puede tener su propio escenario (solicitudes mixtas)."""
    canal = CanalDatosSimulado()
    item_exitoso = CrearItem(privilegio="SELECT")
    item_denegado = CrearItem(privilegio="MODIFY")
    canal.ConfigurarEscenario(
        item_denegado, EscenarioSimulacion.PERMISO_DENEGADO
    )

    resultado_exitoso = canal.Otorgar(item_exitoso)
    resultado_denegado = canal.Otorgar(item_denegado)

    assert resultado_exitoso.estado is EstadoItem.OTORGADO
    assert resultado_denegado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestGrantsVigentesConfigurables():
    """Los grants vigentes se pueden configurar explícitamente por objeto."""
    canal = CanalDatosSimulado()
    objeto = CrearItem().objeto
    grant_previo = CrearItem(privilegio="SELECT")
    canal.ConfigurarGrantsVigentes(objeto, [grant_previo])

    assert canal.ListarGrantsVigentes(objeto) == [grant_previo]


def TestObjetoSinGrantsConfiguradosDevuelveListaVacia():
    """Un objeto sin grants configurados ni otorgados no tiene vigentes."""
    canal = CanalDatosSimulado()
    objeto = ObjetoSecurable(
        identificador="control.otra.tabla", tipo=TipoObjeto.TABLA_DELTA
    )
    assert canal.ListarGrantsVigentes(objeto) == []


def TestSinRegistroDeGrantsSimulaDiscrepanciaDeVerificacion():
    """Con el registro desactivado, lo otorgado no aparece como vigente.

    Este escenario permite ejercitar la discrepancia entre ejecución y
    verificación del pipeline (spec `grant-pipeline`).
    """
    canal = CanalDatosSimulado(registrar_grants_otorgados=False)
    item = CrearItem()

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(item.objeto) == []


def TestRevocacionEliminaElGrantVigente():
    """Revocar un grant otorgado lo quita de la lista de vigentes."""
    canal = CanalDatosSimulado()
    item = CrearItem()
    canal.Otorgar(item)
    assert canal.ListarGrantsVigentes(item.objeto) == [item]

    resultado = canal.Revocar(item)

    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(item.objeto) == []


def TestCanalControlSimuladoCumpleElMismoContrato():
    """El fake del plano de control responde al mismo contrato unificado."""
    canal = CanalControlSimulado()
    item = CrearItem(
        privilegio="CAN_USE",
        tipo=TipoObjeto.SQL_WAREHOUSE,
        identificador="a1b2c3d4e5f6",
    )

    resultado = canal.Otorgar(item)

    assert isinstance(canal, CanalControl)
    assert resultado.estado is EstadoItem.OTORGADO
    assert canal.ListarGrantsVigentes(item.objeto) == [item]


def TestCanalControlSimuladoConPermisoDenegado():
    """El fake de control reproduce el 403 de la Permissions API."""
    canal = CanalControlSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )
    item = CrearItem(
        privilegio="CAN_MANAGE",
        tipo=TipoObjeto.COMPUTO_CLASICO,
        identificador="1122-334455",
    )

    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES


def TestCanalesSimuladosCumplenLosContratosAbstractos():
    """Los fakes son implementaciones de los contratos del dominio."""
    assert isinstance(CanalDatosSimulado(), CanalDatos)
    assert isinstance(CanalControlSimulado(), CanalControl)


def TestCanalesSimuladosNoCarganBibliotecasExternas():
    """Los fakes no importan el SDK ni requieren conexión externa alguna.

    La comprobación es relativa: se toma una instantánea de los módulos ya
    cargados y se afirma que construir y usar los canales simulados no agrega
    bibliotecas de conexión externa (`databricks`/`requests`). No se afirma que
    el proceso esté libre de ellas en términos absolutos: en la suite completa
    las integrales (autorizadas por el humano, change C7) cargan `databricks-sdk`
    en el mismo proceso, y eso es legítimo. Lo que se protege es que la
    superficie simulada del dominio no arrastre el SDK.
    """
    modulos_previos = set(sys.modules)

    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    canal_datos.Otorgar(CrearItem())
    canal_control.Otorgar(
        CrearItem(
            privilegio="CAN_USE",
            tipo=TipoObjeto.DATABRICK_APP,
            identificador="mi-app",
        )
    )

    modulos_agregados = [
        nombre
        for nombre in sys.modules
        if (nombre.startswith("databricks") or nombre.startswith("requests"))
        and nombre not in modulos_previos
    ]
    assert modulos_agregados == [], (
        "Los canales simulados no deben cargar bibliotecas de conexión externa"
    )


def TestOperacionesQuedanRegistradasParaTrazabilidad():
    """El fake registra las operaciones ejecutadas (útil para las pruebas)."""
    canal = CanalDatosSimulado()
    item = CrearItem()
    canal.Otorgar(item)
    canal.Revocar(item)

    assert len(canal.operaciones_ejecutadas) == 2
    assert canal.operaciones_ejecutadas[0].operacion == "otorgar"
    assert canal.operaciones_ejecutadas[1].operacion == "revocar"
