"""Fase de ejecución del pipeline (capability `grant-pipeline`).

Tercera fase del flujo `plan -> pre-flight -> ejecutar -> verificar -> reporte`
(README.md - Arquitectura). Envía cada ítem ejecutable al canal que
corresponde al plano de su objeto (spec `grant-pipeline` - "Fase de ejecución
por canal según el plano"):

- Plano de datos (Unity Catalog) -> canal SQL (`CanalDatos`).
- Plano de control (workspace) -> canal SDK/REST (`CanalControl`).

El enrutamiento se delega en `EnrutadorCanales` (mapa declarativo
`Plano -> canal`, design.md D2/D5), compartido con la fase de verificación
para que ambas usen siempre el mismo canal por plano. Los canales se inyectan
por constructor: las pruebas usan los simulados y C4+ inyectará los reales.

Cada ítem produce su propio `ResultadoItem`: el contrato del canal no propaga
excepciones, por lo que un fallo puntual nunca aborta la ejecución de los
demás ítems.
"""

from control_accesos.pipeline.enrutador import EnrutadorCanales


class Ejecutor:
    """Fase que ejecuta los ítems por el canal correspondiente a su plano."""

    def __init__(self, canal_datos, canal_control):
        """Inicializa el ejecutor con los canales de cada plano.

        Args:
            canal_datos (Canal): canal del plano de datos (SQL GRANT/REVOKE).
            canal_control (Canal): canal del plano de control (Permissions API
                / Token Permissions API).

        Raises:
            ErrorDominio: si alguno de los canales recibidos no implementa el
                contrato unificado `Canal` (validación del enrutador).
        """
        self._enrutador = EnrutadorCanales(
            canal_datos=canal_datos, canal_control=canal_control
        )

    def Ejecutar(self, items):
        """Otorga los privilegios de los ítems por su canal correspondiente.

        Args:
            items (list[ItemGrant]): ítems ejecutables (ya clasificados por la
                fase de pre-flight).

        Returns:
            list[ResultadoItem]: un resultado por ítem, en el mismo orden en
                que los ítems fueron recibidos.
        """
        return [
            self._enrutador.CanalParaItem(item).Otorgar(item) for item in items
        ]

    def Revocar(self, items):
        """Revoca los privilegios de los ítems por su canal correspondiente.

        Args:
            items (list[ItemGrant]): ítems a revocar.

        Returns:
            list[ResultadoItem]: un resultado por ítem, en el mismo orden en
                que los ítems fueron recibidos.
        """
        return [
            self._enrutador.CanalParaItem(item).Revocar(item) for item in items
        ]
