"""Pruebas de aceptación del capability `caller-privilege-resolution`.

Trazabilidad 1:1 con los escenarios del spec delta
`openspec/changes/auth-caller-obo/specs/caller-privilege-resolution/spec.md`:

- Consulta de otorgamientos vigentes por el canal del plano del objeto:
  - Objeto del plano de datos -> TestEscenarioObjetoDelPlanoDeDatos
  - Objeto del plano de control -> TestEscenarioObjetoDelPlanoDeControl
  - Plano sin canal configurado -> TestEscenarioPlanoSinCanalConfigurado
- Emparejamiento de otorgamientos contra las referencias del llamante:
  - Otorgamiento directo al usuario
    -> TestEscenarioOtorgamientoDirectoAlUsuario
  - Otorgamiento a un grupo del llamante
    -> TestEscenarioOtorgamientoAUnGrupoDelLlamante
  - Otorgamiento a un service principal distinto del llamante
    -> TestEscenarioOtorgamientoAUnServicePrincipalDistinto
  - Otorgamiento al App Id del llamante service principal
    -> TestEscenarioOtorgamientoAlAppIdDelLlamanteServicePrincipal
- Compatibilidad de formatos de identificación entre planos:
  - Otorgamiento identificado por referencias del llamante en ambos planos
    -> TestEscenarioReferenciasEmparejanEnAmbosPlanos
- Herencia de otorgamientos reportada por el sistema:
  - Privilegio heredado del padre -> TestEscenarioPrivilegioHeredadoDelPadre
  - Canal que no reporta el origen
    -> TestEscenarioCanalQueNoReportaElOrigen
- Resolución previa a la ejecución:
  - Solicitud con varios ítems -> TestEscenarioSolicitudConVariosItems
- Vista unificada de privilegios efectivos por objeto:
  - Objeto con privilegios efectivos
    -> TestEscenarioObjetoConPrivilegiosEfectivos
  - Objeto sin privilegios efectivos
    -> TestEscenarioObjetoSinPrivilegiosEfectivos
- División de la solicitud según los privilegios del llamante:
  - Ítem con privilegio efectivo -> TestEscenarioItemConPrivilegioEfectivo
  - Ítem sin privilegio efectivo -> TestEscenarioItemSinPrivilegioEfectivo
  - Solicitud mixta -> TestEscenarioSolicitudMixta
  - Llamante sin identidad resuelta
    -> TestEscenarioLlamanteSinIdentidadResuelta
- Mensaje estructurado de privilegios insuficientes:
  - Campos consultables por nombre
    -> TestEscenarioCamposConsultablesPorNombre
  - Texto legible del bloqueo -> TestEscenarioTextoLegibleDelBloqueo
- Errores del resolutor controlados y trazables:
  - Objeto inexistente -> TestEscenarioObjetoInexistente
  - Fallo de transporte o respuesta inválida
    -> TestEscenarioFalloDeTransporteORespuestaInvalida
- La resolución de este change es de solo lectura:
  - Solicitud completa procesada con canales simulados
    -> TestEscenarioSolicitudCompletaConCanalesSimulados

También cubre los criterios del `proposal.md`: resolución ANTES de ejecutar,
split en ítems ejecutables y bloqueados con mensaje de privilegios insuficientes
que indica objeto, privilegio requerido y privilegio faltante, y respeto parcial
de privilegios sin abortar la operación completa. Todo con canales y proveedores
simulados: ninguna escritura llega a un workspace real.
"""

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    APP_ID_DEMO,
    ID_GRUPO_ADMINS_DEMO,
    IDENTIFICADOR_USUARIO_DEMO,
    NOMBRE_GRUPO_ADMINS_DEMO,
    IdentidadServicePrincipal,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio
from control_accesos.resolucion.modelos import (
    PRIVILEGIO_AUTORIZADOR_POR_PLANO,
    MensajePrivilegiosInsuficientes,
)
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Objetos de prueba, uno por plano.
CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
ESQUEMA = ObjetoSecurable(
    identificador="control.finance", tipo=TipoObjeto.ESQUEMA
)
WAREHOUSE = ObjetoSecurable(
    identificador="warehouse_demo", tipo=TipoObjeto.SQL_WAREHOUSE
)

