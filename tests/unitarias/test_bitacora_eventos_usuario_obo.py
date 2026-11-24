"""Pruebas unitarias del campo `usuario` de la bitácora con identidad OBO.

Cubren el escenario "Bitácora registra usuario del llamante" del spec
`audit-logging` de C2, que queda satisfecho en este change
(`caller-identity` - "Identidad del llamante disponible para la bitácora de
eventos"):

- con identidad on-behalf-of resuelta, el evento se registra con el
  identificador del llamante en `usuario`;
- sin identidad, el evento se registra con `usuario` explícitamente nulo y
  **no** se rechaza: la bitácora sigue grabando la actividad;
- la identidad del service principal de la app se registra con su nombre
  (el App Id viaja en las referencias, no en el campo `usuario`);
- un fallo del escritor de bitácora no aborta el pipeline.

Se usa un escritor simulado (espía) porque el objetivo es qué se le pasa al
campo `usuario`, no la escritura delta (eso ya lo cubre C2 y la prueba
funcional del flujo lo repite con el escritor real).
"""

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IdentidadServicePrincipal,
    IdentidadUsuarioConGrupos,
    NOMBRE_SERVICE_PRINCIPAL_DEMO,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal, SolicitudGrant
from control_accesos.pipeline.pipeline_grants import ACCION_PROCESAR_SOLICITUD
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

CATALOGO = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)


class EscritorEventosEspia:
    """Espía del contrato `BitacoraEventos.Registrar`.

    Attributes:
        eventos (list[dict]): llamadas recibidas, con accion, usuario,
            detalle y resultado.
    """

    def __init__(self):
        """Inicializa la lista de eventos recibidos."""
        self.eventos = []

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        """Guarda el evento en memoria en lugar de escribirlo en una tabla.

        Args:
            accion (str): acción realizada por la aplicación.
            usuario (str | None): usuario que provocó el evento.
            detalle (str | None): detalle libre del evento.
            resultado (str | None): resultado observable del evento.

        Returns:
            dict: el evento guardado por el espía.
        """
        evento = {
            "accion": accion,
            "usuario": usuario,
            "detalle": detalle,
            "resultado": resultado,
        }
        self.eventos.append(evento)
        return evento


class EscritorEventosQueFalla:
    """Espía que falla al registrar, para probar la degradación controlada."""

    def __init__(self):
        """Inicializa el contador de intentos."""
        self.intentos = 0

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        """Lanza siempre, imitando un destino de bitácora inaccesible.

        Returns:
            nunca retorna.

        Raises:
            RuntimeError: la bitácora no está disponible.
        """
        self.intentos += 1
        raise RuntimeError("bitácora de eventos inaccesible (simulado)")


def IdentidadUsuario():
    """Devuelve la identidad resuelta del usuario de prueba.

    Returns:
        IdentidadLlamante: identidad con identificador conocido.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


def CrearSolicitud(privilegios=("SELECT",)):
    """Construye una solicitud 1 a 1 de prueba sobre el catálogo.

    Args:
        privilegios (tuple[str, ...]): privilegios a otorgar.

    Returns:
        SolicitudGrant: solicitud válida para procesar.
    """
    return SolicitudGrant.Crear(
        principal=Principal(identificador="beneficiario", tipo=TipoPrincipal.USUARIO),
        privilegios=list(privilegios),
        objeto=CATALOGO,
    )


def CrearPipeline(registrador_eventos=None, identidad_llamante=None):
    """Construye el pipeline con canales simulados en escenario de éxito.

    Args:
        registrador_eventos (object | None): escritor de eventos a inyectar.
        identidad_llamante (IdentidadLlamante | None): identidad del llamante.

    Returns:
        PipelineGrants: orquestador listo para procesar solicitudes.
    """
    canal_datos = CanalDatosSimulado()
    canal_control = CanalControlSimulado()
    return PipelineGrants(
        canal_datos=canal_datos,
        canal_control=canal_control,
        identidad_llamante=identidad_llamante,
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        ),
        registrador_eventos=registrador_eventos,
    )


def TestEventoRegistraUsuarioConIdentidadResuelta():
    """Escenario 'Bitácora registra usuario del llamante'."""
    bitacora = EscritorEventosEspia()

    CrearPipeline(registrador_eventos=bitacora, identidad_llamante=IdentidadUsuario()).Procesar(
        CrearSolicitud()
    )

    assert len(bitacora.eventos) == 1
    assert bitacora.eventos[0]["usuario"] == "usuario_demo@example.com"
    assert bitacora.eventos[0]["accion"] == ACCION_PROCESAR_SOLICITUD


def TestEventoRegistraUsuarioNuloSinIdentidad():
    """Escenario 'Bitácora registra evento sin usuario': nulo explícito, no se rechaza."""
    bitacora = EscritorEventosEspia()

    CrearPipeline(registrador_eventos=bitacora).Procesar(CrearSolicitud())

    assert len(bitacora.eventos) == 1, "El evento se registra aunque no haya identidad"
    assert bitacora.eventos[0]["usuario"] is None, (
        "Sin identidad OBO el campo usuario queda explícitamente sin valor"
    )


def TestUsuarioRegistradoEsElServicePrincipalDeLaApp():
    """La app con su propia identidad registra al service principal."""
    bitacora = EscritorEventosEspia()
    identidad_app = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadServicePrincipal())
    ).ObtenerIdentidadLlamante()

    CrearPipeline(registrador_eventos=bitacora, identidad_llamante=identidad_app).Procesar(
        CrearSolicitud()
    )

    assert bitacora.eventos[0]["usuario"] == NOMBRE_SERVICE_PRINCIPAL_DEMO


def TestFalloDeBitacoraNoAbortaElPipeline():
    """Un fallo del escritor no interrumpe el flujo (degradación controlada)."""
    bitacora = EscritorEventosQueFalla()

    reporte = CrearPipeline(registrador_eventos=bitacora).Procesar(CrearSolicitud())

    assert bitacora.intentos == 1, "Se intenta registrar una sola vez"
    assert reporte.lineas, "El pipeline produjo su reporte a pesar del fallo"


def TestSinBitacoraInyectadaElPipelineFuncionaIgual():
    """Sin bitácora inyectada (configuración de C1) el flujo no cambia."""
    reporte = CrearPipeline().Procesar(CrearSolicitud())

    assert len(reporte.lineas) == 1


def TestEventoIncluyeConteoDeResultados():
    """El detalle del evento describe los estados obtenidos por ítem."""
    bitacora = EscritorEventosEspia()

    CrearPipeline(registrador_eventos=bitacora, identidad_llamante=IdentidadUsuario()).Procesar(
        CrearSolicitud(privilegios=("SELECT", "MODIFY"))
    )

    detalle = bitacora.eventos[0]["detalle"]
    assert "2" in detalle, "El detalle informa la cantidad de ítems procesados"
    assert bitacora.eventos[0]["resultado"], "El evento reporta un resultado observable"
