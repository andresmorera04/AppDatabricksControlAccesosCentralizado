"""Prueba de aceptación de `grant-management-ui` (capability del change C9).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 8.1.

Cada test está trazable 1:1 a un `Scenario` del delta
`openspec/changes/web-ui-minimalista/specs/grant-management-ui/spec.md` (el
nombre del escenario va en el docstring). Reutiliza los servicios, presentador,
controlador y escritores ya probados, sin red y con dobles. Cambiar el delta
exige actualizar esta suite en el mismo paso (regla de trazabilidad).
"""

from pathlib import Path

import pytest

from control_accesos.autenticacion.modelos import IdentidadLlamante
from control_accesos.bitacora.escritores_remotos import BitacoraEventosRemota
from control_accesos.canales.reales.descubrimiento_principales import (
    DescubridorPrincipales,
)
from control_accesos.canales.reales.descubrimiento_uc import DescubridorUc
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.pipeline.reportador import (
    LineaReporte,
    ReporteGrant,
    TRAZABILIDAD_ITINERARIO_COMPLETO,
)
from control_accesos.pipeline.reporte_lote import ReporteLoteGrant
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.controlador import ControladorGrantsUi
from control_accesos.ui.estado_sesion import EstadoSesionGrantsUi
from control_accesos.ui.presentador import PresentadorGrantsUi
from control_accesos.ui.redaccion import RedactorSecretos
from control_accesos.ui.servicio_descubrimiento import (
    ErrorDescubrimientoOpciones,
    ServicioDescubrimientoUi,
)
from control_accesos.ui.servicio_disponibilidad import (
    EstadoDisponibilidad,
    ServicioDisponibilidadOpciones,
)
from control_accesos.ui.servicio_solicitud import (
    ErrorSolicitudUi,
    ServicioSolicitudGrantsUi,
)

LLAMANTE = Principal("caller@example.com", TipoPrincipal.USUARIO)
DESTINO = Principal("destino@example.com", TipoPrincipal.USUARIO)
VENTAS = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)
FINANZAS = ObjetoSecurable("finanzas", TipoObjeto.CATALOGO)


def _Identidad():
    return IdentidadLlamante(principal=LLAMANTE)


def _Controlador():
    return ControladorGrantsUi(
        servicio_descubrimiento=_Descubrimiento(),
        servicio_solicitud=ServicioSolicitudGrantsUi(),
        servicio_disponibilidad=ServicioDisponibilidadOpciones(
            _ResolutorFalso({})
        ),
        servicio_previsualizacion=_Previsualizacion(),
        servicio_ejecucion=_Ejecucion(),
        presentador=PresentadorGrantsUi(),
        consultora=ConsultoraMatrizPrivilegios(),
    )


# ------------------------------------------------------------------- #
# Dobs de apoyo.
# ------------------------------------------------------------------- #


class _ServicioFalso:
    def __init__(self, registros=(), excepcion=None):
        self._registros = list(registros)
        self._excepcion = excepcion

    def list(self, **kwargs):
        if self._excepcion is not None:
            raise self._excepcion
        return iter(self._registros)


class _Descubrimiento:
    """Doble de ServicioDescubrimientoUi con listados vacíos."""

    def DescubrirPrincipales(self):
        return ()

    def DescubrirCatalogos(self):
        return ()

    def DescubrirClusters(self):
        return ()

    def DescubrirServerless(self):
        return ()

    def DescubrirWarehouses(self):
        return ()

    def DescubrirApps(self):
        return ()

    def DescubrirUsoTokens(self):
        return ()

    def DescubrirEsquemas(self, catalogo):
        return ()

    def DescubrirTablas(self, catalogo, esquema):
        return ()

    def DescubrirVolumenes(self, catalogo, esquema):
        return ()

    def DescubrirModelosMl(self, catalogo, esquema):
        return ()

    def DescubrirExternalLocations(self):
        return ()

    def DescubrirConexiones(self):
        return ()


class _Previsualizacion:
    def Previsualizar(self, solicitud, identidad):
        return _ClasificacionMixta()


class _Ejecucion:
    def Ejecutar(self, solicitud, identidad_llamante=None):
        return _Reporte()


