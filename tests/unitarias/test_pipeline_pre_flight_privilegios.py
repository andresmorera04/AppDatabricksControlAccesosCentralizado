"""Pruebas unitarias del segundo eje de la fase de pre-flight.

El pre-flight de C1 clasifica contra la matriz de compatibilidad. El change
`auth-caller-obo` le añade el eje de los **privilegios efectivos del
llamante** (spec `caller-privilege-resolution` - "División de la solicitud
según los privilegios del llamante"), sin tocar el eje de la matriz:

- ítem válido en la matriz Y con privilegio efectivo -> ejecutable;
- ítem válido en la matriz PERO SIN privilegio efectivo -> bloqueado con
  estado `privilegios_insuficientes` y su mensaje estructurado;
- un bloqueo nunca aborta los demás ítems (solicitud mixta);
- un ítem inválido en la matriz se bloquea con el motivo de la matriz y **no**
  llega a consultarse el canal;
- la resolución de todos los objetos ocurre antes de clasificar nada;
- sin identidad resuelta no queda ningún ítem ejecutable por este eje;
- un fallo de consulta clasifica el ítem como `fallido`, no como
  `privilegios_insuficientes`;
- sin resolutor inyectado, el comportamiento de C1 queda intacto
  (retrocompatibilidad).
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    ID_GRUPO_ADMINS_DEMO,
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadServicePrincipal,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import EstadoItem, Plano, TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.pipeline.pre_flight import ClasificacionPreFlight, PreFlight
from control_accesos.resolucion.errores import ErrorObjetivoInaccesible
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Objeto del plano de datos usado por la mayoría de las pruebas.
CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
ESQUEMA = ObjetoSecurable(identificador="control.finance", tipo=TipoObjeto.ESQUEMA)
WAREHOUSE = ObjetoSecurable(identificador="wh1", tipo=TipoObjeto.SQL_WAREHOUSE)


def IdentidadUsuario():
    """Devuelve la identidad resuelta de un usuario con grupos.

    Returns:
        IdentidadLlamante: identidad del llamante de prueba.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


