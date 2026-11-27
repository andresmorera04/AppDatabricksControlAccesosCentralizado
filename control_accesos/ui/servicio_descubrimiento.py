"""Servicio de descubrimiento de opciones de la UI (design.md D6, tareas 3.1-3.4).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`.

Capa de aplicación entre los descubrimientos reales y la vista. Traduce a los
modelos del dominio:

- **principals** (SCIM con el service principal, contexto broker, porque el
  token OBO carece de los scopes SCIM) -> `Principal`;
- **objetos de Unity Catalog** (catálogos, esquemas y tablas, con la credencial
  OBO del llamante, porque `catalog.*` sí está disponible) -> `ObjetoSecurable`.

Preserva el App Id de los service principals como identificador, el nombre
calificado de los objetos UC, el orden, el límite y la distinción entre fallo y
lista vacía que ya aportan los adaptadores. Un fallo de listado se traduce a
`ErrorDescubrimientoOpciones` (error de catálogo de opciones): la vista lo
distingue de una lista auténticamente vacía y no habilita ejecución sobre datos
incompletos (spec `grant-management-ui`). El servicio NO valida autoridad (eso
lo hace la disponibilidad, design.md D7).
"""

from control_accesos.canales.reales.descubrimiento_control import (
    ErrorListadoControl,
)
from control_accesos.canales.reales.descubrimiento_principales import (
    ErrorListadoPrincipales,
)
from control_accesos.canales.reales.descubrimiento_uc import ErrorListadoUc
from control_accesos.dominio.modelos import ObjetoSecurable, Principal

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_DESCUBRIMIENTO_UI = "ui.servicio_descubrimiento"


class ErrorDescubrimientoOpciones(RuntimeError):
    """Fallo del descubrimiento de opciones, distinguible de una lista vacía.

    Representa "no pude listar", nunca "no hay opciones".
    """


