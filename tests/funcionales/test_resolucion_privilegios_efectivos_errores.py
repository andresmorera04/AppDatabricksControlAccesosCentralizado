"""Pruebas funcionales de los errores del resolutor de privilegios efectivos.

Cubren el escenario "Errores del resolutor controlados y trazables" del spec
`caller-privilege-resolution` (change `auth-caller-obo`) con el escritor de
producción `BitacoraErrores` sobre Spark local + Delta:

- objeto inexistente, fallo de transporte y respuesta inválida del sistema
  externo se capturan, se registran en `bitacora_errores` con su `STRUCT` y
  se propagan como `ErrorObjetivoInaccesible`, que la fase de pre-flight
  traduce a estado `fallido` (nunca a `privilegios_insuficientes`);
- un fallo de consulta no deja al resolutor en un estado que impida resolver
  el siguiente objeto ("sin afectar al resto de los ítems de la solicitud");
- la lectura denegada NO es un error de consulta: degrada a vista sin
  privilegios, de forma fail-safe, sin abortar nada.

La clasificación concreta de los ítems como `fallido` se verifica de extremo
a extremo en `test_split_pre_flight_funcional.py`.
"""

import pytest

from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.autenticacion.simulados import (
    IdentidadUsuarioConGrupos,
    ProveedorIdentidadSimulado,
)
from control_accesos.canales.errores import (
    ErrorCanal,
    ErrorPrivilegiosInsuficientes,
)
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.persistencia.capa_persistencia import CapaPersistencia
from control_accesos.persistencia.ddl import ESQUEMA_APLICACION
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.resolucion.errores import (
    ErrorIdentidadNoResuelta,
    ErrorObjetivoInaccesible,
)
from control_accesos.resolucion.resolutor import (
    MODULO_BITACORA_ERRORES,
    ResolutorPrivilegiosEfectivos,
)

# Catálogo de Spark local con Delta (igual que las funcionales de C2).
CATALOGO_LOCAL = "spark_catalog"

# Nombre calificado de la bitácora de errores para las consultas de prueba.
TABLA_ERRORES = f"{CATALOGO_LOCAL}.{ESQUEMA_APLICACION}.bitacora_errores"

# Marcadores únicos por prueba: la tabla de errores es común a la corrida.
MARCAS_DE_PRUEBA = {
    "objeto_inexistente": "OBJETO_INEXISTENTE_PRUEBA_FUNCIONAL_C3",
    "transporte": "ERROR_DE_TRANSPORTE_PRUEBA_FUNCIONAL_C3",
    "respuesta_invalida": "RESPUESTA_INVALIDA_PRUEBA_FUNCIONAL_C3",
    "lectura_denegada": "LECTURA_DENEGADA_PRUEBA_FUNCIONAL_C3",
}


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


def IdentidadUsuario():
    """Devuelve la identidad resuelta del usuario de prueba.

    Returns:
        IdentidadLlamante: identidad con sus grupos.
    """
    return ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadSimulado(contexto=IdentidadUsuarioConGrupos())
    ).ObtenerIdentidadLlamante()


class CanalQueFallaAlListar(CanalDatosSimulado):
    """Canal simulado cuya lectura de otorgamientos falla con lo configurado.

    En lugar de subclases por prueba, el error se configura por instancia:
    así el mensaje único de cada prueba (que la identifica en la bitácora)
    viaja como dato, no como nombre de clase.

    Attributes:
        veces_que_falla (int): cuántas consultas deben fallar (None = todas).
    """

    def __init__(self, marca, tipo_error=ErrorCanal, veces_que_falla=None):
        """Configura el error que el canal lanzará al listar otorgamientos.

        Args:
            marca (str): texto único de la prueba, incluido en el mensaje del
                error para poder localizar su fila en `bitacora_errores`.
            tipo_error (Class): tipo de excepción a lanzar (`ErrorCanal` para
                objeto inexistente, `ErrorPrivilegiosInsuficientes` para
                lectura denegada, u otro para transporte/respuesta inválida).
            veces_que_falla (int | None): cuántas consultas fallan; None hace
                que fallen todas.
        """
        super().__init__()
        self._marca = marca
        self._tipo_error = tipo_error
        self.veces_que_falla = veces_que_falla
        self.consultas_recibidas = 0

    def ListarGrantsVigentes(self, objeto):
        """Falla mientras quede presupuesto de fallos, o delega lo normal.

        Args:
            objeto (ObjetoSecurable): objeto consultado.

        Returns:
            list[ItemGrant]: otorgamientos del canal simulado, cuando la
                consulta ya no debe fallar.

        Raises:
            ErrorCanal | ErrorPrivilegiosInsuficientes | Exception: el error
                configurado, con la marca de la prueba en el mensaje.
        """
        self.consultas_recibidas += 1

        debe_fallar = (
            self.veces_que_falla is None or self.consultas_recibidas <= self.veces_que_falla
        )
        if debe_fallar:
            raise self._tipo_error(f"{self._marca}: fallo simulado del canal")

        return super().ListarGrantsVigentes(objeto)


def ConsultarFilasPorMarca(sesion_spark, marca):
    """Devuelve las filas de la bitácora cuyo mensaje contiene la marca.

    Args:
        sesion_spark: sesión Spark local de la corrida.
        marca (str): marcador único de la prueba dentro del mensaje del error.

    Returns:
        list: filas del registro de errores coincidentes.
    """
    return sesion_spark.sql(
        f"SELECT modulo, usuario, detalle.tipo_excepcion AS tipo, "
        f"detalle.mensaje AS mensaje, detalle.contexto AS contexto "
        f"FROM {TABLA_ERRORES} "
        f"WHERE detalle.mensaje LIKE '%{marca}%'"
    ).collect()


