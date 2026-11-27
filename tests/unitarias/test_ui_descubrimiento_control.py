"""Prueba unitaria del descubrimiento de objetos del plano de control (D6).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 3.4.

Contrato que fija esta prueba, sobre el adaptador de control (`DescubridorControl`)
con dos contextos —service principal (cómpunto) y OBO (warehouses/Apps)— y su
traducción a `ObjetoSecurable`:

- clusters (`COMPUTO_CLASICO`) y serverless compute objects
  (`COMPUTO_SERVERLESS`) se listan con el service principal (el token OBO
  carece de los scopes `clusters`), con su id real como identificador;
- SQL warehouses (`SQL_WAREHOUSE`) y Databricks Apps (`DATABRICK_APP`) se
  listan con la credencial OBO;
- `USO_TOKEN` es singleton: se expone un único objeto con el identificador
  lógico configurado (`identificador_logico_uso_token`), sin listado de API;
- un fallo de listado se traduce a `ErrorDescubrimientoOpciones` (denegación)
  y se distingue de una lista auténticamente vacía (tupla vacía, p. ej. cero
  clusters all-purpose);
- el límite configurable recorta el listado.

No hay red ni SDK real: los clientes SP y OBO son dobles con `list()`.
"""

from types import SimpleNamespace

import pytest

from control_accesos.canales.reales.descubrimiento_control import (
    DescubridorControl,
)
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable
from control_accesos.ui.servicio_descubrimiento import (
    ErrorDescubrimientoOpciones,
    ServicioDescubrimientoUi,
)

CLUSTER_ID = "0808-123456-abcde"
SERVERLESS_ID = "sc-1234567890abcdef"
WAREHOUSE_ID = "1234567890abcdef"
APP_NOMBRE = "securitymanager"
IDENTIFICADOR_LOGICO_TOKEN = "workspace"


def _Registro(**campos):
    """Doble de un registro del SDK (campos como atributos)."""
    return SimpleNamespace(**campos)


class ServicioListadoFalso:
    """Doble de un servicio del SDK con `list()` que registra llamadas."""

    def __init__(self, registros=(), excepcion=None):
        self._registros = list(registros)
        self._excepcion = excepcion
        self.llamadas = []

    def list(self):
        self.llamadas.append(True)
        if self._excepcion is not None:
            raise self._excepcion
        return iter(self._registros)


class ClienteSpFalso:
    """Cliente SP falso: clusters y serverless compute (contexto broker)."""

    def __init__(self, clusters=None, serverless=None):
        self.clusters = clusters or ServicioListadoFalso()
        self.serverless_compute_service = serverless or ServicioListadoFalso()


class ClienteOboFalso:
    """Cliente OBO falso: SQL warehouses y Databricks Apps."""

    def __init__(self, warehouses=None, apps=None):
        self.warehouses = warehouses or ServicioListadoFalso()
        self.apps = apps or ServicioListadoFalso()


def _CrearServicio(
    clusters=(),
    serverless=(),
    warehouses=(),
    apps=(),
    limite=None,
    identificador_logico_token=IDENTIFICADOR_LOGICO_TOKEN,
):
    """Construye el servicio UI sobre un descubridor de control real.

    Returns:
        tuple: (ServicioDescubrimientoUi, ClienteSpFalso, ClienteOboFalso).
    """
    cliente_sp = ClienteSpFalso(
        clusters=ServicioListadoFalso(clusters),
        serverless=ServicioListadoFalso(serverless),
    )
    cliente_obo = ClienteOboFalso(
        warehouses=ServicioListadoFalso(warehouses),
        apps=ServicioListadoFalso(apps),
    )
    descubridor = DescubridorControl(
        cliente_sp=cliente_sp,
        cliente_obo=cliente_obo,
        limite=limite,
        identificador_logico_token=identificador_logico_token,
    )
    return ServicioDescubrimientoUi(descubridor_control=descubridor), cliente_sp, cliente_obo