# Beneficiario de los ítems de prueba (distinto del llamante, que es quien debe
# tener autoridad para otorgar).
BENEFICIARIO = "beneficiario"

# Service principal ajeno al llamante, con otorgamientos propios.
APP_ID_AJENO = "11111111-2222-3333-4444-555555555555"

# Privilegios de prueba por plano.
PRIVILEGIO_DATOS = "SELECT"
PRIVILEGIO_CONTROL = "CAN_USE"


class CanalDatosQueRegistra(CanalDatosSimulado):
    """Canal de datos simulado que deja constancia del orden de las operaciones.

    Attributes:
        secuencia (list[tuple]): pares (operación, objeto o ítem) en el orden
            en que ocurrieron, compartida con el canal de control para poder
            afirmar que la resolución precede a la ejecución.
    """

    def __init__(self, secuencia):
        """Inicializa el canal con la secuencia compartida.

        Args:
            secuencia (list[tuple]): lista donde registrar las operaciones.
        """
        super().__init__()
        self.secuencia = secuencia

    def ListarGrantsVigentes(self, objeto):
        """Registra la lectura y delega en el canal simulado.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: grants vigentes del objeto.
        """
        self.secuencia.append(("listar_datos", objeto))
        return super().ListarGrantsVigentes(objeto)

    def EjecutarOtorgamiento(self, item):
        """Registra la escritura y delega en el canal simulado.

        Args:
            item (ItemGrant): ítem otorgado.
        """
        self.secuencia.append(("otorgar_datos", item))
        super().EjecutarOtorgamiento(item)


class CanalControlQueRegistra(CanalControlSimulado):
    """Canal de control simulado que deja constancia de sus operaciones.

    Attributes:
        secuencia (list[tuple]): pares (operación, objeto o ítem) en orden.
    """

    def __init__(self, secuencia):
        """Inicializa el canal con la secuencia compartida.

        Args:
            secuencia (list[tuple]): lista donde registrar las operaciones.
        """
        super().__init__()
        self.secuencia = secuencia

    def ListarGrantsVigentes(self, objeto):
        """Registra la lectura de la ACL y delega en el canal simulado.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: permisos vigentes del objeto.
        """
        self.secuencia.append(("listar_control", objeto))
        return super().ListarGrantsVigentes(objeto)


class CanalQueFallaParaUnObjeto(CanalDatosSimulado):
    """Canal de datos que falla solo al consultar un objeto determinado.

    Permite verificar que un fallo de consulta afecta únicamente a los ítems de
    ese objeto y no al resto de la solicitud.

    Attributes:
        objeto_que_falla (ObjetoSecurable): objeto cuya consulta falla.
    """

    def __init__(self, objeto_que_falla, tipo_error=ErrorCanal):
        """Inicializa el canal con el objeto que fallará y el tipo de error.

        Args:
            objeto_que_falla (ObjetoSecurable): objeto cuya lectura falla.
            tipo_error (Class): excepción a lanzar (`ErrorCanal` para objeto
                inexistente, `RuntimeError` para fallo de transporte,
                `ValueError` para respuesta inválida).
        """
        super().__init__()
        self.objeto_que_falla = objeto_que_falla
        self._tipo_error = tipo_error

    def ListarGrantsVigentes(self, objeto):
        """Falla para el objeto configurado y delega en los demás.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: grants vigentes de los objetos que no fallan.

        Raises:
            Exception: el tipo configurado, para el objeto que falla.
        """
        if objeto == self.objeto_que_falla:
            raise self._tipo_error(
                f"Fallo simulado al consultar {objeto.identificador}"
            )
        return super().ListarGrantsVigentes(objeto)


class EnrutadorSinCanalParaElPlano:
    """Doble de enrutador que reproduce un plano sin canal configurado."""

    def CanalParaObjeto(self, objeto):
        """Lanza siempre: el plano del objeto no tiene canal.

        Args:
            objeto (ObjetoSecurable): objeto a enrutar.

        Returns:
            nunca retorna.

        Raises:
            ErrorDominio: plano sin canal configurado.
        """
        raise ErrorDominio(
            f"El plano {objeto.plano.value} no tiene canal configurado."
        )


