"""Prueba funcional del split de pre-flight de punta a punta.

Ejercita `PipelineGrants` con identidad on-behalf-of, resolutor de privilegios
y canales simulados, sobre una solicitud que produce las **tres** clases de
resultado por ítem exigidas por el proyecto (README.md - Solución):

- `otorgado`: privilegio válido en la matriz Y efectivo para el llamante;
- `privilegios_insuficientes`: privilegio válido en la matriz PERO NO
  efectivo: queda bloqueado en pre-flight sin llegar al canal;
- `fallido`: privilegio válido y efectivo, pero la ejecución responde con un
  error ajeno a los privilegios (objeto inexistente).

Ningún bloqueo ni fallo aborta los demás ítems, y el bloqueado por privilegios
lleva su mensaje estructurado con objeto, plano, privilegio requerido y
faltante (spec `caller-privilege-resolution` - "Mensaje estructurado de
privilegios insuficientes").

Se usa una sola solicitud 1 a 1 (un principal, varios privilegios, un objeto),
que es la cardinalidad del dominio en C1; las cardinalidades con varios objetos
llegan en C5 (`grants-batch`). El plano de control se cubre con una solicitud
propia sobre un SQL warehouse, para verificar que el eje de privilegios enruta
por el canal del plano del objeto.

No hay conexión externa: los canales son los simulados de `channel-adapters`
(spec `caller-privilege-resolution` - "La resolución de este change es de solo
lectura").
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IDENTIFICADOR_USUARIO_DEMO,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.pipeline.reportador import TRAZABILIDAD_ITINERARIO_BLOQUEADO
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio
from control_accesos.resolucion.modelos import MensajePrivilegiosInsuficientes
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Objetos de prueba: uno por plano, para verificar el enrutamiento del eje.
CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
WAREHOUSE = ObjetoSecurable(
    identificador="warehouse_demo", tipo=TipoObjeto.SQL_WAREHOUSE
)

# Privilegios de la solicitud mixta del plano de datos: uno otorgable, uno sin
# privilegio efectivo del llamante y uno cuya ejecución falla.
PRIVILEGIO_OTORGABLE = "SELECT"
PRIVILEGIO_BLOQUEABLE = "MODIFY"
PRIVILEGIO_FALLIDO = "USE CATALOG"

# Privilegio del plano de control (Permissions API).
PRIVILEGIO_DE_CONTROL = "CAN_USE"

# Principal que recibe los privilegios (distinto del llamante, que es quien
# debe tener autoridad para otorgarlos).
BENEFICIARIO = "beneficiario"

# Autoridad que el sistema exige al llamante por plano (dato declarado en
# `resolucion/modelos.py`), usada aquí para verificar el mensaje estructurado.
AUTORIDAD_ESPERADA_EN_DATOS = "MANAGE"


def IdentidadUsuario():
    """Devuelve la identidad on-behalf-of del usuario de prueba.

    Returns:
        IdentidadLlamante: identidad resuelta desde el proveedor simulado.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        )
    ).ObtenerIdentidadLlamante()


def OtorgarAlLlamante(privilegio, objeto):
    """Construye un otorgamiento vigente a favor del usuario llamante.

    Args:
        privilegio (str): privilegio ya otorgado al llamante.
        objeto (ObjetoSecurable): objeto sobre el que está otorgado.

    Returns:
        ItemGrant: otorgamiento vigente, en el formato del contrato `Canal`.
    """
    return ItemGrant(
        principal=Principal(
            identificador=IDENTIFICADOR_USUARIO_DEMO, tipo="usuario"
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearItem(privilegio, objeto=CATALOGO):
    """Construye un ítem de solicitud de prueba.

    Args:
        privilegio (str): privilegio a otorgar.
        objeto (ObjetoSecurable): objetivo del otorgamiento.

    Returns:
        ItemGrant: ítem listo para procesar.
    """
    return ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def CrearSolicitud(privilegios, objeto=CATALOGO):
    """Construye una solicitud 1 a 1 de prueba.

    Args:
        privilegios (list[str]): privilegios a otorgar.
        objeto (ObjetoSecurable): objeto objetivo de la solicitud.

    Returns:
        SolicitudGrant: solicitud válida para procesar.
    """
    return SolicitudGrant.Crear(
        principal=Principal(
            identificador=BENEFICIARIO, tipo=TipoPrincipal.USUARIO
        ),
        privilegios=list(privilegios),
        objeto=objeto,
    )


def PrepararCanales():
    """Prepara los canales simulados con el estado del workspace.

    Estado configurado:

    - el llamante tiene vigentes `SELECT` y `USE CATALOG` sobre el catálogo,
      pero **no** `MODIFY`: ese ítem debe bloquearse en pre-flight;
    - el ítem `USE CATALOG` fallará al ejecutarse por objeto inexistente
      (error ajeno a los privilegios del llamante);
    - sobre el warehouse, el llamante tiene vigente `CAN_USE`.

    Returns:
        tuple: (canal_datos, canal_control).
    """
    canal_datos = CanalDatosSimulado()
    canal_datos.ConfigurarGrantsVigentes(
        CATALOGO,
        [
            OtorgarAlLlamante(PRIVILEGIO_OTORGABLE, CATALOGO),
            OtorgarAlLlamante(PRIVILEGIO_FALLIDO, CATALOGO),
        ],
    )
    # `MODIFY` no se configura: el llamante no lo tiene vigente.

    # El objeto inexistente se simula por ítem, al momento de ejecutarse.
    canal_datos.ConfigurarEscenario(
        CrearItem(PRIVILEGIO_FALLIDO), EscenarioSimulacion.OBJETO_INEXISTENTE
    )

    canal_control = CanalControlSimulado()
    canal_control.ConfigurarGrantsVigentes(
        WAREHOUSE, [OtorgarAlLlamante(PRIVILEGIO_DE_CONTROL, WAREHOUSE)]
    )

    return canal_datos, canal_control


def CrearPipeline():
    """Compone el pipeline con identidad, resolutor y canales simulados.

    Returns:
        tuple: (pipeline, canal_datos, canal_control).
    """
    canal_datos, canal_control = PrepararCanales()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        ),
    )
    return pipeline, canal_datos, canal_control


