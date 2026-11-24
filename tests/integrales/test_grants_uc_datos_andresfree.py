"""Pruebas integrales del canal SQL real contra el workspace `andresFree`.

Change C4 (`grants-uc-datos`), capa integral (marker `free`, README D5):
ejercita el código de producción real (`CanalSqlDatos`, `PipelineGrants`,
`ResolutorPrivilegiosEfectivos`) contra el workspace real, inyectando la sesión
SQL del transporte por CLI ya instalado (`SesionSqlDatabricks`). No se instala
ninguna biblioteca nueva (regla "Prohibición de instalación por la IA").

Verifica en el workspace real:

- otorgamiento 1 a 1, verificación con `SHOW GRANT` y revocación para cada tipo
  de objeto soportado que la fábrica pueda crear;
- ítem clasificado `fallido` ante objeto inexistente y principal inexistente;
- vertical slice de punta a punta (split de pre-flight + GRANT real + SHOW GRANT)
  con identidad OBO y resolutor, y bloqueo del ítem incompatible por la matriz
  antes de ejecutar instrucción alguna.

El caso de permiso denegado se valida a nivel funcional con errores de forma
real (decisión del humano, design D3) y aquí solo se contrasta si la respuesta
real ocurre de forma natural. Los tipos que Free Edition no pueda crear (p. ej.
vista materializada o streaming table) se omiten con su motivo documentado en
`fixtures.no_creados`; el humano autorizó el fallback en `andresAzureDev`
(marker `azure_approval`) si Free Edition lo limitara.

Notas de ejecución: requiere el CLI autenticado con `andresFree` y red; si no
los hay, la prueba se SALTA (no falla). El warehouse serverless puede arrancar
en frío. La prueba crea y destruye sus propias fixtures (sin estado residual).
"""

import shutil

import pytest

