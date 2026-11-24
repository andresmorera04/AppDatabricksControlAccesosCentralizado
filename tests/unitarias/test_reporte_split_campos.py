"""Pruebas unitarias del reporte por campo de los ítems bloqueados por privilegios.

El spec `caller-privilege-resolution` exige que el bloqueo sea un **dato** con
los cuatro campos consultables por el reporte y la interfaz (change C9), no
una cadena que haya que parsear. Estas pruebas verifican que:

- la línea de reporte de un ítem bloqueado por privilegios expone el
  `MensajePrivilegiosInsuficientes` como campo, además del `detalle` textual;
- las líneas de los demás estados (otorgado, fallido por matriz, fallido por
  verificación) mantienen `motivo_insuficiencia` en None, sin cambiar;
- un bloqueo por privilegios nunca aborta el reporte de los demás ítems.
"""

from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import EstadoItem, Plano, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
)
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight, PreFlight
from control_accesos.pipeline.reportador import Reportador
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)


def CrearItem(privilegio="SELECT", objeto=CATALOGO):
    """Construye un ítem de prueba sobre el objeto indicado.

    Args:
        privilegio (str): privilegio del ítem.
        objeto (ObjetoSecurable): objetivo del otorgamiento.

    Returns:
        ItemGrant: ítem listo para reportar.
    """
    return ItemGrant(
        principal=Principal(identificador="beneficiario", tipo=TipoPrincipal.USUARIO),
        privilegio=privilegio,
        objeto=objeto,
    )


def IdentidadUsuario():
    """Devuelve la identidad de un usuario de prueba, sin otorgamientos.

    Returns:
        IdentidadLlamante: identidad resuelta del llamante.
    """
    from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
    from control_accesos.autenticacion.simulados import (
        IdentidadUsuarioConGrupos,
        ProveedorIdentidadSimulado,
    )

    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


def ClasificarSinPrivilegios(items):
    """Clasifica los ítems con un canal sin otorgamientos vigentes.

    Args:
        items (list[ItemGrant]): ítems a clasificar por el eje de privilegios.

    Returns:
        ClasificacionPreFlight: clasificación con los bloqueos estructurados.
    """
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=CanalDatosSimulado(), canal_control=CanalControlSimulado()
    )
    return PreFlight(resolutor_privilegios=resolutor).Clasificar(
        items, identidad_llamante=IdentidadUsuario()
    )


def TestLineaDeBloqueadoExponeElMensajePorCampo():
    """Escenario 'Campos consultables por nombre' aplicado al reporte."""
    item = CrearItem("SELECT")
    clasificacion = ClasificarSinPrivilegios([item])

    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=[],
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES

    motivo = linea.motivo_insuficiencia
    assert isinstance(motivo, MensajePrivilegiosInsuficientes)
    assert motivo.objeto == CATALOGO
    assert motivo.plano is Plano.DATOS
    assert motivo.privilegio_requerido == "SELECT"
    assert motivo.privilegio_faltante == "MANAGE"


def TestElDetalleTextualDelReporteCoincideConElMensaje():
    """El `detalle` del reporte es el texto legible del mismo dato."""
    item = CrearItem("SELECT")
    clasificacion = ClasificarSinPrivilegios([item])

    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=[],
    )

    linea = reporte.lineas[0]
    assert linea.detalle == linea.motivo_insuficiencia.ComoTexto()


def TestReporteNoAbortaConBloqueadosY_OTORGADOS():
    """Escenario 'Solicitud mixta': el reporte cubre bloqueados y ejecutados."""
    item_bloqueado = CrearItem("SELECT")
    item_otorgado = CrearItem("USE CATALOG")
    clasificacion = ClasificarSinPrivilegios([item_bloqueado])

    reporte = Reportador().Reportar(
        items_planificados=[item_bloqueado, item_otorgado],
        clasificacion=clasificacion,
        resultados_verificados=[ResultadoItem.Otorgado(item_otorgado)],
    )

    assert len(reporte.lineas) == 2
    assert reporte.ObtenerLineasPorEstado(EstadoItem.PRIVILEGIOS_INSUFICIENTES)
    assert reporte.ObtenerLineasPorEstado(EstadoItem.OTORGADO)


def TestLineasSinBloqueoPorPrivilegiosTienenMotivoNulo():
    """Los demás estados conservan `motivo_insuficiencia` en None (C1 intacto)."""
    item = CrearItem("CAN_USE", CATALOGO)

    # Bloqueo por la matriz de C1: no es un caso de privilegios insuficientes.
    clasificacion = PreFlight().Clasificar([item])
    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=[],
    )

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert reporte.lineas[0].motivo_insuficiencia is None


def TestReporteDeBloqueadoConservaTrazabilidadDePreFlight():
    """El ítem bloqueado por privilegios solo llega hasta pre-flight."""
    item = CrearItem("SELECT")
    clasificacion = ClasificarSinPrivilegios([item])

    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=[],
    )

    assert "pre-flight" in " ".join(reporte.lineas[0].trazabilidad)


def TestClasificacionConConstruccionLegadaNoRompeElReporte():
    """Una clasificación sin mensajes (construida como en C1) reporta igual."""
    item = CrearItem("SELECT")
    clasificacion = ClasificacionPreFlight(
        items_ejecutables=(),
        items_bloqueados=(
            ResultadoItem.Fallido(item, detalle="motivo heredado de C1"),
        ),
    )

    reporte = Reportador().Reportar(
        items_planificados=[item],
        clasificacion=clasificacion,
        resultados_verificados=[],
    )

    assert reporte.lineas[0].motivo_insuficiencia is None
    assert reporte.lineas[0].detalle == "motivo heredado de C1"