class RegistradorErroresEspia:
    """Espía del contrato `BitacoraErrores.Registrar`.

    Attributes:
        registros (list[dict]): llamadas recibidas.
    """

    def __init__(self):
        """Inicializa la lista de registros."""
        self.registros = []

    def Registrar(self, excepcion, modulo=None, usuario=None, contexto=""):
        """Guarda el registro en memoria.

        Args:
            excepcion (BaseException): excepción capturada.
            modulo (str | None): módulo que reporta el fallo.
            usuario (str | None): usuario relacionado con el fallo.
            contexto (str): operación que falló.

        Returns:
            dict: registro guardado.
        """
        registro = {
            "excepcion": excepcion,
            "modulo": modulo,
            "usuario": usuario,
            "contexto": contexto,
        }
        self.registros.append(registro)
        return registro


def IdentidadUsuario():
    """Resuelve la identidad simulada del usuario llamante con sus grupos.

    Returns:
        IdentidadLlamante: identidad de producción resuelta por el servicio.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def IdentidadServicePrincipalDeLaApp():
    """Resuelve la identidad simulada del service principal de la app.

    Returns:
        IdentidadLlamante: identidad de tipo `service_principal` con App Id.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadServicePrincipal())
    ).ObtenerIdentidadLlamante()


# Centinela para pedir un otorgamiento sin atributo `origen` (el canal no lo
# declara), distinto de informar origen=None explícitamente.
_SIN_ORIGEN = object()


def OtorgamientoA(referencia, privilegio, objeto, tipo=TipoPrincipal.USUARIO,
                  origen=_SIN_ORIGEN, heredado_de=None):
    """Construye un otorgamiento vigente como lo reporta un canal.

    Args:
        referencia (str): identificación del otorgatario (correo, nombre de
            grupo, id opaco o App Id).
        privilegio (str): privilegio otorgado.
        objeto (ObjetoSecurable): objeto sobre el que está otorgado.
        tipo (TipoPrincipal): tipo del principal otorgatario.
        origen (str | None): origen que informa el canal (`directo`,
            `heredado`, o None cuando declara no saberlo); por defecto el
            otorgamiento no trae el atributo, como un `ItemGrant` del contrato.
        heredado_de (str | None): securable padre cuando el origen es heredado.

    Returns:
        ItemGrant: otorgamiento vigente, con el origen declarado si aplica.
    """
    if origen is _SIN_ORIGEN:
        return ItemGrant(
            principal=Principal(identificador=referencia, tipo=tipo),
            privilegio=privilegio,
            objeto=objeto,
        )

    class OtorgamientoConOrigen(ItemGrant):
        """Otorgamiento cuyo origen (y padre) declara el canal explícitamente."""

        @property
        def origen(self):
            """Origen informado por el canal.

            Returns:
                str | None: `directo`, `heredado` o None si no lo sabe.
            """
            return origen

        @property
        def heredado_de(self):
            """Securable padre del que viene el otorgamiento.

            Returns:
                str | None: identificación del padre, o None.
            """
            return heredado_de

    return OtorgamientoConOrigen(
        principal=Principal(identificador=referencia, tipo=tipo),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearItem(privilegio, objeto=CATALOGO):
    """Construye un ítem de solicitud de prueba.

    Args:
        privilegio (str): privilegio a otorgar.
        objeto (ObjetoSecurable): objeto objetivo.

    Returns:
        ItemGrant: ítem listo para clasificar.
    """
    return ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearResolutor(canal_datos=None, canal_control=None, enrutador=None,
                   registrador_errores=None):
    """Construye el resolutor de producción con canales simulados.

    Args:
        canal_datos (Canal | None): canal del plano de datos.
        canal_control (Canal | None): canal del plano de control.
        enrutador (object | None): enrutador inyectado (doble).
        registrador_errores (object | None): escritor de la bitácora de errores.

    Returns:
        ResolutorPrivilegiosEfectivos: resolutor listo para resolver.
    """
    return ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos or CanalDatosSimulado(),
        canal_control=canal_control or CanalControlSimulado(),
        enrutador=enrutador,
        registrador_errores=registrador_errores,
    )


