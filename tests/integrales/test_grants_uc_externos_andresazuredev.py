"""Pruebas integrales de grants sobre external locations contra `andresAzureDev`.

Change C6 (`grants-uc-externos`), capa integral con marker `azure_approval`
(tarea 5.3, **pre-aprobada por el humano** en design D6): la fixture de external
location requiere el storage credential y la cuenta de almacenamiento del
workspace de Azure Databricks, que `andresFree` no tiene. Ejercita el código de
producción real (`CanalSqlDatos`, `PipelineGrants`,
`ResolutorPrivilegiosEfectivos`) sobre external locations creadas por la propia
corrida en el contenedor de pruebas `test`, inyectando la sesión SQL del
transporte por CLI ya instalado. No se instala ninguna biblioteca nueva (regla
"Prohibición de instalación por la IA").

**Estas pruebas se omiten en la corrida por defecto**
(`python -m pytest -m "not azure_approval"`) y solo se ejecutan con la
autorización expresa del humano
(`python -m pytest tests/integrales -m azure_approval -q`).

Verifica en el workspace real:

- otorgamiento 1 a 1 (`READ FILES`), verificación con `SHOW GRANT` y revocación
  sobre la external location creada, con la palabra clave de dos tokens
  `EXTERNAL LOCATION` en la instrucción real;
- ítem clasificado `fallido` ante external location inexistente y ante principal
  inexistente, dejando constancia del código real que reporta el workspace para
  contrastar el patrón declarativo `EXTERNAL_LOCATION_NOT_FOUND` (design D3);
- vertical slice de punta a punta (split de pre-flight + GRANT real + SHOW GRANT)
  con identidad OBO y resolutor, y bloqueo del ítem incompatible por la matriz;
- lote 1 a N sobre dos external locations reales con resultado por ítem
  (cardinalidad reutilizada de C5 sin cambios en el pipeline, design D5);
- ausencia de estado residual al final: ni grants ni external locations de la
  corrida quedan en el workspace.

Notas de ejecución: requiere el CLI autenticado con `andresAzureDev` y red; si
no los hay, o si el workspace no permite crear la fixture, la prueba se SALTA
con el motivo documentado (spec - "Tipo no creable en ningún perfil").
"""

import shutil

import pytest

from adaptador_auth_databricks import ProveedorIdentidadScimCli
from adaptador_sql_databricks import (
    EjecutarComandoCli,
    DescubrirWarehouseServerless,
    SesionSqlDatabricks,
)
from control_accesos.autenticacion.servicio import ServicioIdentidadLlamante
from control_accesos.canales.reales.canal_sql_datos import CanalSqlDatos
from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

from fixtures_uc_externos import (
    PERFIL_CLI_AZURE,
    RUTA_API_EXTERNAL_LOCATIONS,
    FixtureObjetoExterno,
    FixturesUcExternos,
)

# Todas las pruebas de este módulo son integrales contra andresAzureDev,
# pre-aprobadas por el humano (marker azure_approval).
pytestmark = pytest.mark.azure_approval

# Cantidad de external locations que crea la corrida: dos, para ejercitar la
# cardinalidad 1 a N del lote sobre objetos externos reales.
CANTIDAD_LOCATIONS_FIXTURE = 2


class SesionRegistradora:
    """Envuelve la sesión real y registra las sentencias ejecutadas.

    Permite a las pruebas verificar qué instrucciones emitió el canal de
    producción (por ejemplo, que un ítem bloqueado no produjo ningún GRANT).

    Attributes:
        sentencias (list[str]): sentencias ejecutadas, en orden.
    """

    def __init__(self, sesion_real):
        self._sesion_real = sesion_real
        self.sentencias = []

    def sql(self, sentencia):
        """Registra la sentencia y la delega en la sesión real."""
        self.sentencias.append(sentencia)
        return self._sesion_real.sql(sentencia)

    def SentenciasGrant(self):
        """Devuelve las sentencias GRANT/REVOKE emitidas (sin SHOW GRANT)."""
        return [
            sentencia
            for sentencia in self.sentencias
            if not sentencia.startswith("SHOW GRANT")
        ]


