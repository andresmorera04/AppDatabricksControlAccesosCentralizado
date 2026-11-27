"""Prueba unitaria del descubrimiento de objetos de Unity Catalog (design.md D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 3.2.

Contrato que fija esta prueba, sobre el adaptador UC con la credencial OBO
(`DescubridorUc`) y su traducción a `ObjetoSecurable` del dominio:

- catálogos, esquemas y tablas se traducen con su tipo y **nombre calificado**
  (catálogo: ``catalogo``; esquema: ``catalogo.esquema``; tabla:
  ``catalogo.esquema.tabla``), normalizado a minúsculas por el dominio (plano
  de datos);
- el **filtrado por metadatos** clasifica los tipos tabulares según
  ``table_type``: MANAGED/EXTERNAL -> ``TABLA_DELTA``, STREAMING_TABLE ->
  ``STREAMING_TABLE``, VIEW -> ``VISTA_SQL``, MATERIALIZED_VIEW ->
  ``VISTA_MATERIALIZADA``, y descarta los tipos no soportados;
- el límite configurable recorta el listado (paginación acotada caminando el
  iterador del servicio, sin asumir una sola página);
- un fallo del listado se traduce a `ErrorDescubrimientoOpciones`, distinguible
  de una lista auténticamente vacía (tupla vacía).

No hay red ni SDK real: el cliente UC es un doble con ``list()`` por servicio
(``catalogs``, ``schemas``, ``tables``).
"""

from types import SimpleNamespace

import pytest

from control_accesos.canales.reales.descubrimiento_uc import DescubridorUc
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.ui.servicio_descubrimiento import (
    ErrorDescubrimientoOpciones,
    ServicioDescubrimientoUi,
)

# Valores de prueba (sin ids reales del workspace).
CATALOGO_VENTAS = "ventas"
ESQUEMA_BRONCE = "Bronce"
TABLA_CLIENTES = "clientes"


def _Registro(**campos):
    """Doble de un registro del SDK de UC (campos como atributos)."""
    return SimpleNamespace(**campos)


class ServicioListadoFalso:
    """Doble de un servicio UC con `list(**kwargs)` que registra las llamadas."""

    def __init__(self, registros=(), excepcion=None):
        self._registros = list(registros)
        self._excepcion = excepcion
        self.llamadas = []

    def list(self, **kwargs):
        self.llamadas.append(kwargs)
        if self._excepcion is not None:
            raise self._excepcion
        return iter(self._registros)


class ClienteUcFalso:
    """Cliente UC falso con los siete servicios que consume el descubridor."""

    def __init__(
        self,
        catalogs=None,
        schemas=None,
        tables=None,
        volumes=None,
        registered_models=None,
        external_locations=None,
        connections=None,
    ):
        self.catalogs = catalogs or ServicioListadoFalso()
        self.schemas = schemas or ServicioListadoFalso()
        self.tables = tables or ServicioListadoFalso()
        self.volumes = volumes or ServicioListadoFalso()
        self.registered_models = registered_models or ServicioListadoFalso()
        self.external_locations = external_locations or ServicioListadoFalso()
        self.connections = connections or ServicioListadoFalso()


def _CrearServicio(
    catalogs=(),
    schemas=(),
    tables=(),
    volumes=(),
    registered_models=(),
    external_locations=(),
    connections=(),
    limite=None,
):
    """Construye el servicio UI sobre un descubridor UC real y un cliente falso.

    Returns:
        tuple: (ServicioDescubrimientoUi, ClienteUcFalso).
    """
    cliente = ClienteUcFalso(
        catalogs=ServicioListadoFalso(catalogs),
        schemas=ServicioListadoFalso(schemas),
        tables=ServicioListadoFalso(tables),
        volumes=ServicioListadoFalso(volumes),
        registered_models=ServicioListadoFalso(registered_models),
        external_locations=ServicioListadoFalso(external_locations),
        connections=ServicioListadoFalso(connections),
    )
    descubridor = DescubridorUc(cliente=cliente, limite=limite)
    return ServicioDescubrimientoUi(descubridor_uc=descubridor), cliente


def TestCatalogoConNombreCalificado():
    """Un catálogo se traduce a ObjetoSecurable con su nombre calificado."""
    servicio, _ = _CrearServicio(catalogs=[_Registro(name=CATALOGO_VENTAS)])

    objetos = servicio.DescubrirCatalogos()

    assert len(objetos) == 1
    assert isinstance(objetos[0], ObjetoSecurable)
    assert objetos[0].tipo == TipoObjeto.CATALOGO
    assert objetos[0].identificador == CATALOGO_VENTAS


def TestEsquemaConNombreCalificado():
    """Un esquema se traduce con `catalogo.esquema` (normalizado)."""
    servicio, _ = _CrearServicio(
        schemas=[_Registro(name=ESQUEMA_BRONCE)],
    )

    objetos = servicio.DescubrirEsquemas(CATALOGO_VENTAS)

    assert len(objetos) == 1
    assert objetos[0].tipo == TipoObjeto.ESQUEMA
    assert objetos[0].identificador == f"{CATALOGO_VENTAS}.bronce"


