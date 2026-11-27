"""Estado de sesión de la UI: huella, previsualización y confirmación única.

Change C9 (`web-ui-minimalista`), capability `grant-management-ui`, tarea 4.3.

Implementa las invariantes de estado del design.md D9, sin depender de
Streamlit ni del token del llamante:

- la **huella canónica** de una solicitud es independiente del orden de
  selección: se ordenan principals, objetos y privilegios antes de firmarla;
- la previsualización se asocia a la huella y a la **identidad** del llamante
  (no al token); cualquier cambio de formulario o de identidad la invalida;
- la **confirmación es de un solo uso**: se consume antes de iniciar la
  ejecución, de modo que un rerender, doble clic o repetición del evento no
  vuelve a ejecutar; requiere al menos un ítem ejecutable.

Este objeto vive durante una única acción y NO guarda tokens, clientes,
sesiones ni credenciales: solo selecciones y la `ClasificacionPreFlight`.
"""

from control_accesos.dominio.modelos import NormalizarPrivilegio

# Identificador del módulo para trazas y mensajes (convención del proyecto).
MODULO_ESTADO_SESION = "ui.estado_sesion"


class EstadoSesionGrantsUi:
    """Guarda la previsualización vigente y consume la confirmación única.

    Estado efímero del controlador (por acción): inicia vacío y se alimenta con
    `GuardarPrevisualizacion`. La vigencia se resuelve comparando huella e
    identidad; la confirmación consume el estado una sola vez.
    """

    def __init__(self):
        """Inicializa el estado vacío (sin previsualización ni confirmación)."""
        self._huella = None
        self._identidad = None
        self._clasificacion = None
        self._consumida = False

    @staticmethod
    def Huella(principales, objetos, privilegios):
        """Firma canónica de una solicitud, independiente del orden.

        Args:
            principales (Iterable[Principal]): principals de la selección.
            objetos (Iterable[ObjetoSecurable]): objetos de la selección.
            privilegios (Iterable[str]): privilegios seleccionados.

        Returns:
            str: huella estable ante reordenamientos (mismo contenido, misma
                firma; contenido distinto, firma distinta).
        """
        lista_principales = [
            f"{p.tipo.value}:{p.identificador}" for p in principales
        ]
        lista_objetos = [
            f"{o.tipo.value}:{o.identificador}" for o in objetos
        ]
        lista_privilegios = [
            NormalizarPrivilegio(privilegio) for privilegio in privilegios
        ]

        return "|".join(
            [
                ";" .join(sorted(lista_principales)),
                ";".join(sorted(lista_objetos)),
                ";".join(sorted(lista_privilegios)),
            ]
        )

    def GuardarPrevisualizacion(self, huella, identidad, clasificacion):
        """Asocia la huella e identidad a la previsualización del dominio.

        Args:
            huella (str): huella canónica de la solicitud.
            identidad (str): identificador del llamante que la obtuvo.
            clasificacion (ClasificacionPreFlight): resultado del pre-flight.
        """
        self._huella = huella
        self._identidad = identidad
        self._clasificacion = clasificacion
        self._consumida = False

    def PrevisualizacionVigente(self, huella, identidad):
        """Devuelve la previsualización vigente para huella e identidad.

        Args:
            huella (str): huella a contrastar.
            identidad (str): identificador del llamante actual.

        Returns:
            ClasificacionPreFlight | None: la previsualización si la huella y
                la identidad coinciden y aún no se consumió; None en otro caso.
        """
        if (
            self._huella == huella
            and self._identidad == identidad
            and self._clasificacion is not None
            and not self._consumida
        ):
            return self._clasificacion
        return None

    def Confirmar(self, huella, identidad):
        """Consume la confirmación si hay una ejecutable vigente y sin consumir.

        Args:
            huella (str): huella de la solicitud a ejecutar.
            identidad (str): identificador del llamante.

        Returns:
            bool: True exactamente una vez (a la primera confirmación válida);
                False si no hay previsualización vigente, no tiene ítems
                ejecutables o la confirmación ya fue consumida.
        """
        clasificacion = self._PrevisualizacionConfirmable(huella, identidad)
        if clasificacion is None:
            return False
        self._consumida = True
        return True

    def _PrevisualizacionConfirmable(self, huella, identidad):
        """Devuelve la previsualización ejecutable y vigente, o None."""
        if (
            self._huella != huella
            or self._identidad != identidad
            or self._consumida
            or self._clasificacion is None
        ):
            return None
        # Sin ítems ejecutables no hay nada que confirmar (design.md D9).
        if not self._clasificacion.items_ejecutables:
            return None
        return self._clasificacion
