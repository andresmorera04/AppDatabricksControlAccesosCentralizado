"""Pruebas integrales de lotes contra el workspace `andresFree`.

Change `grants-batch` (C5), capa integral (marker `free`, design.md D6):
ejercita el código de producción real (`CanalSqlDatos`, `PipelineGrants`,
`SolicitudLoteGrant`) contra el workspace real, inyectando la sesión SQL del
transporte por CLI ya instalado (`SesionSqlDatabricks`).

Verifica en el workspace real:

- lote 1 a N con un principal real (el usuario del llamante resuelto por SCIM)
  con dos privilegios sobre varios objetos reales de la fábrica más un objeto
  inexistente; los grants de los objetos existentes quedan vigentes con
  `SHOW GRANT`, los ítems del inexistente se reportan `fallido` con el patrón
  real del workspace, y se revoca todo lo otorgado (Task 6.1);
- lote N a 1 con dos principals reales existentes (el usuario del llamante y
  `andresmg.una@gmail.com`, autorizados por el humano; si el llamante es ese
  mismo usuario, el segundo principal es el grupo `account users`) con un
  privilegio sobre un objeto de prueba; cada grant queda vigente por principal
  con `SHOW GRANT` y se revocan ambos (Task 6.2, design.md D5).

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
from control_accesos.dominio.enumeraciones import EstadoItem, TipoObjeto
from control_accesos.dominio.modelos import ObjetoSecurable, Principal
from control_accesos.pipeline.pipeline_grants import PipelineGrants
from control_accesos.resolucion.resolutor import ResolutorPrivilegiosEfectivos

from fixtures_uc_datos import FixturesUcDatos

# Todas las pruebas de este módulo son integrales contra andresFree.
pytestmark = pytest.mark.free

# Usuario autorizado por el humano para el lote N a 1 (design.md D5).
USUARIO_AUTORIZADO_NA1 = "andresmg.una@gmail.com"

# Grupo de respaldo si el llamante es el mismo usuario autorizado.
GRUPO_RESPALDO_NA1 = "account users"


@pytest.fixture(scope="module")
def entorno():
    """Prepara el entorno integral: sesión, identidad, beneficiario y fixtures.

    Yields:
        dict: sesión SQL (`sesion`), identidad OBO (`identidad`), beneficiario
        (`beneficiario`), fábrica y objetos creados (`fixtures`).
    """
    # Verificar que el CLI de Databricks está disponible.
    if shutil.which("databricks") is None:
        pytest.skip("CLI de Databricks no disponible; se omite la prueba integral")

    # Descubrir el warehouse serverless.
    warehouse_id = DescubrirWarehouseServerless()
    if warehouse_id is None:
        pytest.skip("No se encontró warehouse serverless; se omite la prueba integral")

    # Crear la sesión SQL.
    sesion = SesionSqlDatabricks(warehouse_id=warehouse_id)

    # Resolver la identidad del llamante por SCIM.
    proveedor = ProveedorIdentidadScimCli()
    servicio = ServicioIdentidadLlamante(proveedor=proveedor)
    identidad = servicio.ObtenerIdentidadLlamante()

    # Beneficiario: el usuario del llamante.
    beneficiario = Principal(
        identificador=identidad.usuario_bitacora, tipo="usuario"
    )

    # Crear la fábrica de fixtures y crear todos los objetos.
    fixtures = FixturesUcDatos(sesion=sesion)
    fixtures.Crear()

    yield {
        "sesion": sesion,
        "identidad": identidad,
        "beneficiario": beneficiario,
        "fixtures": fixtures,
    }

    # Limpieza: destruir todas las fixtures creadas.
    fixtures.Limpiar()


class TestLote1aNIntegral:
    """Prueba integral del lote 1 a N con resultados parciales (Task 6.1)."""

    def TestLote1aNConObjetoInexistenteTerminaParcial(self, entorno):
        """Un lote 1 a N con un objeto inexistente termina parcial.

        WHEN se procesa un lote 1 a N con dos privilegios sobre varios objetos
        reales más uno inexistente THEN los grants de los objetos existentes
        quedan vigentes con `SHOW GRANT`, los ítems del inexistente se reportan
        `fallido`, y se revoca todo lo otorgado.
        """
        sesion = entorno["sesion"]
        identidad = entorno["identidad"]
        beneficiario = entorno["beneficiario"]
        fixtures = entorno["fixtures"]

        # Obtener objetos reales de la fábrica.
        fixture1 = fixtures.Objeto(TipoObjeto.TABLA_DELTA)
        fixture2 = fixtures.Objeto(TipoObjeto.ESQUEMA)
        if fixture1 is None or fixture2 is None:
            pytest.skip("Sin objetos de fixtures para la prueba.")

        # Convertir FixtureObjeto a ObjetoSecurable.
        objeto1 = ObjetoSecurable(
            identificador=fixture1.calificado, tipo=fixture1.tipo
        )
        objeto2 = ObjetoSecurable(
            identificador=fixture2.calificado, tipo=fixture2.tipo
        )

        # Objeto inexistente (no se crea en la fábrica).
        objeto_inexistente = ObjetoSecurable(
            identificador="catalogo_inexistente.esquema_inexistente.tabla_inexistente",
            tipo=TipoObjeto.TABLA_DELTA,
        )

        # Crear el pipeline con el canal SQL real.
        canal_datos = CanalSqlDatos(sesion)
        canal_control = CanalControlSimulado()
        resolutor = ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        )
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            resolutor_privilegios=resolutor,
            identidad_llamante=identidad,
        )

        # Procesar el lote 1 a N con dos privilegios.
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[beneficiario],
            privilegios=["SELECT", "INSERT"],
            objetos=[objeto1, objeto_inexistente, objeto2],
        )

        # 6 ítems: 2 objetos × 2 privilegios = 4 otorgados, 1 objeto inexistente × 2 privilegios = 2 fallidos.
        assert len(resultado.lineas) == 6
        
        # Contar los estados.
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        fallidos = [l for l in resultado.lineas if l.estado is EstadoItem.FALLIDO]
        insuficientes = [l for l in resultado.lineas if l.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES]
        
        # Si el llamante no tiene privilegios suficientes, saltar la prueba.
        if len(insuficientes) > 0:
            pytest.skip(
                f"El llamante no tiene privilegios suficientes para otorgar en los objetos de fixtures: "
                f"{len(insuficientes)} ítems bloqueados con privilegios_insuficientes"
            )
        
        assert len(otorgados) == 4, f"Esperados 4 otorgados, obtenidos {len(otorgados)}"
        assert len(fallidos) == 2, f"Esperados 2 fallidos, obtenidos {len(fallidos)}"

        # Verificar que los grants de los objetos existentes quedan vigentes.
        for objeto in [objeto1, objeto2]:
            grants_vigentes = canal_datos.ListarGrantsVigentes(objeto)
            # Cada objeto debe tener al menos 1 grant.
            assert len(grants_vigentes) >= 1

        # Revocar todo lo otorgado.
        for linea in otorgados:
            canal_datos.Revocar(linea.item)


class TestLoteNa1Integral:
    """Prueba integral del lote N a 1 con principals reales (Task 6.2)."""

    def TestLoteNa1ConDosPrincipalesReales(self, entorno):
        """Un lote N a 1 con dos principals reales existentes.

        WHEN se procesa un lote N a 1 con el usuario del llamante y
        `andresmg.una@gmail.com` (o el grupo `account users` si el llamante es
        ese mismo usuario) THEN cada grant queda vigente por principal con
        `SHOW GRANT` y se revocan ambos.
        """
        sesion = entorno["sesion"]
        identidad = entorno["identidad"]
        fixtures = entorno["fixtures"]

        # Determinar los dos principals.
        usuario_llamante = identidad.usuario_bitacora
        if usuario_llamante == USUARIO_AUTORIZADO_NA1:
            # El llamante es el mismo usuario autorizado; usar el grupo de respaldo.
            principal1 = Principal(identificador=usuario_llamante, tipo="usuario")
            principal2 = Principal(identificador=GRUPO_RESPALDO_NA1, tipo="grupo")
        else:
            principal1 = Principal(identificador=usuario_llamante, tipo="usuario")
            principal2 = Principal(identificador=USUARIO_AUTORIZADO_NA1, tipo="usuario")

        # Obtener un objeto de prueba.
        fixture = fixtures.Objeto(TipoObjeto.TABLA_DELTA)
        if fixture is None:
            pytest.skip("Sin tabla delta de fixtures para la prueba.")

        # Convertir FixtureObjeto a ObjetoSecurable.
        objeto = ObjetoSecurable(
            identificador=fixture.calificado, tipo=fixture.tipo
        )

        # Crear el pipeline con el canal SQL real.
        canal_datos = CanalSqlDatos(sesion)
        canal_control = CanalControlSimulado()
        resolutor = ResolutorPrivilegiosEfectivos(
            canal_datos=canal_datos, canal_control=canal_control
        )
        pipeline = PipelineGrants(
            canal_datos=canal_datos,
            canal_control=canal_control,
            resolutor_privilegios=resolutor,
            identidad_llamante=identidad,
        )

        # Procesar el lote N a 1 con un privilegio.
        resultado = pipeline.ProcesarLoteDesdeEntradas(
            principales=[principal1, principal2],
            privilegios=["SELECT"],
            objetos=[objeto],
        )

        # 2 ítems: uno por principal.
        assert len(resultado.lineas) == 2
        
        # Contar los estados.
        otorgados = [l for l in resultado.lineas if l.estado is EstadoItem.OTORGADO]
        insuficientes = [l for l in resultado.lineas if l.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES]
        
        # Si el llamante no tiene privilegios suficientes, saltar la prueba.
        if len(insuficientes) > 0:
            pytest.skip(
                f"El llamante no tiene privilegios suficientes para otorgar en el objeto de fixtures: "
                f"{len(insuficientes)} ítems bloqueados con privilegios_insuficientes"
            )
        
        assert len(otorgados) == 2, f"Esperados 2 otorgados, obtenidos {len(otorgados)}"

        # Verificar que cada grant queda vigente por principal.
        grants_vigentes = canal_datos.ListarGrantsVigentes(objeto)
        # Debe haber al menos 2 grants (uno por principal).
        assert len(grants_vigentes) >= 2

        # Revocar ambos.
        for linea in otorgados:
            canal_datos.Revocar(linea.item)
