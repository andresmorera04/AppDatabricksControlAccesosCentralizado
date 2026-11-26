"""Prueba integral del spike del gate de viabilidad OBO (C9, tarea 2.4, D4).

Capa integral (marker `free`) contra el workspace `andresFree`. Esta prueba es
el gate go/no-go del change `web-ui-minimalista`: NINGUNA tarea posterior a
2.4 puede marcarse completada si el gate no verifica todos los scopes y
recursos necesarios (tasks.md 2.4; design.md D4 - "si el workspace no ofrece
un scope necesario, la implementación se detiene en ese gate y se eleva al
humano la limitación concreta", jamás un fallback a la identidad de la App).

Bucle del gate (la creación de la App, los scopes y el consentimiento son
MANUALES por diseño, design.md D4 y plan de migración paso 2):

1. crear la App spike en `andresFree` con autorización de usuario y los
   scopes requeridos::

       databricks apps create control-accesos-spike \\
         --profile andresFree \\
         --forward-user-access-token \\
         --description "Spike del gate OBO (C9 web-ui-minimalista)" \\
         --json '{"user_api_scopes": ["sql", "apps", "catalog.catalogs",
                                      "catalog.schemas", "catalog.tables",
                                      "catalog.connections",
                                      "workspace.workspace"]}'

2. subir el bundle desplegable al sistema de archivos del workspace y
   desplegarlo. La subida usa ``databricks bundle sync`` (``databricks.yml``
   de la raíz): en el CLI v1.27 ``fs cp`` no soporta rutas WSFS
   (``/Workspace/...``) y ``workspace import-dir`` convertiría los ``.py`` en
   notebooks sin extensión; ``bundle sync`` sube exactamente ``app.py``,
   ``app.yaml``, ``requirements.txt``, ``config/`` y ``control_accesos/``
   preservando nombres y extensiones (verificado con ``--dry-run``)::

       databricks bundle sync
       databricks apps deploy control-accesos-spike \\
         --source-code-path /Workspace/Users/<usuario>/spike-control-accesos \\
         --profile andresFree

3. visitar la App en el navegador, consentir los scopes, pulsar "Ejecutar
   verificaciones del gate D4" y descargar la evidencia JSON;

4. guardar la evidencia en
   ``results/web-ui-minimalista/spike_obo_evidencia.json``;

5. ejecutar esta prueba con el comando de la tarea::

       python -m pytest tests/integrales/test_ui_spike_obo_andresfree.py \\
         -m free --junitxml=results/web-ui-minimalista/spike-free.xml -q

Criterios del gate sobre la evidencia (24 sondas del spike ``app.py``):

- CONJUNTO MÍNIMO (viabilidad del núcleo C9): identidad OBO, descubrimiento
  UC de catálogos/esquemas/tablas, warehouses, SQL remoto (SELECT 1 y SHOW
  GRANTS) y lectura/escritura de ACL del warehouse con restauración.
- CONJUNTO COMPLETO (alcance total de C9 sobre C1-C8): listados SCIM de
  usuarios/grupos/service principals, conexiones UC, rutas SQL de
  descubrimiento de volúmenes/modelos/external locations, clusters, apps y
  lectura/escritura de ACL de cluster, app y del singleton de tokens.

Una sonda en ``no_disponible`` (el workspace no expone el recurso) NO
invalida el gate; una sonda en ``fallo`` sí (limitación de scope o de
runtime: se eleva al humano con el detalle).

Rojo antes del despliegue: sin App creada ni evidencia, las pruebas fallan
con las instrucciones anteriores; ese rojo es el estado inicial exigido por
la tarea ("ejecutar el rojo antes del despliegue").
"""

import json
from pathlib import Path

import pytest
import yaml

from adaptador_sql_databricks import (
    EjecutarComandoCli,
    ErrorTransporteDatabricks,
)

# Todas las pruebas de este módulo son integrales contra andresFree.
pytestmark = pytest.mark.free

# Raíz del proyecto, derivada de la ubicación de este archivo
# (tests/integrales/ -> raíz), sin rutas absolutas escritas a mano.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Nombre de la App spike acordado para el gate (fixture del workspace, misma
# convención que PERFIL_CLI_INTEGRAL: constante explícita de la capa
# integral, no configuración de producción).
NOMBRE_APP_SPIKE = "control-accesos-spike"
RUTA_API_APP_SPIKE = f"/api/2.0/apps/{NOMBRE_APP_SPIKE}"

# Identificador del spike que la evidencia debe reportar (app.py).
IDENTIFICADOR_SPIKE_ESPERADO = "spike-obo-c9"

# Ruta relativa de la evidencia descargada desde la App desplegada.
RUTA_RELATIVA_EVIDENCIA = (
    "results/web-ui-minimalista/spike_obo_evidencia.json"
)
RUTA_ARCHIVO_EVIDENCIA = RAIZ_PROYECTO / Path(RUTA_RELATIVA_EVIDENCIA)

# Estado de la App que permite ejecutar las sondas.
ESTADO_APP_ACTIVA = "ACTIVE"

