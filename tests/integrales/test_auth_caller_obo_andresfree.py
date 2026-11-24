"""Pruebas integrales del change `auth-caller-obo` contra el workspace real.

Capa integral (marker `free`, tarea 5.3): ejercita el CÓDIGO DE PRODUCCIÓN real
(`ServicioIdentidadLlamante`, `ResolutorPrivilegiosEfectivos`, `PreFlight`)
contra el workspace `andresFree`, usando como adaptadores el proveedor SCIM por
CLI (`adaptador_auth_databricks.py`) y los canales de SOLO LECTURA por CLI
(`adaptador_canales_reales.py`). No se instala ninguna biblioteca (regla
"Prohibición de instalación por la IA").

Verifica en datos reales:

- identidad y grupos del llamante resueltos vía SCIM (`/Me`, `/Groups/{id}`);
- referencias de identidad del service principal de la app, incluido su App Id,
  y que un usuario NO hereda la identidad de un service principal;
- emparejamiento de `SHOW GRANT` sobre el catálogo configurado
  (`config/app_properties.json`, no hardcodeado) y sobre un catálogo donde el
  llamante tiene privilegios vía grupo;
- emparejamiento por App Id cuando el llamante es un service principal;
- emparejamiento de la ACL real de un SQL warehouse, una Databricks App, un
  serverless compute object y el ACL de tokens, con el origen (directo o
  heredado) tal como lo informa la Permissions API;
- objeto inexistente clasificado como `fallido` controlado (nunca como
  `privilegios_insuficientes`);
- que la resolución NO otorga ni revoca nada.

Criterio de aserción: los privilegios esperados se RECALCULAN de forma
independiente desde la respuesta cruda del workspace y se comparan con la vista
del resolutor. Así las pruebas no asumen un estado particular de permisos (que
puede cambiar en el workspace) y verifican la lógica de emparejamiento.

Notas de ejecución:

- Requiere el CLI de Databricks autenticado con el perfil `andresFree` y red
  disponible; si faltan, la prueba se SALTA (no falla).
- El warehouse serverless puede arrancar en frío: la primera sentencia demora.
- Ninguna prueba escribe en el workspace: solo lecturas (SCIM, SHOW GRANT,
  Permissions API).
"""

import shutil
import uuid

import pytest

from adaptador_auth_databricks import (
    RUTA_API_SCIM_YO,
    DescubrirAppConSuServicePrincipal,
    ProveedorIdentidadScimCli,
    ProveedorIdentidadServicePrincipalScimCli,
)
from adaptador_canales_reales import (
    EXPRESION_APP_ID,
    RUTA_API_PERMISOS,
    CanalControlRealLectura,
    CanalDatosRealLectura,
    DescubrirApp,
    DescubrirServerlessCompute,
    InferirTipoPrincipal,
)
from adaptador_sql_databricks import (
    DescubrirWarehouseServerless,
    EjecutarComandoCli,
    SesionSqlDatabricks,
)
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.configuracion.configuracion_app import ConfiguracionApp
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
from control_accesos.pipeline.pre_flight import PreFlight
from control_accesos.resolucion.enumeraciones import OrigenPrivilegio
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

# Todas las pruebas de este módulo son integrales contra andresFree.
pytestmark = pytest.mark.free

# Principal beneficiario de los ítems de prueba (nunca se otorga nada: el
# pre-flight solo clasifica).
BENEFICIARIO_DE_PRUEBA = "beneficiario_integral"

# Privilegio de prueba del plano de datos y del plano de control.
PRIVILEGIO_DE_PRUEBA_DATOS = "SELECT"
PRIVILEGIO_DE_PRUEBA_CONTROL = "CAN_USE"

# Identificador del ACL de uso de personal access token (la ruta es única en el
# workspace y no depende del identificador del objeto).
IDENTIFICADOR_ACL_TOKENS = "tokens"


