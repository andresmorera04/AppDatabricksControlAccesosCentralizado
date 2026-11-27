"""Transporte de permisos mixto para la ejecución del plano de control (design.md D10).

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 6.4.

El modelo broker verificado distingue dos transportes por recurso de la
Permissions API:

- `apps` (Databricks Apps): la ACL se lee/escribe con la **credencial OBO** del
  llamante (scope `apps`, verificado GO);
- el resto del plano de control (`clusters`, `serverless-compute`,
  `sql/warehouses`, `authorization/tokens`): se lee/escribe con la **identidad
  del service principal** de la App (superficie solo broker).

Este transporte compone ambos y despacha por `recurso`, de modo que el canal
`CanalControlComputo` (que ya compone la ACL por lectura-modificación-escritura)
use la identidad correcta en cada operación sin duplicar lógica.
"""

# Recurso cuyo transporte de ejecución es el OBO del llamante (design.md D10).
RECURSO_APPS = "apps"
class TransportePermisosMixto:
    """Despacha LeerAcl/EscribirAcl entre OBO (apps) y SP (resto del control).

    Attributes:
        transporte_apps_obo (ClientePermisosSdk): transporte OBO para `apps`.
        transporte_control_sp (ClientePermisosSdk): transporte SP para el resto.
    """

    def __init__(self, transporte_apps_obo, transporte_control_sp):
        """Inicializa el transporte mixto con sus dos transportes.

        Args:
            transporte_apps_obo: transporte OBO (apps).
            transporte_control_sp: transporte SP (cómputo, warehouses, tokens).

        Raises:
            ValueError: si falta alguno de los transportes.
        """
        if transporte_apps_obo is None or transporte_control_sp is None:
            raise ValueError(
                "El transporte mixto requiere un transporte OBO (apps) y un "
                "transporte SP (resto del plano de control)."
            )
        self._transporte_apps_obo = transporte_apps_obo
        self._transporte_control_sp = transporte_control_sp

    def LeerAcl(self, recurso, identificador):
        """Lee la ACL del recurso con el transporte que le corresponde."""
        return self._ParaRecurso(recurso).LeerAcl(recurso, identificador)

    def EscribirAcl(self, recurso, identificador, entradas):
        """Escribe la ACL del recurso con el transporte que le corresponde."""
        return self._ParaRecurso(recurso).EscribirAcl(
            recurso, identificador, entradas
        )

    def _ParaRecurso(self, recurso):
        """Elige el transporte según el recurso (apps -> OBO, resto -> SP)."""
        if recurso == RECURSO_APPS:
            return self._transporte_apps_obo
        return self._transporte_control_sp