@pytest.fixture(scope="module")
def entorno():
    """Prepara el entorno integral de Azure: sesión, identidad y fixtures.

    Crea las external locations de la corrida con el storage credential y la
    cuenta descubiertos en el propio workspace, sobre el contenedor de pruebas
    `test`. Si el workspace no expone warehouse, credential ni URL de la que
    derivarlos, el módulo se SALTA con el motivo documentado.

    Yields:
        dict: sesión registradora (`sesion`), identidad OBO (`identidad`),
        beneficiario (`beneficiario`) y fábrica de fixtures (`fixtures`).
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado; la capa integral requiere "
            "el perfil andresAzureDev autenticado."
        )

    warehouse_id = DescubrirWarehouseServerless(PERFIL_CLI_AZURE)
    if warehouse_id is None:
        pytest.skip(
            "El perfil andresAzureDev no expone un SQL warehouse serverless; no "
            "hay dónde ejecutar las instrucciones integrales."
        )

    sesion = SesionRegistradora(
        SesionSqlDatabricks(warehouse_id=warehouse_id, perfil=PERFIL_CLI_AZURE)
    )
    fabrica = FixturesUcExternos(
        sesion_location=sesion, perfil_location=PERFIL_CLI_AZURE
    )
    fabrica.CrearExternalLocation(cantidad=CANTIDAD_LOCATIONS_FIXTURE)

    if not fabrica.locations:
        pytest.skip(
            "El workspace andresAzureDev no permitió crear la external location "
            f"de pruebas: {fabrica.no_creados}"
        )

    identidad = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadScimCli(perfil=PERFIL_CLI_AZURE)
    ).ObtenerIdentidadLlamante()

    yield {
        "sesion": sesion,
        "identidad": identidad,
        "beneficiario": identidad.principal.identificador,
        "fixtures": fabrica,
    }

    # Limpieza total: REVOKE de lo otorgado y DROP de las locations creadas.
    fabrica.Limpiar()

    # Confirmación de ausencia de estado residual (tarea 5.3): tras la limpieza,
    # ninguna external location de la corrida debe figurar en el workspace.
    residuales = [
        location.get("name")
        for location in EjecutarComandoCli(
            ["get", RUTA_API_EXTERNAL_LOCATIONS], PERFIL_CLI_AZURE
        ).get("external_locations", [])
        if location.get("name") in {
            fixture.nombre for fixture in fabrica.locations
        }
    ]
    if residuales:
        pytest.fail(
            f"Quedó estado residual en el workspace: {residuales}"
        )


def CrearItem(fixture, principal, privilegio=None, tipo_principal=TipoPrincipal.USUARIO):
    """Construye un ítem de grant sobre la external location de la fixture.

    Args:
        fixture (FixtureObjetoExterno): objeto externo de la fábrica.
        principal (str): identificación del principal destinatario.
        privilegio (str | None): privilegio a otorgar; por defecto el de la
            fixture (`READ FILES`).
        tipo_principal (TipoPrincipal): tipo del principal destinatario.

    Returns:
        ItemGrant: ítem listo para otorgar/revocar.
    """
    return ItemGrant(
        principal=Principal(identificador=principal, tipo=tipo_principal),
        privilegio=privilegio or fixture.privilegio,
        objeto=ObjetoSecurable(
            identificador=fixture.identificador, tipo=fixture.tipo
        ),
    )


def TieneGrant(canal, fixture, principal, privilegio=None):
    """Indica si el principal tiene el privilegio vigente sobre la location.

    Args:
        canal (CanalSqlDatos): canal real para consultar SHOW GRANT.
        fixture (FixtureObjetoExterno): objeto externo a consultar.
        principal (str): identificación del otorgatario.
        privilegio (str | None): privilegio a buscar; None usa el de la fixture.

    Returns:
        bool: True si hay un grant vigente del principal (y privilegio) sobre el
            objeto.
    """
    objeto = ObjetoSecurable(
        identificador=fixture.identificador, tipo=fixture.tipo
    )
    privilegio_buscado = (privilegio or fixture.privilegio).upper()
    return any(
        grant.privilegio == privilegio_buscado
        and grant.principal.identificador.lower() == principal.lower()
        for grant in canal.ListarGrantsVigentes(objeto)
    )


def TestOtorgaVerificaYRevocaExternalLocation(entorno):
    """GRANT, SHOW GRANT y REVOKE reales funcionan sobre una external location.

    Escenarios "Grant sobre una external location", "Grant confirmado por la
    verificación" e "Instrucción enviada a la sesión inyectada" del spec
    `uc-external-object-grants`.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    beneficiario = entorno["beneficiario"]
    location = fixtures.locations[0]

    canal = CanalSqlDatos(sesion)
    item = CrearItem(location, beneficiario)

    resultado_grant = canal.Otorgar(item)
    assert resultado_grant.estado is EstadoItem.OTORGADO, (
        f"El grant sobre la external location '{location.nombre}' falló: "
        f"{resultado_grant.detalle}"
    )
    # La instrucción real usa la palabra clave de dos tokens (design D1).
    assert any(
        sentencia.startswith("GRANT READ FILES ON EXTERNAL LOCATION ")
        for sentencia in sesion.SentenciasGrant()
    )
    assert TieneGrant(canal, location, beneficiario), (
        "Tras otorgar, SHOW GRANT debe reportar READ FILES sobre la external "
        f"location '{location.nombre}'"
    )
    # Se anota para la revocación de la limpieza (sin estado residual).
    fixtures.RegistrarGrant(item)

    resultado_revocar = canal.Revocar(item)
    assert resultado_revocar.estado is EstadoItem.OTORGADO, (
        f"La revocación falló: {resultado_revocar.detalle}"
    )
    assert not TieneGrant(canal, location, beneficiario), (
        "Tras revocar, el privilegio no debe figurar en SHOW GRANT de la "
        f"external location '{location.nombre}'"
    )