def TestClustersSeListanConElServicePrincipal():
    """Los clusters se listan con el SP y su identificador es el cluster_id."""
    servicio, _, _ = _CrearServicio(
        clusters=[_Registro(cluster_id=CLUSTER_ID)],
    )

    objetos = servicio.DescubrirClusters()

    assert len(objetos) == 1
    assert objetos[0].tipo == TipoObjeto.COMPUTO_CLASICO
    assert objetos[0].identificador == CLUSTER_ID


def TestServerlessSeListaConElServicePrincipal():
    """Los serverless compute objects se listan con el SP (serverless_compute_id)."""
    servicio, _, _ = _CrearServicio(
        serverless=[_Registro(serverless_compute_id=SERVERLESS_ID)],
    )

    objetos = servicio.DescubrirServerless()

    assert len(objetos) == 1
    assert objetos[0].tipo == TipoObjeto.COMPUTO_SERVERLESS
    assert objetos[0].identificador == SERVERLESS_ID


def TestWarehousesYAppsSeListanConObo():
    """Warehouses y Apps se listan con la credencial OBO del llamante."""
    servicio, _, cliente_obo = _CrearServicio(
        warehouses=[_Registro(id=WAREHOUSE_ID)],
        apps=[_Registro(name=APP_NOMBRE)],
    )

    warehouses = servicio.DescubrirWarehouses()
    apps = servicio.DescubrirApps()

    assert warehouses[0].tipo == TipoObjeto.SQL_WAREHOUSE
    assert warehouses[0].identificador == WAREHOUSE_ID
    assert apps[0].tipo == TipoObjeto.DATABRICK_APP
    assert apps[0].identificador == APP_NOMBRE
    # Ambos listados partieron del cliente OBO (no del SP).
    assert cliente_obo.warehouses.llamadas and cliente_obo.apps.llamadas


def TestUsoTokensEsSingletonConIdentificadorLogico():
    """USO_TOKEN se expone como singleton con el identificador lógico configurado."""
    servicio, _, _ = _CrearServicio()

    objetos = servicio.DescubrirUsoTokens()

    assert len(objetos) == 1
    assert objetos[0].tipo == TipoObjeto.USO_TOKEN
    assert objetos[0].identificador == IDENTIFICADOR_LOGICO_TOKEN


def TestLimiteConfigurableEnClusters():
    """El límite recorta el listado de clusters."""
    clusters = [_Registro(cluster_id=f"cl-{indice}") for indice in range(5)]
    servicio, _, _ = _CrearServicio(clusters=clusters, limite=2)

    objetos = servicio.DescubrirClusters()

    assert [o.identificador for o in objetos] == ["cl-0", "cl-1"]


def TestDenegacionNoSeConvierteEnListaVacia():
    """Una denegación de listado eleva error; el vacío auténtico, tupla vacía."""
    def _servicio(sp_excepcion=None, obo_excepcion=None):
        cliente_sp = ClienteSpFalso(
            clusters=ServicioListadoFalso(excepcion=sp_excepcion),
            serverless=ServicioListadoFalso(excepcion=sp_excepcion),
        )
        cliente_obo = ClienteOboFalso(
            warehouses=ServicioListadoFalso(excepcion=obo_excepcion),
            apps=ServicioListadoFalso(excepcion=obo_excepcion),
        )
        descubridor = DescubridorControl(cliente_sp=cliente_sp, cliente_obo=cliente_obo)
        return ServicioDescubrimientoUi(descubridor_control=descubridor)

    with pytest.raises(ErrorDescubrimientoOpciones):
        _servicio(sp_excepcion=RuntimeError("clusters: permiso denegado")).DescubrirClusters()
    with pytest.raises(ErrorDescubrimientoOpciones):
        _servicio(obo_excepcion=RuntimeError("warehouses: sin scope")).DescubrirWarehouses()

    # Cero clusters all-purpose (Free Edition) es vacío auténtico, no error.
    servicio_vacio, _, _ = _CrearServicio(clusters=(), serverless=())
    assert servicio_vacio.DescubrirClusters() == ()
    assert servicio_vacio.DescubrirServerless() == ()
