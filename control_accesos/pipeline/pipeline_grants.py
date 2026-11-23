"""Orquestador del flujo de otorgamiento (capability `grant-pipeline`).

`PipelineGrants` compone las cinco fases del flujo
`plan -> pre-flight -> ejecutar -> verificar -> reporte` (README.md -
Arquitectura; spec `grant-pipeline`). Cada fase es una clase independiente con
sus dependencias inyectadas (design.md D5):

- `Planificador`: construye la solicitud y la expande en ítems atómicos.
- `PreFlight`: clasifica los ítems contra la matriz de compatibilidad.
- `Ejecutor`: otorga por el canal del plano del objeto.
- `Verificador`: confirma los otorgamientos contra los grants vigentes.
- `Reportador`: consolida el reporte por ítem con su trazabilidad.

El orquestador no conoce la mecánica de ningún canal ni el contenido de la
matriz: recibe los canales (simulados en este change; reales en C4+) y,
opcionalmente, la consultora de la matriz. Una falla puntual de un ítem nunca
aborta la operación completa.
"""

from control_accesos.pipeline.ejecutor import Ejecutor
from control_accesos.pipeline.planificador import Planificador
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.pipeline.reportador import Reportador
from control_accesos.pipeline.verificador import Verificador


class PipelineGrants:
    """Orquestador del flujo completo de otorgamiento de grants."""

    def __init__(self, canal_datos, canal_control, consultora=None):
        """Inicializa el pipeline con sus dependencias inyectadas.

        Args:
            canal_datos (Canal): canal del plano de datos (SQL). En este
                change se inyecta el canal simulado; en C4+ el real.
            canal_control (Canal): canal del plano de control (SDK/REST). En
                este change se inyecta el canal simulado; en C7/C8 el real.
            consultora (ConsultoraMatrizPrivilegios | None): consultora de la
                matriz de compatibilidad. Si es None, se usa la consultora por
                defecto con la matriz declarada en el proyecto.

        Raises:
            ErrorDominio: si alguno de los canales no implementa el contrato
                unificado `Canal` (validación del enrutador de las fases).
        """
        # Las fases se componen aquí; cada una recibe lo que necesita y el
        # orquestador solo las secuencia (una fase = una clase, design.md D5).
        self._planificador = Planificador()
        self._pre_flight = PreFlight(consultora=consultora)
        self._ejecutor = Ejecutor(
            canal_datos=canal_datos, canal_control=canal_control
        )
        self._verificador = Verificador(
            canal_datos=canal_datos, canal_control=canal_control
        )
        self._reportador = Reportador()

    def Procesar(self, solicitud):
        """Procesa una solicitud de grant de punta a punta.

        Args:
            solicitud (SolicitudGrant): solicitud validada de cardinalidad
                1 a 1 (un principal, uno o más privilegios, un objeto).

        Returns:
            ReporteGrant: reporte consolidado con una línea por ítem: estado
                final, detalle o motivo y trazabilidad de fases.

        Raises:
            ErrorDominio: si la entrada no es una `SolicitudGrant`; no se
                ejecuta ninguna fase.
        """
        items_planificados = self._planificador.Planificar(solicitud)
        return self._ProcesarItems(items_planificados)

    def ProcesarDesdeEntradas(self, principal, privilegios, objeto):
        """Construye la solicitud desde las entradas y la procesa.

        Es el camino que usará la interfaz de usuario (change
        `web-ui-minimalista`, C9): recibe las entradas del formulario,
        construye la solicitud validando su forma y ejecuta el flujo completo.

        Args:
            principal (Principal): entidad que recibe los privilegios.
            privilegios (list[str]): uno o más privilegios a otorgar.
            objeto (ObjetoSecurable): objeto sobre el que se otorgan.

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
        return self._ProcesarItems(items_planificados)

    def _ProcesarItems(self, items_planificados):
        """Ejecuta las fases pre-flight -> ejecutar -> verificar -> reporte.

        Args:
            items_planificados (list[ItemGrant]): ítems generados por la fase
                de planificación.

        Returns:
            ReporteGrant: reporte consolidado de la ejecución.
        """
        clasificacion = self._pre_flight.Clasificar(items_planificados)

        resultados_ejecutados = self._ejecutor.Ejecutar(
            list(clasificacion.items_ejecutables)
        )

        resultados_verificados = self._verificador.Verificar(
            resultados_ejecutados
        )

        return self._reportador.Reportar(
            items_planificados=items_planificados,
            clasificacion=clasificacion,
            resultados_verificados=resultados_verificados,
        )