def TestEscenarioObjetoDelPlanoDeDatos():
    """Escenario: Objeto del plano de datos.

    WHEN se consultan los otorgamientos vigentes de un objeto del plano de datos
    THEN el sistema usa el canal del plano de datos y obtiene lo que ese canal
         reporta para el objeto.
    """
    secuencia = []
    canal_datos = CanalDatosQueRegistra(secuencia)
    canal_control = CanalControlQueRegistra(secuencia)
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, PRIVILEGIO_DATOS, CATALOGO)]
    )
    resolutor = CrearResolutor(canal_datos, canal_control)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), CATALOGO)

    assert ("listar_datos", CATALOGO) in secuencia
    assert ("listar_control", CATALOGO) not in secuencia, (
        "El plano de datos no se consulta por el canal de control"
    )
    assert vista.TieneElPrivilegio(PRIVILEGIO_DATOS)
    assert vista.plano is Plano.DATOS


def TestEscenarioObjetoDelPlanoDeControl():
    """Escenario: Objeto del plano de control.

    WHEN se consultan los permisos vigentes de un objeto del plano de control
    THEN el sistema usa el canal del plano de control.
    """
    secuencia = []
    canal_datos = CanalDatosQueRegistra(secuencia)
    canal_control = CanalControlQueRegistra(secuencia)
    canal_control.ConfigurarGrantsVigentes(
        WAREHOUSE,
        [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, PRIVILEGIO_CONTROL, WAREHOUSE)],
    )
    resolutor = CrearResolutor(canal_datos, canal_control)

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), WAREHOUSE)

    assert ("listar_control", WAREHOUSE) in secuencia
    assert ("listar_datos", WAREHOUSE) not in secuencia
    assert vista.TieneElPrivilegio(PRIVILEGIO_CONTROL)
    assert vista.plano is Plano.CONTROL


def TestEscenarioPlanoSinCanalConfigurado():
    """Escenario: Plano sin canal configurado.

    WHEN el objeto pertenece a un plano sin canal configurado
    THEN el fallo se reporta de forma controlada y ningún ítem queda ejecutable.
    """
    resolutor = CrearResolutor(enrutador=EnrutadorSinCanalParaElPlano())
    item = CrearItem(PRIVILEGIO_CONTROL, WAREHOUSE)

    with pytest.raises(ErrorDominio):
        resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), WAREHOUSE)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == (), (
        "Sin canal no se puede afirmar autoridad: nada queda ejecutable"
    )
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO


def TestEscenarioOtorgamientoDirectoAlUsuario():
    """Escenario: Otorgamiento directo al usuario.

    WHEN un otorgamiento vigente identifica al propio usuario llamante
    THEN el privilegio figura entre los efectivos del llamante.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "MODIFY", CATALOGO)]
    )

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CATALOGO
    )

    assert vista.TieneElPrivilegio("MODIFY")
    assert vista.ObtenerOtorgamientoDelPrivilegio("MODIFY").otorgatario == (
        IDENTIFICADOR_USUARIO_DEMO
    )


def TestEscenarioOtorgamientoAUnGrupoDelLlamante():
    """Escenario: Otorgamiento a un grupo del llamante.

    WHEN un otorgamiento vigente identifica a un grupo del que el llamante es
         miembro (por identificador opaco o por nombre)
    THEN el privilegio figura entre los efectivos del llamante.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [OtorgamientoA(ID_GRUPO_ADMINS_DEMO, "SELECT", CATALOGO, TipoPrincipal.GRUPO)],
    )
    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(
        WAREHOUSE,
        [
            OtorgamientoA(
                NOMBRE_GRUPO_ADMINS_DEMO,
                "CAN_MANAGE",
                WAREHOUSE,
                TipoPrincipal.GRUPO,
            )
        ],
    )
    resolutor = CrearResolutor(canal_datos, canal_control)
    identidad = IdentidadUsuario()

    assert resolutor.ResolverPrivilegiosEfectivos(
        identidad, CATALOGO
    ).TieneElPrivilegio("SELECT"), "Empareja por identificador opaco del grupo"
    assert resolutor.ResolverPrivilegiosEfectivos(
        identidad, WAREHOUSE
    ).TieneElPrivilegio("CAN_MANAGE"), "Empareja por nombre del grupo"


