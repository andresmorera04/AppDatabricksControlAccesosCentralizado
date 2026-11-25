"""Pruebas integrales de grants sobre connections contra `andresFree`.

Change C6 (`grants-uc-externos`), capa integral (marker `free`, README D5 y
decisión del humano en design D6): ejercita el código de producción real
(`CanalSqlDatos`, `PipelineGrants`, `ResolutorPrivilegiosEfectivos`) sobre una
**connection de Unity Catalog** creada por la propia corrida hacia el SQL Server
de pruebas, inyectando la sesión SQL del transporte por CLI ya instalado
(`SesionSqlDatabricks`). No se instala ninguna biblioteca nueva (regla
"Prohibición de instalación por la IA").

Verifica en el workspace real:

- otorgamiento 1 a 1 (`USE CONNECTION`), verificación con `SHOW GRANT` y
  revocación sobre la connection creada;
- ítem clasificado `fallido` ante connection inexistente y ante principal
  inexistente, dejando constancia del código real que reporta el workspace para
  contrastar el patrón declarativo `CONNECTION_NOT_FOUND` (design D3);
- vertical slice de punta a punta (split de pre-flight + GRANT real + SHOW GRANT)
  con identidad OBO y resolutor, y bloqueo del ítem incompatible por la matriz
  antes de ejecutar instrucción alguna.

**Fallback autorizado por el humano**: si el perfil `andresFree` no permite
crear la connection, la fixture se intenta contra `andresAzureDev`; solo si
ambos perfiles fallan la prueba se SALTA con el motivo documentado (spec -
"Connection con fallback autorizado" y "Tipo no creable en ningún perfil").

Notas de ejecución: requiere el CLI autenticado y red; si no los hay, la prueba
se SALTA (no falla). El warehouse serverless puede arrancar en frío. La prueba
crea y destruye sus propias fixtures (sin estado residual).
"""

import shutil

import pytest

from adaptador_auth_databricks import ProveedorIdentidadScimCli
from adaptador_sql_databricks import (
    PERFIL_CLI_INTEGRAL,
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
    FixtureObjetoExterno,
    FixturesUcExternos,
)

# Todas las pruebas de este módulo son integrales contra andresFree (con el
# fallback autorizado a andresAzureDev solo si Free no puede crear la fixture).
pytestmark = pytest.mark.free


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


def CrearSesion(perfil):
    """Crea la sesión registradora del perfil indicado, o None si no hay warehouse.

    Args:
        perfil (str): perfil CLI autenticado (`andresFree` o `andresAzureDev`).

    Returns:
        SesionRegistradora | None: sesión lista para ejecutar SQL, o None si el
            perfil no expone un SQL warehouse serverless.
    """
    warehouse_id = DescubrirWarehouseServerless(perfil)
    if warehouse_id is None:
        return None
    return SesionRegistradora(
        SesionSqlDatabricks(warehouse_id=warehouse_id, perfil=perfil)
    )


