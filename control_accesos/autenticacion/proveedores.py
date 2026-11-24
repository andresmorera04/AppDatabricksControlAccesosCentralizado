"""Puerto del proveedor del contexto on-behalf-of del llamante.

La Databricks App obtiene la identidad del usuario que la invoca del contexto
OAuth on-behalf-of que la plataforma le entrega (README.md, decisión D2). Ese
mecanismo pertenece al entorno de ejecución de la app, no al dominio, así que
se aísla detrás de este contrato abstracto (design.md D1):

- **Producción**: el proveedor lee el contexto real de la Databricks App y lo
  traduce a un `ContextoLlamante`. El patrón de llamadas es el mismo que la
  app usará con el token del usuario (identidad propia y grupos).
- **Pruebas**: `simulados.ProveedorIdentidadSimulado` reproduce los casos del
  spec sin conexión externa.

Gracias a este puerto, el resto de la aplicación (resolución de privilegios,
split de pre-flight y bitácora) trabaja siempre con `IdentidadLlamante` y no
depende del runtime de la app.
"""

from abc import ABC, abstractmethod

from control_accesos.autenticacion.modelos import ContextoLlamante


class ProveedorIdentidadLlamante(ABC):
    """Contrato del origen del contexto on-behalf-of del llamante."""

    @abstractmethod
    def ObtenerContexto(self):
        """Obtiene el dictado del contexto on-behalf-of de la invocación.

        Returns:
            ContextoLlamante | None: el contexto reportado por la plataforma,
                o None cuando la invocación no trae contexto de usuario
                verificable (escenario 'Contexto de llamante ausente').

        Raises:
            ErrorContextoLlamanteAusente: cuando el proveedor puede afirmar
                que no hay contexto de usuario.
            ErrorAutenticacionLlamante: cuando el contexto existe pero no
                puede verificarse (token inválido o expirado).
            Exception: cualquier otro fallo del entorno (servicio de
                identidad no disponible, error de transporte). El servicio los
                captura y degrada de forma controlada.
        """
