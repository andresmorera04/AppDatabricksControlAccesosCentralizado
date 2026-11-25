"""Pruebas unitarias del modelo de lote (SolicitudLoteGrant).

Trazabilidad:
- spec `batch-grant-operations` - "Normalización de lotes a ítems atómicos"
- spec `batch-grant-operations` - "Validación de la solicitud por lote"
- spec `grant-domain-model` (MODIFIED) - cardinalidades 1 a N, N a 1, N a M

Convención del proyecto (README.md): clases, funciones y métodos en PascalCase
(pytest.ini registra `python_functions = Test*`); errores del dominio como
`ErrorDominio` con mensaje explícito en español.
"""

import pytest

from control_accesos.dominio.enumeraciones import TipoObjeto
from control_accesos.dominio.errores import ErrorDominio
from control_accesos.dominio.modelos import (
    ItemGrant,
    ObjetoSecurable,
    Principal,
    SolicitudGrant,
    SolicitudLoteGrant,
)


class TestNormalizacionLotes:
    """Verifica que SolicitudLoteGrant normaliza correctamente a ítems atómicos."""

    def TestLote1aNnormalizadoPorObjetoYPrivilegio(self):
        """Scenario: Lote 1 a N normalizado por objeto y privilegio.

        WHEN se normaliza un lote 1 a N con un principal, dos privilegios y
        tres objetos THEN produce seis ítems atómicos recorriendo los objetos
        en su orden de entrada y, dentro de cada uno, los privilegios en su
        orden de entrada.
        """
        principal = Principal(identificador="user@example.com", tipo="usuario")
        privilegios = ["SELECT", "INSERT"]
        objetos = [
            ObjetoSecurable(
                identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
            ),
            ObjetoSecurable(
                identificador="catalogo1.schema1.tabla2", tipo=TipoObjeto.TABLA_DELTA
            ),
            ObjetoSecurable(
                identificador="catalogo1.schema1.tabla3", tipo=TipoObjeto.TABLA_DELTA
            ),
        ]

        lote = SolicitudLoteGrant(
            principales=[principal], privilegios=privilegios, objetos=objetos
        )
        items = lote.NormalizarAItems()

        assert len(items) == 6
        esperado = [
            ItemGrant(principal=principal, privilegio="SELECT", objeto=objetos[0]),
            ItemGrant(principal=principal, privilegio="INSERT", objeto=objetos[0]),
            ItemGrant(principal=principal, privilegio="SELECT", objeto=objetos[1]),
            ItemGrant(principal=principal, privilegio="INSERT", objeto=objetos[1]),
            ItemGrant(principal=principal, privilegio="SELECT", objeto=objetos[2]),
            ItemGrant(principal=principal, privilegio="INSERT", objeto=objetos[2]),
        ]
        assert items == esperado

    def TestLoteNa1NormalizadoPorPrincipalYPrivilegio(self):
        """Scenario: Lote N a 1 normalizado por principal y privilegio.

        WHEN se normaliza un lote N a 1 con tres principals, dos privilegios y
        un objeto THEN produce seis ítems atómicos recorriendo los principals
        en su orden de entrada y, dentro de cada uno, los privilegios en su
        orden de entrada.
        """
        principales = [
            Principal(identificador="user1@example.com", tipo="usuario"),
            Principal(identificador="user2@example.com", tipo="usuario"),
            Principal(identificador="user3@example.com", tipo="usuario"),
        ]
        privilegios = ["SELECT", "INSERT"]
        objeto = ObjetoSecurable(
            identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
        )

        lote = SolicitudLoteGrant(
            principales=principales, privilegios=privilegios, objetos=[objeto]
        )
        items = lote.NormalizarAItems()

        assert len(items) == 6
        esperado = [
            ItemGrant(principal=principales[0], privilegio="SELECT", objeto=objeto),
            ItemGrant(principal=principales[0], privilegio="INSERT", objeto=objeto),
            ItemGrant(principal=principales[1], privilegio="SELECT", objeto=objeto),
            ItemGrant(principal=principales[1], privilegio="INSERT", objeto=objeto),
            ItemGrant(principal=principales[2], privilegio="SELECT", objeto=objeto),
            ItemGrant(principal=principales[2], privilegio="INSERT", objeto=objeto),
        ]
        assert items == esperado

    def TestLoteDegeneradoEquivalenteASolicitud1a1(self):
        """Scenario: Lote degenerado equivalente a una solicitud 1 a 1.

        WHEN se normaliza un lote con un solo principal y un solo objeto THEN
        produce los mismos ítems atómicos que la solicitud 1 a 1 equivalente.
        """
        principal = Principal(identificador="user@example.com", tipo="usuario")
        privilegios = ["SELECT"]
        objeto = ObjetoSecurable(
            identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
        )

        lote = SolicitudLoteGrant(
            principales=[principal], privilegios=privilegios, objetos=[objeto]
        )
        items_lote = lote.NormalizarAItems()

        solicitud_1a1 = SolicitudGrant.Crear(
            principal=principal, privilegios=privilegios, objeto=objeto
        )
        items_1a1 = [
            ItemGrant(
                principal=solicitud_1a1.principal,
                privilegio=privilegio,
                objeto=solicitud_1a1.objeto,
            )
            for privilegio in solicitud_1a1.privilegios
        ]

        assert items_lote == items_1a1