def TestEscenarioOtorgamientoAUnServicePrincipalDistinto():
    """Escenario: Otorgamiento a un service principal distinto del llamante.

    WHEN un otorgamiento identifica a un service principal que no es el llamante
         y el llamante es un usuario
    THEN el privilegio NO figura entre los efectivos del llamante.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgamientoA(
                APP_ID_AJENO,
                "ALL PRIVILEGES",
                CATALOGO,
                TipoPrincipal.SERVICE_PRINCIPAL,
            )
        ],
    )

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CATALOGO
    )

    assert not vista.TieneElPrivilegio("ALL PRIVILEGES")
    assert vista.privilegios_efectivos == frozenset(), (
        "Los service principals son principales independientes"
    )


def TestEscenarioOtorgamientoAlAppIdDelLlamanteServicePrincipal():
    """Escenario: Otorgamiento al App Id del llamante service principal.

    WHEN el llamante es un service principal y un otorgamiento lo identifica por
         su App Id
    THEN el privilegio figura entre los efectivos del llamante.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgamientoA(
                APP_ID_DEMO, "MANAGE", CATALOGO, TipoPrincipal.SERVICE_PRINCIPAL
            )
        ],
    )

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadServicePrincipalDeLaApp(), CATALOGO
    )

    assert vista.TieneElPrivilegio("MANAGE")
    assert vista.ObtenerOtorgamientoDelPrivilegio(
        "MANAGE"
    ).referencia_coincidente == APP_ID_DEMO


def TestEscenarioReferenciasEmparejanEnAmbosPlanos():
    """Escenario: Otorgamiento identificado por referencias en ambos planos.

    WHEN el llamante es un usuario miembro de grupos y un otorgamiento lo
         referencia por identificador en el plano de datos o por nombre de grupo
         en el plano de control
    THEN ambos casos emparejan con las mismas referencias de identidad.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        ESQUEMA,
        [
            OtorgamientoA(
                ID_GRUPO_ADMINS_DEMO,
                "USE SCHEMA",
                ESQUEMA,
                TipoPrincipal.GRUPO,
            )
        ],
    )
    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(
        WAREHOUSE,
        [
            OtorgamientoA(
                NOMBRE_GRUPO_ADMINS_DEMO,
                "CAN_USE",
                WAREHOUSE,
                TipoPrincipal.GRUPO,
            )
        ],
    )
    resolutor = CrearResolutor(canal_datos, canal_control)
    identidad = IdentidadUsuario()

    vista_datos = resolutor.ResolverPrivilegiosEfectivos(identidad, ESQUEMA)
    vista_control = resolutor.ResolverPrivilegiosEfectivos(identidad, WAREHOUSE)

    assert vista_datos.TieneElPrivilegio("USE SCHEMA")
    assert vista_control.TieneElPrivilegio("CAN_USE")
    assert vista_datos.plano is Plano.DATOS
    assert vista_control.plano is Plano.CONTROL


def TestEscenarioPrivilegioHeredadoDelPadre():
    """Escenario: Privilegio heredado del padre.

    WHEN el canal reporta un otorgamiento del llamante heredado de un padre
    THEN se incluye entre los efectivos y queda constancia de su origen.
    """
    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(
        WAREHOUSE,
        [
            OtorgamientoA(
                NOMBRE_GRUPO_ADMINS_DEMO,
                "CAN_MANAGE",
                WAREHOUSE,
                TipoPrincipal.GRUPO,
                origen=OrigenPrivilegio.HEREDADO.value,
                heredado_de="/sql/warehouses/",
            )
        ],
    )

    vista = CrearResolutor(canal_control=canal_control).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), WAREHOUSE
    )

    assert vista.TieneElPrivilegio("CAN_MANAGE")
    assert vista.ObtenerOrigenDelPrivilegio("CAN_MANAGE") is (
        OrigenPrivilegio.HEREDADO
    )
    assert vista.ObtenerOtorgamientoDelPrivilegio("CAN_MANAGE").heredado_de == (
        "/sql/warehouses/"
    )


def TestEscenarioCanalQueNoReportaElOrigen():
    """Escenario: Canal que no reporta el origen.

    WHEN el canal consultado no informa si un otorgamiento es heredado
    THEN el privilegio es efectivo con origen explícitamente no determinado.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgamientoA(
                IDENTIFICADOR_USUARIO_DEMO,
                "SELECT",
                CATALOGO,
                origen=None,
            )
        ],
    )

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CATALOGO
    )

    assert vista.TieneElPrivilegio("SELECT")
    assert vista.ObtenerOrigenDelPrivilegio("SELECT") is (
        OrigenPrivilegio.NO_DETERMINADO
    ), "No se supone que sea directo cuando el canal no lo dice"


