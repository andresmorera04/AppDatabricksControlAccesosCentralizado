"""Pruebas unitarias del mapeo declarativo extendido de recursos y el rechazo de
tipos ajenos tras la extensión del canal de cómputo (tarea 1.1 del change
`grants-apps-tokens`).

Verifican que `RECURSO_PERMISOS_POR_TIPO_OBJETO` ahora cubre los cinco tipos del
plano de control (tres de cómputo de C7 + dos nuevos de C8), la construcción de
la ruta con la regla singleton para `USO_TOKEN` (sin segmento de id) y el
rechazo explícito de tipos del plano de datos.
"""

import pytest

from control_accesos.canales.errores import ErrorCanal
from control_accesos.canales.reales.canal_control_computo import (
    PREFIJO_API_PERMISOS,
    RECURSO_PERMISOS_POR_TIPO_OBJETO,
    CanalControlComputo,
)
from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable


class TestRecursosAppsTokens:
    """Los dos tipos nuevos del plano de control resuelven su recurso de la API."""

    def TestDatabricksAppResuelveApps(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.DATABRICK_APP)
        assert recurso == "apps"

    def TestUsoTokenResuelveAuthorizationTokens(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.USO_TOKEN)
        assert recurso == "authorization/tokens"


class TestRutasAppsTokens:
    """La ruta incluye el recurso y conserva la escritura del id; para
    `USO_TOKEN` la ruta es singleton (sin segmento de id).
    """

    def TestRutaAppConIdentificador(self):
        objeto = ObjetoSecurable(
            identificador="mi-databricks-app", tipo=TipoObjeto.DATABRICK_APP
        )
        ruta = CanalControlComputo.RutaDePermisos(objeto)
        assert ruta == f"{PREFIJO_API_PERMISOS}/apps/mi-databricks-app"

    def TestRutaAppConservaEscrituraDelId(self):
        objeto = ObjetoSecurable(
            identificador="MiApp123", tipo=TipoObjeto.DATABRICK_APP
        )
        ruta = CanalControlComputo.RutaDePermisos(objeto)
        assert ruta.endswith("/MiApp123")

    def TestRutaTokenSinSegmentoDeId(self):
        objeto = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        ruta = CanalControlComputo.RutaDePermisos(objeto)
        # authorization/tokens es singleton del workspace: la ruta no lleva id
        assert ruta == f"{PREFIJO_API_PERMISOS}/authorization/tokens"


class TestMapaExtendidoCompleto:
    """El mapa declarativo cubre los cinco tipos del plano de control."""

    def TestCincoTipos(self):
        assert set(RECURSO_PERMISOS_POR_TIPO_OBJETO) == {
            # Cómputo (C7)
            TipoObjeto.COMPUTO_CLASICO,
            TipoObjeto.COMPUTO_SERVERLESS,
            TipoObjeto.SQL_WAREHOUSE,
            # Apps y tokens (C8)
            TipoObjeto.DATABRICK_APP,
            TipoObjeto.USO_TOKEN,
        }


class TestNoRegresionComputo:
    """Los tres tipos de cómputo de C7 siguen funcionando tras la extensión."""

    def TestClusterClasico(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.COMPUTO_CLASICO)
        assert recurso == "clusters"

    def TestComputoServerless(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.COMPUTO_SERVERLESS)
        assert recurso == "serverless-compute"

    def TestSqlWarehouse(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.SQL_WAREHOUSE)
        assert recurso == "sql/warehouses"


class TestRechazoTipoAjeno:
    """Un tipo del plano de datos se rechaza antes de llamar a la API."""

    @pytest.mark.parametrize(
        "tipo_recibido",
        [
            TipoObjeto.TABLA_DELTA,
            TipoObjeto.ESQUEMA,
            TipoObjeto.VOLUMEN,
        ],
    )
    def TestRechazoPlanoDeDatos(self, tipo_recibido):
        with pytest.raises(ErrorCanal) as capturado:
            CanalControlComputo.RecursoDeTipo(tipo_recibido)
        assert tipo_recibido.value in str(capturado.value)
