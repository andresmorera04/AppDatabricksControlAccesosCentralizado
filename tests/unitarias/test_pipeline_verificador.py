"""Pruebas unitarias de la fase `Verificador` del pipeline.

Cubren el requirement "Fase de verificación posterior al otorgamiento" del
spec `grant-pipeline`: tras la ejecución se reconsultan los grants vigentes
del objeto por el canal correspondiente; lo otorgado y confirmado se mantiene
OTORGADO, y cualquier discrepancia se convierte en FALLIDO con el detalle de
la verificación.
"""

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
    ResultadoItem,
)
from control_accesos.pipeline.ejecutor import Ejecutor
from control_accesos.pipeline.verificador import Verificador


def CrearItem(privilegio="SELECT", tipo=TipoObjeto.TABLA_DELTA, identificador=None):
    """Construye un ítem de prueba.

    Args:
        privilegio (str): privilegio del ítem.
        tipo (TipoObjeto): tipo del objeto securable.
        identificador (str | None): identificación del objeto.

    Returns:
        ItemGrant: ítem listo para verificar.
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


def CrearCanales(registrar_grants_datos=True):
    """Construye los canales simulados para ejecutor y verificador.

    Args:
        registrar_grants_datos (bool): cuando es False, el canal de datos no
            deja visible lo otorgado, simulando la discrepancia de verificación.

    Returns:
        tuple: (canal_datos, canal_control).
    """
    canal_datos = CanalDatosSimulado(
        registrar_grants_otorgados=registrar_grants_datos
    )
    canal_control = CanalControlSimulado()
    return canal_datos, canal_control


def TestOtorgadoVerificadoSeMantieneOtorgado():
    """Escenario del spec: otorgado y confirmado vigente -> sigue OTORGADO."""
    canal_datos, canal_control = CrearCanales()
    item = CrearItem()
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    assert len(verificados) == 1
    assert verificados[0].estado is EstadoItem.OTORGADO
    assert verificados[0].item == item


def TestDiscrepanciaSeReportaFallido():
    """Escenario del spec: otorgado que no aparece vigente -> FALLIDO."""
    canal_datos, canal_control = CrearCanales(registrar_grants_datos=False)
    item = CrearItem()
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    assert verificados[0].estado is EstadoItem.FALLIDO


def TestDetalleDeDiscrepanciaEsPreciso():
    """El detalle de la discrepancia menciona privilegio, principal y objeto."""
    canal_datos, canal_control = CrearCanales(registrar_grants_datos=False)
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([CrearItem(privilegio="MODIFY")])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    detalle = verificados[0].detalle
    assert "MODIFY" in detalle
    assert "usuario_demo" in detalle
    assert "control.produccion.ventas" in detalle
    assert "verificación" in detalle.lower()


def TestFallidoDeEjecucionPasaSinVerificacion():
    """Un resultado ya FALLIDO no se re-verifica: pasa tal cual al reporte."""
    canal_datos, canal_control = CrearCanales()
    item = CrearItem()
    canal_datos.ConfigurarEscenario(
        item, EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    assert verificados[0].estado is EstadoItem.FALLIDO
    assert verificados[0].detalle == resultados[0].detalle


def TestPrivilegiosInsuficientesPasaSinVerificacion():
    """Un resultado de privilegios insuficientes no se re-verifica."""
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )
    item = CrearItem(
        privilegio="CAN_USE",
        tipo=TipoObjeto.SQL_WAREHOUSE,
        identificador="a1b2c3",
    )
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    assert verificados[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert verificados[0].detalle == resultados[0].detalle


def TestVerificacionDeSolicitudMixta():
    """Ítems verificados y con discrepancia conviven en la misma ejecución."""
    canal_datos = CanalDatosSimulado(registrar_grants_otorgados=False)
    canal_control = CanalControlSimulado()
    item_datos = CrearItem()
    item_control = CrearItem(
        privilegio="CAN_USE",
        tipo=TipoObjeto.SQL_WAREHOUSE,
        identificador="a1b2c3",
    )
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item_datos, item_control])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    estados = {resultado.item: resultado.estado for resultado in verificados}
    # El ítem de datos sufre la discrepancia (registro desactivado en su canal).
    assert estados[item_datos] is EstadoItem.FALLIDO
    # El ítem de control se verifica por su propio canal y queda confirmado.
    assert estados[item_control] is EstadoItem.OTORGADO


def TestVerificacionConsultaLosGrantsVigentesDelObjeto():
    """La verificación reconsulta el canal del plano del objeto (spec)."""
    canal_datos = CanalDatosSimulado(registrar_grants_otorgados=False)
    canal_control = CanalControlSimulado()
    item = CrearItem()
    # Se configura manualmente el grant vigente que el otorgamiento no registró:
    # la verificación debe encontrarlo y confirmar el estado OTORGADO.
    canal_datos.ConfigurarGrantsVigentes(item.objeto, [item])
    resultados = Ejecutor(
        canal_datos=canal_datos, canal_control=canal_control
    ).Ejecutar([item])

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar(resultados)

    assert verificados[0].estado is EstadoItem.OTORGADO


def TestListaVaciaDevuelveListaVacia():
    """Sin resultados que verificar, la fase devuelve una lista vacía."""
    canal_datos, canal_control = CrearCanales()
    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar([])
    assert verificados == []


def TestVerificadorAceptaResultadoConstruidoADirectamente():
    """El verificador trabaja con cualquier ResultadoItem OTORGADO."""
    canal_datos, canal_control = CrearCanales()
    item = CrearItem()
    canal_datos.ConfigurarGrantsVigentes(item.objeto, [item])
    resultado_manual = ResultadoItem.Otorgado(item)

    verificados = Verificador(
        canal_datos=canal_datos, canal_control=canal_control
    ).Verificar([resultado_manual])

    assert verificados[0].estado is EstadoItem.OTORGADO
