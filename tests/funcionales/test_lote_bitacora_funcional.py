"""Prueba funcional del registro por ítem en la bitácora del camino de lote.

Change `grants-batch` (C5), capability `batch-grant-operations` (design.md
D4): tras procesar un lote con canales simulados, la tabla `bitacora_eventos`
contiene una fila por ítem con el `usuario` OBO y su estado final, más la fila
consolidada del lote.

Usa Spark local + Delta (igual que `test_persistencia_capa.py` de C2) y los
escritores reales de bitácora (`BitacoraEventos`, `BitacoraErrores`).
"""

import pytest

from control_accesos.bitacora.escritores import BitacoraErrores, BitacoraEventos
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.persistencia.inicializador import InicializadorPersistencia
from control_accesos.pipeline.pipeline_grants import (
    ACCION_PROCESAR_LOTE,
    PipelineGrants,
)

# Catálogo de Spark local con Delta.
CATALOGO_LOCAL = "spark_catalog"


class IdentidadLlamanteFalsa:
    """Doble de `IdentidadLlamante` con el atributo `usuario_bitacora`."""

    def __init__(self, usuario):
        self.usuario_bitacora = usuario


def CrearConfiguracionLocal(tmp_path):
    """Crea una configuración local con el catálogo de Spark local.

    Args:
        tmp_path: ruta temporal de pytest para el almacenamiento Delta.

    Returns:
        ConfiguracionApp: configuración con el catálogo local.
    """
    import json

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(json.dumps({"catalogo": CATALOGO_LOCAL}), encoding="utf-8")
    return ConfiguracionApp.Cargar(ruta_archivo=ruta)


def _CrearPrincipal(email="user@example.com"):
    """Construye un principal de prueba."""
    return Principal(identificador=email, tipo="usuario")


def _CrearObjetoTabla(identificador="catalogo1.schema1.tabla1"):
    """Construye un objeto de prueba del plano de datos."""
    return ObjetoSecurable(
        identificador=identificador, tipo=TipoObjeto.TABLA_DELTA
    )


class TestBitacoraLoteFuncional:
    """Verifica el registro por ítem en la bitácora con escritores reales."""

    def TestLoteRegistraUnaFilaPorItemMasConsolidada(self, sesion_spark, tmp_path):
        """Tras procesar un lote, bitacora_eventos tiene una fila por ítem + consolidada.

        WHEN se procesa un lote de 3 ítems con llamante autenticado THEN la
        tabla `bitacora_eventos` contiene 3 filas por ítem (con usuario OBO y
        estado final) más 1 fila consolidada del lote.
        """
        configuracion = CrearConfiguracionLocal(tmp_path)
        InicializadorPersistencia(
            sesion=sesion_spark, configuracion=configuracion
        ).Inicializar()

        escritor_eventos = BitacoraEventos(
            sesion=sesion_spark, configuracion=configuracion
        )
        escritor_errores = BitacoraErrores(
            sesion=sesion_spark, configuracion=configuracion
        )

        principal = _CrearPrincipal()
        objetos = [
            _CrearObjetoTabla("tabla1"),
            _CrearObjetoTabla("tabla2"),
            _CrearObjetoTabla("tabla3"),
        ]
        llamante = IdentidadLlamanteFalsa("llamante@example.com")

        canal_datos = CanalDatosSimulado()
        canal_control = CanalControlSimulado()
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            identidad_llamante=llamante,
            registrador_eventos=escritor_eventos,
            registrador_errores=escritor_errores,
        )

        pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal],
            privilegios=["SELECT"],
            objetos=objetos,
        )

        # Consultar la tabla bitacora_eventos.
        eventos = sesion_spark.sql(
            f"SELECT accion, usuario, detalle, resultado "
            f"FROM {CATALOGO_LOCAL}.control_acceso_app.bitacora_eventos "
            f"WHERE accion = '{ACCION_PROCESAR_LOTE}'"
        ).collect()

        # 3 eventos por ítem + 1 evento consolidado = 4 eventos.
        assert len(eventos) == 4

        # Verificar que todos tienen el usuario OBO.
        for evento in eventos:
            assert evento["usuario"] == "llamante@example.com"

        # Verificar que hay 3 eventos con detalle por ítem (contienen "tabla").
        eventos_por_item = [e for e in eventos if "tabla" in e["detalle"].lower()]
        assert len(eventos_por_item) == 3

        # Verificar que hay 1 evento consolidado (contiene "3 ítem").
        eventos_consolidados = [e for e in eventos if "3 ítem" in e["detalle"]]
        assert len(eventos_consolidados) == 1
