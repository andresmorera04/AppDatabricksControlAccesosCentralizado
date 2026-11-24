"""Prueba funcional de la autenticación on-behalf-of (capability `caller-identity`).

Verifica el escenario "Errores de autenticación visibles y controlados" del
spec `caller-identity` con el escritor de producción `BitacoraErrores` sobre
Spark local + Delta (misma infraestructura que las funcionales de C2):

- un fallo del proveedor de contexto (token ausente o expirado, servicio no
  disponible) se captura con `try/except`, se registra en `bitacora_errores`
  con el `DetalleError` STRUCT completo y deja la identidad explícitamente sin
  resolver, **sin propagar excepción** al pipeline;
- el identificador vacío del llamante se registra como fallo controlado;
- una resolución exitosa no escribe ningún error nuevo en la bitácora.

El contexto on-behalf-of llega por `ProveedorIdentidadSimulado`: no hay
conexión a workspace alguno (spec `caller-privilege-resolution` - "La
resolución de este change es de solo lectura").

Nota de aislamiento: la sesión Spark y la tabla `bitacora_errores` son
compartidas por toda la corrida (fixture de sesión, design.md D3 de C2), así
que cada prueba identifica SUS filas por un marcador único en el mensaje del
error, en lugar de contar la tabla completa.
"""

from control_accesos.autenticacion.modelos import ContextoLlamante
from control_accesos.autenticacion.servicio import (
    MODULO_BITACORA_ERRORES,
    ServicioIdentidadLlamante,
)
from control_accesos.autenticacion.simulados import (
    ContextoConFallo,
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import TipoPrincipal
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Catálogo de Spark local con Delta (igual que las funcionales de C2).
CATALOGO_LOCAL = "spark_catalog"

# Nombre calificado de la bitácora de errores para las consultas de prueba.
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"


def PrepararBitacoraErrores(sesion_spark, tmp_path):
    """Inicializa la persistencia local y devuelve el escritor de errores.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        tmp_path (Path): directorio temporal de la prueba.

    Returns:
        BitacoraErrores: escritor real contra la tabla delta local.
    """
    import json

    from control_accesos.bitacora.escritores import BitacoraErrores

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8")
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)
    InicializadorPersistencia(
        sesion=sesion_spark, configuracion=configuracion
    ).Inicializar()
    capa = CapaPersistencia(sesion=sesion_spark, configuracion=configuracion)
    return BitacoraErrores(sesion=sesion_spark, capa=capa)


class ProveedorQueFalla(ProveedorIdentidadSimulado):
    """Proveedor simulado que lanza una excepción con un mensaje único.

    Simula el fallo del entorno de ejecución de la Databricks App al leer el
    contexto on-behalf-of del usuario.
    """

    # Marcador que identifica el mensaje de esta prueba en la bitácora.
    MARCA = "MARCA_PRUEBA_FUNCIONAL_OBO"

    def ObtenerContexto(self):
        """Falla siempre, con un mensaje reconocible en la bitácora.

        Returns:
            ContextoLlamante | None: nunca retorna: siempre lanza.

        Raises:
            RuntimeError: fallo simulado del servicio de identidad, con la
                marca única de la prueba en el mensaje.
        """
        raise RuntimeError(f"{self.MARCA}: fallo simulado del entorno OBO")


def TestFalloDeTokenSeRegistraConDetalleStructSinPropagar(sesion_spark, tmp_path):
    """Escenario 'Token de usuario inválido o ausente': error controlado.

    El fallo del proveedor se captura, se escribe en la bitácora de errores
    con el STRUCT completo (tipo, mensaje, traza y contexto) y el servicio
    devuelve la identidad sin resolver, sin propagar la excepción al llamador.
    """
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    class ProveedorTokenExpirado(ProveedorQueFalla):
        """Proveedor que falla como lo haría un token OBO expirado."""

        MARCA = "TOKEN_EXPIRED_PRUEBA_OBO"

    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorTokenExpirado(), registrador_errores=bitacora
    )

    # El fallo NO se propaga: la operación principal continúa.
    assert servicio.ObtenerIdentidadLlamante() is None, (
        "El fallo de token deja la identidad sin resolver."
    )

    filas = sesion_spark.sql(
        f"SELECT * FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}' "
        f"AND detalle.mensaje LIKE '%{ProveedorTokenExpirado.MARCA}%'"
    ).collect()

    assert len(filas) == 1, (
        "El fallo de autenticación debe quedar registrado exactamente una vez"
    )
    guardado = filas[0]
    assert guardado.usuario is None, (
        "Sin identidad resuelta, el error se registra sin usuario"
    )

    detalle = guardado.detalle
    assert detalle.tipo_excepcion == "RuntimeError"
    assert ProveedorTokenExpirado.MARCA in detalle.mensaje
    assert "ObtenerContexto" in detalle.traza, (
        "La traza registrada debe ser la traza real de la excepción lanzada"
    )
    assert "on-behalf-of" in detalle.contexto, (
        "El contexto del STRUCT debe describir la operación que falló"
    )


