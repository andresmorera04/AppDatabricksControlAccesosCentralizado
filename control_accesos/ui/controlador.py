"""Controlador de la UI de grants (design.md D2, tareas 6.1-6.3).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Coordinador POO entre la vista (Streamlit, en la entrada delgada) y los
servicios de aplicación ya construidos: descubrimiento (OBO y broker),
solicitud, disponibilidad, previsualización, ejecución, presentación y estado
de sesión. No conoce Streamlit: expone métodos puros que la entrada delgada
invoca y que las pruebas funcionales ejercitan con colaboradores simulados.

Responsabilidades:

- **selección**: principals, tipo de objeto, objetos y privilegios (de la
  matriz); al cambiar el tipo se descartan objetos y privilegios previos
  (limpieza);
- **disponibilidad**: evalúa los objetos seleccionados con el resolutor
  híbrido (canal de datos OBO + canal de control SP, design.md D2 broker);
- **previsualización**: planifica y clasifica, guarda la clasificación
  asociada a huella+identidad, y presenta el split;
- **confirmación/ejecución**: confirmación de un solo uso y re-ejecución del
  pre-flight en el pipeline; presenta el reporte por ítem;
- **errores controlados**: un fallo de descubrimiento inhabilita la ejecución
  y se reporta sin secretos (redacción D11).

Estado efímero por sesión: nunca guarda tokens, clientes ni credenciales.
"""

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto
from control_accesos.dominio.modelos import MAPA_TIPO_OBJETO_A_PLANO
from control_accesos.ui.estado_sesion import EstadoSesionGrantsUi
from control_accesos.ui.redaccion import RedactorSecretos

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_CONTROLADOR = "ui.controlador"