# Scopes de autorización de usuario que la App spike debe tener declarados
# (catálogo oficial de scopes soportados por Databricks Apps, consultado en
# C9; los iam.* por defecto no se declaran y acompañan siempre).
SCOPES_REQUERIDOS = (
    "sql",
    "apps",
    "catalog.catalogs",
    "catalog.schemas",
    "catalog.tables",
    "catalog.connections",
    "workspace.workspace",
)

# Estados de sonda que satisfacen el gate (``no_disponible`` = el workspace
# no expone el recurso; no es una limitación de scope).
ESTADOS_ACEPTABLES = ("ok", "no_disponible")

# CONJUNTO MÍNIMO: núcleo de viabilidad de C9 (identidad, descubrimiento UC,
# SQL remoto y Permissions API del warehouse con escritura restaurada).
CONJUNTO_MINIMO_GATE = (
    "identidad_obo",
    "uc_catalogos",
    "uc_esquemas",
    "uc_tablas",
    "sql_warehouses",
    "sql_select_uno",
    "sql_show_grants",
    "acl_lectura_warehouse",
    "acl_escritura_warehouse_restaurada",
)

# CONJUNTO COMPLETO: operaciones del alcance total de C9 sobre C1-C8 cuyo
# fallo constituye la limitación que la tarea 2.4 manda elevar al humano.
CONJUNTO_COMPLETO_GATE = (
    "scim_usuarios",
    "scim_grupos",
    "scim_service_principals",
    "uc_conexiones",
    "computo_clusters",
    "apps_lista",
    "sql_show_volumes",
    "sql_show_models",
    "sql_show_external_locations",
    "acl_lectura_cluster",
    "acl_lectura_app",
    "acl_lectura_tokens",
    "acl_escritura_cluster_restaurada",
    "acl_escritura_app_restaurada",
    "acl_escritura_tokens_restaurada",
)

# Paquete desplegable mínimo: archivos que deben viajar al workspace.
ARCHIVOS_BUNDLE_DESPLEGABLE = (
    "app.py",
    "app.yaml",
    "requirements.txt",
    "config/app_properties.json",
)

# Pines de runtime que el bundle debe declarar (tareas 1.1/1.2/2.3).
PINES_RUNTIME_ESPERADOS = (
    "streamlit==",
    "databricks-sdk==",
    "databricks-connect==",
)

# Instrucciones para el humano cuando falta la App o la evidencia (el
# docstring del módulo las desarrolla; aquí se usa la referencia corta).
INSTRUCCIONES_GATE = (
    "Pasos humanos pendientes (docstring de este módulo y tasks.md 2.4): "
    "crear la App con autorización de usuario y scopes, subir el bundle, "
    "desplegar, visitar la App, consentir, ejecutar las sondas y guardar la "
    "evidencia JSON descargada en "
    f"'{RUTA_RELATIVA_EVIDENCIA}'."
)


def TestBundleDesplegableCoherente():
    """El bundle de la raíz es coherente con el manifiesto y el runtime.

    Verificación local (sin red): la entrada del spike existe, el manifiesto
    la arranca con Streamlit y el runtime declara los tres pines acordados
    (Streamlit 1.67.0, SDK 0.170.0 y Connect 15.4.27).
    """
    for archivo_relativo in ARCHIVOS_BUNDLE_DESPLEGABLE:
        assert (RAIZ_PROYECTO / archivo_relativo).is_file(), (
            f"El bundle desplegable no incluye '{archivo_relativo}'; la App "
            f"no puede construirse (tarea 2.4)."
        )

    manifiesto = yaml.safe_load(
        (RAIZ_PROYECTO / "app.yaml").read_text(encoding="utf-8")
    )
    assert "app.py" in (manifiesto.get("command") or []), (
        "El manifiesto app.yaml no arranca 'app.py': el bundle desplegado no "
        "ejecutaría la entrada del spike (design.md D1)."
    )

    texto_runtime = (RAIZ_PROYECTO / "requirements.txt").read_text(
        encoding="utf-8"
    )
    for pin_esperado in PINES_RUNTIME_ESPERADOS:
        assert pin_esperado in texto_runtime, (
            f"requirements.txt no declara '{pin_esperado}': el contenedor de "
            f"la App no instalaría el runtime validado (tareas 1.1/2.3)."
        )


