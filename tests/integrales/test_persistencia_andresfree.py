"""Prueba integral de la persistencia contra el workspace real `andresFree`.

Change C2 (`persistencia-bitacora`), tarea 5.1 (capa integral, marker `free`,
README D5): ejecuta la INICIALIZACIÓN REAL de la persistencia —las clases de
producción `ConfiguracionApp` e `InicializadorPersistencia`— contra el catálogo
`control` del workspace `andresFree`, usando la identidad del perfil CLI ya
autenticado (el adaptador `SesionSqlDatabricks` ejecuta el DDL real vía la
Statement Execution API con el CLI instalado; no se instala nada nuevo).

Verifica en el workspace real:

- creación del esquema dedicado `control.control_acceso_app`;
- creación de `bitacora_eventos` y `bitacora_errores` con sus columnas
  (incluido el STRUCT del detalle del error);
- propiedades delta habilitadas (CDF, optimizeWrite, autoCompact) y liquid
  clustering declarado, vía inspección de metadatos;
- idempotencia: una segunda inicialización no falla y conserva los datos
  escritos entre ambas;
- fallo controlado ante un catálogo inexistente (`ErrorInicializacionPersistencia`).

Notas de ejecución:

- Requiere el CLI de Databricks autenticado con el perfil `andresFree` y red
  disponible; si el entorno no los tiene, la prueba se SALTA (no falla) para
  no bloquear corridas en otras máquinas.
- El warehouse serverless puede arrancar en frío: la primera sentencia puede
  demorar; el adaptador sondea hasta el estado terminal.
- La prueba escribe datos reales en las bitácoras del workspace (un evento
  marcador con identificador único por corrida); es el comportamiento esperado
  de una bitácora y no requiere limpieza.
"""

import shutil
import uuid

import pytest

from adaptador_sql_databricks import (
    ErrorTransporteDatabricks,
    DescubrirWarehouseServerless,
    SesionSqlDatabricks,
)
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from control_accesos.persistencia.ddl import (
    DEFINICIONES_TABLAS_APLICACION,
    ESQUEMA_APLICACION,
    PROPIEDADES_DELTA_OBLIGATORIAS,
)
from control_accesos.persistencia.errores import ErrorInicializacionPersistencia
from control_accesos.persistencia.inicializador import InicializadorPersistencia

# Todas las pruebas de este módulo son integrales contra andresFree.
pytestmark = pytest.mark.free