def TestSplitProduceLasTresClasesDeResultado():
    """El split divide la solicitud sin abortar la operación completa.

    Escenario "Solicitud mixta" del spec `caller-privilege-resolution`.
    """
    pipeline, _, _ = CrearPipeline()

    reporte = pipeline.Procesar(
        CrearSolicitud(
            [PRIVILEGIO_OTORGABLE, PRIVILEGIO_BLOQUEABLE, PRIVILEGIO_FALLIDO]
        )
    )

    assert len(reporte.lineas) == 3, (
        "Ningún bloqueo ni fallo elimina ítems del reporte"
    )
    assert len(reporte.ObtenerLineasPorEstado(EstadoItem.OTORGADO)) == 1
    assert len(
        reporte.ObtenerLineasPorEstado(EstadoItem.PRIVILEGIOS_INSUFICIENTES)
    ) == 1
    assert len(reporte.ObtenerLineasPorEstado(EstadoItem.FALLIDO)) == 1


def TestBloqueadoPorPrivilegiosNuncaLlegaAlCanal():
    """El ítem sin privilegio efectivo no se ejecuta: se resuelve en pre-flight.

    Escenario "Ítem sin privilegio efectivo" del spec
    `caller-privilege-resolution`.
    """
    pipeline, canal_datos, _ = CrearPipeline()

    pipeline.Procesar(
        CrearSolicitud([PRIVILEGIO_OTORGABLE, PRIVILEGIO_BLOQUEABLE])
    )

    items_ejecutados = [
        operacion.item for operacion in canal_datos.operaciones_ejecutadas
    ]
    assert CrearItem(PRIVILEGIO_BLOQUEABLE) not in items_ejecutados, (
        "Un bloqueo por privilegios no debe enviar instrucciones al canal"
    )
    assert CrearItem(PRIVILEGIO_OTORGABLE) in items_ejecutados, (
        "El ítem con privilegio efectivo sí se entrega a la fase de ejecución"
    )


def TestBloqueadoLlevaMensajeEstructuralCompleto():
    """El reporte expone el bloqueo por privilegios como dato por campo.

    Escenario "Campos consultables por nombre" del spec
    `caller-privilege-resolution`.
    """
    pipeline, _, _ = CrearPipeline()

    reporte = pipeline.Procesar(
        CrearSolicitud([PRIVILEGIO_OTORGABLE, PRIVILEGIO_BLOQUEABLE])
    )

    linea = reporte.ObtenerLineasPorEstado(
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )[0]

    assert isinstance(
        linea.motivo_insuficiencia, MensajePrivilegiosInsuficientes
    )
    assert linea.motivo_insuficiencia.objeto == CATALOGO
    assert linea.motivo_insuficiencia.privilegio_requerido == (
        PRIVILEGIO_BLOQUEABLE
    )
    assert linea.motivo_insuficiencia.privilegio_faltante == (
        AUTORIDAD_ESPERADA_EN_DATOS
    )
    assert PRIVILEGIO_BLOQUEABLE in linea.detalle, (
        "El detalle textual también identifica el privilegio requerido"
    )