@pytest.mark.parametrize(
    "clave_marca,tipo_error",
    [
        ("objeto_inexistente", ErrorCanal),
        ("transporte", ConnectionError),
        ("respuesta_invalida", ValueError),
    ],
    ids=["objeto-inexistente", "error-de-transporte", "respuesta-invalida"],
)
def TestFalloDeConsultaSeRegistraYSePropagaComoInaccesible(
    sesion_spark, tmp_path, clave_marca, tipo_error
):
    """Escenarios 'Objeto inexistente' y 'Fallo de transporte o respuesta inválida'.

    El resolutor captura el fallo, lo registra con su `STRUCT` y lo propaga
    como `ErrorObjetivoInaccesible`, que el pipeline reporta como `fallido`.
    """
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)
    marca = MARCAS_DE_PRUEBA[clave_marca]

    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=CanalQueFallaAlListar(marca=marca, tipo_error=tipo_error),
        canal_control=CanalControlSimulado(),
        registrador_errores=bitacora,
    )

    with pytest.raises(ErrorObjetivoInaccesible) as error:
        resolutor.ResolverPrivilegiosEfectivos(
            IdentidadUsuario(),
            ObjetoSecurable(identificador="control.finance", tipo=TipoObjeto.ESQUEMA),
        )

    # El error identificado es de accesibilidad, no de privilegios: pre-flight
    # debe clasificar el ítem como fallido, nunca como insuficientes.
    assert "privilegios_insuficientes" not in str(error.value)
    assert error.value.objeto is not None

    filas = ConsultarFilasPorMarca(sesion_spark, marca)
    assert len(filas) == 1, "Cada fallo de consulta se registra una sola vez"
    assert filas[0]["modulo"] == MODULO_BITACORA_ERRORES
    assert filas[0]["tipo"] == tipo_error.__name__
    assert "otorgamientos" in filas[0]["contexto"]


def TestTrasUnFalloSePuedeResolverOtroObjeto(sesion_spark, tmp_path):
    """Escenario 'sin afectar al resto': el resolutor sigue utilizable.

    Un fallo de consulta no deja estado corrupto: la siguiente consulta del
    mismo plano se resuelve con normalidad.
    """
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)
    marca = MARCAS_DE_PRUEBA["transporte"]

    # Solo la primera consulta falla: la segunda ya debe responder normal.
    canal = CanalQueFallaAlListar(
        marca=marca, tipo_error=ErrorCanal, veces_que_falla=1
    )
    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=canal,
        canal_control=CanalControlSimulado(),
        registrador_errores=bitacora,
    )
    objeto_ok = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)

    with pytest.raises(ErrorObjetivoInaccesible):
        resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto_ok)

    # Ahora el canal responde: la misma identidad y el mismo objeto se
    # resuelven sin rastro del fallo anterior.
    vista = resolutor.ResolverPrivilegiosEfectivos(IdentidadUsuario(), objeto_ok)

    assert vista.FueConsultaExitosa is True
    assert vista.privilegios_efectivos == frozenset()


def TestLecturaDenegadaDegradaASinPrivilegiosSinAbortar(sesion_spark, tmp_path):
    """Permiso denegado al leer: cero privilegios afirmados, sin excepción.

    La ausencia de evidencia de privilegios nunca se interpreta como
    autorización: la vista queda vacía y `FueConsultaExitosa` en False, y el
    hecho queda registrado para auditoría.
    """
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)
    marca = MARCAS_DE_PRUEBA["lectura_denegada"]

    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=CanalQueFallaAlListar(
            marca=marca, tipo_error=ErrorPrivilegiosInsuficientes
        ),
        canal_control=CanalControlSimulado(),
        registrador_errores=bitacora,
    )

    vista = resolutor.ResolverPrivilegiosEfectivos(
        IdentidadUsuario(),
        ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO),
    )

    assert vista.privilegios_efectivos == frozenset()
    assert vista.FueConsultaExitosa is False

    filas = ConsultarFilasPorMarca(sesion_spark, marca)
    assert len(filas) == 1
    assert filas[0]["tipo"] == "ErrorPrivilegiosInsuficientes"


def TestSinIdentidadSeRegistraErrorYNoSeAfirmanPrivilegios(sesion_spark, tmp_path):
    """Escenario 'identidad no resuelta': error registrado y excepcion propia."""
    bitacora = PrepararBitacoraErrores(sesion_spark, tmp_path)

    resolutor = ResolutorPrivilegiosEfectivos(
        canal_datos=CanalDatosSimulado(),
        canal_control=CanalControlSimulado(),
        registrador_errores=bitacora,
    )

    with pytest.raises(ErrorIdentidadNoResuelta):
        resolutor.ResolverPrivilegiosEfectivos(
            None, ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
        )

    filas = sesion_spark.sql(
        f"SELECT detalle.mensaje AS mensaje FROM {TABLA_ERRORES} "
        f"WHERE modulo = '{MODULO_BITACORA_ERRORES}' "
        f"AND detalle.mensaje LIKE '%identidad del llamante%'"
    ).collect()

    assert len(filas) == 1, "La identidad ausente se registra una sola vez"