def TestTablasSeClasificanPorMetadatosDeTipo():
    """Los tipos tabulares se mapean por `table_type` y se descartan los demás."""
    registros = [
        _Registro(name="delta_man", table_type="MANAGED"),
        _Registro(name="delta_ext", table_type="EXTERNAL"),
        _Registro(name="stream", table_type="STREAMING_TABLE"),
        _Registro(name="vista", table_type="VIEW"),
        _Registro(name="vista_mat", table_type="MATERIALIZED_VIEW"),
        _Registro(name="otro", table_type="FOREIGN"),
    ]
    servicio, cliente = _CrearServicio(tables=registros)

    objetos = servicio.DescubrirTablas(CATALOGO_VENTAS, ESQUEMA_BRONCE)

    tipos = [objeto.tipo for objeto in objetos]
    assert tipos == [
        TipoObjeto.TABLA_DELTA,
        TipoObjeto.TABLA_DELTA,
        TipoObjeto.STREAMING_TABLE,
        TipoObjeto.VISTA_SQL,
        TipoObjeto.VISTA_MATERIALIZADA,
    ], "Los tipos no soportados se descartan (filtrado por metadatos)."
    assert [objeto.identificador for objeto in objetos] == [
        "ventas.bronce.delta_man",
        "ventas.bronce.delta_ext",
        "ventas.bronce.stream",
        "ventas.bronce.vista",
        "ventas.bronce.vista_mat",
    ]
    # El listado de tablas se pidió acotado al catálogo y esquema solicitados.
    assert cliente.tables.llamadas == [
        {"catalog_name": CATALOGO_VENTAS, "schema_name": ESQUEMA_BRONCE}
    ]


def TestLimiteConfigurableRecortaElListado():
    """El límite recorta el listado caminando el iterador sin asumir una página."""
    catalogs = [
        _Registro(name=f"catalogo_{indice}") for indice in range(5)
    ]
    servicio, _ = _CrearServicio(catalogs=catalogs, limite=2)

    objetos = servicio.DescubrirCatalogos()

    assert [objeto.identificador for objeto in objetos] == [
        "catalogo_0",
        "catalogo_1",
    ]


def TestFalloDeListadoEsDistinguibleDeListaVacia():
    """Un fallo del listado eleva error; el vacío auténtico, tupla vacía."""
    def _servicio_con_fallo():
        cliente = ClienteUcFalso(catalogs=ServicioListadoFalso(excepcion=RuntimeError("catalogos sin scope")))
        descubridor = DescubridorUc(cliente=cliente)
        return ServicioDescubrimientoUi(descubridor_uc=descubridor)

    with pytest.raises(ErrorDescubrimientoOpciones):
        _servicio_con_fallo().DescubrirCatalogos()

    servicio_vacio, _ = _CrearServicio(
        catalogs=(), schemas=(), tables=(),
        volumes=(), registered_models=(), external_locations=(), connections=(),
    )
    assert servicio_vacio.DescubrirCatalogos() == ()
    assert servicio_vacio.DescubrirEsquemas(CATALOGO_VENTAS) == ()
    assert servicio_vacio.DescubrirTablas(CATALOGO_VENTAS, ESQUEMA_BRONCE) == ()
    assert servicio_vacio.DescubrirVolumenes(CATALOGO_VENTAS, ESQUEMA_BRONCE) == ()
    assert servicio_vacio.DescubrirModelosMl(CATALOGO_VENTAS, ESQUEMA_BRONCE) == ()
    assert servicio_vacio.DescubrirExternalLocations() == ()
    assert servicio_vacio.DescubrirConexiones() == ()


def TestVolumenesYModelosConNombreCalificado():
    """Volúmenes y modelos se traducen con `catalogo.esquema.nombre`."""
    servicio, cliente = _CrearServicio(
        volumes=[_Registro(name="bronce_vol_1")],
        registered_models=[_Registro(name="modelo_riesgo")],
    )

    volumenes = servicio.DescubrirVolumenes(CATALOGO_VENTAS, ESQUEMA_BRONCE)
    modelos = servicio.DescubrirModelosMl(CATALOGO_VENTAS, ESQUEMA_BRONCE)

    assert len(volumenes) == 1
    assert volumenes[0].tipo == TipoObjeto.VOLUMEN
    assert volumenes[0].identificador == "ventas.bronce.bronce_vol_1"
    assert len(modelos) == 1
    assert modelos[0].tipo == TipoObjeto.MODELO_ML
    assert modelos[0].identificador == "ventas.bronce.modelo_riesgo"
    # Los listados se pidieron acotados al catálogo y esquema solicitados.
    assert cliente.volumes.llamadas == [
        {"catalog_name": CATALOGO_VENTAS, "schema_name": ESQUEMA_BRONCE}
    ]
    assert cliente.registered_models.llamadas == [
        {"catalog_name": CATALOGO_VENTAS, "schema_name": ESQUEMA_BRONCE}
    ]


def TestExternalLocationsYConexionesConNombreSimple():
    """External locations y connections se traducen por su nombre (una parte)."""
    servicio, _ = _CrearServicio(
        external_locations=[_Registro(name="ubicacion_s3")],
        connections=[_Registro(name="mysql_analitica")],
    )

    ubicaciones = servicio.DescubrirExternalLocations()
    conexiones = servicio.DescubrirConexiones()

    assert len(ubicaciones) == 1
    assert ubicaciones[0].tipo == TipoObjeto.EXTERNAL_LOCATION
    assert ubicaciones[0].identificador == "ubicacion_s3"
    assert len(conexiones) == 1
    assert conexiones[0].tipo == TipoObjeto.CONNECTION
    assert conexiones[0].identificador == "mysql_analitica"


def TestFalloDeListadoUcNuevoSeTraduce():
    """Un fallo en conexiones se traduce a ErrorDescubrimientoOpciones."""
    cliente = ClienteUcFalso(
        connections=ServicioListadoFalso(excepcion=RuntimeError("connections sin scope"))
    )
    descubridor = DescubridorUc(cliente=cliente)
    servicio = ServicioDescubrimientoUi(descubridor_uc=descubridor)

    with pytest.raises(ErrorDescubrimientoOpciones):
        servicio.DescubrirConexiones()