def TestEscenarioSolicitudConVariosItems():
    """Escenario: Solicitud con varios ítems.

    WHEN una solicitud produce varios ítems sobre uno o varios objetos
    THEN se resuelven los privilegios de todos los objetos antes de clasificar o
         ejecutar cualquier ítem.
    """
    secuencia = []
    canal_datos = CanalDatosQueRegistra(secuencia)
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]
    )
    canal_datos.ConfigurarGrantsVigentes(
        ESQUEMA, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", ESQUEMA)]
    )
    resolutor = CrearResolutor(canal_datos, CanalControlQueRegistra(secuencia))
    items = [
        CrearItem("SELECT", CATALOGO),
        CrearItem("USE CATALOG", CATALOGO),
        CrearItem("SELECT", ESQUEMA),
    ]

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        items, identidad_llamante=IdentidadUsuario()
    )

    lecturas = [
        entrada for entrada in secuencia if entrada[0] == "listar_datos"
    ]
    assert {objeto for _, objeto in lecturas} == {CATALOGO, ESQUEMA}, (
        "Todos los objetos involucrados se resuelven durante la clasificación"
    )
    assert not any(
        operacion.startswith("otorgar") for operacion, _ in secuencia
    ), "Ningún ítem se ejecuta antes de resolver los objetos"
    assert len(clasificacion.items_ejecutables) == 2


def TestEscenarioObjetoConPrivilegiosEfectivos():
    """Escenario: Objeto con privilegios efectivos.

    WHEN la consulta devuelve otorgamientos del llamante sobre el objeto
    THEN la vista unificada expone objeto, plano, canal usado y privilegios.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO),
            OtorgamientoA(ID_GRUPO_ADMINS_DEMO, "MODIFY", CATALOGO, TipoPrincipal.GRUPO),
        ],
    )

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CATALOGO
    )

    assert vista.objeto == CATALOGO
    assert vista.plano is Plano.DATOS
    assert vista.canal_consultado, "La vista declara el canal por el que consultó"
    assert set(vista.privilegios_efectivos) == {"SELECT", "MODIFY"}


def TestEscenarioObjetoSinPrivilegiosEfectivos():
    """Escenario: Objeto sin privilegios efectivos.

    WHEN la consulta no devuelve ningún otorgamiento del llamante
    THEN la vista expone una lista explícitamente vacía, distinguible de un fallo.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(CATALOGO, [])

    vista = CrearResolutor(canal_datos).ResolverPrivilegiosEfectivos(
        IdentidadUsuario(), CATALOGO
    )

    assert vista.privilegios_efectivos == frozenset()
    assert vista.otorgamientos == ()
    assert vista.FueConsultaExitosa is True, (
        "El vacío es de privilegios, no un fallo de consulta"
    )


