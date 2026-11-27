"""Orquestador del flujo de otorgamiento (capability `grant-pipeline`).

`PipelineGrants` compone las cinco fases del flujo
`plan -> pre-flight -> ejecutar -> verificar -> reporte` (README.md -
Arquitectura; spec `grant-pipeline`). Cada fase es una clase independiente con
sus dependencias inyectadas (design.md D5):

- `Planificador`: construye la solicitud y la expande en ítems atómicos.
- `PreFlight`: clasifica los ítems contra la matriz de compatibilidad y, desde
  el change `auth-caller-obo`, contra los privilegios efectivos del llamante.
- `Ejecutor`: otorga por el canal del plano del objeto.
- `Verificador`: confirma los otorgamientos contra los grants vigentes.
- `Reportador`: consolida el reporte por ítem con su trazabilidad.

El orquestador no conoce la mecánica de ningún canal ni el contenido de la
matriz: recibe los canales (simulados en este change; reales en C4+) y,
opcionalmente, la consultora de la matriz. Una falla puntual de un ítem nunca
aborta la operación completa.

Identidad del llamante y bitácora (change `auth-caller-obo`, C3):

- La identidad on-behalf-of (`IdentidadLlamante`) se inyecta al construir el
  pipeline o por invocación; alimenta el segundo eje del pre-flight y el campo
  `usuario` de la bitácora de eventos (spec `caller-identity` - "Identidad del
  llamante disponible para la bitácora de eventos").
- Sin identidad, el campo `usuario` se registra explícitamente sin valor y el
  evento se registra igual: la bitácora nunca rechaza actividad por falta de
  identidad.
- Registrar el evento es un efecto lateral de auditoría, no parte del resultado:
  si falla, el pipeline devuelve su reporte y deja constancia del fallo en la
  bitácora de errores cuando está inyectada (degradación controlada, design.md
  D4).
"""

import sys

from control_accesos.dominio.enumeraciones import EstadoItem
from control_accesos.pipeline.ejecutor import Ejecutor
from control_accesos.pipeline.planificador import Planificador
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reportador import Reportador
from control_accesos.pipeline.reporte_lote import AgregadorReporteLote
from control_accesos.pipeline.verificador import Verificador

# Acción canónica con la que el pipeline deja constancia de su actividad en la
# bitácora de eventos (spec `audit-logging` del change `persistencia-bitacora`).
ACCION_PROCESAR_SOLICITUD = "procesar_solicitud_grant"

# Acción canónica del camino de lote (change `grants-batch`, C5): se registra
# un evento por ítem y un evento consolidado del lote (design.md D4).
ACCION_PROCESAR_LOTE = "procesar_lote_grant"

# Módulo que se declara en la bitácora de errores cuando el registro del evento
# falla (mismo criterio que los módulos de autenticación y resolución).
MODULO_BITACORA_ERRORES = "pipeline"

# Operación que se declara en el STRUCT de detalle del error registrado.
CONTEXTO_REGISTRO_EVENTO = "registro del evento de bitácora del pipeline"

# Resultados observables del evento, derivados de los estados finales por ítem.
# Se declaran como constantes para que la interfaz y los reportes los consuman
# sin escribirlos a mano (regla No HardCoded).
RESULTADO_TODO_OTORGADO = "otorgado"
RESULTADO_PARCIAL = "parcial"
RESULTADO_SIN_OTORGADOS = "sin_otorgados"

# Identidad de ejecución del modo broker (change `app-broker-identidad-ejecucion`,
# spec `app-broker-grants` - "Aislamiento entre llamantes y auditoría con usuario
# OBO"): cuando la App ejecuta con la identidad del service principal, el evento
# lo declara en su detalle para distinguirlo de la ejecución OBO del llamante. El
# campo `usuario` sigue siendo la identidad OBO que provocó el cambio.
IDENTIDAD_EJECUCION_APP = "app"
MARCAR_IDENTIDAD_EJECUCION_APP = " | ejecución: identidad de la App"


