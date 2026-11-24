"""Prueba unitaria del módulo DDL de la capa de persistencia.

Change C2 (`persistencia-bitacora`), capability `app-persistence` (design.md
D4): el DDL de esquema y tablas se declara como plantillas SQL en mayúsculas,
idempotentes (`IF NOT EXISTS`), parametrizadas con el catálogo de la
configuración y el esquema dedicado `control_acceso_app` (constantes del
módulo, nada hardcodeado por sentencia), con liquid clustering (`CLUSTER BY`)
y las tres propiedades delta del estándar (change data feed, optimizeWrite y
autoCompact).

Estas pruebas son de lógica pura (generación de texto SQL): no requieren
sesión Spark. La ejecución real del DDL se verifica en las pruebas
funcionales del inicializador (`test_persistencia_inicializador.py`).
"""

from control_accesos.persistencia.ddl import (
    DEFINICIONES_TABLAS_APLICACION,
    DEFINICION_BITACORA_ERRORES,
    DEFINICION_BITACORA_EVENTOS,
    ESQUEMA_APLICACION,
    PROPIEDADES_DELTA_OBLIGATORIAS,
    ConstructorDdl,
)

# Catálogo de prueba distinto del distribuido (`control`) para demostrar que
# el DDL se parametriza desde la configuración y no lleva el valor embebido.
CATALOGO_DE_PRUEBA = "otro_catalogo"

# Propiedades delta que exige el estándar del proyecto (README.md).
NOMBRES_PROPIEDADES_DELTA = [
    nombre for nombre, _ in PROPIEDADES_DELTA_OBLIGATORIAS
]


def TestDdlEsquemaEsIdempotenteYCalificado():
    """El DDL del esquema debe ser idempotente y usar el nombre calificado."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    ddl = constructor.DdlEsquema()

    assert "CREATE SCHEMA IF NOT EXISTS" in ddl, (
        "El DDL del esquema debe ser idempotente (IF NOT EXISTS) y estar en "
        "mayúsculas (estándar: SQL en mayúsculas)"
    )
    assert f"{CATALOGO_DE_PRUEBA}.{ESQUEMA_APLICACION}" in ddl, (
        "El esquema debe quedar calificado con el catálogo parametrizado y "
        f"el esquema dedicado '{ESQUEMA_APLICACION}'"
    )


def TestDdlTablaEsIdempotenteConFormatoDelta():
    """El DDL de tabla debe ser idempotente y declarar el formato delta."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    ddl = constructor.DdlTabla(DEFINICION_BITACORA_EVENTOS)

    assert "CREATE TABLE IF NOT EXISTS" in ddl, (
        "El DDL de la tabla debe ser idempotente (IF NOT EXISTS)"
    )
    assert "USING DELTA" in ddl, (
        "Toda tabla de la aplicación debe crearse en formato delta"
    )
    nombre_calificado = (
        f"{CATALOGO_DE_PRUEBA}.{ESQUEMA_APLICACION}."
        f"{DEFINICION_BITACORA_EVENTOS.nombre}"
    )
    assert nombre_calificado in ddl, (
        f"La tabla debe crearse con su nombre calificado {nombre_calificado}"
    )


def TestDdlTablaIncluyeLiquidClustering():
    """El DDL debe declarar liquid clustering (CLUSTER BY)."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    for definicion in DEFINICIONES_TABLAS_APLICACION:
        ddl = constructor.DdlTabla(definicion)

        assert "CLUSTER BY" in ddl, (
            f"La tabla {definicion.nombre} debe declarar liquid clustering"
        )
        for columna in definicion.cluster_por:
            assert columna in ddl, (
                f"La columna de clustering '{columna}' debe figurar en el DDL "
                f"de {definicion.nombre}"
            )


def TestDdlTablaIncluyeLasTresPropiedadesDelta():
    """El DDL debe habilitar CDF, optimizeWrite y autoCompact desde la creación."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    for definicion in DEFINICIONES_TABLAS_APLICACION:
        ddl = constructor.DdlTabla(definicion)

        assert "TBLPROPERTIES" in ddl, (
            f"La tabla {definicion.nombre} debe declarar TBLPROPERTIES"
        )
        for nombre, valor in PROPIEDADES_DELTA_OBLIGATORIAS:
            assert f"'{nombre}'='{valor}'" in ddl, (
                f"La tabla {definicion.nombre} debe habilitar la propiedad "
                f"delta '{nombre}'='{valor}' desde su creación"
            )


