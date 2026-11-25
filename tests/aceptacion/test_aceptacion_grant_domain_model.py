"""Pruebas de aceptación del capability `grant-domain-model`.

Trazabilidad 1:1 con los escenarios del spec
`openspec/specs/grant-domain-model/spec.md`:

- Representación de principals:
  - Principal de usuario válido -> TestEscenarioPrincipalDeUsuarioValido
  - Tipo de principal no soportado -> TestEscenarioTipoDePrincipalNoSoportado
  - Principal sin identificador -> TestEscenarioPrincipalSinIdentificador
- Representación de objetos securables tipados:
  - Objeto del plano de datos -> TestEscenarioObjetoDelPlanoDeDatos
  - Objeto del plano de control -> TestEscenarioObjetoDelPlanoDeControl
  - Tipo de objeto no soportado -> TestEscenarioTipoDeObjetoNoSoportado
- Solicitud de grant cardinalidad 1 a 1:
  - Solicitud válida -> TestEscenarioSolicitudValida
  - Solicitud sin privilegios -> TestEscenarioSolicitudSinPrivilegios
  - Solicitud con cardinalidad N a M -> TestEscenarioSolicitudConCardinalidadNM
- Resultado por ítem:
  - Ítem otorgado -> TestEscenarioItemOtorgado
  - Ítem fallido -> TestEscenarioItemFallido
  - Ítem con privilegios insuficientes -> TestEscenarioItemConPrivilegiosInsuficientes
- Normalización de identificadores de objetos:
  - Dos referencias al mismo catálogo -> TestEscenarioDosReferenciasAlMismoCatalogo
"""

import pytest

from control_accesos.canales.simulados.canales_simulados import (
    CanalControlSimulado,
    CanalDatosSimulado,
    EscenarioSimulacion,
)
from control_accesos.dominio.enumeraciones import (
    EstadoItem,
    Plano,
    TipoObjeto,
    TipoPrincipal,
)
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
)
from control_accesos.pipeline.pipeline_grants import PipelineGrants


def TestEscenarioPrincipalDeUsuarioValido():
    """Escenario: Principal de usuario válido.

    WHEN se registra el principal `usuario_demo` con tipo `usuario`
    THEN el sistema acepta el principal y lo identifica por su identificador
         y su tipo.
    """
    principal = Principal(
        identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
    )
    assert principal.identificador == "usuario_demo"
    assert principal.tipo is TipoPrincipal.USUARIO


def TestEscenarioTipoDePrincipalNoSoportado():
    """Escenario: Tipo de principal no soportado.

    WHEN se registra un principal con tipo no perteneciente a la enumeración
    THEN el sistema lo rechaza con un error explícito que indica el tipo
         recibido y los tipos válidos.
    """
    with pytest.raises(ErrorDominio) as error:
        Principal(identificador="robot_demo", tipo="robot")

    mensaje = str(error.value)
    assert "robot" in mensaje
    assert "usuario" in mensaje
    assert "grupo" in mensaje
    assert "service_principal" in mensaje


def TestEscenarioPrincipalSinIdentificador():
    """Escenario: Principal sin identificador.

    WHEN se registra un principal cuyo identificador está vacío o es nulo
    THEN el sistema rechaza el principal con un error explícito.
    """
    with pytest.raises(ErrorDominio):
        Principal(identificador="", tipo=TipoPrincipal.USUARIO)
    with pytest.raises(ErrorDominio):
        Principal(identificador=None, tipo=TipoPrincipal.USUARIO)


def TestEscenarioObjetoDelPlanoDeDatos():
    """Escenario: Objeto del plano de datos.

    WHEN se registra un objeto de tipo `catalogo`
    THEN el sistema acepta el objeto y lo clasifica automáticamente en el
         plano de datos.
    """
    objeto = ObjetoSecurable(identificador="control", tipo=TipoObjeto.CATALOGO)
    assert objeto.plano is Plano.DATOS


def TestEscenarioObjetoDelPlanoDeControl():
    """Escenario: Objeto del plano de control.

    WHEN se registra un objeto de tipo `sql_warehouse`
    THEN el sistema acepta el objeto y lo clasifica automáticamente en el
         plano de control.
    """
    objeto = ObjetoSecurable(
        identificador="a1b2c3d4e5f6", tipo=TipoObjeto.SQL_WAREHOUSE
    )
    assert objeto.plano is Plano.CONTROL