@pytest.fixture(scope="module")
def entorno():
    """Prepara el entorno integral: sesión, identidad, beneficiario y fixtures.

    Crea la connection de pruebas contra `andresFree` y, solo si ese perfil
    falla, contra `andresAzureDev` (fallback autorizado por el humano, design
    D6). Si ningún perfil puede crearla, el módulo se SALTA con el motivo.

    Yields:
        dict: sesión efectiva (`sesion`), perfil efectivo (`perfil`), identidad
        OBO (`identidad`), beneficiario (`beneficiario`) y fábrica de fixtures
        (`fixtures`).
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado; la capa integral requiere "
            "el perfil andresFree autenticado."
        )

    sesion_free = CrearSesion(PERFIL_CLI_INTEGRAL)
    if sesion_free is None:
        pytest.skip(
            "El perfil andresFree no expone un SQL warehouse serverless; no hay "
            "dónde ejecutar las instrucciones integrales."
        )

    # 1) Intento en el perfil primario (andresFree).
    fabrica = FixturesUcExternos(sesion_connection=sesion_free)
    fabrica.CrearConnection()

    perfil_efectivo = PERFIL_CLI_INTEGRAL
    if fabrica.Objeto(TipoObjeto.CONNECTION) is None:
        # 2) Fallback autorizado: el mismo DDL contra andresAzureDev.
        motivo_free = fabrica.no_creados.get(
            TipoObjeto.CONNECTION.value, "motivo no reportado"
        )
        sesion_azure = None
        try:
            sesion_azure = CrearSesion(PERFIL_CLI_AZURE)
        except Exception as error:  # noqa: BLE001 - el fallback es best-effort
            sesion_azure = None
            motivo_azure = f"{type(error).__name__}: {error}"

        if sesion_azure is None:
            pytest.skip(
                "La connection no se pudo crear en andresFree "
                f"({motivo_free}) y el perfil andresAzureDev no expone un SQL "
                "warehouse serverless para el fallback autorizado."
            )

        fabrica.sesion_connection = sesion_azure
        fabrica.CrearConnection()
        if fabrica.Objeto(TipoObjeto.CONNECTION) is None:
            pytest.skip(
                "La connection no se pudo crear en ningún perfil (ni andresFree "
                f"ni andresAzureDev): {fabrica.no_creados}"
            )
        perfil_efectivo = PERFIL_CLI_AZURE

    # La identidad OBO se resuelve en el mismo workspace donde vive la fixture.
    identidad = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadScimCli(perfil=perfil_efectivo)
    ).ObtenerIdentidadLlamante()

    yield {
        "sesion": fabrica.SesionConnection(),
        "perfil": perfil_efectivo,
        "identidad": identidad,
        "beneficiario": identidad.principal.identificador,
        "fixtures": fabrica,
    }

    # Limpieza total: REVOKE de lo otorgado y DROP de la connection creada.
    fabrica.Limpiar()


def CrearItem(fixture, principal, privilegio=None, tipo_principal=TipoPrincipal.USUARIO):
    """Construye un ítem de grant sobre la connection de la fixture.

    Args:
        fixture (FixtureObjetoExterno): objeto externo de la fábrica.
        principal (str): identificación del principal destinatario.
        privilegio (str | None): privilegio a otorgar; por defecto el de la
            fixture (`USE CONNECTION`).
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
    """Indica si el principal tiene el privilegio vigente sobre la connection.

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


def TestOtorgaVerificaYRevocaConnection(entorno):
    """GRANT, SHOW GRANT y REVOKE reales funcionan sobre una connection.

    Escenarios "Grant sobre una connection", "Grant confirmado por la
    verificación" e "Instrucción enviada a la sesión inyectada" del spec
    `uc-external-object-grants`.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    beneficiario = entorno["beneficiario"]
    connection = fixtures.Objeto(TipoObjeto.CONNECTION)

    canal = CanalSqlDatos(sesion)
    item = CrearItem(connection, beneficiario)

    resultado_grant = canal.Otorgar(item)
    assert resultado_grant.estado is EstadoItem.OTORGADO, (
        f"El grant sobre la connection '{connection.nombre}' falló: "
        f"{resultado_grant.detalle}"
    )
    # La instrucción real usa la palabra clave CONNECTION (design D1).
    assert any(
        sentencia.startswith("GRANT USE CONNECTION ON CONNECTION ")
        for sentencia in sesion.SentenciasGrant()
    )
    assert TieneGrant(canal, connection, beneficiario), (
        "Tras otorgar, SHOW GRANT debe reportar USE CONNECTION sobre la "
        f"connection '{connection.nombre}'"
    )
    # Se anota para la revocación de la limpieza (sin estado residual).
    fixtures.RegistrarGrant(item)

    resultado_revocar = canal.Revocar(item)
    assert resultado_revocar.estado is EstadoItem.OTORGADO, (
        f"La revocación falló: {resultado_revocar.detalle}"
    )
    assert not TieneGrant(canal, connection, beneficiario), (
        "Tras revocar, el privilegio no debe figurar en SHOW GRANT de la "
        f"connection '{connection.nombre}'"
    )


