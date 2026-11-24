"""Fase de pre-flight del pipeline (capability `grant-pipeline`).

Segunda fase del flujo `plan -> pre-flight -> ejecutar -> verificar -> reporte`
(README.md - Arquitectura). Evalúa cada ítem contra dos ejes, ANTES de ejecutar
operación alguna (spec `grant-pipeline` - "Fase de pre-flight"):

1. **Matriz de compatibilidad** privilegio x tipo de objeto (capability
   `privilege-matrix`): un privilegio inválido para el tipo de objeto se
   bloquea con el mensaje preciso de la matriz (estado `fallido`).
2. **Privilegios efectivos del llamante** (capability
   `caller-privilege-resolution`, change `auth-caller-obo`): un privilegio
   válido pero que el llamante no puede otorgar se bloquea con estado
   `privilegios_insuficientes` y su mensaje estructurado.

El segundo eje solo opera cuando se inyecta un resolutor: sin él, la fase se
comporta exactamente como en C1 (retrocompatibilidad). El orden importa por
economía y por seguridad: la matriz filtra primero, así no se consulta el
workspace por combinaciones que el dominio ya rechazó.

Ningún bloqueo aborta los demás ítems: los bloqueados pasan directamente al
reporte como `ResultadoItem` (README.md - Solución).
"""

from dataclasses import dataclass, field

from control_accesos.dominio.modelos import ResultadoItem
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.resolucion.errores import ErrorResolucionPrivilegios
from control_accesos.resolucion.modelos import (
    MensajePrivilegiosInsuficientes,
    PRIVILEGIO_AUTORIZADOR_POR_PLANO,
)

# Causa reportada cuando no hay identidad del llamante: sin a quién mirar no
# se afirma ningún privilegio, y así lo dice el bloqueo (fail-safe).
CAUSA_IDENTIDAD_NO_RESUELTA = (
    "privilegios insuficientes: no se resolvió la identidad del llamante "
    "(autenticación on-behalf-of ausente o fallida), por lo que no puede "
    "afirmarse que tenga autoridad para otorgar {privilegio} sobre {objeto}"
)


def _NombreObjeto(objeto):
    """Describe un objeto securable para los mensajes del bloqueo.

    Args:
        objeto (ObjetoSecurable): objeto a describir.

    Returns:
        str: `tipo 'identificador'`.
    """
    return f"{objeto.tipo.value} '{objeto.identificador}'"


@dataclass(frozen=True)
class ClasificacionPreFlight:
    """Resultado de la clasificación de los ítems en la fase de pre-flight.

    Attributes:
        items_ejecutables (tuple[ItemGrant, ...]): ítems que superaron ambos
            ejes de la clasificación y pueden pasar a la fase de ejecución.
        items_bloqueados (tuple[ResultadoItem, ...]): ítems excluidos de la
            ejecución, ya expresados como resultados por ítem (estado `fallido`
            con el mensaje de la matriz, o `privilegios_insuficientes` con el
            mensaje estructurado), listos para incorporarse al reporte.
        mensajes_por_item (dict): ítem bloqueado por privilegios ->
            `MensajePrivilegiosInsuficientes`, para que el reporte y la
            interfaz consulten cada campo en lugar de parsear texto.
    """

    items_ejecutables: tuple
    items_bloqueados: tuple
    mensajes_por_item: dict = field(default_factory=dict)

    def mensaje_de_bloqueo(self, item):
        """Devuelve el mensaje estructurado de un ítem bloqueado.

        Args:
            item (ItemGrant): ítem bloqueado en pre-flight.

        Returns:
            MensajePrivilegiosInsuficientes | None: el dato del bloqueo por
                privilegios, o None si el ítem no tiene mensaje estructurado
                (bloqueos de la matriz de C1).
        """
        return self.mensajes_por_item.get(item)


