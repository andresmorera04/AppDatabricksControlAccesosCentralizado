"""Prueba unitaria del aislamiento y la autorización del modo broker (design.md D2).

Change `app-broker-identidad-ejecucion`, capability `app-broker-grants`.

Contrato que fija esta prueba sobre `AutorizadorBroker`:

- la autoridad del llamante se resuelve leyendo las ACL del plano de control con
  el canal del SP y emparejando con la identidad y los grupos del llamante
  (`ResolutorPrivilegiosEfectivos`, semántica C3 sin cambios);
- una escritura broker con el privilegio autorizador validado (CAN_MANAGE) se
  DELEGA al canal del SP; sin ese privilegio se lanza
  `ErrorPrivilegiosInsuficientes` y la operación NO llega al canal (aunque el SP
  pueda ejecutarla);
- la revalidación al confirmar relee los privilegios vigentes: si cambian entre
  la previsualización y la confirmación, la ejecución bloquea los ítems que ya
  no estén autorizados (TOCTOU);
- dos llamantes no comparten autorización: cada uno se valida con su propia
  identidad, sin cache ni estado compartido.

El canal del SP se simula con `CanalControlSimulado` (registra las operaciones
ejecutadas), lo que permite verificar exactamente qué llega —o no— al workspace.
"""

from control_accesos.autenticacion.modelos import Grupo, IdentidadLlamante
from control_accesos.canales.errores import ErrorPrivilegiosInsuficientes
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ItemGrant, ObjetoSecurable, Principal
from control_accesos.resolucion.autorizador_broker import AutorizadorBroker
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

NOMBRE_GRUPO_ADMINS = "analistas"
USUARIO_CON_GRUPO = "usuario@example.com"
USUARIO_SIN_GRUPO = "externo@example.com"
DESTINO = "destino@example.com"


def _CrearWarehouse():
    """Construye un SQL warehouse del plano de control para las pruebas."""
    return ObjetoSecurable(identificador="wh-1", tipo=TipoObjeto.SQL_WAREHOUSE)


def _GrantDeControl(grupo, privilegio, warehouse):
    """Construye un grant de control (para sembrar la ACL) sobre el objeto."""
    return ItemGrant(
        principal=Principal(identificador=grupo, tipo=TipoPrincipal.GRUPO),
        privilegio=privilegio,
        objeto=warehouse,
    )


def _ItemAEscribir(warehouse, privilegio="CAN_USE"):
    """Construye el ítem de escritura broker (lo que el llamante quiere otorgar)."""
    return ItemGrant(
        principal=Principal(identificador=DESTINO, tipo=TipoPrincipal.USUARIO),
        privilegio=privilegio,
        objeto=warehouse,
    )


def _Identidad(grupo=None):
    """Construye una identidad de llamante, con o sin el grupo de administración."""
    grupos = ()
    if grupo is not None:
        grupos = (Grupo(identificador=grupo, nombre=grupo),)
    return IdentidadLlamante(
        principal=Principal(
            identificador=USUARIO_CON_GRUPO if grupo else USUARIO_SIN_GRUPO,
            tipo=TipoPrincipal.USUARIO,
        ),
        grupos=grupos,
    )


def _ConstruirAutorizador(acl_vigente=()):
    """Construye el autorizador con un canal de control simulado ya sembrado.

    Args:
        acl_vigente (iterable[ItemGrant]): grants que el canal SP reportará como
            vigentes sobre el warehouse.

    Returns:
        tuple: (autorizador, canal_control, warehouse).
    """
    warehouse = _CrearWarehouse()
    canal_control = CanalControlSimulado()
    canal_datos = CanalDatosSimulado()
    if acl_vigente:
        canal_control.ConfigurarGrantsVigentes(warehouse, list(acl_vigente))
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )
    autorizador = AutorizadorBroker(
        canal_control=canal_control, resolutor_privilegios=resolutor
    )
    return autorizador, canal_control, warehouse


def TestEscrituraEjecutadaConPrivilegioDelLlamante():
    """Con CAN_MANAGE del llamante, la escritura se delega al canal del SP."""
    warehouse = _CrearWarehouse()
    acl = (_GrantDeControl(NOMBRE_GRUPO_ADMINS, "CAN_MANAGE", warehouse),)
    autorizador, canal_control, _ = _ConstruirAutorizador(acl_vigente=acl)

    autorizador.EjecutarOtorgamiento(
        _ItemAEscribir(warehouse), _Identidad(grupo=NOMBRE_GRUPO_ADMINS)
    )

    assert [operacion.operacion for operacion in canal_control.operaciones_ejecutadas] == ["otorgar"], (
        "La escritura autorizada se delega al canal del SP exactamente una vez."
    )


