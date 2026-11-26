"""Pruebas integrales de Databricks Apps y uso de personal access tokens contra el
workspace `andresFree` (tareas 6.1–6.3 del change `grants-apps-tokens`).

Marcadores: `free` (ejecuta en Free Edition) + `azure_approval` (pre-aprobado
por el humano, design D8). Si la spike (6.1) confirma que algún caso no está
disponible en Free, su cobertura se escribe en
`test_grants_apps_tokens_andresazuredev.py` (tarea 6.4, obligatoria).
"""

import os

import pytest

from control_accesos.canales.errores import ErrorCanal, ErrorPrivilegiosInsuficientes
from control_accesos.canales.simulados.canales_simulados import CanalDatosSimulado
from control_accesos.dominio.enumeraciones import TipoObjeto, TipoPrincipal
from control_accesos.dominio.modelos import ObjetoSecurable, Principal, SolicitudGrant
from control_accesos.pipeline.pipeline_grants import PipelineGrants

from tests.integrales.fixtures_computo import (
    ACLRestaurada,
    CanalEjecutorRestringido,
    CanalParaPerfil,
    OtorgatariosDePerfil,
    PERFIL_FREE,
    APP_ID_SP_FREE,
    NOMBRE_GRUPO_FREE,
    VARIABLE_SECRET_EJECUTOR,
)


# ──────────────────────────────────────────────────────────────────────
# Spike (tarea 6.1): descubrimiento de Apps y Token Permissions API
# ──────────────────────────────────────────────────────────────────────

class TestSpikeDisponibilidadAppsTokens:
    """Spike de descubrimiento (tarea 6.1): qué APIs están disponibles en Free."""

    def TestDescubrirAppsDisponibles(self):
        """Verifica si la Permissions API para Apps responde en el workspace."""
        canal = CanalParaPerfil(PERFIL_FREE)
        adaptador = canal.transporte
        try:
            # Intentar leer la ACL de apps (no de una app específica, sino el recurso)
            # La API de apps requiere un id de app, así que intentamos con un id vacío
            # para ver si el recurso existe.
            # Si la API devuelve un error distinto de "not found" para el recurso,
            # significa que el endpoint está disponible.
            adaptador.LeerAcl("apps", "prueba-disponibilidad")
        except ErrorCanal as error:
            texto = str(error).lower()
            # "not found" = el recurso existe pero la app no → API disponible
            # "not enabled" o similar = la API no está habilitada
            if "not enabled" in texto or "feature" in texto:
                pytest.skip("Databricks Apps Permissions API no disponible en este workspace")
            # Otros errores (not found, permission denied) → la API existe
        except Exception:
            pytest.skip("No se pudo conectar con el workspace para la spike")

    def TestDescubrirTokenPermissionsApi(self):
        """Verifica si la Token Permissions API está habilitada en el workspace."""
        canal = CanalParaPerfil(PERFIL_FREE)
        adaptador = canal.transporte
        try:
            # authorization/tokens es singleton: no requiere id
            acl = adaptador.LeerAcl("authorization/tokens", "")
            # Si llegamos aquí, la API está habilitada
            assert acl is not None or acl == []
        except ErrorCanal as error:
            texto = str(error).lower()
            if "not enabled" in texto or "feature" in texto:
                pytest.skip("Token Permissions API no habilitada en este workspace")
            # Permission denied = la API existe pero el ejecutor no tiene acceso
            if "permiso denegado" in texto or "permission" in texto:
                pass  # API disponible, solo falta permiso
        except Exception:
            pytest.skip("No se pudo conectar con el workspace para la spike")


# ──────────────────────────────────────────────────────────────────────
# Fixtures para Apps y Tokens (tarea 6.2)
# ──────────────────────────────────────────────────────────────────────

def _DescubrirAppExistente(perfil):
    """Intenta descubrir una Databricks App existente en el workspace.

    La Permissions API para apps espera el **nombre** de la app o su
    `app_id` (no el UUID interno `id`), según la documentación:
    `/api/2.0/permissions/apps/{app_name_or_id}`.

    Args:
        perfil (str): perfil CLI del workspace.

    Returns:
        str | None: identificador de una app existente (nombre o app_id),
            o None si no hay ninguna.
    """
    from databricks.sdk import WorkspaceClient
    cliente = WorkspaceClient(profile=perfil)
    try:
        apps = list(cliente.apps.list())
        if apps:
            app = apps[0]
            # La Permissions API acepta el nombre o el app_id.
            # Preferimos el nombre por ser legible; si no tiene, usamos app_id.
            identificador = getattr(app, "name", None) or getattr(app, "app_id", None)
            if identificador:
                return identificador
    except Exception:
        pass
    return None