def TestEscenarioTipoDeObjetoNoSoportado():
    """Escenario: Tipo de objeto no soportado.

    WHEN se registra un objeto cuyo tipo no pertenece a la enumeración
    THEN el sistema lo rechaza con un error explícito que indica el tipo
         recibido y la lista de tipos soportados.
    """
    with pytest.raises(ErrorDominio) as error:
        ObjetoSecurable(identificador="demo", tipo="impresora")

    mensaje = str(error.value)
    assert "impresora" in mensaje
    assert "catalogo" in mensaje
    assert "sql_warehouse" in mensaje


def TestEscenarioSolicitudValida():
    """Escenario: Solicitud válida.

    WHEN se crea una solicitud con un principal, dos privilegios y un objeto
    THEN el sistema acepta la solicitud y la deja lista para su procesamiento.
    """
    solicitud = SolicitudGrant.Crear(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT", "MODIFY"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )
    assert len(solicitud.privilegios) == 2
    # Lista para procesamiento: el pipeline la expande sin errores.
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=CanalControlSimulado(),
    )
    reporte = pipeline.Procesar(solicitud)
    assert len(reporte.lineas) == 2


def TestEscenarioSolicitudSinPrivilegios():
    """Escenario: Solicitud sin privilegios.

    WHEN se crea una solicitud cuya lista de privilegios está vacía
    THEN el sistema la rechaza con un error explícito antes de ejecutar
         cualquier operación.
    """
    with pytest.raises(ErrorDominio):
        SolicitudGrant.Crear(
            principal=Principal(
                identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
            ),
            privilegios=[],
            objeto=ObjetoSecurable(
                identificador="control", tipo=TipoObjeto.CATALOGO
            ),
        )


def TestEscenarioSolicitudConCardinalidadNM():
    """Escenario: Solicitud con cardinalidad N a M.

    WHEN se crea una solicitud que involucra varios principals y varios
         objetos simultáneamente
    THEN el sistema la rechaza con un mensaje explícito que indica que la
         cardinalidad N a M está fuera de alcance.
    """
    with pytest.raises(ErrorDominio) as error:
        SolicitudGrant.CrearDesdeConjuntos(
            principales=[
                Principal(
                    identificador="usuario_a", tipo=TipoPrincipal.USUARIO
                ),
                Principal(
                    identificador="usuario_b", tipo=TipoPrincipal.USUARIO
                ),
            ],
            privilegios=["SELECT"],
            objetos=[
                ObjetoSecurable(
                    identificador="control", tipo=TipoObjeto.CATALOGO
                ),
                ObjetoSecurable(
                    identificador="produccion", tipo=TipoObjeto.CATALOGO
                ),
            ],
        )

    mensaje = str(error.value)
    assert "N a M" in mensaje
    assert "fuera de alcance" in mensaje


def TestEscenarioItemOtorgado():
    """Escenario: Ítem otorgado.

    WHEN un ítem de grant se procesa y el canal de ejecución confirma el
         otorgamiento
    THEN el resultado del ítem registra el estado `otorgado` con la referencia
         completa al principal, privilegio y objeto.
    """
    pipeline = PipelineGrants(
        canal_datos=CanalDatosSimulado(),
        canal_control=CanalControlSimulado(),
    )

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.OTORGADO
    # Referencia completa al ítem procesado.
    assert linea.item.principal.identificador == "usuario_demo"
    assert linea.item.privilegio == "SELECT"
    assert linea.item.objeto.identificador == "control.produccion.ventas"


def TestEscenarioItemFallido():
    """Escenario: Ítem fallido.

    WHEN un ítem de grant se procesa y el canal de ejecución reporta un error
    THEN el resultado del ítem registra el estado `fallido` con el detalle del
         error ocurrido.
    """
    canal_datos = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.OBJETO_INEXISTENTE
    )
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.inexistente", tipo=TipoObjeto.TABLA_DELTA
        ),
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.FALLIDO
    assert "no existe" in linea.detalle


