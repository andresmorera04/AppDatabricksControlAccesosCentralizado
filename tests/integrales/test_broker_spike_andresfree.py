"""Prueba integral del spike broker (change `app-broker-identidad-ejecucion`).

Capa integral (marker `free`) contra el workspace `andresFree`. Es el gate
go/no-go del modelo broker: verifica que la App desplegada ejecuta con la
identidad del service principal las sondas que el token OBO no cubre (listados
SCIM, clusters y ACL del plano de control) y que la resolución de privilegios
sigue evaluando al llamante OBO sobre la ACL leída con el SP (design.md D2/D6).

Bucle del gate (la asignación de privilegios al SP y el consentimiento son
MANUALES, design.md D5/D6):

1. (Acción humana, tarea 1.2) asignar al SP `app-62644q control-accesos-spike`
   el rol Workspace admin y los entitlements Databricks SQL Access, Workspace
   Access y Consumer Access;
2. redesplegar el spike con las sondas broker::

        databricks bundle sync
        databricks apps deploy control-accesos-spike \\
          --source-code-path /Workspace/Users/<usuario>/spike-control-accesos \\
          --profile andresFree

3. visitar la App, consentir, pulsar "Ejecutar verificaciones del gate broker
   (SP)" y guardar la evidencia descargada en
   ``results/app-broker-identidad-ejecucion/broker_evidencia.json``;
4. ejecutar este gate::

        python -m pytest tests/integrales/test_broker_spike_andresfree.py \\
          -m free --junitxml=results/app-broker-identidad-ejecucion/broker-free.xml -q

Rojo antes del despliegue: sin las sondas broker desplegadas ni evidencia, las
pruebas del gate fallan con las instrucciones; ese rojo es el estado inicial
exigido por la tarea 4.1 ("registrar el rojo en broker-free.xml").
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

# Raíz del proyecto, derivada de la ubicación de este archivo.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Nombre de la App spike acordado (misma App que el gate OBO de C9: se reutiliza
# y se le añaden las sondas broker, design.md D6).
NOMBRE_APP_SPIKE = "control-accesos-spike"
RUTA_API_APP_SPIKE = f"/api/2.0/apps/{NOMBRE_APP_SPIKE}"

# Identificador del spike broker que la evidencia debe reportar (app.py).
IDENTIFICADOR_SPIKE_ESPERADO = "spike-broker-app"

# Ruta relativa de la evidencia broker descargada desde la App desplegada.
RUTA_RELATIVA_EVIDENCIA = (
    "results/app-broker-identidad-ejecucion/broker_evidencia.json"
)
RUTA_ARCHIVO_EVIDENCIA = RAIZ_PROYECTO / Path(RUTA_RELATIVA_EVIDENCIA)

# Estados de la App que permiten ejecutar las sondas.
ESTADOS_APP_OPERATIVA = ("RUNNING", "ACTIVE")

# Estados de sonda que satisfacen el gate (``no_disponible`` = el workspace no
# expone el recurso, no es limitación del modelo broker).
ESTADOS_ACEPTABLES = ("ok", "no_disponible")

# CONJUNTO MÍNIMO (viabilidad del núcleo broker): listados SCIM con SP,
# ACL de warehouse y tokens (lectura y escritura restaurada) y resolución de
# los privilegios efectivos del llamante leyendo la ACL con el SP.
CONJUNTO_MINIMO_GATE = (
    "broker_scim_usuarios",
    "broker_scim_grupos",
    "broker_scim_service_principals",
    "broker_acl_lectura_warehouse",
    "broker_acl_escritura_warehouse_restaurada",
    "broker_acl_lectura_tokens",
    "broker_acl_escritura_tokens_restaurada",
    "broker_resolucion_privilegios",
)

# CONJUNTO COMPLETO: superficies de cómputo (clusters all-purpose y serverless
# compute) que el workspace puede no exponer; su fallo es la limitación a elevar
# al humano. Nota "cluster vs compute" (hallazgo 4.2): `clusters` es el cómputo
# all-purpose (0 en Free Edition) y `serverless-compute` es el cómputo serverless
# (la superficie real del workspace), con su ACL en la Permissions API.
CONJUNTO_COMPLETO_GATE = (
    "broker_clusters",
    "broker_serverless",
    "broker_acl_lectura_cluster",
    "broker_acl_lectura_serverless",
    "broker_acl_escritura_cluster_restaurada",
    "broker_acl_escritura_serverless_restaurada",
)

# Paquete desplegable mínimo: archivos que deben viajar al workspace.
ARCHIVOS_BUNDLE_DESPLEGABLE = (
    "app.py",
    "app.yaml",
    "requirements.txt",
    "config/app_properties.json",
)

# Pines de runtime que el bundle debe declarar (tras 2.2, Connect quedó fuera).
PINES_RUNTIME_ESPERADOS = ("streamlit==", "databricks-sdk==")
PINES_RUNTIME_RETIRADOS = ("databricks-connect==",)

# Instrucciones para el humano cuando falta la App o la evidencia.
INSTRUCCIONES_GATE = (
    "Pasos humanos pendientes (docstring de este módulo y tasks.md 4.2): "
    "asignar Workspace admin + entitlements al SP, redesplegar el spike, "
    "visitar la App, consentir, ejecutar las sondas broker y guardar la "
    f"evidencia JSON en '{RUTA_RELATIVA_EVIDENCIA}'."
)


def TestBundleDesplegableBrokerCoherente():
    """El bundle es coherente y retiró databricks-connect (corrección F2)."""
    for archivo_relativo in ARCHIVOS_BUNDLE_DESPLEGABLE:
        assert (RAIZ_PROYECTO / archivo_relativo).is_file(), (
            f"El bundle desplegable no incluye '{archivo_relativo}'."
        )

    manifiesto = yaml.safe_load(
        (RAIZ_PROYECTO / "app.yaml").read_text(encoding="utf-8")
    )
    assert "app.py" in (manifiesto.get("command") or []), (
        "El manifiesto app.yaml no arranca 'app.py'."
    )

    texto_runtime = (RAIZ_PROYECTO / "requirements.txt").read_text(
        encoding="utf-8"
    )
    for pin_esperado in PINES_RUNTIME_ESPERADOS:
        assert pin_esperado in texto_runtime, (
            f"requirements.txt no declara '{pin_esperado}'."
        )
    for pin_retirado in PINES_RUNTIME_RETIRADOS:
        assert pin_retirado not in texto_runtime, (
            f"requirements.txt aún declara '{pin_retirado}': la corrección F2 "
            f"retiró databricks-connect del runtime (SQL OBO por Statement "
            f"Execution API)."
        )


def TestAppSpikeOperativa():
    """La App spike existe en andresFree y está en ejecución."""
    try:
        respuesta = EjecutarComandoCli(["get", RUTA_API_APP_SPIKE])
    except ErrorTransporteDatabricks as excepcion:
        pytest.fail(
            f"La App spike '{NOMBRE_APP_SPIKE}' no existe o no es accesible en "
            f"andresFree. {INSTRUCCIONES_GATE} Error: {excepcion}"
        )

    estado_app = respuesta.get("app_status") or respuesta.get("status")
    if isinstance(estado_app, dict):
        estado_app = estado_app.get("state")
    assert estado_app in ESTADOS_APP_OPERATIVA, (
        f"La App '{NOMBRE_APP_SPIKE}' no está en ejecución (estado: "
        f"{estado_app!r}); despliegue/arranque pendientes. {INSTRUCCIONES_GATE}"
    )


def _CargarEvidencia():
    """Carga y valida la evidencia broker del gate.

    Returns:
        dict: evidencia descargada desde la App desplegada.
    """
    if not RUTA_ARCHIVO_EVIDENCIA.is_file():
        pytest.fail(
            f"No existe la evidencia broker en '{RUTA_RELATIVA_EVIDENCIA}'. "
            f"{INSTRUCCIONES_GATE}"
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
        f"La evidencia '{RUTA_RELATIVA_EVIDENCIA}' no tiene la forma esperada "
        f"(dict con 'sondas')."
    )
    return evidencia


def TestEvidenciaDelGateBrokerDisponible():
    """La evidencia existe, es del spike broker y está ligada a un usuario OBO."""
    evidencia = _CargarEvidencia()

    assert evidencia.get("spike") == IDENTIFICADOR_SPIKE_ESPERADO, (
        f"La evidencia no fue generada por el spike "
        f"'{IDENTIFICADOR_SPIKE_ESPERADO}' (valor: {evidencia.get('spike')!r})."
    )
    assert evidencia.get("usuario"), (
        "La evidencia no reporta usuario OBO: la resolución de privilegios no "
        "se evaluó con una identidad de usuario real (spec app-broker-grants)."
    )


def _VerificarConjuntoGate(evidencia, conjunto, nombre_conjunto):
    """Verifica que todas las sondas de un conjunto satisfacen el gate."""
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


def TestGateBrokerConjuntoMinimoVerificado():
    """GO/NO-GO mínimo: núcleo broker viable en andresFree."""
    evidencia = _CargarEvidencia()

    problemas = _VerificarConjuntoGate(
        evidencia, CONJUNTO_MINIMO_GATE, "mínimo"
    )
    assert not problemas, (
        "GATE BROKER MÍNIMO NO-GO: el núcleo (SCIM con SP, ACL de warehouse y "
        "tokens con SP, y resolución de privilegios del llamante) no está "
        "verificado en andresFree:\n- " + "\n- ".join(problemas)
    )


def TestGateBrokerConjuntoCompletoVerificado():
    """GO/NO-GO completo: superficies de cómputo clásico con el SP."""
    evidencia = _CargarEvidencia()

    problemas = _VerificarConjuntoGate(
        evidencia, CONJUNTO_COMPLETO_GATE, "completo"
    )
    assert not problemas, (
        "GATE BROKER COMPLETO NO-GO: los clusters clásicos no están "
        "verificados con el SP (elevar la limitación al humano):\n- "
        + "\n- ".join(problemas)
    )