def TestEscrituraBloqueadaSinPrivilegioDelLlamante():
    """Sin CAN_MANAGE, la escritura no llega al canal aunque el SP pueda."""
    warehouse = _CrearWarehouse()
    autorizador, canal_control, _ = _ConstruirAutorizador()

    try:
        autorizador.EjecutarOtorgamiento(
            _ItemAEscribir(warehouse), _Identidad(grupo=None)
        )
    except ErrorPrivilegiosInsuficientes:
        pass
    else:
        raise AssertionError("Se esperaba ErrorPrivilegiosInsuficientes.")

    assert canal_control.operaciones_ejecutadas == [], (
        "Sin autoridad del llamante no se ejecuta NADA en el canal del SP "
        "(aunque el SP tenga Workspace admin, design.md D2)."
    )


def TestRevalidacionAlConfirmarBloqueaTrasPerderPrivilegio():
    """La confirmación relee los privilegios: si cambian, bloquea (TOCTOU)."""
    warehouse = _CrearWarehouse()
    acl_original = (_GrantDeControl(NOMBRE_GRUPO_ADMINS, "CAN_MANAGE", warehouse),)
    autorizador, canal_control, _ = _ConstruirAutorizador(acl_vigente=acl_original)

    item = _ItemAEscribir(warehouse)
    identidad = _Identidad(grupo=NOMBRE_GRUPO_ADMINS)

    # Previsualización: autorizado y ejecutado.
    autorizador.EjecutarOtorgamiento(item, identidad)
    assert len(canal_control.operaciones_ejecutadas) == 1

    # Entre previsualización y confirmación el humano retira el privilegio.
    canal_control.ConfigurarGrantsVigentes(warehouse, [])

    with _Espera(ErrorPrivilegiosInsuficientes):
        autorizador.EjecutarOtorgamiento(item, identidad)

    assert len(canal_control.operaciones_ejecutadas) == 1, (
        "La revalidación al confirmar bloqueó la segunda escritura: no llegó "
        "al canal (TOCTOU cubierto, spec - Revalidación al confirmar)."
    )


def TestRevocacionTambienRequiereAutoridad():
    """La revocación broker exige la misma autoridad que el otorgamiento."""
    warehouse = _CrearWarehouse()
    autorizador, canal_control, _ = _ConstruirAutorizador()

    with _Espera(ErrorPrivilegiosInsuficientes):
        autorizador.EjecutarRevocacion(
            _ItemAEscribir(warehouse), _Identidad(grupo=None)
        )
    assert canal_control.operaciones_ejecutadas == []

    acl = (_GrantDeControl(NOMBRE_GRUPO_ADMINS, "CAN_MANAGE", warehouse),)
    canal_control.ConfigurarGrantsVigentes(warehouse, list(acl))
    autorizador.EjecutarRevocacion(
        _ItemAEscribir(warehouse), _Identidad(grupo=NOMBRE_GRUPO_ADMINS)
    )
    assert [op.operacion for op in canal_control.operaciones_ejecutadas] == ["revocar"]


def TestDosLlamantesNoCompartenAutorizacion():
    """Cada llamante se valida con su propia identidad, sin estado compartido."""
    warehouse = _CrearWarehouse()
    acl = (_GrantDeControl(NOMBRE_GRUPO_ADMINS, "CAN_MANAGE", warehouse),)
    autorizador, canal_control, _ = _ConstruirAutorizador(acl_vigente=acl)

    # Llamante A: miembro del grupo administrador -> autorizado.
    autorizador.EjecutarOtorgamiento(
        _ItemAEscribir(warehouse), _Identidad(grupo=NOMBRE_GRUPO_ADMINS)
    )
    # Llamante B: sin grupo -> bloqueado, sin afectar al otro.
    with _Espera(ErrorPrivilegiosInsuficientes):
        autorizador.EjecutarOtorgamiento(
            _ItemAEscribir(warehouse), _Identidad(grupo=None)
        )

    assert len(canal_control.operaciones_ejecutadas) == 1, (
        "Solo la escritura del llamante autorizado llegó al canal; el otro no "
        "compartió autorización."
    )


def TestResolverLeeLaAclConElCanalDelSp():
    """El resolutor evalúa la identidad y los grupos leyendo la ACL del SP."""
    warehouse = _CrearWarehouse()
    acl = (_GrantDeControl(NOMBRE_GRUPO_ADMINS, "CAN_MANAGE", warehouse),)
    canal_control = CanalControlSimulado()
    canal_datos = CanalDatosSimulado()
    canal_control.ConfigurarGrantsVigentes(warehouse, list(acl))
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )

    vista = resolutor.ResolverPrivilegiosEfectivos(
        _Identidad(grupo=NOMBRE_GRUPO_ADMINS), warehouse
    )

    assert vista.TieneElPrivilegio("CAN_MANAGE"), (
        "El privilegio CAN_MANAGE otorgado al grupo del llamante se lee con el "
        "canal del SP y se empareja con su identidad (design.md D2)."
    )


class _Espera:
    """Contexto que falla si el bloque no lanza la excepción esperada."""

    def __init__(self, tipo_excepcion):
        self._tipo_excepcion = tipo_excepcion

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, trazabilidad):
        if tipo is None:
            raise AssertionError(
                f"Se esperaba la excepción {self._tipo_excepcion.__name__}."
            )
        if not issubclass(tipo, self._tipo_excepcion):
            return False
        return True