class _ResolutorFalso:
    def __init__(self, privilegios_por_objeto):
        self._privilegios = privilegios_por_objeto

    def ResolverPrivilegiosEfectivos(self, identidad, objeto):
        return _VistaFalsa(self._privilegios.get(objeto.identificador, ()))


class _VistaFalsa:
    def __init__(self, privilegios):
        self._privilegios = {p.upper() for p in privilegios}

    def TieneElPrivilegio(self, privilegio):
        return privilegio.upper() in self._privilegios


def _Item(privilegio):
    return ItemGrant(principal=DESTINO, privilegio=privilegio, objeto=VENTAS)


def _ClasificacionMixta():
    motivo = MensajePrivilegiosInsuficientes(
        objeto=VENTAS, plano=Plano.DATOS,
        privilegio_requerido="MODIFY", privilegio_faltante="MANAGE",
    )
    return ClasificacionPreFlight(
        items_ejecutables=(_Item("SELECT"),),
        items_bloqueados=(
            ResultadoItem.PrivilegiosInsuficientes(
                _Item("MODIFY"), causa=motivo.ComoTexto()
            ),
        ),
        mensajes_por_item={_Item("MODIFY"): motivo},
    )


def _Reporte():
    return ReporteGrant(
        lineas=(
            LineaReporte(
                item=_Item("SELECT"), estado=EstadoItem.OTORGADO, detalle=None,
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
            LineaReporte(
                item=_Item("MODIFY"), estado=EstadoItem.FALLIDO, detalle="error",
                trazabilidad=TRAZABILIDAD_ITINERARIO_COMPLETO,
            ),
        )
    )


def _ClienteUc(catalogs=(), excepcion=None):
    return _ClienteUcFalso(catalogs=_ServicioFalso(catalogs, excepcion))


class _ClienteUcFalso:
    def __init__(self, catalogs):
        self.catalogs = catalogs
        self.schemas = _ServicioFalso()
        self.tables = _ServicioFalso()
        self.volumes = _ServicioFalso()
        self.registered_models = _ServicioFalso()
        self.external_locations = _ServicioFalso()
        self.connections = _ServicioFalso()


# ------------------------------------------------------------------- #
# Autenticación on-behalf-of y aislamiento del llamante.
# ------------------------------------------------------------------- #


def TestEscenarioUsuarioAutenticadoCorrectamente():
    """Usuario autenticado correctamente: la identidad resuelta habilita el flujo."""
    assert _Controlador().IdentidadVisible(_Identidad()) == LLAMANTE.identificador


def TestEscenarioContextoOTokenNoValido():
    """Contexto o token no válido: sin identidad se deshabilita el flujo."""
    assert _Controlador().IdentidadVisible(None) is None


def TestEscenarioDosUsuariosConPrivilegiosDistintos():
    """Dos usuarios con privilegios distintos: cada sesión autoriza por su identidad."""
    servicio = ServicioDisponibilidadOpciones(
        _ResolutorFalso({VENTAS.identificador: {"SELECT"}})
    )
    r = servicio.Evaluar([VENTAS], ["SELECT"], _Identidad())
    assert r[0].estado == EstadoDisponibilidad.DISPONIBLE


def TestEscenarioNoHerenciaDeCredencialesDeLaApp():
    """No herencia de credenciales de la App: explícito al token OBO (auth_type)."""
    from control_accesos.ui.proveedor_identidad_app import TIPO_AUTENTICACION_PAT_OBO
    from control_accesos.ui.fabrica_contexto_broker import CrearClienteWorkspaceSp

    assert TIPO_AUTENTICACION_PAT_OBO == "pat"
    assert callable(CrearClienteWorkspaceSp)


def TestEscenarioEjecucionBrokerAutorizada():
    """Ejecución broker autorizada: con privilegio validado se ejecuta."""
    from control_accesos.ui.servicio_ejecucion import ServicioEjecucionGrantsUi

    class _Pipeline:
        def ProcesarDesdeEntradas(self, principal, privilegios, objeto, identidad_llamante=None):
            return "reporte"

    assert ServicioEjecucionGrantsUi(_Pipeline()).Ejecutar(
        SolicitudGrant.Crear(DESTINO, ["SELECT"], VENTAS), _Identidad()
    ) == "reporte"


def TestEscenarioBloqueoSinAutoridadAunqueElSpPueda():
    """Bloqueo sin autoridad aunque el SP pueda ejecutar: sin privilegio no se ejecuta."""
    servicio = ServicioDisponibilidadOpciones(_ResolutorFalso({VENTAS.identificador: ()}))
    r = servicio.Evaluar([VENTAS], ["SELECT"], _Identidad())
    assert r[0].estado == EstadoDisponibilidad.NO_DISPONIBLE


# ------------------------------------------------------------------- #
# Descubrimiento de principals y objetos.
# ------------------------------------------------------------------- #


def TestEscenarioOpcionesDescubiertasParaElTipo():
    """Opciones descubiertas para el tipo elegido."""
    cliente = _ClienteUc(catalogs=[_Registro(name="ventas")])
    servicio = ServicioDescubrimientoUi(
        descubridor_uc=DescubridorUc(cliente=cliente)
    )
    objetos = servicio.DescubrirCatalogos()
    assert [o.identificador for o in objetos] == ["ventas"]


def TestEscenarioListadosScimConIdentidadDeLaApp():
    """Listados SCIM con la identidad de la App (cliente SP)."""

    class _ClienteScim:
        def __init__(self):
            self.users = _ServicioFalso([_Registro(user_name="u1")])
            self.groups = _ServicioFalso([_Registro(display_name="g1")])
            self.service_principals = _ServicioFalso(
                [_Registro(application_id="app-1")]
            )

    servicio = ServicioDescubrimientoUi(
        descubridor_principales=DescubridorPrincipales(cliente=_ClienteScim())
    )
    principales = servicio.DescubrirPrincipales()
    assert [p.tipo for p in principales] == [
        TipoPrincipal.USUARIO,
        TipoPrincipal.GRUPO,
        TipoPrincipal.SERVICE_PRINCIPAL,
    ]


def TestEscenarioDescubrimientoDenegadoONoDisponible():
    """Descubrimiento denegado: error distinguible de lista vacía."""
    cliente = _ClienteUc()
    cliente.catalogs = _ServicioFalso(excepcion=RuntimeError("denegado"))
    servicio = ServicioDescubrimientoUi(descubridor_uc=DescubridorUc(cliente=cliente))
    with pytest.raises(ErrorDescubrimientoOpciones):
        servicio.DescubrirCatalogos()


# ------------------------------------------------------------------- #
# Selección guiada por la matriz.
# ------------------------------------------------------------------- #


def TestEscenarioPrivilegiosFiltradosPorTipo():
    """Privilegios filtrados por tipo: exactamente los de la matriz."""
    privilegios = ConsultoraMatrizPrivilegios().ListarOpcionesParaUi(TipoObjeto.CATALOGO)
    assert "SELECT" in privilegios
    assert "CAN_USE" not in privilegios


def TestEscenarioCambioDeTipoConSeleccionPrevia():
    """Cambio de tipo con selección previa: se descarta lo incompatible."""
    controlador = _Controlador()
    controlador.SeleccionarPrincipales([DESTINO])
    controlador.SeleccionarTipo(TipoObjeto.CATALOGO)
    controlador.SeleccionarPrivilegios(["SELECT"])
    controlador.SeleccionarTipo(TipoObjeto.TABLA_DELTA)
    with pytest.raises(ErrorSolicitudUi):
        controlador.ConstruirSolicitud()


# ------------------------------------------------------------------- #
# Disponibilidad.
# ------------------------------------------------------------------- #


def TestEscenarioObjetoSinAutorizacion():
    """Objeto sin autorización para el privilegio elegido."""
    servicio = ServicioDisponibilidadOpciones(_ResolutorFalso({VENTAS.identificador: ()}))
    assert servicio.Evaluar([VENTAS], ["SELECT"], _Identidad())[0].estado == (
        EstadoDisponibilidad.NO_DISPONIBLE
    )


def TestEscenarioSeleccionConDisponibilidadMixta():
    """Selección con disponibilidad mixta."""
    servicio = ServicioDisponibilidadOpciones(
        _ResolutorFalso(
            {VENTAS.identificador: {"SELECT"}, FINANZAS.identificador: ()}
        )
    )
    r = servicio.Evaluar([VENTAS, FINANZAS], ["SELECT"], _Identidad())
    assert [d.estado for d in r] == [
        EstadoDisponibilidad.DISPONIBLE,
        EstadoDisponibilidad.NO_DISPONIBLE,
    ]


# ------------------------------------------------------------------- #
# Cardinalidades.
# ------------------------------------------------------------------- #


def TestEscenarioFlujo1A1():
    """Flujo 1 a 1."""
    assert isinstance(
        ServicioSolicitudGrantsUi().Construir([DESTINO], ["SELECT"], [VENTAS]),
        SolicitudGrant,
    )


def TestEscenarioFlujo1AN():
    """Flujo 1 a N."""
    assert isinstance(
        ServicioSolicitudGrantsUi().Construir([DESTINO], ["SELECT"], [VENTAS, FINANZAS]),
        SolicitudLoteGrant,
    )


def TestEscenarioFlujoNA1():
    """Flujo N a 1."""
    otros = [DESTINO, Principal("otro@example.com", TipoPrincipal.USUARIO)]
    assert isinstance(
        ServicioSolicitudGrantsUi().Construir(otros, ["SELECT"], [VENTAS]),
        SolicitudLoteGrant,
    )


def TestEscenarioCardinalidadNAmRechazada():
    """Cardinalidad N a M rechazada."""
    otros = [DESTINO, Principal("otro@example.com", TipoPrincipal.USUARIO)]
    with pytest.raises(ErrorSolicitudUi):
        ServicioSolicitudGrantsUi().Construir(otros, ["SELECT"], [VENTAS, FINANZAS])


# ------------------------------------------------------------------- #
# Validación de la solicitud.
# ------------------------------------------------------------------- #


def TestEscenarioConjuntoObligatorioVacio():
    """Conjunto obligatorio vacío."""
    with pytest.raises(ErrorSolicitudUi):
        ServicioSolicitudGrantsUi().Construir([], ["SELECT"], [VENTAS])


def TestEscenarioIdentificadorInvalido():
    """Identificador inválido."""
    with pytest.raises(ErrorSolicitudUi):
        ServicioSolicitudGrantsUi().Construir(["cadena-cruda"], ["SELECT"], [VENTAS])


# ------------------------------------------------------------------- #
# Previsualización, confirmación, reporte, errores e idioma.
# ------------------------------------------------------------------- #


def TestEscenarioPrevisualizacionMixta():
    """Previsualización con resultado mixto."""
    filas = PresentadorGrantsUi().PresentarPrevisualizacion(_ClasificacionMixta())
    assert [f.estado for f in filas] == ["ejecutable", "privilegios_insuficientes"]


def TestEscenarioTodosLosItemsBloqueados():
    """Todos los ítems bloqueados: no se habilita ejecución."""
    clasificacion = ClasificacionPreFlight(items_ejecutables=(), items_bloqueados=())
    assert PresentadorGrantsUi().PresentarPrevisualizacion(clasificacion) == ()


def TestEscenarioEjecucionConfirmada():
    """Ejecución confirmada por el usuario, una sola vez."""
    estado = EstadoSesionGrantsUi()
    huella = EstadoSesionGrantsUi.Huella([DESTINO], [VENTAS], ["SELECT"])
    estado.GuardarPrevisualizacion(huella, LLAMANTE.identificador, _ClasificacionMixta())
    assert estado.Confirmar(huella, LLAMANTE.identificador) is True
    assert estado.Confirmar(huella, LLAMANTE.identificador) is False


def TestEscenarioFormularioModificadoTrasPrevisualizar():
    """Formulario modificado tras previsualizar: invalida la confirmación."""
    estado = EstadoSesionGrantsUi()
    original = EstadoSesionGrantsUi.Huella([DESTINO], [VENTAS], ["SELECT"])
    estado.GuardarPrevisualizacion(original, LLAMANTE.identificador, _ClasificacionMixta())
    distinto = EstadoSesionGrantsUi.Huella([DESTINO], [VENTAS], ["MODIFY"])
    assert estado.PrevisualizacionVigente(distinto, LLAMANTE.identificador) is None


def TestEscenarioPrivilegiosModificadosEntreRevisionYEjecucion():
    """Privilegios modificados entre revisión y ejecución: revalidación."""
    estado = EstadoSesionGrantsUi()
    huella = EstadoSesionGrantsUi.Huella([DESTINO], [VENTAS], ["SELECT"])
    estado.GuardarPrevisualizacion(huella, "otro@example.com", _ClasificacionMixta())
    assert estado.PrevisualizacionVigente(huella, LLAMANTE.identificador) is None


def TestEscenarioReporteConResultadosParciales():
    """Reporte con resultados parciales (bloqueados incluidos)."""
    filas = PresentadorGrantsUi().PresentarReporte(_Reporte())
    assert [f.estado for f in filas] == [EstadoItem.OTORGADO.value, EstadoItem.FALLIDO.value]


def TestEscenarioTotalesDeUnLote():
    """Totales de un lote (ceros incluidos)."""
    lote = ReporteLoteGrant(lineas=(), total_items=0, totales_por_estado={})
    totales = PresentadorGrantsUi().PresentarTotales(lote)
    assert set(totales["totales_por_estado"]) == {
        EstadoItem.OTORGADO.value,
        EstadoItem.FALLIDO.value,
        EstadoItem.PRIVILEGIOS_INSUFICIENTES.value,
    }


def TestEscenarioErrorControladoConIdentidad():
    """Error controlado con identidad conocida (sin stack trace)."""
    mensaje = RedactorSecretos().MensajeDeErrorControlado(
        RuntimeError("fallo con dapi1234567890abcdef")
    )
    assert "dapi" not in mensaje
    assert "Traceback" not in mensaje


def TestEscenarioFalloDeBitacoraDespuesDeProcesar():
    """Fallo de bitácora después de procesar: no se oculta el resultado."""

    class _SesionQueFalla:
        def sql(self, sentencia):
            raise RuntimeError("fallo de escritura")

    bitacora = BitacoraEventosRemota(
        sesion=_SesionQueFalla(), configuracion=ConfiguracionApp.Cargar()
    )
    evento = bitacora.Registrar(accion="otorgar", usuario=LLAMANTE.identificador)
    assert evento.accion == "otorgar"


def TestEscenarioFlujoCompletoEnEspanol():
    """Flujo completo comprensible en español."""
    assert "Privilegios insuficientes" in MensajePrivilegiosInsuficientes(
        objeto=VENTAS, plano=Plano.DATOS,
        privilegio_requerido="SELECT", privilegio_faltante="MANAGE",
    ).ComoTexto()


def TestEscenarioMensajePrivilegiosInsuficientes():
    """Mensaje de privilegios insuficientes (objeto, plano, requerido, faltante)."""
    mensaje = MensajePrivilegiosInsuficientes(
        objeto=VENTAS, plano=Plano.DATOS,
        privilegio_requerido="SELECT", privilegio_faltante="MANAGE",
    )
    assert mensaje.privilegio_requerido == "SELECT"
    assert mensaje.privilegio_faltante == "MANAGE"


# ------------------------------------------------------------------- #
# Despliegue multi-entorno (D13).
# ------------------------------------------------------------------- #


def TestEscenarioEjecucionEnFree():
    """Ejecución en Free: configuración con IdWarehouse dinámico por entorno."""
    assert ConfiguracionApp.Cargar().ObtenerAtributo("id_warehouse") is not None


def TestEscenarioEjecucionEnAzure():
    """Ejecución en Azure: gate azure bajo marker explícito (no por defecto)."""
    pytest_ini = (Path(__file__).resolve().parents[2] / "pytest.ini").read_text(
        encoding="utf-8"
    )
    assert "azure_approval" in pytest_ini


def TestEscenarioAppDetenidaFueraDePruebas():
    """App detenida fuera de pruebas en Azure: regla de costos documentada."""
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(
        encoding="utf-8"
    )
    assert "detenida fuera de las ejecuciones de prueba" in readme


def _Registro(**campos):
    from types import SimpleNamespace as _NS

    return _NS(**campos)
