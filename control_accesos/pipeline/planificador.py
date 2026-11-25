"""Fase de planificación del pipeline (capability `grant-pipeline`).

Primera fase del flujo `plan -> pre-flight -> ejecutar -> verificar -> reporte`
(README.md - Arquitectura). Construye la solicitud de grant a partir de las
entradas recibidas y la expande en ítems atómicos, que son la unidad de
procesamiento y de reporte de todas las fases siguientes (spec
`grant-pipeline` - "Fase de planificación").
"""

from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    SolicitudGrant,
    SolicitudLoteGrant,
)


class Planificador:
    """Fase que construye la solicitud y la expande en ítems atómicos."""

    def Planificar(self, solicitud):
        """Expande una solicitud de grant en sus ítems atómicos.

        Args:
            solicitud (SolicitudGrant): solicitud validada de cardinalidad
                1 a 1 (un principal, uno o más privilegios, un objeto).

        Returns:
            list[ItemGrant]: un ítem por cada privilegio de la solicitud, en el
                orden en que fueron recibidos.

        Raises:
            ErrorDominio: si la entrada no es una `SolicitudGrant`; no se
                genera ningún ítem.
        """
        if not isinstance(solicitud, SolicitudGrant):
            raise ErrorDominio(
                "La fase de planificación requiere una instancia de "
                f"SolicitudGrant; se recibió {type(solicitud).__name__}."
            )

        # Un ítem atómico por cada privilegio: principal y objeto compartidos.
        return [
            ItemGrant(
                principal=solicitud.principal,
                privilegio=privilegio,
                objeto=solicitud.objeto,
            )
            for privilegio in solicitud.privilegios
        ]

    def PlanificarDesdeEntradas(self, principal, privilegios, objeto):
        """Construye la solicitud desde las entradas y la expande en ítems.

        Es el punto de entrada del pipeline para las entradas recibidas desde
        la interfaz de usuario (change `web-ui-minimalista`, C9): la
        construcción valida la forma de la solicitud antes de generar ítems.

        Args:
            principal (Principal): entidad que recibe los privilegios.
            privilegios (list[str]): uno o más privilegios a otorgar.
            objeto (ObjetoSecurable): objeto sobre el que se otorgan.

        Returns:
            list[ItemGrant]: ítems atómicos de la solicitud.

        Raises:
            ErrorDominio: si la forma de la solicitud es inválida (por ejemplo,
                lista de privilegios vacía); no se genera ningún ítem.
        """
        solicitud = SolicitudGrant.Crear(
            principal=principal, privilegios=privilegios, objeto=objeto
        )
        return self.Planificar(solicitud)

    def PlanificarDesdeConjuntos(self, principales, privilegios, objetos):
        """Valida la cardinalidad de los conjuntos recibidos y planifica.

        Punto de entrada explícito de validación de cardinalidad antes de
        cualquier ejecución (spec `grant-domain-model`): la cardinalidad N a M
        se rechaza con mensaje explícito, y las cardinalidades 1 a N y N a 1
        se procesarán como varias solicitudes 1 a 1 en el change
        `grants-batch` (C5).

        Args:
            principales (list[Principal]): principals recibidos.
            privilegios (list[str]): privilegios recibidos.
            objetos (list[ObjetoSecurable]): objetos recibidos.

        Returns:
            list[ItemGrant]: ítems atómicos de la solicitud 1 a 1.

        Raises:
            ErrorDominio: si la cardinalidad no es 1 a 1; no se genera ningún
                ítem ni se ejecuta fase alguna.
        """
        solicitud = SolicitudGrant.CrearDesdeConjuntos(
            principales=principales, privilegios=privilegios, objetos=objetos
        )
        return self.Planificar(solicitud)

    def PlanificarLote(self, solicitud_lote):
        """Valida el lote y lo normaliza a ítems atómicos.

        Es la fase de planificación del camino de lote (design.md D2): valida
        que la entrada sea una `SolicitudLoteGrant` y delega la normalización
        en el modelo, que produce los ítems atómicos recorriendo el eje
        múltiple en orden de entrada (spec `batch-grant-operations` -
        "Normalización de lotes a ítems atómicos").

        Args:
            solicitud_lote (SolicitudLoteGrant): solicitud de lote validada de
                cardinalidad 1 a N o N a 1.

        Returns:
            list[ItemGrant]: ítems atómicos del lote en orden determinístico.

        Raises:
            ErrorDominio: si la entrada no es una `SolicitudLoteGrant`; no se
                genera ningún ítem.
        """
        if not isinstance(solicitud_lote, SolicitudLoteGrant):
            raise ErrorDominio(
                "La fase de planificación de lote requiere una instancia de "
                f"SolicitudLoteGrant; se recibió {type(solicitud_lote).__name__}."
            )
        return solicitud_lote.NormalizarAItems()

    def PlanificarLoteDesdeEntradas(self, principales, privilegios, objetos):
        """Construye el lote desde las entradas y lo normaliza a ítems.

        Es el punto de entrada del pipeline para las entradas recibidas desde
        la interfaz de usuario (change `web-ui-minimalista`, C9) en el camino
        de lote: la construcción valida la forma del lote (conjuntos vacíos y
        cardinalidad N a M) antes de generar ítems (spec `batch-grant-operations`
        - "Validación de la solicitud por lote" y "Rechazo explícito de
        cardinalidad N a M").

        Args:
            principales (list[Principal]): principals del lote.
            privilegios (list[str]): privilegios del lote.
            objetos (list[ObjetoSecurable]): objetos del lote.

        Returns:
            list[ItemGrant]: ítems atómicos del lote en orden determinístico.

        Raises:
            ErrorDominio: si la forma del lote es inválida (conjuntos vacíos o
                cardinalidad N a M); no se genera ningún ítem ni se ejecuta
                fase alguna.
        """
        solicitud_lote = SolicitudLoteGrant(
            principales=principales, privilegios=privilegios, objetos=objetos
        )
        return self.PlanificarLote(solicitud_lote)