class TestValidacionLote:
    """Verifica que SolicitudLoteGrant valida la solicitud por lote."""

    def TestLoteSinPrincipalesRechazado(self):
        """Scenario: Lote sin principals.

        WHEN llega una solicitud por lote cuya lista de principals está vacía
        THEN el sistema la rechaza con un error explícito que indica que falta
        al menos un principal, sin generar ítems ni ejecutar fase alguna.
        """
        objeto = ObjetoSecurable(
            identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
        )
        with pytest.raises(ErrorDominio) as excinfo:
            SolicitudLoteGrant(
                principales=[], privilegios=["SELECT"], objetos=[objeto]
            )
        assert "principal" in str(excinfo.value).lower()

    def TestLoteSinObjetosRechazado(self):
        """Scenario: Lote sin objetos.

        WHEN llega una solicitud por lote cuya lista de objetos está vacía
        THEN el sistema la rechaza con un error explícito que indica que falta
        al menos un objeto.
        """
        principal = Principal(identificador="user@example.com", tipo="usuario")
        with pytest.raises(ErrorDominio) as excinfo:
            SolicitudLoteGrant(
                principales=[principal], privilegios=["SELECT"], objetos=[]
            )
        assert "objeto" in str(excinfo.value).lower()

    def TestLoteSinPrivilegiosRechazado(self):
        """Scenario: Lote sin privilegios.

        WHEN llega una solicitud por lote cuya lista de privilegios está vacía
        THEN el sistema la rechaza con un error explícito que indica que falta
        al menos un privilegio.
        """
        objeto = ObjetoSecurable(
            identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
        )
        principal = Principal(identificador="user@example.com", tipo="usuario")
        with pytest.raises(ErrorDominio) as excinfo:
            SolicitudLoteGrant(
                principales=[principal], privilegios=[], objetos=[objeto]
            )
        assert "privilegio" in str(excinfo.value).lower()


class TestRechazoNaM:
    """Verifica que SolicitudLoteGrant rechaza la cardinalidad N a M."""

    def TestSolicitudNaMRechazada(self):
        """Scenario: Solicitud N a M rechazada con mensaje de alcance.

        WHEN llega a la entrada por lote una solicitud con dos principals y dos
        objetos THEN el sistema la rechaza con un mensaje explícito que declara
        la cardinalidad N a M fuera de alcance y no se genera ningún ítem.
        """
        principales = [
            Principal(identificador="user1@example.com", tipo="usuario"),
            Principal(identificador="user2@example.com", tipo="usuario"),
        ]
        objetos = [
            ObjetoSecurable(
                identificador="catalogo1.schema1.tabla1", tipo=TipoObjeto.TABLA_DELTA
            ),
            ObjetoSecurable(
                identificador="catalogo1.schema1.tabla2", tipo=TipoObjeto.TABLA_DELTA
            ),
        ]
        with pytest.raises(ErrorDominio) as excinfo:
            SolicitudLoteGrant(
                principales=principales,
                privilegios=["SELECT"],
                objetos=objetos,
            )
        mensaje = str(excinfo.value)
        assert "N a M" in mensaje and "fuera de alcance" in mensaje