class PipelineGrants:
    """Orquestador del flujo completo de otorgamiento de grants."""

    def __init__(
        self,
        canal_datos,
        canal_control,
        consultora=None,
        identidad_llamante=None,
        resolutor_privilegios=None,
        registrador_eventos=None,
        registrador_errores=None,
        agregador_lote=None,
        sesion_spark=None,
        identidad_ejecucion=None,
    ):
        """Inicializa el pipeline con sus dependencias inyectadas.

        Args:
            canal_datos (Canal): canal del plano de datos (SQL). En este
                change se inyecta el canal simulado; en C4+ el real.
            canal_control (Canal): canal del plano de control (SDK/REST). En
                este change se inyecta el canal simulado; en C7/C8 el real.
            consultora (ConsultoraMatrizPrivilegios | None): consultora de la
                matriz de compatibilidad. Si es None, se usa la consultora por
                defecto con la matriz declarada en el proyecto.
            identidad_llamante (IdentidadLlamante | None): identidad
                on-behalf-of del llamante resuelta por
                `ServicioIdentidadLlamante`. None cuando no hay llamante
                autenticado (change `auth-caller-obo`); puede sustituirse por
                invocación en `Procesar` y `ProcesarDesdeEntradas`.
            resolutor_privilegios (ResolutorPrivilegiosEfectivos | None):
                resolutor del segundo eje del pre-flight. Si es None, la
                clasificación se limita a la matriz de C1 (retrocompatible).
            registrador_eventos (BitacoraEventos | None): escritor de la
                bitácora de eventos. Si es None, el pipeline no registra
                actividad (comportamiento de C1).
            registrador_errores (BitacoraErrores | None): escritor de la
                bitácora de errores, usado solo si el registro del evento
                falla. Si es None, el fallo se informa por salida de error.
            agregador_lote (object | None): agregador del reporte de lote con el
                puerto `Agregar(reporte) -> ReporteLoteGrant`. Inyectado por la
                composición según la ruta: `AgregadorReporteLote` (PySpark) en
                CLI/lote y `AgregadorReporteLotePython` en la Databricks App
                (change `app-broker-identidad-ejecucion`, F2). Si se aporta,
                tiene prioridad sobre `sesion_spark`. Obligatorio para devolver
                un `ReporteLoteGrant`; el camino 1 a 1 no lo requiere.
            sesion_spark (SparkSession | None): sesión Spark para la agregación
                masiva del reporte de lote de la ruta CLI/lote (design.md D3,
                retrocompatible). Si no hay `agregador_lote`, se construye con
                ella un `AgregadorReporteLote` de PySpark.
            identidad_ejecucion (str | None): identidad con la que se ejecuta el
                cambio. None (por defecto) equivale a OBO (el llamante); en el
                modo broker se pasa `IDENTIDAD_EJECUCION_APP`, de modo que el
                detalle del evento de bitácora declare "identidad de la App"
                mientras el campo `usuario` conserva al llamante OBO (spec
                `app-broker-grants`).

        Raises:
            ErrorDominio: si alguno de los canales no implementa el contrato
                unificado `Canal` (validación del enrutador de las fases).
        """
        # Las fases se componen aquí; cada una recibe lo que necesita y el
        # orquestador solo las secuencia (una fase = una clase, design.md D5).
        self._planificador = Planificador()
        self._pre_flight = PreFlight(
            consultora=consultora, resolutor_privilegios=resolutor_privilegios
        )
        self._ejecutor = Ejecutor(
            canal_datos=canal_datos, canal_control=canal_control
        )
        self._verificador = Verificador(
            canal_datos=canal_datos, canal_control=canal_control
        )
        self._reportador = Reportador()

        # Colaboradores de identidad y auditoría (opcionales: sin ellos el
        # pipeline se comporta exactamente como en C1).
        self._identidad_llamante = identidad_llamante
        self._registrador_eventos = registrador_eventos
        self._registrador_errores = registrador_errores

        # Agregador del reporte de lote (design.md D3): solo se usa en el camino
        # de lote. El inyectado explícito tiene prioridad; si no, se deriva de
        # la sesión Spark (ruta CLI/lote, retrocompatible).
        self._agregador_lote = agregador_lote
        if self._agregador_lote is None and sesion_spark is not None:
            self._agregador_lote = AgregadorReporteLote(sesion=sesion_spark)

        # Identidad con la que se ejecuta el cambio (OBO por defecto; `app` en
        # el modo broker). Solo informa el detalle del evento: nunca sustituye el
        # campo `usuario` (identidad OBO que provocó el cambio).
        self._identidad_ejecucion = identidad_ejecucion

    def Procesar(self, solicitud, identidad_llamante=None):
        """Procesa una solicitud de grant de punta a punta.

        Args:
            solicitud (SolicitudGrant): solicitud validada de cardinalidad
                1 a 1 (un principal, uno o más privilegios, un objeto).
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación; si es None se usa la inyectada
                al construir el pipeline.

        Returns:
            ReporteGrant: reporte consolidado con una línea por ítem: estado
                final, detalle o motivo y trazabilidad de fases.

        Raises:
            ErrorDominio: si la entrada no es una `SolicitudGrant`; no se
                ejecuta ninguna fase.
        """
        items_planificados = self._planificador.Planificar(solicitud)
        return self._ProcesarItems(items_planificados, identidad_llamante)

    def ProcesarDesdeEntradas(self, principal, privilegios, objeto,
                              identidad_llamante=None):
        """Construye la solicitud desde las entradas y la procesa.

        Es el camino que usará la interfaz de usuario (change
        `web-ui-minimalista`, C9): recibe las entradas del formulario,
        construye la solicitud validando su forma y ejecuta el flujo completo.

        Args:
            principal (Principal): entidad que recibe los privilegios.
            privilegios (list[str]): uno o más privilegios a otorgar.
            objeto (ObjetoSecurable): objeto sobre el que se otorgan.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación; si es None se usa la inyectada
                al construir el pipeline.

        Returns:
            ReporteGrant: reporte consolidado del flujo completo.

        Raises:
            ErrorDominio: si la forma de la solicitud es inválida (por
                ejemplo, lista de privilegios vacía); no se genera ningún ítem
                ni se ejecuta fase alguna.
        """
        items_planificados = self._planificador.PlanificarDesdeEntradas(
            principal=principal, privilegios=privilegios, objeto=objeto
        )
        return self._ProcesarItems(items_planificados, identidad_llamante)

    def ProcesarLote(self, solicitud_lote, identidad_llamante=None):
        """Procesa una solicitud de lote de grant de punta a punta.

        Es el punto de entrada del camino de lote (design.md D2): valida la
        solicitud, la normaliza a ítems atómicos y ejecuta el mismo flujo de
        fases `_ProcesarItems` de C1 (pre-flight con split por ítem → ejecución
        ítem a ítem por canal del plano → verificación → reporte por ítem).
        Un fallo puntual nunca aborta el resto del lote (spec
        `batch-grant-operations` - "Resultados parciales por ítem").

        Si se inyectó una sesión Spark al construir el pipeline, el reporte se
        agrega con funciones masivas de PySpark y se devuelve un
        `ReporteLoteGrant` con `total_items` y `totales_por_estado` (design.md
        D3). Sin sesión, se devuelve el `ReporteGrant` base (retrocompatible).

        Args:
            solicitud_lote (SolicitudLoteGrant): solicitud de lote validada de
                cardinalidad 1 a N o N a 1.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación; si es None se usa la inyectada
                al construir el pipeline.

        Returns:
            ReporteLoteGrant | ReporteGrant: reporte consolidado del lote.

        Raises:
            ErrorDominio: si la entrada no es una `SolicitudLoteGrant`; no se
                ejecuta ninguna fase.
        """
        items_planificados = self._planificador.PlanificarLote(solicitud_lote)
        identidad_efectiva = self._IdentidadEfectiva(identidad_llamante)
        reporte = self._ProcesarItems(
            items_planificados, identidad_llamante, accion=ACCION_PROCESAR_LOTE,
            registrar_consolidado=False
        )
        # Registrar eventos por ítem primero, luego el consolidado (design.md D4).
        self._RegistrarEventosPorItem(reporte, identidad_efectiva)
        self._RegistrarEvento(reporte, identidad_efectiva, accion=ACCION_PROCESAR_LOTE)
        return self._AgregarReporteLote(reporte)

    def ProcesarLoteDesdeEntradas(
        self, principales, privilegios, objetos, identidad_llamante=None
    ):
        """Construye el lote desde las entradas y lo procesa.

        Es el camino que usará la interfaz de usuario (change
        `web-ui-minimalista`, C9) para el modo por lote: recibe las entradas
        del formulario, construye la solicitud de lote validando su forma
        (conjuntos vacíos y cardinalidad N a M) y ejecuta el flujo completo.

        Si se inyectó una sesión Spark al construir el pipeline, el reporte se
        agrega con funciones masivas de PySpark y se devuelve un
        `ReporteLoteGrant` con `total_items` y `totales_por_estado` (design.md
        D3). Sin sesión, se devuelve el `ReporteGrant` base (retrocompatible).

        Args:
            principales (list[Principal]): principals del lote.
            privilegios (list[str]): privilegios del lote.
            objetos (list[ObjetoSecurable]): objetos del lote.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación; si es None se usa la inyectada
                al construir el pipeline.

        Returns:
            ReporteLoteGrant | ReporteGrant: reporte consolidado del lote.

        Raises:
            ErrorDominio: si la forma del lote es inválida (por ejemplo,
                cardinalidad N a M o conjuntos vacíos); no se genera ningún
                ítem ni se ejecuta fase alguna.
        """
        items_planificados = self._planificador.PlanificarLoteDesdeEntradas(
            principales=principales, privilegios=privilegios, objetos=objetos
        )
        identidad_efectiva = self._IdentidadEfectiva(identidad_llamante)
        reporte = self._ProcesarItems(
            items_planificados, identidad_llamante, accion=ACCION_PROCESAR_LOTE,
            registrar_consolidado=False
        )
        # Registrar eventos por ítem primero, luego el consolidado (design.md D4).
        self._RegistrarEventosPorItem(reporte, identidad_efectiva)
        self._RegistrarEvento(reporte, identidad_efectiva, accion=ACCION_PROCESAR_LOTE)
        return self._AgregarReporteLote(reporte)

    def _AgregarReporteLote(self, reporte):
        """Agrega el reporte de lote si hay un agregador inyectado.

        Args:
            reporte (ReporteGrant): reporte base con las líneas por ítem.

        Returns:
            ReporteLoteGrant | ReporteGrant: el reporte agregado si hay
                agregador (PySpark en CLI/lote o Python en la App), o el
                reporte base si no (retrocompatible, no agrega totales).
        """
        if self._agregador_lote is None:
            return reporte
        return self._agregador_lote.Agregar(reporte)

    def _ProcesarItems(self, items_planificados, identidad_llamante=None, accion=None, registrar_consolidado=True):
        """Ejecuta las fases pre-flight -> ejecutar -> verificar -> reporte.

        Args:
            items_planificados (list[ItemGrant]): ítems generados por la fase
                de planificación.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación.
            accion (str | None): acción canónica para el evento consolidado de
                bitácora. Si es None, se usa `ACCION_PROCESAR_SOLICITUD`
                (camino 1 a 1); el camino de lote pasa `ACCION_PROCESAR_LOTE`.
            registrar_consolidado (bool): si True, registra el evento
                consolidado al final (camino 1 a 1); si False, no lo registra
                (camino de lote, que registra per-item + consolidado manualmente).

        Returns:
            ReporteGrant: reporte consolidado de la ejecución.
        """
        identidad_efectiva = self._IdentidadEfectiva(identidad_llamante)

        clasificacion = self._pre_flight.Clasificar(
            items_planificados, identidad_llamante=identidad_efectiva
        )

        resultados_ejecutados = self._ejecutor.Ejecutar(
            list(clasificacion.items_ejecutables)
        )

        resultados_verificados = self._verificador.Verificar(
            resultados_ejecutados
        )

        reporte = self._reportador.Reportar(
            items_planificados=items_planificados,
            clasificacion=clasificacion,
            resultados_verificados=resultados_verificados,
        )

        # La auditoría va después del resultado: un fallo de la bitácora no
        # puede dejar a la solicitud sin reporte.
        if registrar_consolidado:
            accion_efectiva = accion if accion is not None else ACCION_PROCESAR_SOLICITUD
            self._RegistrarEvento(reporte, identidad_efectiva, accion=accion_efectiva)

        return reporte

    def _IdentidadEfectiva(self, identidad_llamante):
        """Devuelve la identidad que rige esta invocación.

        La identidad por invocación tiene prioridad sobre la inyectada al
        construir el pipeline, de modo que una misma instancia pueda atender
        varios llamantes (por ejemplo, la interfaz de C9).

        Args:
            identidad_llamante (IdentidadLlamante | None): identidad recibida
                en la invocación.

        Returns:
            IdentidadLlamante | None: la identidad de la invocación, o la del
                pipeline, o None si ninguna existe.
        """
        if identidad_llamante is not None:
            return identidad_llamante
        return self._identidad_llamante

    def _RegistrarEvento(self, reporte, identidad_llamante, accion=None):
        """Deja constancia de la solicitud procesada en la bitácora de eventos.

        El campo `usuario` se alimenta con la identidad on-behalf-of resuelta y
        queda explícitamente sin valor cuando no hay llamante: el evento se
        registra de todos modos (spec `caller-identity` - "Bitácora registra
        evento sin usuario").

        Args:
            reporte (ReporteGrant): resultado consolidado de la solicitud.
            identidad_llamante (IdentidadLlamante | None): identidad que
                provocó el evento.
            accion (str | None): acción canónica del evento. Si es None, se usa
                `ACCION_PROCESAR_SOLICITUD` (camino 1 a 1).
        """
        if self._registrador_eventos is None:
            return

        usuario = (
            identidad_llamante.usuario_bitacora
            if identidad_llamante is not None
            else None
        )
        accion_efectiva = accion if accion is not None else ACCION_PROCESAR_SOLICITUD

        try:
            self._registrador_eventos.Registrar(
                accion=accion_efectiva,
                usuario=usuario,
                detalle=self._DetalleEvento(reporte),
                resultado=self._ResultadoEvento(reporte),
            )
        except Exception as excepcion:  # noqa: BLE001
            # La bitácora nunca es un punto de fallo en cascada: se captura,
            # se deja constancia y el reporte ya calculado se devuelve igual.
            self._RegistrarFalloDeAuditoria(excepcion, usuario)

    def _RegistrarEventosPorItem(self, reporte, identidad_llamante):
        """Registra un evento por ítem del lote en la bitácora de eventos.

        Es el registro por ítem del camino de lote (design.md D4): cada ítem
        produce un evento con la acción canónica `ACCION_PROCESAR_LOTE`, el
        usuario OBO (o None sin identidad), el detalle con principal,
        privilegio, objeto y estado final, y el resultado derivado del estado.

        Args:
            reporte (ReporteGrant): reporte con las líneas por ítem.
            identidad_llamante (IdentidadLlamante | None): identidad que
                provocó los eventos.
        """
        if self._registrador_eventos is None:
            return

        usuario = (
            identidad_llamante.usuario_bitacora
            if identidad_llamante is not None
            else None
        )

        for linea in reporte.lineas:
            try:
                self._registrador_eventos.Registrar(
                    accion=ACCION_PROCESAR_LOTE,
                    usuario=usuario,
                    detalle=self._DetalleEventoPorItem(linea),
                    resultado=linea.estado.value,
                )
            except Exception as excepcion:  # noqa: BLE001
                # Degradación controlada: el fallo de un evento por ítem no
                # aborta los demás ni el reporte ya calculado.
                self._RegistrarFalloDeAuditoria(excepcion, usuario)

    def _DetalleEventoPorItem(self, linea):
        """Construye el detalle del evento por ítem.

        Args:
            linea (LineaReporte): línea del reporte con el ítem y su estado.

        Returns:
            str: texto con principal, privilegio, objeto y estado final.
        """
        item = linea.item
        return (
            f"{item.principal.identificador} - {item.privilegio} - "
            f"{item.objeto.identificador} - {linea.estado.value}"
            f"{self._SufijoIdentidadEjecucion()}"
        )

    def _DetalleEvento(self, reporte):
        """Construye el detalle del evento con el desglose de estados por ítem.

        Args:
            reporte (ReporteGrant): resultado consolidado de la solicitud.

        Returns:
            str: texto con la cantidad de ítems procesados y cuántos quedaron
                en cada estado, por ejemplo
                `2 ítem(s) procesado(s): otorgado=1, fallido=1`.
        """
        conteos_por_estado = {}
        for linea in reporte.lineas:
            estado = linea.estado.value
            conteos_por_estado[estado] = conteos_por_estado.get(estado, 0) + 1

        desglose = ", ".join(
            f"{estado}={cantidad}"
            for estado, cantidad in sorted(conteos_por_estado.items())
        )
        return (
            f"{len(reporte.lineas)} ítem(s) procesado(s): {desglose}"
            f"{self._SufijoIdentidadEjecucion()}"
        )

    def _ResultadoEvento(self, reporte):
        """Deriva el resultado observable del evento desde los estados.

        Args:
            reporte (ReporteGrant): resultado consolidado de la solicitud.

        Returns:
            str: `otorgado` cuando todos los ítems se otorgaron, `parcial`
                cuando solo una parte y `sin_otorgados` cuando ninguno.
        """
        cantidad_otorgados = len(
            reporte.ObtenerLineasPorEstado(EstadoItem.OTORGADO)
        )

        if cantidad_otorgados and cantidad_otorgados == len(reporte.lineas):
            return RESULTADO_TODO_OTORGADO
        if cantidad_otorgados:
            return RESULTADO_PARCIAL
        return RESULTADO_SIN_OTORGADOS

    def _SufijoIdentidadEjecucion(self):
        """Devuelve la marca de ejecución de la App en el detalle (o vacío).

        Solo en el modo broker el detalle del evento declara que la ejecución usó
        la identidad de la App; en OBO (o sin identidad declarada) no se añade
        nada. El campo `usuario` de la bitácora sigue siendo el llamante OBO.

        Returns:
            str: la marca `" | ejecución: identidad de la App"` en modo broker,
                o una cadena vacía en cualquier otro caso.
        """
        if self._identidad_ejecucion == IDENTIDAD_EJECUCION_APP:
            return MARCAR_IDENTIDAD_EJECUCION_APP
        return ""

    def _RegistrarFalloDeAuditoria(self, excepcion, usuario):
        """Registra el fallo del registro del evento sin propagarlo.

        Args:
            excepcion (BaseException): excepción capturada al registrar.
            usuario (str | None): identidad del llamante, si se conoce.
        """
        if self._registrador_errores is None:
            print(
                f"[PIPELINE] El evento de bitácora no pudo registrarse: "
                f"{excepcion}",
                file=sys.stderr,
            )
            return

        try:
            self._registrador_errores.Registrar(
                excepcion,
                modulo=MODULO_BITACORA_ERRORES,
                usuario=usuario,
                contexto=CONTEXTO_REGISTRO_EVENTO,
            )
        except Exception as excepcion_registro:  # noqa: BLE001
            print(
                f"[PIPELINE] El fallo de auditoría no pudo escribirse en la "
                f"bitácora de errores: {excepcion_registro}. Fallo original: "
                f"{excepcion}",
                file=sys.stderr,
            )
