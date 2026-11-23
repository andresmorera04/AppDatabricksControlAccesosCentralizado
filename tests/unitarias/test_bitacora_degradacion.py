"""Prueba unitaria de la degradación controlada de los escritores de bitácora.

Change C2 (`persistencia-bitacora`), design.md D7: la bitácora no puede ser un
punto único de fallo en cascada. Cuando la escritura de una bitácora falla por
una causa externa (destino caído, sesión inutilizable), el escritor:

- NO propaga la excepción (la ejecución principal continúa);
- deja constancia visible del fallo en la salida local (stderr);
- NO intenta registrar ese fallo en la propia bitácora (sin recursión).

Estas pruebas son unitarias: no arrancan Spark. La sesión y la capa de
persistencia se simulan con dobles que fallan a propósito; los esquemas son
`StructType` reales (pyspark.sql.types es Python puro, no requiere JVM).
"""

import sys

import pytest
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

from control_accesos.bitacora.escritores import (
    BitacoraErrores,
    BitacoraEventos,
)
from control_accesos.persistencia.errores import ErrorEscrituraPersistencia

# Esquemas simulados de las tablas de bitácora (mismos campos que el DDL; el
# orden es irrelevante para la prueba porque la sesión simulada no escribe).
ESQUEMA_EVENTOS_SIMULADO = StructType(
    [
        StructField("id_evento", StringType(), False),
        StructField("marca_tiempo", TimestampType(), False),
        StructField("usuario", StringType(), True),
        StructField("accion", StringType(), False),
        StructField("detalle", StringType(), True),
        StructField("resultado", StringType(), True),
    ]
)
ESQUEMA_ERRORES_SIMULADO = StructType(
    [
        StructField("id_error", StringType(), False),
        StructField("marca_tiempo", TimestampType(), False),
        StructField("usuario", StringType(), True),
        StructField("modulo", StringType(), False),
        StructField("detalle", StringType(), False),
    ]
)


class TablaSimulada:
    """Tabla simulada que solo expone su esquema (nunca se escribe)."""

    def __init__(self, esquema):
        self.schema = esquema


class MarcoSimulado:
    """DataFrame simulado: marcador opaco que la capa simulada rechaza."""


class SesionSimulada:
    """Sesión Spark simulada para las pruebas unitarias de degradación.

    Args:
        esquema (StructType): esquema que devuelve `table(...).schema`.
        falla_al_crear_marco (bool): si es True, `createDataFrame` lanza un
            error (simula una sesión inutilizable).
    """

    def __init__(self, esquema, falla_al_crear_marco=False):
        self.esquema = esquema
        self.falla_al_crear_marco = falla_al_crear_marco

    def table(self, nombre_calificado):
        return TablaSimulada(self.esquema)

    def createDataFrame(self, filas, esquema):
        if self.falla_al_crear_marco:
            raise RuntimeError("sesion inutilizable: no se pudo crear el marco")
        return MarcoSimulado()


class CapaSimuladaQueFalla:
    """Capa de persistencia simulada cuya escritura falla siempre.

    Cuenta los intentos de escritura para verificar que el fallo NO se
    re-registra de forma recursiva (design.md D7).

    Args:
        error (Exception): excepción que lanza en cada intento de escritura.
    """

    def __init__(self, error):
        self.error = error
        self.intentos_escritura = 0

    def NombreTablaCalificado(self, nombre_tabla):
        return f"simulado.esquema_simulado.{nombre_tabla}"

    def EscribirConIntegridad(self, marco, nombre_tabla, claves_primarias=()):
        self.intentos_escritura += 1
        raise self.error


def TestFalloDeEscrituraDeEventosNoPropagaExcepcion(capsys):
    """El fallo al escribir un evento no interrumpe la ejecución principal."""
    capa = CapaSimuladaQueFalla(
        ErrorEscrituraPersistencia("destino caido: tabla inaccesible")
    )
    bitacora = BitacoraEventos(
        sesion=SesionSimulada(ESQUEMA_EVENTOS_SIMULADO), capa=capa
    )

    # No debe lanzar ninguna excepción hacia el llamador.
    evento = bitacora.Registrar(accion="accion_con_bitacora_caida")

    assert evento.accion == "accion_con_bitacora_caida", (
        "El escritor debe devolver el evento construido aunque la escritura "
        "haya fallado"
    )
    salida_error = capsys.readouterr().err
    assert "destino caido" in salida_error, (
        "El fallo debe quedar visible en la salida local (stderr) con su "
        "detalle"
    )


def TestFalloDeEscrituraDeErroresNoPropagaExcepcion(capsys):
    """El fallo al registrar un error no interrumpe la ejecución principal."""
    capa = CapaSimuladaQueFalla(
        ErrorEscrituraPersistencia("destino caido: tabla inaccesible")
    )
    bitacora = BitacoraErrores(
        sesion=SesionSimulada(ESQUEMA_ERRORES_SIMULADO), capa=capa
    )

    try:
        raise ValueError("error original de la operacion")
    except ValueError as excepcion:
        # No debe lanzar ninguna excepción hacia el llamador.
        registro = bitacora.Registrar(
            excepcion=excepcion, modulo="modulo_de_prueba"
        )

    assert registro.detalle.tipo_excepcion == "ValueError", (
        "El escritor debe devolver el registro construido aunque la escritura "
        "haya fallado"
    )
    salida_error = capsys.readouterr().err
    assert "destino caido" in salida_error, (
        "El fallo debe quedar visible en la salida local (stderr)"
    )


def TestFalloNoSeRegistraDeFormaRecursiva():
    """El fallo de la bitácora no debe reintentar escribir en la bitácora."""
    capa = CapaSimuladaQueFalla(
        ErrorEscrituraPersistencia("destino caido: tabla inaccesible")
    )
    bitacora = BitacoraErrores(
        sesion=SesionSimulada(ESQUEMA_ERRORES_SIMULADO), capa=capa
    )

    try:
        raise ValueError("error original de la operacion")
    except ValueError as excepcion:
        bitacora.Registrar(excepcion=excepcion, modulo="modulo_de_prueba")

    assert capa.intentos_escritura == 1, (
        "Debe haber exactamente un intento de escritura: el fallo NO debe "
        "re-registrarse en la propia bitácora (anti-recursión, design.md D7)"
    )


def TestSesionInutilizableTambienDegrada(capsys):
    """Una sesión que falla al construir el marco también degrada sin propagar."""
    capa = CapaSimuladaQueFalla(
        ErrorEscrituraPersistencia("destino caido: tabla inaccesible")
    )
    bitacora = BitacoraEventos(
        sesion=SesionSimulada(
            ESQUEMA_EVENTOS_SIMULADO, falla_al_crear_marco=True
        ),
        capa=capa,
    )

    # No debe lanzar: el fallo ocurre antes de llegar a la capa.
    bitacora.Registrar(accion="accion_con_sesion_caida")

    salida_error = capsys.readouterr().err
    assert "sesion inutilizable" in salida_error, (
        "El fallo de la sesión debe quedar visible en la salida local (stderr)"
    )
    assert capa.intentos_escritura == 0, (
        "Si el marco no llegó a construirse, la capa no debe ser invocada"
    )
