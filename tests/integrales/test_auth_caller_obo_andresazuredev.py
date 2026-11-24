"""Pruebas integrales que requieren `andresAzureDev` (Databricks Enterprise).

Capa integral con marker `azure_approval` (tarea 5.4 del change
`auth-caller-obo`, decisión F del humano): cubren lo que es **imposible de
verificar en `andresFree`** porque Free Edition no tiene cómputo clásico
(`/api/2.0/clusters/list` devuelve vacío). Son las dos únicas pruebas de este
change que tocan el workspace de Azure:

1. resolución de privilegios efectivos del llamante sobre un **cluster
   clásico** (Permissions API, `permissions/clusters/<id>`);
2. **split de pre-flight** con un ítem sobre ese cluster clásico: el ítem con
   privilegio efectivo queda ejecutable y el ítem sin privilegio efectivo queda
   bloqueado con su mensaje estructurado.

**Estas pruebas se omiten en la corrida por defecto**
(`python -m pytest -m "not azure_approval"`) y solo se ejecutan con
autorización expresa del humano
(`python -m pytest tests/integrales -m azure_approval -q`).

Son de SOLO LECTURA: usan los mismos adaptadores que la capa `free`
(`adaptador_auth_databricks.py` y `adaptador_canales_reales.py`), cuyos
`Otorgar`/`Revocar` lanzan `NotImplementedError`. Nada se escribe en el
workspace de Azure.

Las expectativas no asumen un estado concreto de permisos: se derivan de lo que
el propio workspace reporta en el momento de la corrida (qué privilegios
efectivos tiene el llamante sobre el cluster descubierto), de modo que la
prueba verifica la coherencia entre resolución y split, no una foto fija de los
permisos del workspace.
"""

import shutil

import pytest

from adaptador_auth_databricks import ProveedorIdentidadScimCli
from adaptador_canales_reales import (
    CanalControlRealLectura,
    DescubrirCluster,
)
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.simulados.canales_simulados import (
    CanalDatosSimulado,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    NORMALIZAR_A_MINUSCULAS_POR_PLANO,
    ItemGrant,
    ObjetoSecurable,
    Principal,
)
from control_accesos.matriz.consultora import ConsultoraMatrizPrivilegios
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.resolucion.modelos import (
    PRIVILEGIO_AUTORIZADOR_POR_PLANO,
    MensajePrivilegiosInsuficientes,
)
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Todas las pruebas de este módulo requieren el workspace de Azure y, por lo
# tanto, la autorización expresa del humano (decisión F).
pytestmark = pytest.mark.azure_approval

# Perfil CLI del workspace Enterprise (README D5: solo con aprobación).
PERFIL_CLI_AZURE = "andresAzureDev"

# Principal beneficiario de los ítems de prueba (nunca se otorga nada).
BENEFICIARIO_DE_PRUEBA = "beneficiario_integral_azure"