def TestExternalLocationInexistenteSeReportaFallo(entorno):
    """Un grant sobre una external location inexistente se traduce a fallido.

    Escenario "External location o connection inexistente" del spec. El detalle
    se imprime para dejar constancia del código real que reporta el workspace y
    contrastar el patrón declarativo `EXTERNAL_LOCATION_NOT_FOUND` (design D3):
    si el motor usara otro código, el ítem seguiría siendo `fallido` (fail-safe)
    y el patrón se ajustaría como dato, sin tocar lógica.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    beneficiario = entorno["beneficiario"]

    inexistente = FixtureObjetoExterno(
        tipo=TipoObjeto.EXTERNAL_LOCATION,
        nombre=f"{fixtures.locations[0].nombre}_inexistente",
        privilegio="READ FILES",
        identificador=f"{fixtures.locations[0].nombre}_inexistente",
    )

    resultado = CanalSqlDatos(sesion).Otorgar(
        CrearItem(inexistente, beneficiario)
    )
    print(f"[INTEGRAL] Detalle real del workspace: {resultado.detalle}")

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Una external location inexistente debe reportarse fallida, nunca "
        "privilegios insuficientes"
    )
    assert inexistente.nombre in resultado.detalle, (
        "El detalle debe identificar la external location involucrada"
    )


def TestPrincipalInexistenteSobreExternalLocationSeReportaFallo(entorno):
    """Un grant a un principal inexistente sobre la location se reporta fallido.

    Escenario "Principal inexistente" del spec, ejercitado sobre un objeto
    externo: el patrón `PRINCIPAL_DOES_NOT_EXIST` ya contrastado en C4 aplica
    igual aquí.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    location = fixtures.locations[0]

    resultado = CanalSqlDatos(sesion).Otorgar(
        CrearItem(location, "principal_inexistente_c6@example.com")
    )
    print(f"[INTEGRAL] Detalle real del principal inexistente: {resultado.detalle}")

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Un principal inexistente debe reportarse fallido, nunca privilegios "
        "insuficientes"
    )


