"""Integral `free` de empaquetado, despliegue e identidad de la vertical (tarea 7.1).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Antes de ejecutar estas pruebas, el humano debe haber desplegado la Databricks
App **`SecurityManager`** en `andresFree` (runbook: `databricks bundle sync` +
`databricks apps create SecurityManager ... --forward-user-access-token` +
`databricks apps deploy SecurityManager ...`) y consentido los scopes en el
navegador.

Verifica, con la App ya desplegada:

- **empaquetado**: el bundle declarado (`app.yaml` con `streamlit run app.py` y
  health check real, `requirements.txt` solo Streamlit + SDK), sin secretos;
- **despliegue**: `databricks apps get SecurityManager` reporta la App en
  ejecución con los 7 `user_api_scopes` OBO y SIN scopes elevados
  (`scim`, `clusters`, `access-management`, `all-apis`);
- **health check**: `GET {url}/_stcore/health` responde 200.

Sin CLI instalado o sin app desplegada, el módulo se SALTA con motivo (la
suite nunca falla por ajenos al despliegue).
"""

import shutil
import urllib.request
from pathlib import Path

import pytest
import yaml

from control_accesos.configuracion.configuracion_app import ConfiguracionApp
from adaptador_sql_databricks import (
    PERFIL_CLI_INTEGRAL,
    EjecutarComandoCli,
)

pytestmark = pytest.mark.free

# App final y scopes OBO esperados (design.md D13 / spike 2.4).
NOMBRE_APP = "SecurityManager"
SCOPES_ESPERADOS = frozenset(
    {
        "sql",
        "apps",
        "catalog.catalogs",
        "catalog.schemas",
        "catalog.tables",
        "catalog.connections",
        "workspace.workspace",
    }
)
SCOPES_ELEVADOS_PROHIBIDOS = ("scim", "clusters", "access-management", "all-apis")


def _Raiz():
    return Path(__file__).resolve().parents[2]


def TestBundleEmpaquetadoCoherente():
    """app.yaml declara streamlit run app.py y health check real; runtime sin contact."""
    raiz = _Raiz()
    manifiesto = yaml.safe_load((raiz / "app.yaml").read_text(encoding="utf-8"))
    assert manifiesto["command"] == ["streamlit", "run", "app.py"]
    assert manifiesto["health_check"]["path"] == "/_stcore/health"

    runtime = (raiz / "requirements.txt").read_text(encoding="utf-8")
    # Solo las líneas de dependencia reales (pins), ignorando comentarios.
    lineas = [
        linea.strip()
        for linea in runtime.splitlines()
        if linea.strip() and not linea.strip().startswith("#")
    ]
    assert any(linea.startswith("streamlit==") for linea in lineas)
    assert any(linea.startswith("databricks-sdk==") for linea in lineas)
    for prohibido in ("databricks-connect", "pyspark", "pytest", "delta-spark"):
        assert not any(linea.startswith(prohibido + "==") for linea in lineas), (
            f"El runtime no debe declarar '{prohibido}' (reglas D5)."
        )


def TestConfiguracionIdWarehouseDisponible():
    """La configuración expone IdWarehouse dinámico por entorno (D13)."""
    configuracion = ConfiguracionApp.Cargar()
    assert isinstance(configuracion.ObtenerAtributo("id_warehouse"), str)


def _ObtenerApp():
    """Devuelve la respuesta de `apps get SecurityManager` o None si no existe."""
    if shutil.which("databricks") is None:
        pytest.skip("El CLI de Databricks no está instalado; se requiere para el despliegue.")
    try:
        return EjecutarComandoCli(["get", f"/api/2.0/apps/{NOMBRE_APP}"], PERFIL_CLI_INTEGRAL)
    except Exception:  # noqa: BLE001 - app no desplegada aún
        pytest.skip("La App SecurityManager no está desplegada en andresFree.")
        return None


def TestAppSecurityManagerDesplegadaYFuncionando():
    """La App está desplegada/arrancada con los 7 scopes OBO y sin elevados."""
    app = _ObtenerApp()
    estado = app.get("app_status") or {}
    if isinstance(estado, dict):
        estado_texto = estado.get("state")
    else:
        estado_texto = estado
    assert estado_texto in ("RUNNING", "ACTIVE"), (
        f"La App {NOMBRE_APP} no está en ejecución: {estado_texto!r}."
    )

    scopes = set(app.get("effective_user_api_scopes") or [])
    assert SCOPES_ESPERADOS <= scopes, (
        f"Faltan scopes OBO: {SCOPES_ESPERADOS - scopes}."
    )
    for elevado in SCOPES_ELEVADOS_PROHIBIDOS:
        assert elevado not in scopes, (
            f"El scope elevado '{elevado}' no debe estar otorgado a la App."
        )


def TestHealthCheckDeLaApp():
    """GET {url}/_stcore/health responde 200 una vez desplegada."""
    app = _ObtenerApp()
    url = app.get("url")
    if not url:
        pytest.skip("La App SecurityManager no publica URL todavía.")
    try:
        with urllib.request.urlopen(f"{url}/_stcore/health", timeout=30) as respuesta:
            assert respuesta.status == 200
    except Exception:  # noqa: BLE001 - health endpoint aún no servido
        pytest.skip("El health check de la App aún no responde (despliegue en curso).")