def TestBloqueadoSoloLlegaHastaPreFlight():
    """La trazabilidad del bloqueado muestra que jamás fue ejecutado."""
    pipeline, _, _ = CrearPipeline()

    reporte = pipeline.Procesar(
        CrearSolicitud([PRIVILEGIO_OTORGABLE, PRIVILEGIO_BLOQUEABLE])
    )

    linea_bloqueada = reporte.ObtenerLineasPorEstado(
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )[0]
    linea_otorgada = reporte.ObtenerLineasPorEstado(EstadoItem.OTORGADO)[0]

    assert linea_bloqueada.trazabilidad == TRAZABILIDAD_ITINERARIO_BLOQUEADO
    assert len(linea_otorgada.trazabilidad) > len(
        linea_bloqueada.trazabilidad
    ), "El ítem ejecutable continúa su itinerario hasta la verificación"


def TestFalloDeEjecucionNoSeConfundeConFaltaDePrivilegios():
    """El error ajeno a privilegios se reporta como fallido, con su detalle."""
    pipeline, _, _ = CrearPipeline()

    reporte = pipeline.Procesar(CrearSolicitud([PRIVILEGIO_FALLIDO]))

    linea_fallida = reporte.lineas[0]
    assert linea_fallida.estado is EstadoItem.FALLIDO
    assert "no existe" in linea_fallida.detalle
    assert linea_fallida.motivo_insuficiencia is None, (
        "Un fallo de ejecución no produce un mensaje de privilegios"
    )


def TestElEjeDeMatrizSigueBloqueandoPrimero():
    """Un privilegio inválido para el tipo se bloquea por la matriz (C1)."""
    pipeline, canal_datos, _ = CrearPipeline()

    reporte = pipeline.Procesar(CrearSolicitud([PRIVILEGIO_DE_CONTROL]))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert linea.motivo_insuficiencia is None, (
        "El bloqueo de la matriz no es un caso de privilegios insuficientes"
    )
    assert canal_datos.operaciones_ejecutadas == [], (
        "La matriz filtra antes: el canal no recibe ninguna instrucción"
    )


def TestSinIdentidadNadaQuedaEjecutable():
    """Sin identidad OBO el pipeline bloquea todo por el eje de privilegios.

    Escenario "Llamante sin identidad resuelta" del spec
    `caller-privilege-resolution`.
    """
    canal_datos, canal_control = PrepararCanales()
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        ),
    )

    reporte = pipeline.Procesar(CrearSolicitud([PRIVILEGIO_OTORGABLE]))

    assert reporte.lineas[0].estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "identidad" in reporte.lineas[0].detalle.lower(), (
        "El motivo informa que no se resolvió la identidad del llamante"
    )
    assert canal_datos.operaciones_ejecutadas == []


def TestElEjeDePrivilegiosUsaElCanalDelPlanoDeControl():
    """Un objeto del plano de control se resuelve y otorga por su canal.

    Escenario "Objeto del plano de control" del spec
    `caller-privilege-resolution`.
    """
    pipeline, _, canal_control = CrearPipeline()

    reporte = pipeline.Procesar(
        CrearSolicitud([PRIVILEGIO_DE_CONTROL], WAREHOUSE)
    )

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert [
        operacion.item.objeto
        for operacion in canal_control.operaciones_ejecutadas
    ] == [WAREHOUSE], "La ejecución del warehouse va por el canal de control"


def TestSinPrivilegioEfectivoEnControlTambienSeBloquea():
    """El eje de privilegios aplica igual en el plano de control."""
    canal_datos, canal_control = PrepararCanales()
    # El llamante no tiene `CAN_MANAGE` sobre el warehouse.
    pipeline = PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=IdentidadUsuario(),
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        ),
    )

    reporte = pipeline.Procesar(CrearSolicitud(["CAN_MANAGE"], WAREHOUSE))

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert linea.motivo_insuficiencia.privilegio_faltante == "CAN_MANAGE", (
        "En el plano de control la autoridad exigida es CAN_MANAGE"
    )
    assert canal_control.operaciones_ejecutadas == []


def TestOrigenDelPrivilegioEfectivoEsDirecto():
    """La vista marca el otorgamiento del propio objeto como directo."""
    canal_datos, canal_control = PrepararCanales()
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal_datos, canal_control=canal_control
    )

    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), CATALOGO)

    assert vista.ObtenerOrigenDelPrivilegio(PRIVILEGIO_OTORGABLE) is (
        OrigenPrivilegio.DIRECTO
    )


def TestSinResolutorElPipelineConservaElComportamientoDeC1():
    """Sin resolutor inyectado, el split de privilegios no aplica (C1)."""
    canal_datos, canal_control = PrepararCanales()
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=canal_control
    )

    reporte = pipeline.Procesar(CrearSolicitud([PRIVILEGIO_BLOQUEABLE]))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO, (
        "Sin resolutor no hay eje de privilegios: MODIFY se ejecuta igual"
    )
