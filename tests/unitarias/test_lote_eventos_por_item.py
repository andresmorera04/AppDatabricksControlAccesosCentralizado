"""Pruebas unitarias del registro por ítem en la bitácora del camino de lote.

Trazabilidad:
- spec `batch-grant-operations` - "Registro en bitácora de cada ítem del lote"
- design.md D4 - evento por ítem + consolidado, escritura masiva, degradación controlada

Convención del proyecto (README.md): clases, funciones y métodos en PascalCase
(pytest.ini registra `python_functions = Test*`); los escritores de bitácora se
simulan para verificar las llamadas sin tocar la persistencia real.
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.pipeline.pipeline_grants import (
    ACCION_PROCESAR_LOTE,
    PipelineGrants,
)


class EscritorBitacoraFalso:
    """Doble de `BitacoraEventos` que registra las llamadas sin persistir.

    Attributes:
        eventos_registrados (list): lista de tuplas (accion, usuario, detalle,
            resultado) por cada llamada a `Registrar`.
    """

    def __init__(self):
        self.eventos_registrados = []

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        """Simula el registro de un evento de bitácora."""
        self.eventos_registrados.append((accion, usuario, detalle, resultado))


class EscritorBitacoraQueFalla:
    """Doble de `BitacoraEventos` que lanza una excepción al registrar.

    Simula un fallo de la bitácora para verificar la degradación controlada
    (design.md D4): el fallo no aborta el lote y se registra en la bitácora de
    errores.
    """

    def __init__(self):
        self.llamadas = 0

    def Registrar(self, accion, usuario=None, detalle=None, resultado=None):
        """Lanza una excepción para simular un fallo de la bitácora."""
        self.llamadas += 1
        raise RuntimeError("Fallo simulado de la bitácora")


class EscritorErroresFalso:
    """Doble de `BitacoraErrores` que registra las llamadas sin persistir.

    Attributes:
        errores_registrados (list): lista de tuplas (excepcion, modulo, usuario,
            contexto) por cada llamada a `Registrar`.
    """

    def __init__(self):
        self.errores_registrados = []

    def Registrar(self, excepcion, modulo, usuario=None, contexto=""):
        """Simula el registro de un error de bitácora."""
        self.errores_registrados.append((excepcion, modulo, usuario, contexto))


class IdentidadLlamanteFalsa:
    """Doble de `IdentidadLlamante` con el atributo `usuario_bitacora`.

    Simula la identidad on-behalf-of del llamante para las pruebas de bitácora.
    """

    def __init__(self, usuario):
        self.usuario_bitacora = usuario


def _CrearPrincipal(email="user@example.com"):
    """Construye un principal de prueba."""
    return Principal(identificador=email, tipo="usuario")


def _CrearObjetoTabla(identificador="catalogo1.schema1.tabla1"):
    """Construye un objeto de prueba del plano de datos."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.TABLA_DELTA
    )


class TestRegistroPorItemEnBitacora:
    """Verifica el registro por ítem en la bitácora del camino de lote."""

    def TestLoteDeCuatroItemsRegistraUnEventoPorItemMasConsolidado(self):
        """Scenario: Ítems registrados individualmente.

        WHEN se procesa un lote de cuatro ítems con el llamante autenticado
        THEN la bitácora de eventos registra un evento por ítem con el usuario
        del llamante y el estado final de cada uno, además del evento
        consolidado del lote.
        """
        principal = _CrearPrincipal()
        objetos = [
            _CrearObjetoTabla("tabla1"),
            _CrearObjetoTabla("tabla2"),
            _CrearObjetoTabla("tabla3"),
            _CrearObjetoTabla("tabla4"),
        ]
        llamante = IdentidadLlamanteFalsa("llamante@example.com")
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        escritor_eventos = EscritorBitacoraFalso()
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            identidad_llamante=llamante,
            registrador_eventos=escritor_eventos,
        )
        pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=objetos,
        )
        # 4 eventos por ítem + 1 evento consolidado = 5 eventos.
        assert len(escritor_eventos.eventos_registrados) == 5
        # Los primeros 4 eventos son por ítem, con la acción canónica de lote.
        for i in range(4):
            accion, usuario, detalle, resultado = escritor_eventos.eventos_registrados[i]
            assert accion == ACCION_PROCESAR_LOTE
            assert usuario == "llamante@example.com"
            assert "tabla" in detalle.lower() or "select" in detalle.lower()
        # El quinto evento es el consolidado.
        accion, usuario, detalle, resultado = escritor_eventos.eventos_registrados[4]
        assert accion == ACCION_PROCESAR_LOTE
        assert usuario == "llamante@example.com"
        assert "4" in detalle or "ítem" in detalle.lower()

    def TestLoteSinIdentidadRegistraEventosConUsuarioSinValor(self):
        """Scenario: Ítems registrados sin identidad de llamante.

        WHEN se procesa un lote sin identidad del llamante THEN los eventos por
        ítem se registran igualmente, con el usuario explícitamente sin valor.
        """
        principal = _CrearPrincipal()
        objetos = [_CrearObjetoTabla("tabla1")]
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        escritor_eventos = EscritorBitacoraFalso()
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_eventos=escritor_eventos,
        )
        pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=objetos,
        )
        # 1 evento por ítem + 1 evento consolidado = 2 eventos.
        assert len(escritor_eventos.eventos_registrados) == 2
        # Ambos eventos tienen usuario=None (sin identidad).
        for accion, usuario, detalle, resultado in escritor_eventos.eventos_registrados:
            assert usuario is None

    def TestFalloDelEscritorNoAbortaElLoteYSeRegistraEnErrores(self):
        """Un fallo del escritor no aborta el lote y se registra en la bitácora de errores.

        WHEN el escritor de bitácora lanza una excepción THEN el lote se procesa
        igual y el fallo se registra en la bitácora de errores (degradación
        controlada, design.md D4).
        """
        principal = _CrearPrincipal()
        objetos = [_CrearObjetoTabla("tabla1")]
        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        escritor_eventos = EscritorBitacoraQueFalla()
        escritor_errores = EscritorErroresFalso()
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            registrador_eventos=escritor_eventos,
            registrador_errores=escritor_errores,
        )
        # El lote se procesa sin abortar.
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=objetos,
        )
        assert len(resultado.lineas) == 1
        # El fallo se registró en la bitácora de errores.
        assert len(escritor_errores.errores_registrados) >= 1