from adaptador_auth_databricks import ProveedorIdentidadScimCli
from adaptador_sql_databricks import (
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

from fixtures_uc_datos import FixtureObjeto, FixturesUcDatos

# Todas las pruebas de este módulo son integrales contra andresFree.
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


@pytest.fixture(scope="module")
def entorno():
    """Prepara el entorno integral: sesión, identidad, beneficiario y fixtures.

    Yields:
        dict: sesión registradora (`sesion`), identidad OBO (`identidad`),
        beneficiario (`beneficiario`), grupo del llamante (`grupo`), fábrica y
        objetos creados (`fixtures`).
    """
    if shutil.which("databricks") is None:
        pytest.skip(
            "El CLI de Databricks no está instalado; la capa integral requiere "
            "el perfil andresFree autenticado."
        )

    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip(
            "El perfil andresFree no expone un SQL warehouse serverless; no hay "
            "dónde ejecutar las instrucciones integrales."
        )

    sesion = SesionRegistradora(SesionSqlDatabricks(warehouse_id=warehouse_id))
    identidad = ServicioIdentidadLlamante(
        proveedor=ProveedorIdentidadScimCli()
    ).ObtenerIdentidadLlamante()
    beneficiario = identidad.principal.identificador

    fixtures = FixturesUcDatos(sesion)
    fixtures.Crear()

    yield {
        "sesion": sesion,
        "identidad": identidad,
        "beneficiario": beneficiario,
        "fixtures": fixtures,
    }

    # Limpieza total: el DROP CASCADE arrastra objetos y grants del catálogo.
    fixtures.Limpiar()


def CrearItem(fixture, principal, tipo_principal=TipoPrincipal.USUARIO):
    """Construye un ítem de grant sobre el fixture, para el principal indicado.

    Args:
        fixture (FixtureObjeto): objeto de la fábrica.
        principal (str): identificación del principal destinatario.
        tipo_principal (TipoPrincipal): tipo del principal destinatario.

    Returns:
        ItemGrant: ítem listo para otorgar/revocar.
    """
    return ItemGrant(
        principal=Principal(identificador=principal, tipo=tipo_principal),
        privilegio=fixture.privilegio,
        objeto=ObjetoSecurable(
            identificador=fixture.calificado, tipo=fixture.tipo
        ),
    )


def TieneGrant(canal, fixture, principal, privilegio=None):
    """Indica si el principal tiene el privilegio vigente sobre el objeto.

    Args:
        canal (CanalSqlDatos): canal real para consultar SHOW GRANT.
        fixture (FixtureObjeto): objeto a consultar.
        principal (str): identificación del otorgatario.
        privilegio (str | None): privilegio a buscar; None acepta cualquiera.

    Returns:
        bool: True si hay un grant vigente del principal (y privilegio) sobre
            el objeto.
    """
    objeto = ObjetoSecurable(
        identificador=fixture.calificado, tipo=fixture.tipo
    )
    privilegio_buscado = (privilegio or fixture.privilegio).upper()
    return any(
        grant.privilegio == privilegio_buscado
        and grant.principal.identificador.lower() == principal.lower()
        for grant in canal.ListarGrantsVigentes(objeto)
    )


def TestOtorgaVerificaYRevocaCadaTipoDeObjeto(entorno):
    """GRANT, SHOW GRANT y REVOKE reales funcionan para cada tipo creado.

    Escenario "Grant confirmado por la verificación" del spec.
    """
    canal = CanalSqlDatos(entorno["sesion"])
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]

    tipos_probados = []
    for tipo, fixture in fixtures.objetos.items():
        item = CrearItem(fixture, beneficiario)

        resultado_grant = canal.Otorgar(item)
        assert resultado_grant.estado is EstadoItem.OTORGADO, (
            f"El grant sobre {tipo.value} '{fixture.calificado}' falló: "
            f"{resultado_grant.detalle}"
        )
        assert TieneGrant(canal, fixture, beneficiario), (
            f"Tras otorgar, SHOW GRANT debe reportar el privilegio sobre "
            f"{tipo.value} '{fixture.calificado}'"
        )

        resultado_revocar = canal.Revocar(item)
        assert resultado_revocar.estado is EstadoItem.OTORGADO
        assert not TieneGrant(canal, fixture, beneficiario), (
            f"Tras revocar, el privilegio no debe figurar en SHOW GRANT de "
            f"{tipo.value} '{fixture.calificado}'"
        )
        tipos_probados.append(tipo.value)

    # Los tipos esenciales deben haberse probado.
    for tipo_esencial in (TipoObjeto.CATALOGO, TipoObjeto.ESQUEMA,
                          TipoObjeto.TABLA_DELTA):
        assert tipo_esencial.value in tipos_probados

    # Los tipos opcionales que Free Edition no pudo crear quedan documentados.
    if fixtures.no_creados:
        print(
            "[INTEGRAL] Tipos no creados en andresFree (omitidos): "
            f"{fixtures.no_creados}"
        )


def TestObjetoInexistenteSeReportaFallo(entorno):
    """Un grant sobre objeto inexistente se traduce a fallido controlado.

    Escenario "Objeto inexistente" del spec.
    """
    canal = CanalSqlDatos(entorno["sesion"])
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]

    fixture = FixtureObjeto(
        tipo=TipoObjeto.TABLA_DELTA,
        nombre="tabla_inexistente",
        privilegio="SELECT",
        calificado=f"{fixtures.esquema_calificado}.tabla_inexistente",
    )
    resultado = canal.Otorgar(CrearItem(fixture, beneficiario))

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Un objeto inexistente debe reportarse fallido, nunca privilegios "
        "insuficientes"
    )
    # El detalle identifica el objeto (nuestro mensaje o el del propio motor).
    assert "tabla_inexistente" in resultado.detalle


def TestPrincipalInexistenteSeReportaFallo(entorno):
    """Un grant a un principal inexistente se traduce a fallido controlado.

    Escenario "Principal inexistente" del spec. El patrón exacto del error del
    motor se contrasta aquí contra el workspace real y queda registrado en el
    detalle para afinar los patrones declarativos (design D3).
    """
    canal = CanalSqlDatos(entorno["sesion"])
    fixtures = entorno["fixtures"]
    tabla = fixtures.Objeto(TipoObjeto.TABLA_DELTA)
    if tabla is None:
        pytest.skip("Sin tabla delta de fixtures para la prueba.")

    item = CrearItem(
        tabla, "principal_inexistente_c4@example.com"
    )
    resultado = canal.Otorgar(item)

    assert resultado.estado is EstadoItem.FALLIDO, (
        "Un principal inexistente debe reportarse fallido, nunca privilegios "
        "insuficientes"
    )