class PreFlight:
    """Fase que clasifica los ítems contra la matriz y los privilegios."""

    def __init__(self, consultora=None, resolutor_privilegios=None):
        """Inicializa la fase con sus dependencias inyectadas.

        Args:
            consultora (ConsultoraMatrizPrivilegios | None): consultora de la
                matriz de compatibilidad. Si es None, se usa la consultora por
                defecto con la matriz declarada en el proyecto. La inyección
                permite ampliar o restringir la matriz sin tocar esta fase
                (design.md D5: inyección de dependencias por fase).
            resolutor_privilegios (ResolutorPrivilegiosEfectivos | None):
                resolutor del eje de privilegios efectivos del llamante
                (capability `caller-privilege-resolution`). Con None, la fase
                se limita al eje de la matriz, como en C1.
        """
        self._consultora = (
            ConsultoraMatrizPrivilegios() if consultora is None else consultora
        )
        self._resolutor_privilegios = resolutor_privilegios

    def Clasificar(self, items, identidad_llamante=None):
        """Clasifica una lista de ítems en ejecutables y bloqueados.

        Args:
            items (list[ItemGrant]): ítems atómicos generados por la fase de
                planificación.
            identidad_llamante (IdentidadLlamante | None): identidad resuelta
                del llamante para el eje de privilegios efectivos; irrelevante
                si no hay resolutor inyectado.

        Returns:
            ClasificacionPreFlight: los ítems ejecutables (en el orden
                recibido), los bloqueados como resultados por ítem con su
                motivo y, para los bloqueos por privilegios, su mensaje
                estructurado.
        """
        items_ejecutables = []
        items_bloqueados = []

        # --- Eje 1: matriz de compatibilidad privilegio x tipo de objeto. ---
        for item in items:
            if self._consultora.EsCombinacionValida(
                item.privilegio, item.objeto.tipo
            ):
                items_ejecutables.append(item)
                continue

            # Ítem bloqueado por la matriz: se expresa como resultado FALLIDO
            # con el mensaje preciso, y pasa directamente al reporte.
            motivo = self._consultora.MensajeCombinacionInvalida(
                item.privilegio, item.objeto.tipo
            )
            items_bloqueados.append(ResultadoItem.Fallido(item, detalle=motivo))

        # Sin resolutor, el pre-flight es exactamente el de C1.
        if self._resolutor_privilegios is None:
            return ClasificacionPreFlight(
                items_ejecutables=tuple(items_ejecutables),
                items_bloqueados=tuple(items_bloqueados),
            )

        # --- Eje 2: privilegios efectivos del llamante (auth-caller-obo). ---
        return self._AplicarEjeDePrivilegios(
            items_ejecutables, items_bloqueados, identidad_llamante
        )

    def _AplicarEjeDePrivilegios(
        self, items_ejecutables, items_bloqueados, identidad_llamante
    ):
        """Divide los ítems válidos según lo que el llamante puede otorgar.

        Resuelve primero los otorgamientos de **todos** los objetos distintos
        involucrados y solo después clasifica (spec `caller-privilege-
        resolution` - "Resolución previa a la ejecución"), con una consulta por
        objeto.

        Args:
            items_ejecutables (list[ItemGrant]): ítems que pasaron el eje de la
                matriz.
            items_bloqueados (list[ResultadoItem]): bloqueos ya producidos por
                el eje de la matriz, que se conservan.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante; None deja todos los ítems bloqueados por este eje.

        Returns:
            ClasificacionPreFlight: clasificación final del pre-flight.
        """
        resoluciones_por_objeto = self._ResolverObjetos(
            items_ejecutables, identidad_llamante
        )

        ejecutables_finales = []
        bloqueados_por_privilegios = []
        mensajes_por_item = {}

        for item in items_ejecutables:
            if identidad_llamante is None:
                # Sin identidad no se afirma ningún privilegio: fail-safe.
                bloqueados_por_privilegios.append(
                    ResultadoItem.PrivilegiosInsuficientes(
                        item,
                        causa=CAUSA_IDENTIDAD_NO_RESUELTA.format(
                            privilegio=item.privilegio,
                            objeto=_NombreObjeto(item.objeto),
                        ),
                    )
                )
                continue

            resolucion = resoluciones_por_objeto[item.objeto]

            if isinstance(resolucion, ErrorResolucionPrivilegios):
                # No se pudieron consultar los otorgamientos: el ítem falla,
                # pero NO se reporta como privilegios insuficientes (spec).
                bloqueados_por_privilegios.append(
                    ResultadoItem.Fallido(item, detalle=str(resolucion))
                )
                continue

            if resolucion.TieneElPrivilegio(item.privilegio):
                ejecutables_finales.append(item)
                continue

            mensaje = self._ConstruirMensaje(item)
            bloqueados_por_privilegios.append(
                ResultadoItem.PrivilegiosInsuficientes(
                    item, causa=mensaje.ComoTexto()
                )
            )
            mensajes_por_item[item] = mensaje

        return ClasificacionPreFlight(
            items_ejecutables=tuple(ejecutables_finales),
            items_bloqueados=tuple(items_bloqueados) + tuple(bloqueados_por_privilegios),
            mensajes_por_item=mensajes_por_item,
        )

    def _ResolverObjetos(self, items, identidad_llamante):
        """Resuelve los privilegios efectivos de cada objeto distinto.

        Args:
            items (list[ItemGrant]): ítems cuyos objetos se deben resolver.
            identidad_llamante (IdentidadLlamante | None): identidad del
                llamante; None evita cualquier consulta al workspace.

        Returns:
            dict: objeto -> `PrivilegiosEfectivosVista` o la excepción
                `ErrorResolucionPrivilegios` capturada para ese objeto.
        """
        resoluciones = {}
        if identidad_llamante is None:
            return resoluciones

        # `dict.fromkeys` conserva el orden de aparición y elimina duplicados:
        # cada objeto se consulta exactamente una vez por corrida.
        for objeto in dict.fromkeys(item.objeto for item in items):
            try:
                resoluciones[objeto] = (
                    self._resolutor_privilegios.ResolverPrivilegiosEfectivos(
                        identidad_llamante, objeto
                    )
                )
            except ErrorResolucionPrivilegios as error_de_consulta:
                # El fallo de lectura se archiva por objeto para clasificar
                # después solo sus ítems, sin abortar los demás objetos.
                resoluciones[objeto] = error_de_consulta

        return resoluciones

    @staticmethod
    def _ConstruirMensaje(item):
        """Construye el dato del bloqueo por falta de privilegios.

        El privilegio faltante es la autoridad que el llamante necesita sobre
        el objeto para poder otorgar el privilegio solicitado (declarada por
        plano en `PRIVILEGIO_AUTORIZADOR_POR_PLANO`), no el privilegio que la
        solicitud pretende conceder.

        Args:
            item (ItemGrant): ítem bloqueado por este eje.

        Returns:
            MensajePrivilegiosInsuficientes: mensaje estructurado del bloqueo.
        """
        plano = item.objeto.plano
        return MensajePrivilegiosInsuficientes(
            objeto=item.objeto,
            plano=plano,
            privilegio_requerido=item.privilegio,
            # Si el plano no tiene autoridad declarada (no debe ocurrir con
            # los dos planos actuales), se reporta el propio privilegio: así
            # el mensaje nunca afirma un privilegio inventado.
            privilegio_faltante=(
                PRIVILEGIO_AUTORIZADOR_POR_PLANO.get(plano) or item.privilegio
            ),
        )
