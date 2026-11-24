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
from control_accesos.pipeline.verificador import Verificador

# Acción canónica con la que el pipeline deja constancia de su actividad en la
# bitácora de eventos (spec `audit-logging` del change `persistencia-bitacora`).
ACCION_PROCESAR_SOLICITUD = "procesar_solicitud_grant"

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

    def _ProcesarItems(self, items_planificados, identidad_llamante=None):
        """Ejecuta las fases pre-flight -> ejecutar -> verificar -> reporte.

        Args:
            items_planificados (list[ItemGrant]): ítems generados por la fase
                de planificación.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante para esta invocación.

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
        self._RegistrarEvento(reporte, identidad_efectiva)

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

    def _RegistrarEvento(self, reporte, identidad_llamante):
        """Deja constancia de la solicitud procesada en la bitácora de eventos.

        El campo `usuario` se alimenta con la identidad on-behalf-of resuelta y
        queda explícitamente sin valor cuando no hay llamante: el evento se
        registra de todos modos (spec `caller-identity` - "Bitácora registra
        evento sin usuario").

        Args:
            reporte (ReporteGrant): resultado consolidado de la solicitud.
            identidad_llamante (IdentidadLlamante | None): identidad que
                provocó el evento.
        """
        if self._registrador_eventos is None:
            return

        usuario = (
            identidad_llamante.usuario_bitacora
            if identidad_llamante is not None
            else None
        )

        try:
            self._registrador_eventos.Registrar(
                accion=ACCION_PROCESAR_SOLICITUD,
                usuario=usuario,
                detalle=self._DetalleEvento(reporte),
                resultado=self._ResultadoEvento(reporte),
            )
        except Exception as excepcion:  # noqa: BLE001
            # La bitácora nunca es un punto de fallo en cascada: se captura,
            # se deja constancia y el reporte ya calculado se devuelve igual.
            self._RegistrarFalloDeAuditoria(excepcion, usuario)

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
        return f"{len(reporte.lineas)} ítem(s) procesado(s): {desglose}"

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