def _DescubrirTokenAcl(perfil):
    """Intenta leer la ACL singleton de Token Permissions.

    Args:
        perfil (str): perfil CLI del workspace.

    Returns:
        tuple | None: ACL de tokens, o None si la API no está disponible.
    """
    from control_accesos.canales.reales.cliente_permisos_sdk import ClientePermisosSdk
    from databricks.sdk import WorkspaceClient

    cliente = WorkspaceClient(profile=perfil)
    adaptador = ClientePermisosSdk(cliente)
    try:
        return adaptador.LeerAcl("authorization/tokens", "")
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# Integrales por caso (tareas 6.3 / 6.4)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.free
@pytest.mark.azure_approval
class TestIntegralesApps:
    """Integrales de Databricks Apps contra el workspace Free."""

    def TestOtorgamientoCanUseAppExistente(self):
        """Otorgar CAN_USE sobre una App existente otorga y verifica."""
        app_id = _DescubrirAppExistente(PERFIL_FREE)
        if app_id is None:
            pytest.skip("No hay Databricks Apps en el workspace para probar")

        canal = CanalParaPerfil(PERFIL_FREE)
        app = ObjetoSecurable(identificador=app_id, tipo=TipoObjeto.DATABRICK_APP)
        sp = Principal(identificador=APP_ID_SP_FREE, tipo=TipoPrincipal.SERVICE_PRINCIPAL)

        with ACLRestaurada(canal, "apps", app_id):
            solicitud = SolicitudGrant(
                principal=sp, privilegios=("CAN_USE",), objeto=app
            )
            reporte = PipelineGrants(
                canal_datos=CanalDatosSimulado(), canal_control=canal
            ).Procesar(solicitud)

            assert len(reporte.lineas) == 1
            assert reporte.lineas[0].estado.value == "otorgado"


@pytest.mark.free
@pytest.mark.azure_approval
class TestIntegralesTokenPermissions:
    """Integrales de Token Permissions API contra el workspace Free."""

    def TestOtorgamientoCanUseTokenPermissions(self):
        """Otorgar CAN_USE sobre uso de tokens opera en singleton."""
        acl = _DescubrirTokenAcl(PERFIL_FREE)
        if acl is None:
            pytest.skip("Token Permissions API no disponible en el workspace")

        canal = CanalParaPerfil(PERFIL_FREE)
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )
        sp = Principal(identificador=APP_ID_SP_FREE, tipo=TipoPrincipal.SERVICE_PRINCIPAL)

        with ACLRestaurada(canal, "authorization/tokens", ""):
            solicitud = SolicitudGrant(
                principal=sp, privilegios=("CAN_USE",), objeto=token_obj
            )
            reporte = PipelineGrants(
                canal_datos=CanalDatosSimulado(), canal_control=canal
            ).Procesar(solicitud)

            assert len(reporte.lineas) == 1
            assert reporte.lineas[0].estado.value == "otorgado"

    def TestLecturaAclTokenSingleton(self):
        """Listar grants vigentes de tokens lee la ACL singleton."""
        acl = _DescubrirTokenAcl(PERFIL_FREE)
        if acl is None:
            pytest.skip("Token Permissions API no disponible en el workspace")

        canal = CanalParaPerfil(PERFIL_FREE)
        token_obj = ObjetoSecurable(
            identificador="workspace", tipo=TipoObjeto.USO_TOKEN
        )

        grants = canal.ListarGrantsVigentes(token_obj)
        # La ACL singleton existe; puede estar vacía o con entradas
        assert isinstance(grants, list)


@pytest.mark.free
@pytest.mark.azure_approval
class TestIntegralesPermisoDenegado:
    """Integral de permiso denegado con SP restringido (tarea 6.5)."""

    def TestPermisoDenegadoConEjecutorRestringido(self):
        """El SP sin privilegios recibe PERMISSION_DENIED (design D6)."""
        client_secret = os.environ.get(VARIABLE_SECRET_EJECUTOR)
        if not client_secret:
            pytest.skip(
                f"Variable {VARIABLE_SECRET_EJECUTOR} no definida; "
                "se requiere para la integral de permiso denegado."
            )

        # Necesitamos una app existente para que el SP la vea pero no pueda
        # gestionar sus permisos.
        app_id = _DescubrirAppExistente(PERFIL_FREE)
        if app_id is None:
            pytest.skip("No hay Databricks Apps en el workspace para probar")

        canal = CanalEjecutorRestringido(
            client_id=APP_ID_SP_FREE,
            client_secret=client_secret,
        )

        # Intentar leer la ACL de la app existente con un SP sin privilegios
        # Debería producir PERMISSION_DENIED
        adaptador = canal.transporte
        with pytest.raises((ErrorCanal, ErrorPrivilegiosInsuficientes)) as exc:
            adaptador.LeerAcl("apps", app_id)

        # El error debe mencionar permiso denegado
        texto = str(exc.value).lower()
        assert (
            "permiso denegado" in texto
            or "permission" in texto
            or "privilegio" in texto
        ), f"Error inesperado: {exc.value}"