@pytest.fixture(scope="module")
def entorno_integral():
    """Prepara el entorno integral: adaptador, configuración e inicialización.

    Descubre el warehouse serverless del perfil, ejecuta la inicialización
    real de la persistencia (primera pasada), escribe un evento marcador con
    identificador único y vuelve a inicializar (segunda pasada) para dejar el
    escenario de idempotencia listo para las aserciones.

    Yields:
        dict: adaptador (`sesion`), esquema calificado (`esquema`), tabla de
        eventos calificada (`tabla_eventos`) e identificador del evento
        marcador (`id_evento_marcador`).
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado en esta máquina; la capa "
            "integral requiere el CLI autenticado con el perfil andresFree."
        )

    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip(
            "El perfil andresFree no expone un SQL warehouse serverless; no "
            "hay dónde ejecutar el DDL integral."
        )

    sesion = SesionSqlDatabricks(warehouse_id=warehouse_id)

    # Configuración REAL del proyecto (config/app_properties.json): el
    # catálogo no se fija en la prueba, se toma de la fuente única.
    configuracion = ConfiguracionApp.Cargar()
    inicializador = InicializadorPersistencia(
        sesion=sesion, configuracion=configuracion
    )

    # Primera inicialización real sobre el workspace.
    inicializador.Inicializar()

    esquema = f"{configuracion.catalogo}.{ESQUEMA_APLICACION}"
    tabla_eventos = f"{esquema}.bitacora_eventos"

    # Evento marcador con identificador único por corrida: permite verificar
    # que la segunda inicialización conserva los datos previos.
    id_marcador = f"integral_{uuid.uuid4()}"
    sesion.sql(
        f"INSERT INTO {tabla_eventos} "
        f"(id_evento, marca_tiempo, usuario, accion, detalle, resultado) "
        f"VALUES ('{id_marcador}', current_timestamp(), "
        f"'prueba_integral_free', 'inicializacion_idempotente', "
        f"'evento marcador de la prueba integral C2', 'ok')"
    )

    # Segunda inicialización: debe ser idempotente (IF NOT EXISTS).
    inicializador.Inicializar()

    yield {
        "sesion": sesion,
        "configuracion": configuracion,
        "esquema": esquema,
        "tabla_eventos": tabla_eventos,
        "id_evento_marcador": id_marcador,
    }


def TestEsquemaDedicadoCreadoEnWorkspaceReal(entorno_integral):
    """El esquema dedicado debe existir en el catálogo configurado."""
    sesion = entorno_integral["sesion"]
    configuracion = entorno_integral["configuracion"]

    filas = sesion.sql(f"SHOW SCHEMAS IN {configuracion.catalogo}")
    nombres_esquema = {fila[0] for fila in filas}

    assert ESQUEMA_APLICACION in nombres_esquema, (
        f"El esquema '{ESQUEMA_APLICACION}' debe existir en el catálogo "
        f"'{configuracion.catalogo}' del workspace andresFree"
    )


def TestTablasBitacoraCreadasEnWorkspaceReal(entorno_integral):
    """Las dos bitácoras deben existir en el esquema dedicado."""
    sesion = entorno_integral["sesion"]
    esquema = entorno_integral["esquema"]

    filas = sesion.sql(f"SHOW TABLES IN {esquema}")
    nombres_tabla = {fila[1] for fila in filas}

    esperadas = {definicion.nombre for definicion in DEFINICIONES_TABLAS_APLICACION}
    assert esperadas <= nombres_tabla, (
        f"Las tablas {sorted(esperadas)} deben existir en '{esquema}'; "
        f"presentes: {sorted(nombres_tabla)}"
    )


def TestColumnasRealesIncluyenDetalleStruct(entorno_integral):
    """Las columnas reales deben coincidir con la declaración, incluido el STRUCT."""
    sesion = entorno_integral["sesion"]
    esquema = entorno_integral["esquema"]

    filas_eventos = sesion.sql(f"DESCRIBE TABLE {esquema}.bitacora_eventos")
    tipos_eventos = {fila[0]: fila[1] for fila in filas_eventos}
    for columna in ("id_evento", "marca_tiempo", "usuario", "accion",
                    "detalle", "resultado"):
        assert columna in tipos_eventos, (
            f"La bitácora de eventos real debe tener la columna '{columna}'"
        )

    filas_errores = sesion.sql(f"DESCRIBE TABLE {esquema}.bitacora_errores")
    tipos_errores = {fila[0]: fila[1] for fila in filas_errores}
    for columna in ("id_error", "marca_tiempo", "usuario", "modulo", "detalle"):
        assert columna in tipos_errores, (
            f"La bitácora de errores real debe tener la columna '{columna}'"
        )

    tipo_detalle = tipos_errores["detalle"].lower().replace(" ", "")
    assert tipo_detalle.startswith("struct<"), (
        f"El detalle real debe ser STRUCT; se encontró: {tipos_errores['detalle']}"
    )
    for campo in ("tipo_excepcion", "mensaje", "traza", "contexto"):
        assert campo in tipo_detalle, (
            f"El STRUCT real del detalle debe incluir el campo '{campo}'"
        )


def TestPropiedadesDeltaHabilitadasEnTablasReales(entorno_integral):
    """CDF, optimizeWrite y autoCompact deben figurar habilitadas en las tablas."""
    sesion = entorno_integral["sesion"]
    esquema = entorno_integral["esquema"]

    for nombre_tabla in ("bitacora_eventos", "bitacora_errores"):
        filas = sesion.sql(
            f"SHOW TBLPROPERTIES {esquema}.{nombre_tabla}"
        )
        propiedades = {fila[0]: fila[1] for fila in filas}

        for nombre_propiedad, valor in PROPIEDADES_DELTA_OBLIGATORIAS:
            assert propiedades.get(nombre_propiedad) == valor, (
                f"La tabla real '{nombre_tabla}' debe tener "
                f"'{nombre_propiedad}'='{valor}'; se encontró: "
                f"{propiedades.get(nombre_propiedad)!r}"
            )


def TestLiquidClusteringDeclaradoEnTablasReales(entorno_integral):
    """El DDL real de las tablas debe declarar liquid clustering (CLUSTER BY)."""
    sesion = entorno_integral["sesion"]
    esquema = entorno_integral["esquema"]

    for nombre_tabla in ("bitacora_eventos", "bitacora_errores"):
        filas = sesion.sql(
            f"SHOW CREATE TABLE {esquema}.{nombre_tabla}"
        )
        ddl_real = "\n".join(fila[0] for fila in filas).upper()

        assert "CLUSTER BY" in ddl_real, (
            f"La tabla real '{nombre_tabla}' debe declarar liquid clustering "
            f"(CLUSTER BY) en su DDL"
        )
        assert "MARCA_TIEMPO" in ddl_real, (
            f"El clustering de '{nombre_tabla}' debe ser por marca_tiempo"
        )


def TestSegundaInicializacionConservaDatosReales(entorno_integral):
    """El evento marcador debe conservarse tras la segunda inicialización."""
    sesion = entorno_integral["sesion"]
    tabla_eventos = entorno_integral["tabla_eventos"]
    id_marcador = entorno_integral["id_evento_marcador"]

    filas = sesion.sql(
        f"SELECT COUNT(*) FROM {tabla_eventos} "
        f"WHERE id_evento = '{id_marcador}'"
    )

    assert filas[0][0] == "1", (
        "La re-inicialización idempotente no debe alterar los datos escritos "
        "previamente en el workspace real"
    )


def TestCatalogoInexistenteReportaErrorControladoReal(tmp_path):
    """Un catálogo inexistente debe producir un error explícito y controlado."""
    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip("Sin warehouse serverless disponible en andresFree.")

    sesion = SesionSqlDatabricks(warehouse_id=warehouse_id)

    # Configuración temporal que apunta a un catálogo que no existe: el DDL
    # real fallará en el workspace y el inicializador debe traducirlo.
    import json

    ruta = tmp_path / "app_properties.json"
    ruta.write_text(
        json.dumps({"catalogo": "catalogo_inexistente_c2"}), encoding="utf-8"
    )
    configuracion = ConfiguracionApp.Cargar(ruta_archivo=ruta)
    inicializador = InicializadorPersistencia(
        sesion=sesion, configuracion=configuracion
    )

    with pytest.raises(ErrorInicializacionPersistencia) as error:
        inicializador.Inicializar()

    assert "catalogo_inexistente_c2" in error.value.mensaje, (
        "El error controlado debe identificar el catálogo que falló"
    )