def TestIdentificadorVacioSeRegistraComoFalloControlado(sesion_spark, tmp_path):
    """Escenario 'Identificador del llamante vacío': queda registrado."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    # Contexto malformado, como lo devolvería la plataforma: sin identificador.
    contexto_sin_identificador = ContextoLlamante(
        tipo=TipoPrincipal.USUARIO,
        identificador="   ",
        nombre_mostrable="Usuario Demo",
    )

    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=contexto_sin_identificador),
        registrador_errores=bitacora,
    )

    assert servicio.ObtenerIdentidadLlamante() is None

    fila = sesion_spark.sql(
        f"SELECT detalle.tipo_excepcion AS tipo, detalle.mensaje AS mensaje "
        f"FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}' "
        f"AND detalle.tipo_excepcion = 'ErrorContextoLlamanteAusente'"
    ).collect()

    assert len(fila) == 1, (
        "Solo esta prueba produce un contexto sin identificador"
    )
    assert "identificador" in fila[0]["mensaje"].lower()


def TestServicioNoDisponibleSeRegistraSinAbortar(sesion_spark, tmp_path):
    """El fallo de servicio no aborta: se registra y la identidad queda vacía."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)
    marca = "SERVICIO_NO_DISPONIBLE_PRUEBA_OBO"

    servicio = ServicioIdentidadLlamante(
        proveedor=ContextoConFallo(marca),
        registrador_errores=bitacora,
    )

    assert servicio.ObtenerIdentidadLlamante() is None
    assert servicio.IdentidadResuelta is False

    cantidad = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {TABLA_ERRORES} "
        f"WHERE detalle.mensaje LIKE '%{marca}%'"
    ).collect()[0]["n"]
    assert cantidad == 1


def TestIdentidadResueltaNoEscribeErrores(sesion_spark, tmp_path):
    """Un llamante autenticado no debe escribir en la bitácora de errores."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    # La tabla es común a la corrida: se compara el conteo antes y después.
    antes = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {TABLA_ERRORES}"
    ).collect()[0]["n"]

    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(
            contexto=IdentidadUsuarioConGrupos()
        ),
        registrador_errores=bitacora,
    )

    assert servicio.IdentidadResuelta is True
    assert len(servicio.ObtenerGruposLlamante()) == 2

    despues = sesion_spark.sql(
        f"SELECT COUNT(*) AS n FROM {TABLA_ERRORES}"
    ).collect()[0]["n"]
    assert despues == antes, (
        "Una resolución exitosa no debe escribir en la bitácora de errores"
    )


def TestFalloDeBitacoraNoAbortaLaResolucion(sesion_spark, tmp_path):
    """Si la propia bitácora falla, la identidad sigue degradando controlada.

    No hay registro recursivo: el fallo se reporta en la salida local y el
    servicio devuelve identidad sin resolver (degradación de C2, design.md D7).
    """

    class RegistradorQueExplota:
        """Espía que falla al registrar, imitando un destino inaccesible."""

        def __init__(self):
            """Inicializa el contador de intentos."""
            self.intentos = 0

        def Registrar(self, excepcion, modulo, usuario=None, contexto=""):
            """Lanza siempre, para provocar el fallo del registrador.

            Raises:
                RuntimeError: destino de bitácora inaccesible.
            """
            self.intentos += 1
            raise RuntimeError("destino de bitácora inaccesible (simulado)")

    registrador = RegistradorQueExplota()
    servicio = ServicioIdentidadLlamante(
        proveedor=ProveedorQueFalla(), registrador_errores=registrador
    )

    assert servicio.ObtenerIdentidadLlamante() is None
    assert registrador.intentos == 1, (
        "El fallo se intenta registrar una sola vez, sin reintentos recursivos"
    )