def IdentidadApp():
    """Devuelve la identidad del service principal con el que corre la app.

    Returns:
        IdentidadLlamante: identidad de service principal con App Id.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadServicePrincipal())
    ).ObtenerIdentidadLlamante()


def CrearItem(privilegio, objeto=CATALOGO):
    """Construye un ítem de solicitud sobre el objeto indicado.

    Args:
        privilegio (str): privilegio a otorgar.
        objeto (ObjetoSecurable): objetivo del otorgamiento.

    Returns:
        ItemGrant: ítem listo para clasificar.
    """
    return ItemGrant(
        principal=Principal(identificador="beneficiario", tipo=TipoPrincipal.USUARIO),
        privilegio=privilegio,
        objeto=objeto,
    )


def Otorgamiento(principal, privilegio, objeto):
    """Construye un otorgamiento vigente como lo reporta el contrato `Canal`.

    Args:
        principal (str): otorgatario del otorgamiento.
        privilegio (str): privilegio vigente.
        objeto (ObjetoSecurable): objeto del otorgamiento.

    Returns:
        ItemGrant: otorgamiento vigente.
    """
    return ItemGrant(
        principal=Principal(identificador=principal, tipo="usuario"),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearCanalCon(otorgamientos_por_objeto):
    """Crea un canal de datos simulado con otorgamientos configurados.

    Args:
        otorgamientos_por_objeto (dict): objeto -> lista de otorgamientos a
            configurar como vigentes.

    Returns:
        CanalDatosSimulado: canal con el estado del workspace simulado.
    """
    canal = CanalDatosSimulado()
    for objeto, otorgamientos in otorgamientos_por_objeto.items():
        canal.ConfigurarGrantsVigentes(objeto, otorgamientos)
    return canal


def CrearPreFlight(canal_datos=None, canal_control=None):
    """Pre-flight con el eje de privilegios activado por resolutor inyectado.

    Args:
        canal_datos (Canal | None): canal del plano de datos; por defecto sin
            otorgamientos configurados.
        canal_control (Canal | None): canal del plano de control.

    Returns:
        PreFlight: fase con matriz (por defecto) y resolutor de privilegios.
    """
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos or CanalDatosSimulado(),
        canal_control=canal_control or CanalControlSimulado(),
    )
    return PreFlight(resolutor_privilegios=resolutor)


class CanalQueCuentaConsultas(CanalDatosSimulado):
    """Canal que recuerda cuántas veces y con qué objetos fue consultado."""

    def __init__(self, otorgamientos_por_objeto=None):
        """Inicializa el canal y configura los otorgamientos indicados.

        Args:
            otorgamientos_por_objeto (dict | None): objeto -> otorgamientos.
        """
        super().__init__()
        self.consultas = []
        for objeto, otorgamientos in (otorgamientos_por_objeto or {}).items():
            self.ConfigurarGrantsVigentes(objeto, otorgamientos)

    def ListarGrantsVigentes(self, objeto):
        """Registra la consulta y delega en el canal simulado.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: otorgamientos vigentes reportados.
        """
        self.consultas.append(objeto)
        return super().ListarGrantsVigentes(objeto)


class CanalSiempreInaccesible(CanalDatosSimulado):
    """Canal cuya lectura de otorgamientos falla siempre (objeto inaccesible)."""

    def ListarGrantsVigentes(self, objeto):
        """Falla como lo haría un objeto inexistente en el workspace.

        Args:
            objeto (ObjetoSecurable): objeto consultado (no se usa).

        Raises:
            ErrorCanal: objeto inexistente simulado.
        """
        raise ErrorCanal(
            "[SCHEMA_OR_OBJECT_NOT_FOUND] el objeto no existe (simulado)"
        )


def TestItemValidoYConPrivilegioEfectivoQuedaEjecutable():
    """Escenario 'Ítem con privilegio efectivo' del spec del split."""
    canal_datos = CrearCanalCon(
        {CATALOGO: [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]}
    )
    pre_flight = CrearPreFlight(canal_datos=canal_datos)

    clasificacion = pre_flight.Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadUsuario()
    )

    assert len(clasificacion.items_ejecutables) == 1
    assert clasificacion.items_bloqueados == ()


def TestItemValidoSinPrivilegioEfectivoQuedaBloqueado():
    """Escenario 'Ítem sin privilegio efectivo': estado insuficientes."""
    pre_flight = CrearPreFlight()

    clasificacion = pre_flight.Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert len(clasificacion.items_bloqueados) == 1
    resultado = clasificacion.items_bloqueados[0]
    assert resultado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "SELECT" in resultado.detalle


def TestBloqueadoLlevaElMensajeEstructuralPorCampo():
    """El bloqueo expone el mensaje estructurado como dato consultable."""
    clasificacion = CrearPreFlight().Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadUsuario()
    )

    resultado = clasificacion.items_bloqueados[0]
    mensaje = clasificacion.mensaje_de_bloqueo(resultado.item)

    assert mensaje.objeto == CATALOGO
    assert mensaje.plano is Plano.DATOS
    assert mensaje.privilegio_requerido == "SELECT"
    # El llamante no tiene MANAGE sobre el catálogo: esa es la autoridad que
    # le falta para poder otorgar un privilegio a otro principal.
    assert mensaje.privilegio_faltante == "MANAGE"


def TestSolicitudMixtaNoAbortaLosEjecutables():
    """Escenario 'Solicitud mixta': unos ítems siguen, otros se bloquean."""
    canal_datos = CrearCanalCon(
        {
            CATALOGO: [
                Otorgamiento(ID_GRUPO_ADMINS_DEMO, "SELECT", CATALOGO),
            ],
            ESQUEMA: [],
        }
    )
    pre_flight = CrearPreFlight(canal_datos=canal_datos)
    items = [
        CrearItem("SELECT", CATALOGO),
        CrearItem("SELECT", ESQUEMA),
        CrearItem("MODIFY", ESQUEMA),
    ]

    clasificacion = pre_flight.Clasificar(items, identidad_llamante=IdentidadUsuario())

    assert len(clasificacion.items_ejecutables) == 1
    assert clasificacion.items_ejecutables[0].objeto == CATALOGO
    assert len(clasificacion.items_bloqueados) == 2


def TestInvalidoEnMatrizNoConsultaElCanal():
    """Un ítem inválido en la matriz se bloquea sin consultar otorgamientos."""
    canal_datos = CanalQueCuentaConsultas()
    pre_flight = CrearPreFlight(canal_datos=canal_datos)

    clasificacion = pre_flight.Clasificar(
        [CrearItem("CAN_USE", CATALOGO)], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO
    assert canal_datos.consultas == [], (
        "La matriz bloquea antes: no debe consultarse el canal"
    )


def TestResuelveTodosLosObjetosAntesDeClasificar():
    """Escenario 'Resolución previa a la ejecución' del spec.

    Los objetos distintos de la solicitud se resuelven primero; cada objeto se
    consulta una sola vez (caché por objeto), y después se clasifica.
    """
    canal_datos = CanalQueCuentaConsultas(
        {
            CATALOGO: [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)],
            ESQUEMA: [],
        }
    )
    pre_flight = CrearPreFlight(canal_datos=canal_datos)

    clasificacion = pre_flight.Clasificar(
        [
            CrearItem("SELECT", CATALOGO),
            CrearItem("USE CATALOG", CATALOGO),
            CrearItem("SELECT", ESQUEMA),
        ],
        identidad_llamante=IdentidadUsuario(),
    )

    assert canal_datos.consultas == [CATALOGO, ESQUEMA], (
        "Una sola consulta por objeto distinto, antes de clasificar"
    )
    # Solo `SELECT` sobre el catálogo está otorgado al llamante:
    # `USE CATALOG` (mismo catálogo) y `SELECT` sobre el esquema se bloquean.
    assert len(clasificacion.items_ejecutables) == 1
    assert len(clasificacion.items_bloqueados) == 2


def TestFalloDeConsultaClasificaFallidoNoInsuficientes():
    """Objeto inexistente: el ítem se reporta `fallido`, con su detalle."""
    pre_flight = CrearPreFlight(canal_datos=CanalSiempreInaccesible())

    clasificacion = pre_flight.Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadUsuario()
    )

    resultado = clasificacion.items_bloqueados[0]
    assert resultado.estado is EstadoItem.FALLIDO
    assert clasificacion.items_ejecutables == ()
    assert "privilegios_insuficientes" not in resultado.detalle


def TestSinIdentidadNingunItemQuedaEjecutable():
    """Escenario 'Llamante sin identidad resuelta' del spec."""
    canal_datos = CrearCanalCon(
        {CATALOGO: [Otorgamiento(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]}
    )
    pre_flight = CrearPreFlight(canal_datos=canal_datos)

    clasificacion = pre_flight.Clasificar([CrearItem("SELECT")], identidad_llamante=None)

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )
    assert "identidad" in clasificacion.items_bloqueados[0].detalle.lower()


def TestServicienPrincipalPropietarioDeOtorgamientoEsEjecutable():
    """La app con su propio service principal otorga lo que su App Id permite."""
    from control_accesos.autenticacion.simulados import APP_ID_DEMO

    canal_datos = CrearCanalCon(
        {CATALOGO: [Otorgamiento(APP_ID_DEMO, "SELECT", CATALOGO)]}
    )
    pre_flight = CrearPreFlight(canal_datos=canal_datos)

    clasificacion = pre_flight.Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadApp()
    )

    assert len(clasificacion.items_ejecutables) == 1


def TestSinResolutorElComportamientoDeC1SigueIgual():
    """Retrocompatibilidad: sin resolutor, solo actúa la matriz (C1)."""
    clasificacion = PreFlight().Clasificar(
        [CrearItem("SELECT"), CrearItem("CAN_USE")]
    )

    assert len(clasificacion.items_ejecutables) == 1
    assert len(clasificacion.items_bloqueados) == 1
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO


def TestClasificacionVaciaSigueSiendoValida():
    """Sin ítems no hay consultas al canal ni bloqueos."""
    canal_datos = CanalQueCuentaConsultas()
    clasificacion = CrearPreFlight(canal_datos=canal_datos).Clasificar(
        [], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados == ()
    assert canal_datos.consultas == []


def TestClasificacionNuevaTieneMapaDeMensajesVacioPorDefecto():
    """`ClasificacionPreFlight` sigue construyéndose como en C1."""
    clasificacion = ClasificacionPreFlight(
        items_ejecutables=(), items_bloqueados=()
    )

    assert clasificacion.mensajes_por_item == {}
    assert clasificacion.mensaje_de_bloqueo(CrearItem("SELECT")) is None


def TestFallaSiElResolutorDevuelveOtroTipoDError():
    """Un fallo inesperado del resolutor no se convierte en autorización."""

    class ResolutorQueExplota:
        """Doble de resolutor que lanza un error no previsto."""

        def ResolverPrivilegiosEfectivos(self, identidad_llamante, objeto):
            """Lanza siempre un TypeError, como un defecto interno.

            Args:
                identidad_llamante (object): identidad (no se usa).
                objeto (object): objeto (no se usa).

            Returns:
                nunca retorna.

            Raises:
                ErrorObjetivoInaccesible: fallo controlado de consulta.
            """
            raise ErrorObjetivoInaccesible("resolutor mal configurado", objeto=None)

    pre_flight = PreFlight(resolutor_privilegios=ResolutorQueExplota())

    clasificacion = pre_flight.Clasificar(
        [CrearItem("SELECT")], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO
