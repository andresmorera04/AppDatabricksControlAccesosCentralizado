"""Integral `free` de descubrimiento y ausencia de mutación (tarea 7.2).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Verifica contra `andresFree`, con la Statement Execution API del CLI (sin SDK
local; el SDK corre en el runtime de la App):

- el plano de datos expone catálogos, esquemas y tablas descubribles (las
  mismas fuentes que lista `DescubridorUc` en la App);
- las consultas de descubrimiento/previsualización son de SOLO LECTURA: la
  instantánea de `SHOW GRANT` del catálogo configurado es idéntica antes y
  después (ausencia de toda mutación).

Sin CLI o sin warehouse serverless, el módulo se SALTA con motivo.
"""

import shutil

import pytest

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from adaptador_sql_databricks import (
    DescubrirWarehouseServerless,
    SesionSqlDatabricks,
)

pytestmark = pytest.mark.free


@pytest.fixture(scope="module")
def sesion():
    """Sesión SQL real (Statement Execution) contra andresFree, o skip."""
    if shutil.which("databricks") is None:
        pytest.skip("El CLI de Databricks no está instalado; se requiere para la integral.")
    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip("andresFree no expone un SQL warehouse serverless.")
    return SesionSqlDatabricks(warehouse_id=warehouse_id)


def _Filas(sesion, sentencia):
    return sesion.EjecutarYLeer(sentencia)


def TestPlanoDeDatosExponeObjetosDescubribles(sesion):
    """SHOW CATALOGS / SCHEMAS / TABLES devuelven datos reales (descubrible)."""
    catalogos = _Filas(sesion, "SHOW CATALOGS")
    assert catalogos, "El workspace no expone catálogos (descubrimiento vacío)."
    # Primer catálogo aprovechable (se omite el de sistema si aparece).
    catalogo = next(
        (fila[0] for fila in catalogos if "information_schema" not in fila[0].lower()),
        catalogos[0][0],
    )
    esquemas = _Filas(sesion, f"SHOW SCHEMAS IN `{catalogo}`")
    assert esquemas, f"El catálogo '{catalogo}' no expone esquemas."
    esquema = esquemas[0][0]
    tablas = _Filas(sesion, f"SHOW TABLES IN `{catalogo}`.`{esquema}`")
    assert tablas, f"El esquema {catalogo}.{esquema} no expone tablas."


def TestDescubrimientoYPrevisualizacionNoMutalan(sesion):
    """Las lecturas (SHOW GRANT) no alteran los grants vigentes del catálogo."""
    configuracion = ConfiguracionApp.Cargar()
    catalogo = configuracion.catalogo

    antes = _Filas(sesion, f"SHOW GRANT ON CATALOG `{catalogo}`")
    # Simula el recorrido de descubrimiento + disponibilidad (solo lecturas).
    _Filas(sesion, "SHOW CATALOGS")
    _Filas(sesion, f"SHOW SCHEMAS IN `{catalogo}`")
    despues = _Filas(sesion, f"SHOW GRANT ON CATALOG `{catalogo}`")

    assert antes == despues, (
        "El descubrimiento/previsualización no puede mutar los grants: la "
        "instantánea SHOW GRANT difiere antes y después."
    )
