"""Fase de verificación del pipeline (capability `grant-pipeline`).

Cuarta fase del flujo `plan -> pre-flight -> ejecutar -> verificar -> reporte`
(README.md - Arquitectura). Tras la ejecución, reconsulta los grants vigentes
del objeto por el canal del plano correspondiente (SHOW GRANTS en el plano de
datos; lectura de la ACL en el plano de control) y confirma que el privilegio
quedó efectivamente concedido (spec `grant-pipeline` - "Fase de verificación
posterior al otorgamiento").

Reglas de la fase:

- Solo se verifican los resultados en estado OTORGADO; los resultados FALLIDO
  y PRIVILEGIOS_INSUFICIENTES pasan al reporte sin cambios (no tiene sentido
  reconsultar lo que no se otorgó).
- Si el ítem otorgado aparece en los grants vigentes, se mantiene OTORGADO.
- Cualquier discrepancia (otorgado que no aparece como vigente) se convierte
  en FALLIDO con un detalle preciso que menciona privilegio, principal y
  objeto.
"""

from control_accesos.dominio.enumeraciones import EstadoItem
from control_accesos.dominio.modelos import ResultadoItem
from control_accesos.pipeline.enrutador import EnrutadorCanales


class Verificador:
    """Fase que confirma los otorgamientos contra los grants vigentes."""

    def __init__(self, canal_datos, canal_control):
        """Inicializa el verificador con los canales de consulta por plano.

        Args:
            canal_datos (Canal): canal del plano de datos, usado para reconsultar
                los grants vigentes (equivalente a SHOW GRANTS).
            canal_control (Canal): canal del plano de control, usado para
                reconsultar la ACL del objeto.
        """
        # El mismo enrutador del ejecutor garantiza que la verificación
        # consulte el canal del plano que ejecutó el ítem.
        self._enrutador = EnrutadorCanales(
            canal_datos=canal_datos, canal_control=canal_control
        )

    def Verificar(self, resultados):
        """Verifica los resultados otorgados contra los grants vigentes.

        Args:
            resultados (list[ResultadoItem]): resultados de la fase de
                ejecución, uno por ítem.

        Returns:
            list[ResultadoItem]: un resultado por ítem, en el mismo orden
                recibido. Los OTORGADO confirmados se mantienen; los OTORGADO
                no confirmados se convierten en FALLIDO con el detalle de la
                discrepancia; el resto pasa sin cambios.
        """
        resultados_verificados = []

        for resultado in resultados:
            if resultado.estado is not EstadoItem.OTORGADO:
                # Nada que verificar: lo no otorgado pasa al reporte tal cual.
                resultados_verificados.append(resultado)
                continue

            resultados_verificados.append(
                self._VerificarOtorgado(resultado)
            )

        return resultados_verificados

    def _VerificarOtorgado(self, resultado):
        """Confirma un resultado OTORGADO reconsultando los grants vigentes.

        Args:
            resultado (ResultadoItem): resultado en estado OTORGADO.

        Returns:
            ResultadoItem: el mismo resultado si el grant aparece vigente, o
                un resultado FALLIDO con el detalle de la discrepancia.
        """
        item = resultado.item
        canal = self._enrutador.CanalParaItem(item)
        grants_vigentes = canal.ListarGrantsVigentes(item.objeto)

        if item in grants_vigentes:
            # Confirmado: el privilegio quedó efectivamente concedido.
            return resultado

        return ResultadoItem.Fallido(
            item, detalle=self._MensajeDiscrepancia(item)
        )

    def _MensajeDiscrepancia(self, item):
        """Construye el detalle de una discrepancia de verificación.

        Args:
            item (ItemGrant): ítem otorgado que no apareció como vigente.

        Returns:
            str: mensaje explícito en español con privilegio, principal y
                objeto involucrados.
        """
        return (
            f"Verificación fallida tras el otorgamiento: el privilegio "
            f"{item.privilegio} para el principal "
            f"'{item.principal.identificador}' no aparece en los grants "
            f"vigentes de {item.objeto.tipo.value} "
            f"'{item.objeto.identificador}'."
        )
