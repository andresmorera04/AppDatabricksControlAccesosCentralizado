"""Pruebas unitarias del mapeo declarativo de recursos y el rechazo de tipos
ajenos del canal de cómputo (tareas 1.1 y 1.2 del change `grants-compute`).

Verifican el dato declarativo `RECURSO_PERMISOS_POR_TIPO_OBJETO` (design D2), la
construcción de la ruta con la conservación de la escritura del id (los ids del
plano de control no se normalizan a minúsculas) y la validación del transporte
inyectado en el constructor, sin realizar llamada externa alguna.
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


class TestRecursoDeTipo:
    """El mapa declarativo asocia cada tipo de cómputo a su recurso de la API."""

    def TestClusterClasico(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.COMPUTO_CLASICO)
        assert recurso == "clusters"

    def TestComputoServerless(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.COMPUTO_SERVERLESS)
        assert recurso == "serverless-compute"

    def TestSqlWarehouse(self):
        recurso = CanalControlComputo.RecursoDeTipo(TipoObjeto.SQL_WAREHOUSE)
        assert recurso == "sql/warehouses"

    def TestMapaCompleto(self):
        assert set(RECURSO_PERMISOS_POR_TIPO_OBJETO) == {
            TipoObjeto.COMPUTO_CLASICO,
            TipoObjeto.COMPUTO_SERVERLESS,
            TipoObjeto.SQL_WAREHOUSE,
        }


class TestRechazoTipoAjeno:
    """Un tipo fuera de los tres de cómputo se rechaza antes de llamar a la API."""

    @pytest.mark.parametrize(
        "tipo_recibido",
        [
            TipoObjeto.TABLA_DELTA,
            TipoObjeto.DATABRICK_APP,
            TipoObjeto.USO_TOKEN,
        ],
    )
    def TestRechazo(self, tipo_recibido):
        with pytest.raises(ErrorCanal) as capturado:
            CanalControlComputo.RecursoDeTipo(tipo_recibido)
        assert tipo_recibido.value in str(capturado.value)


class TestRutaDePermisos:
    """La ruta incluye el recurso y el id del objeto conservando su escritura."""

    def TestRutaIncluyeRecursoEIdentificador(self):
        objeto = ObjetoSecurable(
            identificador="MiCluster123", tipo=TipoObjeto.COMPUTO_CLASICO
        )
        ruta = CanalControlComputo.RutaDePermisos(objeto)
        assert ruta == f"{PREFIJO_API_PERMISOS}/clusters/MiCluster123"

    def TestIdentificadorNoSeNormalizaAMinusculas(self):
        objeto = ObjetoSecurable(
            identificador="Wh-AbC-XyZ", tipo=TipoObjeto.SQL_WAREHOUSE
        )
        ruta = CanalControlComputo.RutaDePermisos(objeto)
        assert ruta.endswith("/Wh-AbC-XyZ")


class TestConstruccionCanal:
    """Validación del transporte inyectado en el constructor (design D3)."""

    def TestTransporteValidoSeAcepta(self):
        transporte = _TransporteMinimo()
        canal = CanalControlComputo(transporte)
        assert canal.transporte is transporte

    def TestTransporteSinPuertosSeRechaza(self):
        with pytest.raises(ValueError):
            CanalControlComputo(object())

    def TestTransporteNuloSeRechaza(self):
        with pytest.raises(ValueError):
            CanalControlComputo(None)


class _TransporteMinimo:
    """Transporte de permisos mínimo para ejercitar el constructor."""

    def LeerAcl(self, recurso, identificador):
        return ()

    def EscribirAcl(self, recurso, identificador, entradas):
        return None