@pytest.fixture(scope="module")
def entorno_azure():
    """Prepara el entorno integral de Azure: perfil, identidad y canal.

    Yields:
        dict: identidad del llamante en el workspace de Azure, canal de solo
            lectura del plano de control, resolutor y objeto del cluster
            clásico descubierto.
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado en esta máquina; la capa "
            "integral requiere el CLI autenticado."
        )

    cluster_id = DescubrirCluster(perfil=PERFIL_CLI_AZURE)
    if cluster_id is None:
        pytest.skip(
            f"El perfil {PERFIL_CLI_AZURE} no expone clusters clásicos; sin "
            "cómputo clásico no hay nada que verificar fuera de andresFree."
        )

    proveedor = ProveedorIdentidadScimCli(perfil=PERFIL_CLI_AZURE)
    identidad = ServicioIdentidadLlamante(
        proveedor=proveedor
    ).ObtenerIdentidadLlamante()
    if identidad is None:
        pytest.skip(
            f"El perfil {PERFIL_CLI_AZURE} no resuelve un llamante "
            "autenticado vía SCIM."
        )

    canal_control = CanalControlRealLectura(perfil=PERFIL_CLI_AZURE)
    # Estas pruebas solo consultan objetos del plano de control, pero el
    # `EnrutadorCanales` de producción valida los dos planos al construirse:
    # se aporta el canal simulado del plano de datos para satisfacerlo. Nunca
    # llega a consultarse (los objetos de prueba son clusters clásicos), y así
    # no se abre una sesión SQL innecesaria contra el workspace de Azure.
    canal_datos = CanalDatosSimulado()
    cluster = ObjetoSecurable(
        identificador=cluster_id, tipo=TipoObjeto.COMPUTO_CLASICO
    )

    yield {
        "identidad": identidad,
        "canal_control": canal_control,
        "resolutor": ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        ),
        "cluster": cluster,
    }


def PrivilegiosEsperados(grants, identidad):
    """Recalcula de forma independiente los privilegios del llamante.

    Args:
        grants (list[ItemGrant]): permisos vigentes reportados por la
            Permissions API del workspace de Azure.
        identidad (IdentidadLlamante): identidad resuelta del llamante.

    Returns:
        set[str]: privilegios que corresponden al llamante, en mayúsculas.
    """
    a_minusculas = NORMALIZAR_A_MINUSCULAS_POR_PLANO.get(Plano.CONTROL, False)
    referencias = {
        (
            str(referencia).strip().lower()
            if a_minusculas
            else str(referencia).strip()
        )
        for referencia in identidad.ReferenciasDeIdentidad()
    }

    esperados = set()
    for grant in grants:
        otorgatario = str(grant.principal.identificador).strip()
        if (otorgatario.lower() if a_minusculas else otorgatario) in referencias:
            esperados.add(grant.privilegio.strip().upper())
    return esperados


def CrearItem(privilegio, objeto):
    """Construye un ítem de solicitud de prueba.

    Args:
        privilegio (str): privilegio a otorgar.
        objeto (ObjetoSecurable): objeto objetivo del ítem.

    Returns:
        ItemGrant: ítem listo para clasificar.
    """
    return ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO_DE_PRUEBA, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=privilegio,
        objeto=objeto,
    )


def TestResolucionDePrivilegiosSobreComputoClasicoReal(entorno_azure):
    """El resolutor empareja la ACL real de un cluster clásico.

    Imposible en `andresFree`: Free Edition no tiene cómputo clásico.
    """
    identidad = entorno_azure["identidad"]
    canal_control = entorno_azure["canal_control"]
    resolutor = entorno_azure["resolutor"]
    cluster = entorno_azure["cluster"]

    grants_reales = canal_control.ListarGrantsVigentes(cluster)
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad, cluster)

    assert vista.plano is Plano.CONTROL
    assert vista.objeto == cluster
    assert vista.FueConsultaExitosa, (
        "La ACL del cluster clásico se leyó sin denegaciones"
    )
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad
    ), "La vista empareja exactamente los permisos del llamante y sus grupos"
    assert vista.privilegios_efectivos, (
        "El llamante de Azure tiene permisos vigentes sobre el cluster "
        "descubierto (al menos los heredados de su rol de administrador)"
    )


def TestSplitPreFlightConItemsSobreClusterClasicoReal(entorno_azure):
    """El split clasifica ítems de un cluster clásico según la resolución real.

    Un ítem cuyo privilegio es efectivo para el llamante queda ejecutable; uno
    cuyo privilegio válido en la matriz NO es efectivo queda bloqueado con
    estado `privilegios_insuficientes` y su mensaje estructurado. Ninguno de
    los dos llega a ejecutarse: este change es de solo lectura.
    """
    identidad = entorno_azure["identidad"]
    resolutor = entorno_azure["resolutor"]
    cluster = entorno_azure["cluster"]

    vista = resolutor.ResolverPrivilegiosEfectivos(identidad, cluster)
    privilegios_validos = ConsultoraMatrizPrivilegios().ObtenerPrivilegios(
        TipoObjeto.COMPUTO_CLASICO
    )
    sin_privilegio = sorted(
        privilegio
        for privilegio in privilegios_validos
        if not vista.TieneElPrivilegio(privilegio)
    )
    if not sin_privilegio:
        pytest.skip(
            "El llamante tiene todos los privilegios válidos del cómputo "
            "clásico sobre el cluster; no hay caso bloqueado que verificar."
        )

    item_ejecutable = None
    if vista.privilegios_efectivos:
        privilegio_efectivo = sorted(
            privilegio
            for privilegio in vista.privilegios_efectivos
            if privilegio in privilegios_validos
        )[0]
        item_ejecutable = CrearItem(privilegio_efectivo, cluster)

    item_bloqueado = CrearItem(sin_privilegio[0], cluster)
    items = [
        item
        for item in (item_ejecutable, item_bloqueado)
        if item is not None
    ]

    clasificacion = PreFlight(
        resolutor_privilegios=resolutor
    ).Clasificar(items, identidad_llamante=identidad)

    # El ítem sin privilegio efectivo queda bloqueado, con su mensaje.
    bloqueados = {
        resultado.item: resultado
        for resultado in clasificacion.items_bloqueados
    }
    assert item_bloqueado in bloqueados
    assert bloqueados[item_bloqueado].estado is (
        EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )

    mensaje = clasificacion.mensaje_de_bloqueo(item_bloqueado)
    assert isinstance(mensaje, MensajePrivilegiosInsuficientes)
    assert mensaje.objeto == cluster
    assert mensaje.plano is Plano.CONTROL
    assert mensaje.privilegio_requerido == sin_privilegio[0]
    assert mensaje.privilegio_faltante == (
        PRIVILEGIO_AUTORIZADOR_POR_PLANO[Plano.CONTROL]
    )

    # El ítem con privilegio efectivo continúa hacia la ejecución.
    if item_ejecutable is not None:
        assert item_ejecutable in clasificacion.items_ejecutables

    # Solo lectura: el canal de Azure no puede otorgar ni revocar nada.
    with pytest.raises(NotImplementedError):
        entorno_azure["canal_control"].EjecutarOtorgamiento(item_bloqueado)