def TestEscenarioItemConPrivilegiosInsuficientes():
    """Escenario: Ítem con privilegios insuficientes.

    WHEN un ítem de grant se procesa y el ejecutor carece de privilegios para
         otorgarlo
    THEN el resultado del ítem registra el estado `privilegios_insuficientes`
         con el detalle de la causa.
    """
    canal_datos = CanalDatosSimulado(
        escenario_por_defecto=EscenarioSimulacion.PERMISO_DENEGADO
    )
    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=CanalControlSimulado()
    )

    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["SELECT"],
        objeto=ObjetoSecurable(
            identificador="control.produccion.ventas",
            tipo=TipoObjeto.TABLA_DELTA,
        ),
    )

    linea = reporte.lineas[0]
    assert linea.estado is EstadoItem.PRIVILEGIOS_INSUFICIENTES
    assert "PERMISSION_DENIED" in linea.detalle


def TestEscenarioDosReferenciasAlMismoCatalogo():
    """Escenario: Dos referencias al mismo catálogo.

    WHEN una referencia usa `Control` y otra usa `control` para el mismo
         catálogo dentro del procesamiento de una solicitud
    THEN el sistema las trata como el mismo objeto securable en la validación
         y en el reporte.
    """
    # El estado previo del workspace se configura con la referencia en
    # minúsculas y sin registro automático de grants...
    canal_datos = CanalDatosSimulado(registrar_grants_otorgados=False)
    referencia_minusculas = ObjetoSecurable(
        identificador="control", tipo=TipoObjeto.CATALOGO
    )
    from control_accesos.dominio.modelos import ItemGrant

    grant_previo = ItemGrant(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegio="USE CATALOG",
        objeto=referencia_minusculas,
    )
    canal_datos.ConfigurarGrantsVigentes(referencia_minusculas, [grant_previo])

    pipeline = PipelineGrants(
        canal_datos=canal_datos, canal_control=CanalControlSimulado()
    )

    # ...mientras la solicitud usa la referencia con mayúscula inicial.
    reporte = pipeline.ProcesarDesdeEntradas(
        principal=Principal(
            identificador="usuario_demo", tipo=TipoPrincipal.USUARIO
        ),
        privilegios=["USE CATALOG"],
        objeto=ObjetoSecurable(
            identificador="Control", tipo=TipoObjeto.CATALOGO
        ),
    )

    # La verificación encontró el grant vigente configurado bajo la otra
    # escritura: ambas referencias resolvieron al mismo objeto securable.
    assert reporte.lineas[0].estado is EstadoItem.OTORGADO
    assert reporte.lineas[0].item.objeto.identificador == "control"


def TestEscenarioSolicitudConCardinalidad1aN():
    """Escenario: Solicitud con cardinalidad 1 a N.

    WHEN se crea una solicitud con un principal, uno o más privilegios y varios objetos
    THEN el sistema la acepta como solicitud por lote, lista para su normalización en ítems atómicos 1 a 1.
    """
    from control_accesos.dominio.modelos import SolicitudLoteGrant

    principal = Principal(identificador="usuario_demo", tipo=TipoPrincipal.USUARIO)
    privilegios = ["SELECT"]
    objetos = [
        ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA),
        ObjetoSecurable(identificador="tabla2", tipo=TipoObjeto.TABLA_DELTA),
    ]
    lote = SolicitudLoteGrant(
        principales=[principal], privilegios=privilegios, objetos=objetos
    )
    items = lote.NormalizarAItems()
    assert len(items) == 2


def TestEscenarioSolicitudConCardinalidadNa1():
    """Escenario: Solicitud con cardinalidad N a 1.

    WHEN se crea una solicitud con varios principals, uno o más privilegios y un objeto
    THEN el sistema la acepta como solicitud por lote, lista para su normalización en ítems atómicos 1 a 1.
    """
    from control_accesos.dominio.modelos import SolicitudLoteGrant

    principales = [
        Principal(identificador="usuario1_demo", tipo=TipoPrincipal.USUARIO),
        Principal(identificador="usuario2_demo", tipo=TipoPrincipal.USUARIO),
    ]
    privilegios = ["SELECT"]
    objeto = ObjetoSecurable(identificador="tabla1", tipo=TipoObjeto.TABLA_DELTA)
    lote = SolicitudLoteGrant(
        principales=principales, privilegios=privilegios, objetos=[objeto]
    )
    items = lote.NormalizarAItems()
    assert len(items) == 2