def TestVerticalSliceExternalLocationDePuntaAPunta(entorno):
    """El pipeline otorga y verifica 1 a 1 sobre una external location real.

    Escenario del slice de punta a punta aplicado a objetos externos: con
    identidad OBO y resolutor de C3, primero se comprueba que sin concesión
    explícita al llamante el split bloquea el ítem; después se concede el
    privilegio al llamante (que es el propio destinatario, siempre otorgable) y
    el slice otorga y verifica, dejando el workspace limpio.
    """
    sesion = entorno["sesion"]
    identidad = entorno["identidad"]
    destinatario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]
    location = fixtures.locations[0]

    canal = CanalSqlDatos(sesion)
    canal_control = CanalControlSimulado()
    pipeline = PipelineGrants(
        canal_datos=canal,
        canal_control=canal_control,
        identidad_llamante=identidad,
        resolutor_privilegios=ResolutorPrivilegiosEfectivos(
            canal_datos=canal, canal_control=canal_control
        ),
    )

    def Solicitud():
        return SolicitudGrant.Crear(
            principal=Principal(
                identificador=destinatario, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["READ FILES"],
            objeto=ObjetoSecurable(
                identificador=location.identificador,
                tipo=TipoObjeto.EXTERNAL_LOCATION,
            ),
        )

    item_llamante = CrearItem(location, destinatario)

    # 1) Sin concesión explícita al llamante, el split bloquea el ítem.
    reporte_bloqueado = pipeline.Procesar(Solicitud())
    assert (
        reporte_bloqueado.lineas[0].estado
        is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    ), f"Detalle del bloqueo: {reporte_bloqueado.lineas[0].detalle}"

    # 2) Se concede al llamante el privilegio que el split exige.
    assert canal.Otorgar(item_llamante).estado is EstadoItem.OTORGADO
    fixtures.RegistrarGrant(item_llamante)

    # 3) El slice otorga y verifica 1 a 1 de punta a punta.
    reporte = pipeline.Procesar(Solicitud())
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO, (
        f"El slice debió otorgar; detalle: {reporte.lineas[0].detalle}"
    )
    assert TieneGrant(canal, location, destinatario)

    # 4) Sin estado residual: se revoca la concesión del slice.
    assert canal.Revocar(item_llamante).estado is EstadoItem.OTORGADO
    assert not TieneGrant(canal, location, destinatario)


def TestLote1aNSobreExternalLocationsReales(entorno):
    """Un lote 1 a N sobre external locations reales otorga y verifica por ítem.

    Escenario "Lote 1 a N sobre external locations" del spec: un principal, un
    privilegio y las dos external locations de la corrida producen un ítem
    atómico por objeto, cada uno otorgado y verificado con su resultado parcial
    (design D5: la normalización de C5 se reutiliza sin cambios).
    """
    sesion = entorno["sesion"]
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]

    if len(fixtures.locations) < 2:
        pytest.skip(
            "Se requieren dos external locations de fixture para el lote 1 a N; "
            f"creadas: {len(fixtures.locations)}"
        )

    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.ProcesarLoteDesdeEntradas(
        principales=[
            Principal(identificador=beneficiario, tipo=TipoPrincipal.USUARIO)
        ],
        privilegios=["READ FILES"],
        objetos=[
            ObjetoSecurable(
                identificador=location.identificador,
                tipo=TipoObjeto.EXTERNAL_LOCATION,
            )
            for location in fixtures.locations
        ],
    )

    assert len(reporte.lineas) == len(fixtures.locations)
    for linea in reporte.lineas:
        assert linea.estado is EstadoItem.OTORGADO, (
            f"El ítem sobre '{linea.item.objeto.identificador}' debió "
            f"otorgarse; detalle: {linea.detalle}"
        )
        fixture = next(
            fixture
            for fixture in fixtures.locations
            if fixture.identificador == linea.item.objeto.identificador
        )
        assert TieneGrant(canal, fixture, beneficiario)
        fixtures.RegistrarGrant(linea.item)

    # Cada ítem emitió su propia instrucción con la palabra clave de dos tokens.
    grants_emitidos = [
        sentencia
        for sentencia in sesion.SentenciasGrant()
        if sentencia.startswith("GRANT READ FILES ON EXTERNAL LOCATION ")
    ]
    assert len(grants_emitidos) >= len(fixtures.locations)

    # Sin estado residual del lote: se revoca lo otorgado por ítem.
    for linea in reporte.lineas:
        assert canal.Revocar(linea.item).estado is EstadoItem.OTORGADO


def TestItemIncompatibleSobreExternalLocationBloqueadoAntesDeEjecutar(entorno):
    """SELECT no es válido para una external location: se bloquea sin GRANT.

    Escenario "Privilegios según la matriz" del spec: la matriz de
    compatibilidad filtra antes de cualquier ejecución.
    """
    sesion = entorno["sesion"]
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]
    location = fixtures.locations[0]

    pipeline = PipelineGrants(
        canal_datos=CanalSqlDatos(sesion),
        canal_control=CanalControlSimulado(),
    )
    sentencias_previas = len(sesion.SentenciasGrant())

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=beneficiario, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto=ObjetoSecurable(
                identificador=location.identificador,
                tipo=TipoObjeto.EXTERNAL_LOCATION,
            ),
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert "no es válido" in reporte.lineas[0].detalle
    assert len(sesion.SentenciasGrant()) == sentencias_previas, (
        "La matriz filtra antes: no debe emitirse ninguna instrucción GRANT"
    )