def TestPropiedadesDeltaObligatoriasSonLasDelEstandar():
    """Las propiedades declaradas deben ser exactamente las del estándar."""
    assert set(NOMBRES_PROPIEDADES_DELTA) == {
        "delta.enableChangeDataFeed",
        "delta.autoOptimize.optimizeWrite",
        "delta.autoOptimize.autoCompact",
    }, (
        "El módulo DDL debe habilitar change data feed, optimizeWrite y "
        "autoCompact (README.md - Estándar de desarrollo)"
    )


def TestRegistroDeTablasIncluyeLasDosBitacoras():
    """El registro declarativo debe contener las dos tablas de bitácora."""
    nombres = {definicion.nombre for definicion in DEFINICIONES_TABLAS_APLICACION}

    assert nombres == {"bitacora_eventos", "bitacora_errores"}, (
        "Las tablas de la aplicación en este change son las dos bitácoras"
    )


def TestRegistroDeTablasDeclaraSusLlavesPrimarias():
    """Cada bitácora debe declarar su llave primaria para los helpers (D5)."""
    assert DEFINICION_BITACORA_EVENTOS.claves_primarias == ("id_evento",), (
        "La llave primaria de la bitácora de eventos es id_evento"
    )
    assert DEFINICION_BITACORA_ERRORES.claves_primarias == ("id_error",), (
        "La llave primaria de la bitácora de errores es id_error"
    )


def TestDdlBitacoraEventosDeclaraSusColumnas():
    """La bitácora de eventos debe declarar sus columnas mínimas (design.md D6)."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    ddl = constructor.DdlTabla(DEFINICION_BITACORA_EVENTOS)

    columnas_esperadas = [
        "id_evento",
        "marca_tiempo",
        "usuario",
        "accion",
        "detalle",
        "resultado",
    ]
    for columna in columnas_esperadas:
        assert columna in ddl, (
            f"La bitácora de eventos debe declarar la columna '{columna}'"
        )


def TestDdlBitacoraErroresDeclaraDetalleStruct():
    """El detalle de la bitácora de errores debe ser de tipo STRUCT<...>."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    ddl = constructor.DdlTabla(DEFINICION_BITACORA_ERRORES)

    assert "detalle STRUCT<" in ddl.replace("  ", " "), (
        "El campo de detalle del error debe declararse como STRUCT (regla "
        "del estándar: detalle del error tipo STRUCT<...>)"
    )
    for campo in ("tipo_excepcion", "mensaje", "traza", "contexto"):
        assert campo in ddl, (
            f"El STRUCT del detalle debe incluir el campo '{campo}'"
        )
    for columna in ("id_error", "marca_tiempo", "usuario", "modulo"):
        assert columna in ddl, (
            f"La bitácora de errores debe declarar la columna '{columna}'"
        )


def TestNombreTablaCalificadoUsaCatalogoParametrizado():
    """El nombre calificado de tabla se deriva del catálogo y las constantes."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    nombre = constructor.NombreTablaCalificado(DEFINICION_BITACORA_EVENTOS)

    assert nombre == (
        f"{CATALOGO_DE_PRUEBA}.{ESQUEMA_APLICACION}.bitacora_eventos"
    ), "El nombre calificado debe ser <catalogo>.<esquema>.<tabla>"


def TestDdlNoContieneElCatalogoPorDefectoEmbebido():
    """El DDL no debe llevar embebido un catálogo distinto del parametrizado."""
    constructor = ConstructorDdl(catalogo=CATALOGO_DE_PRUEBA)

    ddl_esquema = constructor.DdlEsquema()
    ddl_tabla = constructor.DdlTabla(DEFINICION_BITACORA_EVENTOS)

    assert "control.control_acceso_app" not in ddl_esquema, (
        "El DDL del esquema no debe hardcodear el catálogo distribuido"
    )
    assert "control.control_acceso_app" not in ddl_tabla, (
        "El DDL de la tabla no debe hardcodear el catálogo distribuido"
    )