class ControladorGrantsUi:
    """Coordina el flujo de selección → previsualización → ejecución → reporte.

    Attributes:
        servicio_descubrimiento (ServicioDescubrimientoUi): listados OBO/broker.
        servicio_solicitud (ServicioSolicitudGrantsUi): construcción y validación.
        servicio_disponibilidad (ServicioDisponibilidadOpciones): disponibilidad
            por privilegios efectivos.
        servicio_previsualizacion (ServicioPrevisualizacionGrants): split.
        servicio_ejecucion (ServicioEjecucionGrantsUi): ejecución con revalidación.
        presentador (PresentadorGrantsUi): filas para la vista.
        consultora (ConsultoraMatrizPrivilegios): privilegios válidos por tipo.
    """

    def __init__(
        self,
        servicio_descubrimiento,
        servicio_solicitud,
        servicio_disponibilidad,
        servicio_previsualizacion,
        servicio_ejecucion,
        presentador,
        consultora,
        estado=None,
        redactor=None,
    ):
        """Inicializa el controlador con sus colaboradores inyectados.

        Raises:
            ValueError: si falta algún colaborador obligatorio.
        """
        colaboradores = {
            "servicio_descubrimiento": servicio_descubrimiento,
            "servicio_solicitud": servicio_solicitud,
            "servicio_disponibilidad": servicio_disponibilidad,
            "servicio_previsualizacion": servicio_previsualizacion,
            "servicio_ejecucion": servicio_ejecucion,
            "presentador": presentador,
            "consultora": consultora,
        }
        for nombre, valor in colaboradores.items():
            if valor is None:
                raise ValueError(
                    f"El controlador requiere el colaborador '{nombre}'."
                )

        self._servicio_descubrimiento = servicio_descubrimiento
        self._servicio_solicitud = servicio_solicitud
        self._servicio_disponibilidad = servicio_disponibilidad
        self._servicio_previsualizacion = servicio_previsualizacion
        self._servicio_ejecucion = servicio_ejecucion
        self._presentador = presentador
        self._consultora = consultora
        self._estado = estado if estado is not None else EstadoSesionGrantsUi()
        self._redactor = redactor if redactor is not None else RedactorSecretos()
        self._ultimo_reporte = None

        # Selección vigente (modelos de vista sin credenciales).
        self._principales = ()
        self._tipo_objeto = None
        self._catalogo = None
        self._esquema = None
        self._objetos = ()
        self._privilegios = ()
        # Fallo de descubrimiento visible: inhabilita la ejecución.
        self._error_descubrimiento = None

    # ------------------------------------------------------------------ #
    # Identidad y descubrimiento.
    # ------------------------------------------------------------------ #

    def IdentidadVisible(self, identidad):
        """Devuelve el texto de identidad a mostrar (o None sin identidad)."""
        if identidad is None:
            return None
        return identidad.principal.identificador

    def ListarPrincipales(self):
        """Lista los principals descubiertos (SCIM-SP) para elegir.

        Returns:
            tuple[Principal, ...]: principals; tupla vacía si el descubrimiento
                falla (con el error registrado y la ejecución inhabilitada).
        """
        try:
            self._error_descubrimiento = None
            return self._servicio_descubrimiento.DescubrirPrincipales()
        except Exception as excepcion:  # noqa: BLE001 - error de catálogo
            self._error_descubrimiento = self._redactor.MensajeDeErrorControlado(
                excepcion
            )
            return ()

    def ListarObjetos(self, tipo_objeto):
        """Lista los objetos del tipo indicado (plano de datos o control)."""
        try:
            self._error_descubrimiento = None
            return self._DescubrirObjetos(tipo_objeto)
        except Exception as excepcion:  # noqa: BLE001 - error de catálogo
            self._error_descubrimiento = self._redactor.MensajeDeErrorControlado(
                excepcion
            )
            return ()

    def ListarPrivilegios(self, tipo_objeto):
        """Lista los privilegios exactos de la matriz para el tipo."""
        return self._consultora.ListarOpcionesParaUi(tipo_objeto)

    def ErrorDescubrimiento(self):
        """Devuelve el último fallo de descubrimiento (None si no lo hubo)."""
        return self._error_descubrimiento

    def PuedeEjecutar(self):
        """Indica si la ejecución está habilitada (sin fallo de descubrimiento)."""
        return self._error_descubrimiento is None

    # ------------------------------------------------------------------ #
    # Selección con limpieza al cambiar el tipo.
    # ------------------------------------------------------------------ #

    def SeleccionarPrincipales(self, principales):
        self._principales = tuple(principales)

    def SeleccionarTipo(self, tipo_objeto):
        if tipo_objeto != self._tipo_objeto:
            self._objetos = ()
            self._privilegios = ()
        self._tipo_objeto = tipo_objeto

    def SeleccionarObjetos(self, objetos):
        self._objetos = tuple(objetos)

    def SeleccionarPrivilegios(self, privilegios):
        self._privilegios = tuple(privilegios)

    def SeleccionarCatalogo(self, catalogo):
        """Fija el catálogo contenedor (lista hijos) e invalida objetos previos."""
        self._catalogo = catalogo
        self._objetos = ()

    def SeleccionarEsquema(self, esquema):
        """Fija el esquema contenedor (lista tablas/volúmenes/modelos)."""
        self._esquema = esquema
        self._objetos = ()

    # ------------------------------------------------------------------ #
    # Solicitud, disponibilidad, previsualización y ejecución.
    # ------------------------------------------------------------------ #

    def ConstruirSolicitud(self):
        """Construye y valida la solicitud con la selección vigente.

        Returns:
            SolicitudGrant | SolicitudLoteGrant: solicitud validada.

        Raises:
            Exception: errores del servicio de solicitud (ErrorSolicitudUi u
                otros) sin redacción aquí; el llamador los maneja.
        """
        return self._servicio_solicitud.Construir(
            self._principales, self._privilegios, self._objetos
        )

    def Disponibilidad(self, identidad):
        """Evalúa la disponibilidad de la selección vigente.

        Args:
            identidad (IdentidadLlamante | None): identidad del llamante.

        Returns:
            tuple[DisponibilidadObjeto, ...]: uno por objeto seleccionado.
        """
        return self._servicio_disponibilidad.Evaluar(
            self._objetos, self._privilegios, identidad
        )

    def Previsualizar(self, identidad):
        """Previsualiza la selección y presenta el split (guarda el estado).

        Returns:
            tuple[FilaPresentacion, ...]: filas de la previsualización.

        Raises:
            ErrorSolicitudUi: si la selección no es válida.
        """
        solicitud = self.ConstruirSolicitud()
        clasificacion = self._servicio_previsualizacion.Previsualizar(
            solicitud, identidad
        )
        huella = self._HuellaActual()
        self._estado.GuardarPrevisualizacion(
            huella, self._IdentificadorDe(identidad), clasificacion
        )
        return self._presentador.PresentarPrevisualizacion(clasificacion)

    def ConfirmarYEejecutar(self, identidad):
        """Consume la confirmación y ejecuta (reporte presentado).

        Returns:
            tuple[FilaPresentacion, ...] | None: filas del reporte, o None si
                la confirmación no es vigente/consumida (sin ejecución).

        Raises:
            ErrorSolicitudUi: si la selección no es válida.
        """
        huella = self._HuellaActual()
        if not self._estado.Confirmar(huella, self._IdentificadorDe(identidad)):
            return None
        solicitud = self.ConstruirSolicitud()
        reporte = self._servicio_ejecucion.Ejecutar(solicitud, identidad)
        self._ultimo_reporte = reporte
        return self._presentador.PresentarReporte(reporte)

    def TotalesDelUltimoReporte(self):
        """Devuelve los totales del último lote ejecutado (o None si fue 1 a 1).

        Returns:
            dict | None: `{"total_items", "totales_por_estado"}` si el último
                reporte es un `ReporteLoteGrant`; None en otro caso.
        """
        if self._ultimo_reporte is None:
            return None
        if not hasattr(self._ultimo_reporte, "totales_por_estado"):
            return None
        return self._presentador.PresentarTotales(self._ultimo_reporte)

    # ------------------------------------------------------------------ #
    # Internos.
    # ------------------------------------------------------------------ #

    def _HuellaActual(self):
        """Huella canónica de la selección vigente (design.md D9)."""
        return EstadoSesionGrantsUi.Huella(
            self._principales, self._objetos, self._privilegios
        )

    @staticmethod
    def _IdentificadorDe(identidad):
        """Identificador estable de la identidad para asociar el estado."""
        return None if identidad is None else identidad.principal.identificador

    def _DescubrirObjetos(self, tipo_objeto):
        """Despacha el listado de objetos según el tipo elegido (design.md D6).

        Args:
            tipo_objeto (TipoObjeto): tipo cuyo listado se solicita.

        Returns:
            tuple[ObjetoSecurable, ...]: objetos del tipo, en orden.
        """
        tipo = tipo_objeto if isinstance(tipo_objeto, TipoObjeto) else TipoObjeto(tipo_objeto)

        if MAPA_TIPO_OBJETO_A_PLANO[tipo] is Plano.CONTROL:
            descubridores_control = {
                TipoObjeto.COMPUTO_CLASICO: self._servicio_descubrimiento.DescubrirClusters,
                TipoObjeto.COMPUTO_SERVERLESS: self._servicio_descubrimiento.DescubrirServerless,
                TipoObjeto.SQL_WAREHOUSE: self._servicio_descubrimiento.DescubrirWarehouses,
                TipoObjeto.DATABRICK_APP: self._servicio_descubrimiento.DescubrirApps,
                TipoObjeto.USO_TOKEN: self._servicio_descubrimiento.DescubrirUsoTokens,
            }
            return descubridores_control[tipo]()

        # Plano de datos: los tipos contenedores se listan sin padre; los hijos
        # (esquemas, tablas, volúmenes, modelos) exigen catálogo/esquema previo.
        if tipo is TipoObjeto.CATALOGO:
            return self._servicio_descubrimiento.DescubrirCatalogos()
        if tipo is TipoObjeto.EXTERNAL_LOCATION:
            return self._servicio_descubrimiento.DescubrirExternalLocations()
        if tipo is TipoObjeto.CONNECTION:
            return self._servicio_descubrimiento.DescubrirConexiones()
        if tipo is TipoObjeto.ESQUEMA:
            return self._HijosConColumna(
                self._catalogo, "catálogo",
                self._servicio_descubrimiento.DescubrirEsquemas,
            )
        if tipo in (
            TipoObjeto.TABLA_DELTA,
            TipoObjeto.STREAMING_TABLE,
            TipoObjeto.VISTA_MATERIALIZADA,
            TipoObjeto.VISTA_SQL,
        ):
            return self._TablasConPadres()
        if tipo is TipoObjeto.VOLUMEN:
            return self._HijosConColumnas(
                self._catalogo, self._esquema,
                self._servicio_descubrimiento.DescubrirVolumenes,
            )
        return self._HijosConColumnas(
            self._catalogo, self._esquema,
            self._servicio_descubrimiento.DescubrirModelosMl,
        )

    def _HijosConColumna(self, catalogo, etiqueta, descubridor):
        """Lista hijos que exigen un catálogo contenedor (esquemas)."""
        if not catalogo:
            self._error_descubrimiento = (
                f"Seleccione un {etiqueta} contenedor para listar estas opciones."
            )
            return ()
        return descubridor(catalogo)

    def _TablasConPadres(self):
        """Lista tablas/vistas, exigiendo catálogo y esquema previos."""
        return self._HijosConColumnas(
            self._catalogo, self._esquema,
            self._servicio_descubrimiento.DescubrirTablas,
        )

    def _HijosConColumnas(self, catalogo, esquema, descubridor):
        """Lista hijos que exigen catálogo y esquema (tablas/volúmenes/modelos)."""
        if not catalogo:
            self._error_descubrimiento = (
                "Seleccione un catálogo contenedor para listar estas opciones."
            )
            return ()
        if not esquema:
            self._error_descubrimiento = (
                "Seleccione un esquema contenedor para listar estas opciones."
            )
            return ()
        return descubridor(catalogo, esquema)