def TestVerticalSliceDePuntaAPunta(entorno):
    """El pipeline otorga y verifica 1 a 1 con canal real y split de C3.

    Escenario "Solicitud otorgada de punta a punta" del spec. Se usa al propio
    llamante (correo del dueño del catálogo) como destinatario: es un principal
    siempre otorgable y hace el slice determinista. Primero se comprueba que,
    sin concesión explícita al llamante, el split bloquea el ítem (un catálogo
    nuevo NO lista a su propietario en SHOW GRANT: el modelo de C3 se apoya en
    concesiones explícitas, no en la propiedad implícita); después se concede el
    privilegio y el slice otorga 1 a 1 y verifica, dejando el workspace limpio.
    """
    sesion = entorno["sesion"]
    identidad = entorno["identidad"]
    destinatario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]

    tabla = fixtures.Objeto(TipoObjeto.TABLA_DELTA)
    if tabla is None:
        pytest.skip("Sin tabla delta de fixtures para el slice.")

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

    def Item(principal):
        return ItemGrant(
            principal=Principal(
                identificador=principal, tipo=TipoPrincipal.USUARIO
            ),
            privilegio="SELECT",
            objeto=ObjetoSecurable(
                identificador=tabla.calificado, tipo=TipoObjeto.TABLA_DELTA
            ),
        )

    def Solicitud(principal):
        return SolicitudGrant.Crear(
            principal=Principal(
                identificador=principal, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["SELECT"],
            objeto=ObjetoSecurable(
                identificador=tabla.calificado, tipo=TipoObjeto.TABLA_DELTA
            ),
        )

    # 1) Sin concesión explícita al llamante, el split bloquea el ítem.
    reporte_bloqueado = pipeline.Procesar(Solicitud(destinatario))
    assert (
        reporte_bloqueado.lineas[0].estado
        is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    )

    # 2) Concede al llamante el privilegio explícito que el split exige.
    assert canal.Otorgar(Item(destinatario)).estado is EstadoItem.OTORGADO

    # 3) El slice otorga y verifica 1 a 1 de punta a punta.
    reporte = pipeline.Procesar(Solicitud(destinatario))

    assert reporte.lineas[0].estado is EstadoItem.OTORGADO, (
        f"El slice debió otorgar; detalle: {reporte.lineas[0].detalle}"
    )
    assert TieneGrant(canal, tabla, destinatario, "SELECT")

    # 4) Sin estado residual: se revoca la concesión del slice y la del llamante.
    assert canal.Revocar(Item(destinatario)).estado is EstadoItem.OTORGADO
    assert not TieneGrant(canal, tabla, destinatario, "SELECT")


def TestItemIncompatibleBloqueadoAntesDeEjecutar(entorno):
    """Un privilegio inválido para el tipo se bloquea sin emitir GRANT.

    Escenario "Ítem incompatible bloqueado antes de ejecutar" del spec.
    """
    sesion = entorno["sesion"]
    beneficiario = entorno["beneficiario"]
    fixtures = entorno["fixtures"]
    tabla = fixtures.Objeto(TipoObjeto.TABLA_DELTA)
    if tabla is None:
        pytest.skip("Sin tabla delta de fixtures para la prueba.")

    canal = CanalSqlDatos(sesion)
    pipeline = PipelineGrants(
        canal_datos=canal, canal_control=CanalControlSimulado()
    )
    sentencias_previas = len(sesion.SentenciasGrant())

    reporte = pipeline.Procesar(
        SolicitudGrant.Crear(
            principal=Principal(
                identificador=beneficiario, tipo=TipoPrincipal.USUARIO
            ),
            privilegios=["CAN_USE"],
            objeto=ObjetoSecurable(
                identificador=tabla.calificado, tipo=TipoObjeto.TABLA_DELTA
            ),
        )
    )

    assert reporte.lineas[0].estado is EstadoItem.FALLIDO
    assert "no es válido" in reporte.lineas[0].detalle
    assert len(sesion.SentenciasGrant()) == sentencias_previas, (
        "La matriz filtra antes: no debe emitirse ninguna instrucción GRANT"
    )