def TestEscenarioItemConPrivilegioEfectivo():
    """Escenario: Ítem con privilegio efectivo.

    WHEN el privilegio está en la matriz y figura entre los efectivos
    THEN el ítem se clasifica como ejecutable y se entrega a la ejecución.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]
    )
    resolutor = CrearResolutor(canal_datos)
    item = CrearItem("SELECT", CATALOGO)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == (item,)
    assert clasificacion.items_bloqueados == ()


def TestEscenarioItemSinPrivilegioEfectivo():
    """Escenario: Ítem sin privilegio efectivo.

    WHEN el privilegio es válido para el tipo de objeto pero no es efectivo
    THEN el ítem queda bloqueado con estado `privilegios_insuficientes`, con su
         mensaje estructurado, y no se envía a ejecución.
    """
    secuencia = []
    canal_datos = CanalDatosQueRegistra(secuencia)
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]
    )
    resolutor = CrearResolutor(canal_datos, CanalControlQueRegistra(secuencia))
    item = CrearItem("MODIFY", CATALOGO)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )
    mensaje = clasificacion.mensaje_de_bloqueo(item)
    assert isinstance(mensaje, MensajePrivilegiosInsuficientes)
    assert mensaje.privilegio_requerido == "MODIFY"
    assert mensaje.privilegio_faltante == PRIVILEGIO_AUTORIZADOR_POR_PLANO[Plano.DATOS]
    assert not any(
        operacion.startswith("otorgar") for operacion, _ in secuencia
    ), "El ítem bloqueado no llega al canal"


def TestEscenarioSolicitudMixta():
    """Escenario: Solicitud mixta.

    WHEN una solicitud contiene ítems con y sin privilegio efectivo
    THEN se entregan ejecutables y bloqueados por separado y la ejecución de los
         ejecutables no se interrumpe.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]
    )
    resolutor = CrearResolutor(canal_datos)
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=CanalControlSimulado(),
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=resolutor,
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT", "MODIFY"],
            objeto=CATALOGO,
        )
    )

    estados = {linea.item.privilegio: linea.estado for linea in reporte.lineas}
    assert estados["SELECT"] is EstadoItem.OTORGADO, (
        "El ítem con autoridad se otorga a pesar del bloqueo del otro"
    )
    assert estados["MODIFY"] is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert len(reporte.lineas) == 2