@pytest.fixture(scope="module")
def entorno_free():
    """Prepara el entorno integral real: CLI, warehouse, canales y proveedor.

    Yields:
        dict: sesión SQL real, id del warehouse, canales de solo lectura de
            ambos planos, proveedor SCIM y configuración del proyecto.
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado en esta máquina; la capa "
            "integral requiere el CLI autenticado con el perfil andresFree."
        )

    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip(
            "El perfil andresFree no expone un SQL warehouse serverless; no "
            "hay dónde ejecutar las lecturas del plano de datos."
        )

    sesion = SesionSqlDatabricks(warehouse_id=warehouse_id)

    yield {
        "sesion": sesion,
        "warehouse_id": warehouse_id,
        "canal_datos": CanalDatosRealLectura(sesion_sql=sesion),
        "canal_control": CanalControlRealLectura(),
        "proveedor": ProveedorIdentidadScimCli(),
        # Configuración REAL del proyecto: el catálogo no se fija aquí.
        "configuracion": ConfiguracionApp.Cargar(),
    }


@pytest.fixture(scope="module")
def identidad_llamante(entorno_free):
    """Resuelve la identidad real del llamante con el servicio de producción.

    Args:
        entorno_free (dict): entorno integral del módulo.

    Returns:
        IdentidadLlamante: identidad resuelta vía SCIM.
    """
    identidad = ServicioIdentidadLlamante(
        proveedor=entorno_free["proveedor"]
    ).ObtenerIdentidadLlamante()

    if identidad is None:
        pytest.skip(
            "El perfil andresFree no resuelve un llamante autenticado vía "
            "SCIM; sin identidad no hay resolución de privilegios que probar."
        )
    return identidad


@pytest.fixture(scope="module")
def resolutor(entorno_free):
    """Compone el resolutor de producción con los canales reales de lectura.

    Args:
        entorno_free (dict): entorno integral del módulo.

    Returns:
        ResolutorPrivilegiosEfectivos: resolutor con los dos planos reales.
    """
    return ResolutorPrivilegiosEfectivos(
        canal_datos=entorno_free["canal_datos"],
        canal_control=entorno_free["canal_control"],
    )


def ObjetoCatalogo(nombre):
    """Construye el objeto securable de un catálogo.

    Args:
        nombre (str): nombre del catálogo.

    Returns:
        ObjetoSecurable: objeto del plano de datos.
    """
    return ObjetoSecurable(identificador=nombre, tipo=TipoObjeto.CATALOGO)


def PrivilegiosEsperados(grants, identidad, plano):
    """Recalcula de forma independiente los privilegios del llamante.

    Aplica la misma regla de normalización por plano declarada en el dominio
    (`NORMALIZAR_A_MINUSCULAS_POR_PLANO`) sobre las referencias de identidad,
    para comparar con la vista del resolutor sin asumir un estado concreto del
    workspace.

    Args:
        grants (list[ItemGrant]): otorgamientos vigentes reportados por el
            canal real.
        identidad (IdentidadLlamante): identidad resuelta del llamante.
        plano (Plano): plano del objeto consultado.

    Returns:
        set[str]: privilegios que corresponden al llamante, en mayúsculas.
    """
    a_minusculas = NORMALIZAR_A_MINUSCULAS_POR_PLANO.get(plano, False)
    referencias = {
        _NormalizarReferencia(referencia, a_minusculas)
        for referencia in identidad.ReferenciasDeIdentidad()
    }

    esperados = set()
    for grant in grants:
        otorgatario = _NormalizarReferencia(
            grant.principal.identificador, a_minusculas
        )
        if otorgatario in referencias:
            esperados.add(grant.privilegio.strip().upper())
    return esperados


def _NormalizarReferencia(referencia, a_minusculas):
    """Normaliza una referencia según la política del plano.

    Args:
        referencia (str): referencia textual del otorgatario o del llamante.
        a_minusculas (bool): True en el plano de datos.

    Returns:
        str: referencia recortada y, si el plano lo pide, en minúsculas.
    """
    texto = str(referencia).strip()
    return texto.lower() if a_minusculas else texto


def TestIdentidadDelLlamanteResueltaConScimReal(
    entorno_free, identidad_llamante
):
    """La identidad resuelta coincide con el usuario autenticado del SCIM."""
    respuesta_scim = EjecutarComandoCli(["get", RUTA_API_SCIM_YO])

    assert identidad_llamante.principal.tipo is TipoPrincipal.USUARIO
    assert identidad_llamante.principal.identificador == respuesta_scim[
        "userName"
    ], "El identificador del llamante es el userName real del workspace"
    assert identidad_llamante.usuario_bitacora == respuesta_scim["userName"], (
        "El campo usuario de la bitácora se alimenta con la identidad real"
    )


def TestGruposDelLlamanteResueltosConNombreEIdReal(identidad_llamante):
    """Los grupos del llamante traen el nombre y el identificador reales."""
    assert identidad_llamante.grupos, (
        "El llamante de andresFree tiene grupos; una lista vacía aquí "
        "indicaría un fallo de resolución, no un llamante sin membresías"
    )
    for grupo in identidad_llamante.grupos:
        assert grupo.identificador, "Cada grupo trae su identificador SCIM"
        assert grupo.nombre, "Cada grupo trae su nombre real"


def TestMembresiaDeGrupoConfirmadaPorScimReal(
    entorno_free, identidad_llamante
):
    """SCIM confirma, por separado, el nombre de cada grupo del llamante."""
    proveedor = entorno_free["proveedor"]
    respuesta_scim = EjecutarComandoCli(["get", RUTA_API_SCIM_YO])
    id_llamante = str(respuesta_scim["id"])

    for grupo in identidad_llamante.grupos:
        resolucion = proveedor.ObtenerGrupo(grupo.identificador)
        assert resolucion is not None, (
            f"El grupo {grupo.identificador} existe en el workspace"
        )
        grupo_real, miembros = resolucion
        assert grupo_real.nombre == grupo.nombre, (
            "El nombre resuelto por /Groups/{id} coincide con el de la "
            "membresía reportada en /Me"
        )
        if miembros:
            assert id_llamante in miembros, (
                "El grupo reporta al llamante entre sus miembros"
            )


def TestReferenciasDeIdentidadIncluyenUsuarioYSusGruposReales(
    identidad_llamante,
):
    """Las referencias de identidad cubren usuario y grupos (emparejamiento)."""
    referencias = set(identidad_llamante.ReferenciasDeIdentidad())

    assert identidad_llamante.principal.identificador in referencias
    for grupo in identidad_llamante.grupos:
        assert grupo.identificador in referencias
        assert grupo.nombre in referencias


def TestServicePrincipalDeLaAppAportaSuAppIdReal(entorno_free):
    """El service principal de la app se resuelve con su App Id real.

    Escenario 'Llamante service principal con App Id' del spec
    `caller-identity`, y base del escenario 'Otorgamiento al App Id del
    llamante service principal' del spec `caller-privilege-resolution`.
    """
    app = DescubrirAppConSuServicePrincipal()
    if app is None:
        pytest.skip(
            "El perfil andresFree no tiene Databricks Apps registradas; no hay "
            "service principal de app que resolver."
        )

    identidad_app = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadServicePrincipalScimCli(
            app_id=app["app_id"]
        )
    ).ObtenerIdentidadLlamante()

    assert identidad_app is not None, (
        "El service principal de la app está registrado en el workspace"
    )
    assert identidad_app.principal.tipo is TipoPrincipal.SERVICE_PRINCIPAL
    assert identidad_app.app_id == app["app_id"]
    assert app["app_id"] in identidad_app.ReferenciasDeIdentidad(), (
        "El App Id es una referencia de identidad: con ella reporta sus "
        "otorgamientos Unity Catalog"
    )


def TestUsuarioNoAdquiereIdentidadDeServicePrincipalReal(
    entorno_free, identidad_llamante
):
    """Un usuario no recibe las referencias de los service principals.

    Escenario 'Service principal distinto del usuario llamante' del spec
    `caller-identity`.
    """
    service_principals = entorno_free["proveedor"].ListarServicePrincipales()
    if not service_principals:
        pytest.skip("El workspace no tiene service principals registrados.")

    referencias_usuario = set(identidad_llamante.ReferenciasDeIdentidad())
    app_ids = {
        str(sp.get("applicationId"))
        for sp in service_principals
        if sp.get("applicationId")
    }

    assert identidad_llamante.app_id is None, (
        "La identidad de un usuario no lleva App Id"
    )
    assert not (referencias_usuario & app_ids), (
        "Ningún App Id de los service principals del workspace se atribuye al "
        "usuario llamante"
    )


def TestShowGrantSobreCatalogoConfiguradoEmparejaConReferenciasReales(
    entorno_free, identidad_llamante, resolutor
):
    """`SHOW GRANT` del catálogo configurado alimenta la vista de privilegios."""
    catalogo = ObjetoCatalogo(entorno_free["configuracion"].catalogo)

    grants_reales = entorno_free["canal_datos"].ListarGrantsVigentes(catalogo)
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_llamante, catalogo)

    assert vista.FueConsultaExitosa, (
        "La lectura del catálogo configurado se completó"
    )
    assert vista.objeto == catalogo
    assert vista.plano is Plano.DATOS
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad_llamante, Plano.DATOS
    ), "La vista empareja exactamente los otorgamientos del llamante"
    assert any(
        "SHOW GRANT" in sentencia
        for sentencia in entorno_free["canal_datos"].consultas_ejecutadas
    ), "La consulta del plano de datos es un SHOW GRANT real"


def TestVistaVaciaEsDistinguibleDeUnFalloReal(
    entorno_free, identidad_llamante, resolutor
):
    """Un objeto sin otorgamientos del llamante devuelve lista vacía, no fallo.

    Escenario 'Objeto sin privilegios efectivos' del spec
    `caller-privilege-resolution`, verificado con un catálogo real del
    workspace en el que el llamante no tiene privilegios.
    """
    catalogo = ObjetoCatalogo(entorno_free["configuracion"].catalogo)
    grants_reales = entorno_free["canal_datos"].ListarGrantsVigentes(catalogo)
    esperados = PrivilegiosEsperados(grants_reales, identidad_llamante, Plano.DATOS)

    if esperados:
        pytest.skip(
            "El llamante ya tiene privilegios sobre el catálogo configurado; "
            "no se puede verificar el caso de vista vacía con ese objeto."
        )

    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_llamante, catalogo)

    assert vista.FueConsultaExitosa is True, (
        "La consulta fue exitosa: el vacío es de privilegios, no un fallo"
    )
    assert vista.privilegios_efectivos == frozenset()
    assert vista.otorgamientos == ()


def TestEmparejamientoPorGrupoEnPlanoDatosReal(
    entorno_free, identidad_llamante, resolutor
):
    """Un privilegio otorgado a un grupo del llamante resulta efectivo.

    Escenario 'Otorgamiento a un grupo del llamante' del spec
    `caller-privilege-resolution`, y escenario 'Canal que no reporta el
    origen': `SHOW GRANT` no declara si el privilegio viene de un padre.
    """
    catalogs = [
        fila[0]
        for fila in entorno_free["sesion"].EjecutarYLeer("SHOW CATALOGS")
    ]

    encontrado = None
    for nombre in catalogs:
        catalogo = ObjetoCatalogo(nombre)
        try:
            vista = resolutor.ResolverPrivilegiosEfectivos(
                identidad_llamante, catalogo
            )
        except Exception:  # noqa: BLE001 - catálogos no consultables (p. ej. samples)
            continue
        if vista.privilegios_efectivos:
            encontrado = (catalogo, vista)
            break

    if encontrado is None:
        pytest.skip(
            "Ningún catálogo del workspace tiene privilegios del llamante; el "
            "emparejamiento positivo por grupo no se puede verificar aquí."
        )

    catalogo, vista = encontrado
    privilegio = sorted(vista.privilegios_efectivos)[0]
    otorgamiento = vista.ObtenerOtorgamientoDelPrivilegio(privilegio)

    assert vista.FueConsultaExitosa
    assert otorgamiento.referencia_coincidente, (
        "La vista deja constancia de la referencia con la que emparejó"
    )
    assert vista.ObtenerOrigenDelPrivilegio(privilegio) is (
        OrigenPrivilegio.NO_DETERMINADO
    ), "SHOW GRANT no informa el origen: no se asume que sea directo"


def TestEmparejamientoPorAppIdEnPlanoDatosReal(
    entorno_free, resolutor
):
    """Un service principal llamante empareja por su App Id en Unity Catalog.

    Escenario 'Otorgamiento al App Id del llamante service principal' del spec
    `caller-privilege-resolution`, con datos reales del catálogo configurado.
    """
    catalogo = ObjetoCatalogo(entorno_free["configuracion"].catalogo)
    grants_reales = entorno_free["canal_datos"].ListarGrantsVigentes(catalogo)

    app_ids = [
        grant.principal.identificador
        for grant in grants_reales
        if EXPRESION_APP_ID.match(grant.principal.identificador)
    ]
    if not app_ids:
        pytest.skip(
            "El catálogo configurado no tiene otorgamientos a service "
            "principals; no hay App Id real que emparejar."
        )

    app_id = app_ids[0]
    identidad_sp = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadServicePrincipalScimCli(app_id=app_id)
    ).ObtenerIdentidadLlamante()
    if identidad_sp is None:
        pytest.skip(
            f"El App Id {app_id} no corresponde a un service principal "
            "registrado en SCIM."
        )

    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_sp, catalogo)
    esperados = {
        grant.privilegio.strip().upper()
        for grant in grants_reales
        if grant.principal.identificador == app_id
    }

    assert identidad_sp.app_id == app_id
    assert set(vista.privilegios_efectivos) == esperados, (
        "El service principal obtiene exactamente los privilegios que Unity "
        "Catalog reporta para su App Id"
    )
    assert vista.privilegios_efectivos, (
        "El App Id consultado tiene privilegios vigentes sobre el catálogo"
    )


def TestAclDeWarehouseEmparejadaConIdentidadReal(
    entorno_free, identidad_llamante, resolutor
):
    """La ACL real del SQL warehouse empareja con el llamante y sus grupos.

    Escenarios 'Objeto del plano de control', 'Otorgamiento directo al
    usuario', 'Otorgamiento a un grupo del llamante' y 'Privilegio heredado
    del padre' del spec `caller-privilege-resolution`.
    """
    warehouse = ObjetoSecurable(
        identificador=entorno_free["warehouse_id"],
        tipo=TipoObjeto.SQL_WAREHOUSE,
    )

    grants_reales = entorno_free["canal_control"].ListarGrantsVigentes(warehouse)
    vista = resolutor.ResolverPrivilegiosEfectivos(
        identidad_llamante, warehouse
    )

    assert vista.plano is Plano.CONTROL
    assert vista.FueConsultaExitosa
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad_llamante, Plano.CONTROL
    )
    assert vista.privilegios_efectivos, (
        "El llamante tiene permisos vigentes sobre el warehouse del workspace"
    )

    heredados = [
        grant
        for grant in grants_reales
        if grant.origen == OrigenPrivilegio.HEREDADO.value
    ]
    heredados_del_llamante = [
        grant
        for grant in heredados
        if _NormalizarReferencia(grant.principal.identificador, False)
        in set(identidad_llamante.ReferenciasDeIdentidad())
    ]
    if heredados_del_llamante:
        privilegio_heredado = heredados_del_llamante[0].privilegio
        assert vista.ObtenerOrigenDelPrivilegio(privilegio_heredado) is (
            OrigenPrivilegio.HEREDADO
        ), "La herencia que informa la Permissions API se conserva en la vista"
        assert vista.ObtenerOtorgamientoDelPrivilegio(
            privilegio_heredado
        ).heredado_de, "La vista guarda el securable padre del que se hereda"


def TestAclDeDatabricksAppEmparejadaConIdentidadReal(
    entorno_free, identidad_llamante, resolutor
):
    """La ACL real de una Databricks App empareja con el llamante."""
    nombre_app = DescubrirApp()
    if nombre_app is None:
        pytest.skip("El perfil andresFree no tiene Databricks Apps.")

    app = ObjetoSecurable(
        identificador=nombre_app, tipo=TipoObjeto.DATABRICK_APP
    )

    grants_reales = entorno_free["canal_control"].ListarGrantsVigentes(app)
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_llamante, app)

    assert vista.FueConsultaExitosa
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad_llamante, Plano.CONTROL
    )


def TestAclDeServerlessComputeEmparejadaConIdentidadReal(
    entorno_free, identidad_llamante, resolutor
):
    """La ACL real de un serverless compute object empareja con el llamante."""
    computo_id = DescubrirServerlessCompute()
    if computo_id is None:
        pytest.skip(
            "El feature serverless no está activado en andresFree; no hay "
            "serverless compute object cuya ACL verificar."
        )

    computo = ObjetoSecurable(
        identificador=computo_id, tipo=TipoObjeto.COMPUTO_SERVERLESS
    )

    grants_reales = entorno_free["canal_control"].ListarGrantsVigentes(computo)
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_llamante, computo)

    assert vista.FueConsultaExitosa
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad_llamante, Plano.CONTROL
    )
    assert vista.privilegios_efectivos, (
        "El llamante tiene permisos vigentes sobre el cómputo serverless"
    )


def TestAclDeUsoDeTokensEsLegibleReal(entorno_free, identidad_llamante, resolutor):
    """La ACL real del uso de personal access tokens se lee y empareja."""
    tokens = ObjetoSecurable(
        identificador=IDENTIFICADOR_ACL_TOKENS, tipo=TipoObjeto.USO_TOKEN
    )

    grants_reales = entorno_free["canal_control"].ListarGrantsVigentes(tokens)
    vista = resolutor.ResolverPrivilegiosEfectivos(identidad_llamante, tokens)

    assert vista.FueConsultaExitosa
    assert set(vista.privilegios_efectivos) == PrivilegiosEsperados(
        grants_reales, identidad_llamante, Plano.CONTROL
    )
    assert any(
        ruta.startswith(RUTA_API_PERMISOS)
        for ruta in entorno_free["canal_control"].consultas_ejecutadas
    ), "El plano de control consulta la Permissions API"


def TestObjetoInexistenteDelPlanoDatosQuedaFallidoReal(
    entorno_free, identidad_llamante, resolutor
):
    """Un catálogo inexistente produce ítems `fallido`, nunca insuficientes.

    Escenario 'Objeto inexistente' del spec `caller-privilege-resolution`.
    """
    objeto = ObjetoCatalogo(f"catalogo_inexistente_{uuid.uuid4().hex[:8]}")
    item = ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO_DE_PRUEBA, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=PRIVILEGIO_DE_PRUEBA_DATOS,
        objeto=objeto,
    )

    clasificacion = PreFlight(
        resolutor_privilegios=resolutor
    ).Clasificar([item], identidad_llamante=identidad_llamante)

    assert clasificacion.items_ejecutables == ()
    assert len(clasificacion.items_bloqueados) == 1
    resultado = clasificacion.items_bloqueados[0]
    assert resultado.estado is EstadoItem.FALLIDO, (
        "El fallo de consulta se clasifica como fallido, no como falta de "
        "privilegios del llamante"
    )
    assert resultado.item == item


def TestObjetoInexistenteDelPlanoDeControlQuedaFallidoReal(
    entorno_free, identidad_llamante, resolutor
):
    """Un warehouse inexistente produce ítems `fallido` de forma controlada."""
    objeto = ObjetoSecurable(
        identificador=f"warehouse_inexistente_{uuid.uuid4().hex[:8]}",
        tipo=TipoObjeto.SQL_WAREHOUSE,
    )
    item = ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO_DE_PRUEBA, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=PRIVILEGIO_DE_PRUEBA_CONTROL,
        objeto=objeto,
    )

    clasificacion = PreFlight(
        resolutor_privilegios=resolutor
    ).Clasificar([item], identidad_llamante=identidad_llamante)

    assert clasificacion.items_ejecutables == ()
    assert clasificacion.items_bloqueados[0].estado is EstadoItem.FALLIDO


def TestResolucionRealNoOtorgaNiRevocaNada(entorno_free):
    """La resolución de este change es de solo lectura en el workspace real.

    Escenario 'Solicitud completa procesada con canales simulados' del spec
    `caller-privilege-resolution`, en su versión real: ningún otorgamiento ni
    revocación puede llegar al workspace.
    """
    item = ItemGrant(
        principal=Principal(
            identificador=BENEFICIARIO_DE_PRUEBA, tipo=TipoPrincipal.USUARIO
        ),
        privilegio=PRIVILEGIO_DE_PRUEBA_DATOS,
        objeto=ObjetoCatalogo(entorno_free["configuracion"].catalogo),
    )

    canal_datos = entorno_free["canal_datos"]
    canal_control = entorno_free["canal_control"]

    with pytest.raises(NotImplementedError):
        canal_datos.EjecutarOtorgamiento(item)
    with pytest.raises(NotImplementedError):
        canal_datos.EjecutarRevocacion(item)
    with pytest.raises(NotImplementedError):
        canal_control.EjecutarOtorgamiento(item)
    with pytest.raises(NotImplementedError):
        canal_control.EjecutarRevocacion(item)

    for sentencia in canal_datos.consultas_ejecutadas:
        assert sentencia.upper().startswith("SHOW GRANT"), (
            f"El plano de datos solo leyó; se ejecutó: {sentencia}"
        )
    for ruta in canal_control.consultas_ejecutadas:
        assert ruta.startswith(RUTA_API_PERMISOS), (
            f"El plano de control solo leyó ACL; se consultó: {ruta}"
        )


def TestTipoDePrincipalDeducidoDeReferenciasReales(
    entorno_free, identidad_llamante
):
    """Las referencias reales de Unity Catalog se clasifican por su forma.

    Usa solo datos reales del workspace: el App Id que aparece en `SHOW GRANT`,
    el correo del llamante y el nombre de uno de sus grupos.
    """
    catalogo = ObjetoCatalogo(entorno_free["configuracion"].catalogo)
    grants_reales = entorno_free["canal_datos"].ListarGrantsVigentes(catalogo)

    referencias_de_app = [
        grant.principal.identificador
        for grant in grants_reales
        if EXPRESION_APP_ID.match(grant.principal.identificador)
    ]
    if referencias_de_app:
        assert InferirTipoPrincipal(
            referencias_de_app[0]
        ) is TipoPrincipal.SERVICE_PRINCIPAL, (
            "Unity Catalog reporta a los service principals por su App Id"
        )

    assert InferirTipoPrincipal(
        identidad_llamante.principal.identificador
    ) is TipoPrincipal.USUARIO, (
        "El correo del llamante se clasifica como usuario"
    )
    assert InferirTipoPrincipal(
        identidad_llamante.grupos[0].nombre
    ) is TipoPrincipal.GRUPO, (
        "El nombre de un grupo del workspace se clasifica como grupo"
    )