def TestAppSpikeCreadaActivaConScopes():
    """La App spike existe en andresFree, está activa y declara los scopes."""
    try:
        respuesta = EjecutarComandoCli(["get", RUTA_API_APP_SPIKE])
    except ErrorTransporteDatabricks as excepcion:
        pytest.fail(
            f"La App spike '{NOMBRE_APP_SPIKE}' no existe o no es accesible "
            f"en andresFree. {INSTRUCCIONES_GATE} Error del transporte: "
            f"{excepcion}"
        )

    if "user_api_scopes" not in respuesta:
        pytest.fail(
            f"La App '{NOMBRE_APP_SPIKE}' existe pero la respuesta de la "
            f"Apps API no informa 'user_api_scopes': verifique que la "
            f"autorización de usuario esté habilitada con los scopes "
            f"{SCOPES_REQUERIDOS}. {INSTRUCCIONES_GATE}"
        )
    scopes_declarados = respuesta.get("user_api_scopes") or []
    scopes_faltantes = [
        scope
        for scope in SCOPES_REQUERIDOS
        if scope not in scopes_declarados
    ]
    assert not scopes_faltantes, (
        f"A la App '{NOMBRE_APP_SPIKE}' le faltan scopes de autorización de "
        f"usuario: {scopes_faltantes}. Sin ellos las sondas correspondientes "
        f"quedarán denegadas y el gate no podrá verificarse (design.md D4). "
        f"Declarados: {scopes_declarados}."
    )

    estado_app = respuesta.get("app_status") or respuesta.get("status")
    assert estado_app == ESTADO_APP_ACTIVA, (
        f"La App '{NOMBRE_APP_SPIKE}' no está activa (estado: "
        f"{estado_app!r}); despliegue/arranque pendientes. "
        f"{INSTRUCCIONES_GATE}"
    )


def _CargarEvidencia():
    """Carga y valida la estructura de la evidencia del gate.

    Returns:
        dict: evidencia descargada desde la App desplegada.
    """
    if not RUTA_ARCHIVO_EVIDENCIA.is_file():
        pytest.fail(
            f"No existe la evidencia del gate en "
            f"'{RUTA_RELATIVA_EVIDENCIA}'. {INSTRUCCIONES_GATE}"
        )
    try:
        evidencia = json.loads(
            RUTA_ARCHIVO_EVIDENCIA.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as excepcion:
        pytest.fail(
            f"La evidencia '{RUTA_RELATIVA_EVIDENCIA}' no es JSON válido: "
            f"{excepcion}"
        )

    assert isinstance(evidencia, dict) and evidencia.get("sondas"), (
        f"La evidencia '{RUTA_RELATIVA_EVIDENCIA}' no tiene la forma "
        f"esperada (dict con 'sondas'); vuelva a descargarla desde la App "
        f"spike."
    )
    return evidencia


def TestEvidenciaDelGateDisponible():
    """La evidencia existe, es del spike y está ligada a un usuario OBO."""
    evidencia = _CargarEvidencia()

    assert evidencia.get("spike") == IDENTIFICADOR_SPIKE_ESPERADO, (
        f"La evidencia no fue generada por el spike "
        f"'{IDENTIFICADOR_SPIKE_ESPERADO}' (valor encontrado: "
        f"{evidencia.get('spike')!r})."
    )
    assert evidencia.get("usuario"), (
        "La evidencia no reporta usuario OBO: las sondas no se ejecutaron "
        "con una identidad de usuario real consentida (spec - autenticación "
        "on-behalf-of)."
    )


def _VerificarConjuntoGate(evidencia, conjunto, nombre_conjunto):
    """Verifica que todas las sondas de un conjunto satisfacen el gate.

    Args:
        evidencia (dict): evidencia cargada del gate.
        conjunto (tuple[str, ...]): nombres de sondas del conjunto.
        nombre_conjunto (str): nombre legible para el mensaje de fallo.

    Returns:
        list[str]: descripciones de las sondas que no satisfacen el gate.
    """
    sondas_por_nombre = {
        sonda["nombre"]: sonda for sonda in evidencia["sondas"]
    }
    problemas = []
    for nombre_sonda in conjunto:
        sonda = sondas_por_nombre.get(nombre_sonda)
        if sonda is None:
            problemas.append(
                f"{nombre_sonda}: AUSENTE en la evidencia (spike incompleto)."
            )
        elif sonda["estado"] not in ESTADOS_ACEPTABLES:
            problemas.append(
                f"{nombre_sonda}: {sonda['estado']} — {sonda['detalle']}"
            )
    return problemas


def TestGateConjuntoMinimoVerificado():
    """GO/NO-GO mínimo: núcleo OBO viable en andresFree."""
    evidencia = _CargarEvidencia()

    problemas = _VerificarConjuntoGate(
        evidencia, CONJUNTO_MINIMO_GATE, "mínimo"
    )
    assert not problemas, (
        "GATE MÍNIMO NO-GO: el núcleo de C9 (identidad OBO, descubrimiento "
        "UC, SQL remoto y Permissions API del warehouse) no está verificado "
        "en andresFree:\n- " + "\n- ".join(problemas)
    )


def TestGateConjuntoCompletoVerificado():
    """GO/NO-GO completo: todas las operaciones del alcance C9 verificadas.

    Si alguna sonda de este conjunto falla, la limitación concreta debe
    elevarse al humano (tasks.md 2.4): NO se marca la tarea completada, NO
    se continúa con las tareas posteriores y NO se sustituye la credencial
    del llamante por la identidad de la App (design.md D4).
    """
    evidencia = _CargarEvidencia()

    problemas = _VerificarConjuntoGate(
        evidencia, CONJUNTO_COMPLETO_GATE, "completo"
    )
    assert not problemas, (
        "GATE COMPLETO NO-GO: limitaciones de scopes/recursos para el "
        "alcance total de C9 (elevar al humano; detener tareas posteriores):\n- "
        + "\n- ".join(problemas)
    )