def TestEscenarioLlamanteSinIdentidadResuelta():
    """Escenario: Llamante sin identidad resuelta.

    WHEN la identidad del llamante no pudo resolverse
    THEN ningún ítem queda ejecutable por este eje y el motivo se reporta.
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO)]
    )
    resolutor = CrearResolutor(canal_datos)
    item = CrearItem("SELECT", CATALOGO)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item], identidad_llamante=None
    )

    assert clasificacion.items_ejecutables == ()
    bloqueado = clasificacion.items_bloqueados[0]
    assert bloqueado.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "identidad" in bloqueado.detalle.lower(), (
        "El motivo explica que no se resolvió la identidad del llamante"
    )


def TestEscenarioCamposConsultablesPorNombre():
    """Escenario: Campos consultables por nombre.

    WHEN un ítem queda bloqueado por privilegios insuficientes
    THEN el dato del bloqueo expone objeto, plano, privilegio requerido y
         faltante como campos independientes.
    """
    mensaje = MensajePrivilegiosInsuficientes(
        objeto=CATALOGO,
        plano=Plano.DATOS,
        privilegio_requerido="MODIFY",
        privilegio_faltante=PRIVILEGIO_AUTORIZADOR_POR_PLANO[Plano.DATOS],
    )

    assert mensaje.objeto == CATALOGO
    assert mensaje.plano is Plano.DATOS
    assert mensaje.privilegio_requerido == "MODIFY"
    assert mensaje.privilegio_faltante == "MANAGE"


def TestEscenarioTextoLegibleDelBloqueo():
    """Escenario: Texto legible del bloqueo.

    WHEN el reporte presenta un ítem bloqueado por privilegios insuficientes
    THEN el texto identifica objeto, plano, privilegio requerido y faltante.
    """
    mensaje = MensajePrivilegiosInsuficientes(
        objeto=WAREHOUSE,
        plano=Plano.CONTROL,
        privilegio_requerido="CAN_MANAGE",
        privilegio_faltante=PRIVILEGIO_AUTORIZADOR_POR_PLANO[Plano.CONTROL],
    )

    texto = mensaje.ComoTexto()

    assert WAREHOUSE.identificador in texto
    assert Plano.CONTROL.value in texto
    assert "CAN_MANAGE" in texto
    assert PRIVILEGIO_AUTORIZADOR_POR_PLANO[Plano.CONTROL] in texto


def TestEscenarioObjetoInexistente():
    """Escenario: Objeto inexistente.

    WHEN el canal responde que el objeto objetivo no existe
    THEN se registra el error controlado y los ítems de ese objeto se clasifican
         como `fallido`, nunca como `privilegios_insuficientes`.
    """
    registrador = RegistradorErroresEspia()
    canal_datos = CanalQueFallaParaUnObjeto(CATALOGO, tipo_error=ErrorCanal)
    resolutor = CrearResolutor(canal_datos, registrador_errores=registrador)
    item = CrearItem("SELECT", CATALOGO)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item], identidad_llamante=IdentidadUsuario()
    )

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO, (
        "Un objeto inexistente no es una falta de privilegios del llamante"
    )
    assert len(registrador.registros) == 1, (
        "El fallo queda registrado en la bitácora de errores"
    )


def TestEscenarioFalloDeTransporteORespuestaInvalida():
    """Escenario: Fallo de transporte o respuesta inválida.

    WHEN el canal falla por transporte o por una respuesta malformada
    THEN se registra el error, los ítems afectados quedan `fallido` y los demás
         continúan su procesamiento.
    """
    registrador = RegistradorErroresEspia()
    canal_datos = CanalQueFallaParaUnObjeto(CATALOGO, tipo_error=RuntimeError)
    canal_datos.ConfigurarGrantsVigentes(
        ESQUEMA, [OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", ESQUEMA)]
    )
    resolutor = CrearResolutor(canal_datos, registrador_errores=registrador)
    item_que_falla = CrearItem("SELECT", CATALOGO)
    item_que_continua = CrearItem("SELECT", ESQUEMA)

    clasificacion = PreFlight(resolutor_privilegios=resolutor).Clasificar(
        [item_que_falla, item_que_continua],
        identidad_llamante=IdentidadUsuario(),
    )

    bloqueados = {
        resultado.item: resultado.estado
        for resultado in clasificacion.items_bloqueados
    }
    assert bloqueados.get(item_que_falla) is EstadoItem.FALLIDO
    assert item_que_continua in clasificacion.items_ejecutables, (
        "El fallo de un objeto no afecta a los demás ítems de la solicitud"
    )
    assert registrador.registros, "El fallo de transporte se registra"


def TestEscenarioSolicitudCompletaConCanalesSimulados():
    """Escenario: Solicitud completa procesada con canales simulados.

    WHEN una solicitud se procesa con la identidad y los canales simulados
    THEN ningún otorgamiento, revocación ni escritura de permisos llega a un
         workspace real: todo queda en el estado en memoria de los simulados.
    """
    secuencia = []
    canal_datos = CanalDatosQueRegistra(secuencia)
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "SELECT", CATALOGO),
            OtorgamientoA(IDENTIFICADOR_USUARIO_DEMO, "MODIFY", CATALOGO),
        ],
    )
    canal_control = CanalControlQueRegistra(secuencia)
    resolutor = CrearResolutor(canal_datos, canal_control)
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=resolutor,
    )

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto=CATALOGO,
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    # La resolución solo leyó; la única escritura es la del canal simulado.
    assert secuencia[0][0] == "listar_datos", (
        "La primera operación del flujo es una lectura de otorgamientos"
    )
    grants_ahora = canal_datos.ListarGrantsVigentes(CATALOGO)
    assert any(
        grant.principal.identificador == BENEFICIARIO for grant in grants_ahora
    ), "El otorgamiento quedó en el estado en memoria del canal simulado"
    assert canal_control.operaciones_ejecutadas == [], (
        "El canal de control no recibió ninguna operación"
    )