class ServicioDescubrimientoUi:
    """Traduce las opciones descubiertas a los modelos del dominio.

    Colaboradores inyectados por acción: el descubridor de principals (SCIM-SP
    del contexto broker) y el descubridor UC (OBO del llamante). Cada método
    exige su colaborador y falla de forma explícita si no está dispuesto.

    Attributes:
        descubridor_principales: adaptador SCIM-SP (`DescubridorPrincipales`).
        descubridor_uc: adaptador UC OBO (`DescubridorUc`).
    """

    def __init__(
        self,
        descubridor_principales=None,
        descubridor_uc=None,
        descubridor_control=None,
    ):
        """Inicializa el servicio con los descubridores inyectados.

        Args:
            descubridor_principales (DescubridorPrincipales | None): adaptador
                SCIM-SP; obligatorio para los métodos de principals.
            descubridor_uc (DescubridorUc | None): adaptador UC OBO; obligatorio
                para los métodos de objetos de Unity Catalog.
            descubridor_control (DescubridorControl | None): adaptador del plano
                de control (SP + OBO); obligatorio para clusters, serverless,
                warehouses, apps y USO_TOKEN.
        """
        self._descubridor_principales = descubridor_principales
        self._descubridor_uc = descubridor_uc
        self._descubridor_control = descubridor_control

    # ------------------------------------------------------------------ #
    # Principals (SCIM con el service principal, contexto broker).
    # ------------------------------------------------------------------ #

    def DescubrirUsuarios(self):
        """Lista los usuarios del workspace como `Principal` del dominio."""
        return self._TraducirPrincipales(
            self._DescubridorPrincipales().ListarUsuarios
        )

    def DescubrirGrupos(self):
        """Lista los grupos del workspace como `Principal` del dominio."""
        return self._TraducirPrincipales(
            self._DescubridorPrincipales().ListarGrupos
        )

    def DescubrirServicePrincipals(self):
        """Lista los service principals (App Id preservado como identificador)."""
        return self._TraducirPrincipales(
            self._DescubridorPrincipales().ListarServicePrincipals
        )

    def DescubrirPrincipales(self):
        """Lista los tres tipos de principal en un solo agregado estable."""
        return self._TraducirPrincipales(
            self._DescubridorPrincipales().ListarPrincipales
        )

    # ------------------------------------------------------------------ #
    # Unity Catalog (con la credencial OBO del llamante).
    # ------------------------------------------------------------------ #

    def DescubrirCatalogos(self):
        """Lista los catálogos como `ObjetoSecurable` (nombre calificado)."""
        return self._TraducirUc(self._DescubridorUc().ListarCatalogos)

    def DescubrirEsquemas(self, catalogo):
        """Lista los esquemas de un catálogo (`catalogo.esquema`).

        Args:
            catalogo (str): catálogo que acota el listado.

        Returns:
            tuple[ObjetoSecurable, ...]: esquemas.
        """
        return self._TraducirUc(self._DescubridorUc().ListarEsquemas, catalogo)

    def DescubrirTablas(self, catalogo, esquema):
        """Lista las tablas tabulares de un par (`catalogo.esquema.tabla`).

        Args:
            catalogo (str): catálogo.
            esquema (str): esquema.

        Returns:
            tuple[ObjetoSecurable, ...]: tablas clasificadas por metadatos.
        """
        return self._TraducirUc(
            self._DescubridorUc().ListarTablas, catalogo, esquema
        )

    def DescubrirVolumenes(self, catalogo, esquema):
        """Lista los volúmenes de un par (`catalogo.esquema.volumen`)."""
        return self._TraducirUc(
            self._DescubridorUc().ListarVolumenes, catalogo, esquema
        )

    def DescubrirModelosMl(self, catalogo, esquema):
        """Lista los modelos ML de un par (`catalogo.esquema.modelo`)."""
        return self._TraducirUc(
            self._DescubridorUc().ListarModelosMl, catalogo, esquema
        )

    def DescubrirExternalLocations(self):
        """Lista las external locations (`ObjetoSecurable` de una parte)."""
        return self._TraducirUc(self._DescubridorUc().ListarExternalLocations)

    def DescubrirConexiones(self):
        """Lista las connections (`ObjetoSecurable` de una parte)."""
        return self._TraducirUc(self._DescubridorUc().ListarConexiones)

    # ------------------------------------------------------------------ #
    # Plano de control (clusters/serverless con SP; warehouses/apps con OBO).
    # ------------------------------------------------------------------ #

    def DescubrirClusters(self):
        """Lista los clusters all-purpose con el SP (`ObjetoSecurable`)."""
        return self._TraducirControl(self._DescubridorControl().ListarClusters)

    def DescubrirServerless(self):
        """Lista los serverless compute objects con el SP."""
        return self._TraducirControl(self._DescubridorControl().ListarServerless)

    def DescubrirWarehouses(self):
        """Lista los SQL warehouses con OBO."""
        return self._TraducirControl(self._DescubridorControl().ListarWarehouses)

    def DescubrirApps(self):
        """Lista las Databricks Apps con OBO."""
        return self._TraducirControl(self._DescubridorControl().ListarApps)

    def DescubrirUsoTokens(self):
        """Devuelve el singleton USO_TOKEN (identificador lógico configurado)."""
        return self._TraducirControl(self._DescubridorControl().ListarUsoTokens)

    # ------------------------------------------------------------------ #
    # Internos.
    # ------------------------------------------------------------------ #

    def _DescubridorPrincipales(self):
        """Devuelve el descubridor de principals o falla de forma explícita."""
        if self._descubridor_principales is None:
            raise ValueError(
                "No hay un descubridor de principals (service principal) "
                "dispuesto para esta acción."
            )
        return self._descubridor_principales

    def _DescubridorUc(self):
        """Devuelve el descubridor UC o falla de forma explícita."""
        if self._descubridor_uc is None:
            raise ValueError(
                "No hay un descubridor de Unity Catalog (OBO) dispuesto para "
                "esta acción."
            )
        return self._descubridor_uc

    def _DescubridorControl(self):
        """Devuelve el descubridor de control o falla de forma explícita."""
        if self._descubridor_control is None:
            raise ValueError(
                "No hay un descubridor del plano de control (SP + OBO) "
                "dispuesto para esta acción."
            )
        return self._descubridor_control

    def _TraducirPrincipales(self, operacion):
        """Ejecuta un listado de principals y traduce, tipificando el fallo.

        Raises:
            ErrorDescubrimientoOpciones: si el listado falla (no si está vacío).
        """
        try:
            descubiertos = operacion()
        except ErrorListadoPrincipales as excepcion:
            raise ErrorDescubrimientoOpciones(
                f"[{MODULO_DESCUBRIMIENTO_UI}] No se pudieron descubrir los "
                f"principals del workspace: {excepcion}"
            ) from excepcion

        return tuple(
            Principal(identificador=principal.identificador, tipo=principal.tipo)
            for principal in descubiertos
        )

    def _TraducirUc(self, operacion, *argumentos):
        """Ejecuta un listado UC y traduce a `ObjetoSecurable`.

        Raises:
            ErrorDescubrimientoOpciones: si el listado falla (no si está vacío).
        """
        try:
            descubiertos = operacion(*argumentos)
        except ErrorListadoUc as excepcion:
            raise ErrorDescubrimientoOpciones(
                f"[{MODULO_DESCUBRIMIENTO_UI}] No se pudieron descubrir los "
                f"objetos de Unity Catalog: {excepcion}"
            ) from excepcion

        return tuple(
            ObjetoSecurable(identificador=objeto.identificador, tipo=objeto.tipo)
            for objeto in descubiertos
        )

    def _TraducirControl(self, operacion):
        """Ejecuta un listado del plano de control y traduce.

        Raises:
            ErrorDescubrimientoOpciones: si el listado falla (no si está vacío).
        """
        try:
            descubiertos = operacion()
        except ErrorListadoControl as excepcion:
            raise ErrorDescubrimientoOpciones(
                f"[{MODULO_DESCUBRIMIENTO_UI}] No se pudieron descubrir los "
                f"objetos del plano de control: {excepcion}"
            ) from excepcion

        return tuple(
            ObjetoSecurable(identificador=objeto.identificador, tipo=objeto.tipo)
            for objeto in descubiertos
        )