def TestConnectionInexistenteSeReportaFallo(entorno):
    """Un grant sobre una connection inexistente se traduce a fallido.

    Escenario "External location o connection inexistente" del spec. El detalle
    se imprime para dejar constancia del código real que reporta el workspace y
    contrastar el patrón declarativo `CONNECTION_NOT_FOUND` (design D3): si el
    motor usara otro código, el ítem seguiría siendo `fallido` (fail-safe) y el
    patrón se ajustaría como dato, sin tocar lógica.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    beneficiario = entorno["beneficiario"]

    inexistente = FixtureObjetoExterno(
        tipo=TipoObjeto.CONNECTION,
        nombre=f"{fixtures.nombre_connection}_inexistente",
        privilegio="USE CONNECTION",
        identificador=f"{fixtures.nombre_connection}_inexistente",
    )

    resultado = CanalSqlDatos(sesion).Otorgar(
        CrearItem(inexistente, beneficiario)
    )
    print(f"[INTEGRAL] Detalle real del workspace: {resultado.detalle}")

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Una connection inexistente debe reportarse fallida, nunca privilegios "
        "insuficientes"
    )
    assert inexistente.nombre in resultado.detalle, (
        "El detalle debe identificar la connection involucrada"
    )


def TestPrincipalInexistenteSobreConnectionSeReportaFallo(entorno):
    """Un grant a un principal inexistente sobre la connection se reporta fallido.

    Escenario "Principal inexistente" del spec, ejercitado sobre un objeto
    externo: el patrón `PRINCIPAL_DOES_NOT_EXIST` ya contrastado en C4 aplica
    igual aquí.
    """
    sesion = entorno["sesion"]
    fixtures = entorno["fixtures"]
    connection = fixtures.Objeto(TipoObjeto.CONNECTION)

    resultado = CanalSqlDatos(sesion).Otorgar(
        CrearItem(connection, "principal_inexistente_c6@example.com")
    )
    print(f"[INTEGRAL] Detalle real del principal inexistente: {resultado.detalle}")

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Un principal inexistente debe reportarse fallido, nunca privilegios "
        "insuficientes"
    )


def TestVerticalSliceConnectionDePuntaAPunta(entorno):
    """El pipeline otorga y verifica 1 a 1 sobre una connection real.

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
    connection = fixtures.Objeto(TipoObjeto.CONNECTION)

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
            privilegios=["USE CONNECTION"],
            objeto=ObjetoSecurable(
                identificador=connection.identificador,
                tipo=TipoObjeto.CONNECTION,
            ),
        )

    item_llamante = CrearItem(connection, destinatario)

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
    assert TieneGrant(canal, connection, destinatario)

    # 4) Sin estado residual: se revoca la concesión del slice.
    assert canal.Revocar(item_llamante).estado is EstadoItem.OTORGADO
    assert not TieneGrant(canal, connection, destinatario)


def TestItemIncompatibleSobreConnectionBloqueadoAntesDeEjecutar(entorno):
    """SELECT no es válido para una connection: se bloquea sin emitir GRANT.

    Escenario "Privilegios según la matriz" del spec: la matriz de
    compatibilidad filtra antes de cualquier ejecución.
    """
    sesion = entorno["sesion"]
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]
    connection = fixtures.Objeto(TipoObjeto.CONNECTION)

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
                identificador=connection.identificador,
                tipo=TipoObjeto.CONNECTION,
            ),
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert "no es válido" in reporte.lineas[0].detalle
    assert len(sesion.SentenciasGrant()) == sentencias_previas, (
        "La matriz filtra antes: no debe emitirse ninguna instrucción GRANT"
    )
