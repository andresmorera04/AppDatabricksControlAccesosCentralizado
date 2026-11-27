"""Prueba unitaria del servicio de previsualización de grants de la UI (design.md D8).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.2.

Contrato que fija esta prueba, sobre `Planificador` y `PreFlight` inyectados:

- la previsualización planifica la solicitud según su cardinalidad (1 a 1 con
  `Planificar`, lote con `PlanificarLote`) y delega la clasificación en
  `PreFlight.Clasificar` con la identidad del llamante;
- conserva el split ejecutable/bloqueado con sus motivos (matriz y
  privilegios) y los mensajes estructurados, sin alterarlos;
- todos los ítems bloqueados se devuelven tal cual;
- **ausencia total de llamadas de escritura**: el servicio no invoca
  `PipelineGrants.Procesar*`, ni canales de ACL/SQL, ni ejecutor alguno.
"""

import pytest

from control_accesos.dominio.enumeraciones import Plano, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    ResultadoItem,
    SolicitudGrant,
    SolicitudLoteGrant,
)
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.ui.servicio_previsualizacion import (
    ServicioPrevisualizacionGrants,
)

PRINCIPAL = Principal("usuario.uno@example.com", TipoPrincipal.USUARIO)
CATALOGO = ObjetoSecurable("ventas", TipoObjeto.CATALOGO)


def _Item(privilegio="SELECT", principal=PRINCIPAL, objeto=CATALOGO):
    return ItemGrant(principal=principal, privilegio=privilegio, objeto=objeto)


class PlanificadorEspia:
    """Registra qué método de planificación se invocó y devuelve ítems fijos."""

    def __init__(self, items=()):
        self.items = tuple(items)
        self.metodos = []

    def Planificar(self, solicitud):
        self.metodos.append(("Planificar", solicitud))
        return list(self.items)

    def PlanificarLote(self, solicitud_lote):
        self.metodos.append(("PlanificarLote", solicitud_lote))
        return list(self.items)


class PreFlightEspia:
    """Registra las llamadas a Clasificar y devuelve una clasificación fija."""

    def __init__(self, respuesta=None):
        self.respuesta = respuesta or ClasificacionPreFlight(
            items_ejecutables=(), items_bloqueados=()
        )
        self.metodos = []

    def Clasificar(self, items, identidad_llamante=None):
        self.metodos.append(("Clasificar", tuple(items), identidad_llamante))
        return self.respuesta


def _ClasificacionMixta():
    item_ejecutable = _Item("SELECT")
    item_bloqueado = _Item("MODIFY")
    mensaje = MensajePrivilegiosInsuficientes(
        objeto=CATALOGO,
        plano=Plano.DATOS,
        privilegio_requerido="MODIFY",
        privilegio_faltante="MANAGE",
    )
    return ClasificacionPreFlight(
        items_ejecutables=(item_ejecutable,),
        items_bloqueados=(
            ResultadoItem.PrivilegiosInsuficientes(
                item_bloqueado, causa=mensaje.ComoTexto()
            ),
        ),
        mensajes_por_item={item_bloqueado: mensaje},
    )


def TestPrevisualizacion1A1PlanificaYClasifica():
    """Una solicitud 1 a 1 usa Planificar y delega en Clasificar."""
    identidad = object()
    planificador = PlanificadorEspia(items=[_Item()])
    pre_flight = PreFlightEspia()
    servicio = ServicioPrevisualizacionGrants(planificador, pre_flight)
    solicitud = SolicitudGrant.Crear(PRINCIPAL, ["SELECT"], CATALOGO)

    resultado = servicio.Previsualizar(solicitud, identidad)

    assert resultado is pre_flight.respuesta
    assert planificador.metodos[0][0] == "Planificar"
    assert pre_flight.metodos[0] == ("Clasificar", (_Item(),), identidad)


def TestPrevisualizacionLoteUsaPlanificarLote():
    """Una solicitud de lote usa PlanificarLote."""
    planificador = PlanificadorEspia(items=[_Item()])
    pre_flight = PreFlightEspia()
    servicio = ServicioPrevisualizacionGrants(planificador, pre_flight)
    lote = SolicitudLoteGrant(
        principales=(PRINCIPAL,),
        privilegios=("SELECT",),
        objetos=(CATALOGO, ObjetoSecurable("finanzas", TipoObjeto.CATALOGO)),
    )

    servicio.Previsualizar(lote, object())

    assert planificador.metodos[0][0] == "PlanificarLote"


def TestSplitEjecutablesYBloqueadosConMotivos():
    """El split con motivos (matriz y privilegios) se conserva tal cual."""
    clasificacion = _ClasificacionMixta()
    servicio = ServicioPrevisualizacionGrants(
        PlanificadorEspia(items=[_Item("SELECT"), _Item("MODIFY")]),
        PreFlightEspia(respuesta=clasificacion),
    )

    resultado = servicio.Previsualizar(
        SolicitudGrant.Crear(PRINCIPAL, ["SELECT", "MODIFY"], CATALOGO),
        object(),
    )

    assert resultado.items_ejecutables == clasificacion.items_ejecutables
    assert resultado.items_bloqueados == clasificacion.items_bloqueados
    assert resultado.mensajes_por_item == clasificacion.mensajes_por_item


def TestTodosBloqueadosSeDevuelven():
    """Todos los ítems bloqueados se devuelven sin habilitar ejecución."""

    class PreFlightTodoBloqueado(PreFlightEspia):
        def Clasificar(self, items, identidad_llamante=None):
            self.metodos.append(("Clasificar", tuple(items), identidad_llamante))
            return ClasificacionPreFlight(
                items_ejecutables=(), items_bloqueados=tuple(items)
            )

    servicio = ServicioPrevisualizacionGrants(
        PlanificadorEspia(items=[_Item("MODIFY")]),
        PreFlightTodoBloqueado(),
    )

    resultado = servicio.Previsualizar(
        SolicitudGrant.Crear(PRINCIPAL, ["MODIFY"], CATALOGO), object()
    )

    assert resultado.items_ejecutables == ()
    assert resultado.items_bloqueados == (_Item("MODIFY"),)


def TestNoInvocaEscritura():
    """La previsualización no invoca Procesar* ni canales de escritura."""
    class PreFlightSinEscritura(PreFlightEspia):
        """Solo conoce Clasificar; cualquier método distinto no existe."""

    servicio = ServicioPrevisualizacionGrants(
        PlanificadorEspia(items=[_Item()]), PreFlightSinEscritura()
    )

    servicio.Previsualizar(
        SolicitudGrant.Crear(PRINCIPAL, ["SELECT"], CATALOGO), object()
    )

    # El servicio solo posee colaboradores de solo lectura (planificador y
    # pre-flight): no hay ejecutor ni canal de escritura que invocar.
    assert not hasattr(servicio, "_ejecutor")
    assert not hasattr(servicio, "_pipeline")
