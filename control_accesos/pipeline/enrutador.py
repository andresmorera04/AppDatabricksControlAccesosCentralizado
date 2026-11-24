"""Enrutador de canales por plano (capability `grant-pipeline`).

Componente compartido por las fases que interactúan con los canales
(`Ejecutor` y `Verificador`): decide qué canal corresponde a cada ítem según
el plano de su objeto, usando un mapa declarativo `Plano -> canal` (sin
cadenas de if dispersas, design.md D2/D5).

Extraer el enrutamiento a su propia clase evita duplicarlo entre fases y
garantiza que la ejecución y la verificación de un mismo ítem usen siempre el
mismo canal.
"""

from control_accesos.canales.contratos import Canal
from control_accesos.dominio.enumeraciones import Plano
from control_accesos.dominio.errores import ErrorDominio


class EnrutadorCanales:
    """Selecciona el canal de ejecución correspondiente al plano de un ítem."""

    def __init__(self, canal_datos, canal_control):
        """Inicializa el enrutador con los canales de cada plano.

        Args:
            canal_datos (Canal): canal del plano de datos (SQL GRANT/REVOKE y
                SHOW GRANTS).
            canal_control (Canal): canal del plano de control (Permissions API
                / Token Permissions API y lectura de ACLs).

        Raises:
            ErrorDominio: si alguno de los canales recibidos no implementa el
                contrato unificado `Canal`.
        """
        self._ValidarCanal(canal_datos, "canal_datos")
        self._ValidarCanal(canal_control, "canal_control")

        # Mapa declarativo de enrutamiento: el plano del objeto decide el canal.
        self._canales_por_plano = {
            Plano.DATOS: canal_datos,
            Plano.CONTROL: canal_control,
        }

    def CanalParaItem(self, item):
        """Devuelve el canal que corresponde al plano del objeto del ítem.

        Args:
            item (ItemGrant): ítem a enrutar.

        Returns:
            Canal: canal del plano del objeto (datos o control).

        Raises:
            ErrorDominio: si el plano del objeto no tiene canal configurado.
        """
        return self.CanalParaObjeto(item.objeto)

    def CanalParaObjeto(self, objeto):
        """Devuelve el canal que corresponde al plano de un objeto.

        Existe para los consumidores que operan sobre el objeto sin tener un
        ítem completo: la resolución de privilegios efectivos del llamante
        (`caller-privilege-resolution`) consulta los otorgamientos vigentes del
        objetivo antes de que exista ítem clasificado alguno. Reutiliza el
        mismo mapa declarativo `Plano -> canal` que la ejecución y la
        verificación, de modo que nunca se bifurca el criterio de selección
        (spec `grant-pipeline` - "Selección de canal por plano del objeto").

        Args:
            objeto (ObjetoSecurable): objeto cuyo plano decide el canal.

        Returns:
            Canal: canal del plano del objeto (datos o control).

        Raises:
            ErrorDominio: si el objeto no es un `ObjetoSecurable` o si su
                plano no tiene canal configurado.
        """
        plano = getattr(objeto, "plano", None)
        if plano is None:
            raise ErrorDominio(
                "El enrutamiento por plano requiere un ObjetoSecurable; se "
                f"recibió {type(objeto).__name__}."
            )

        canal = self._canales_por_plano.get(plano)
        if canal is None:
            raise ErrorDominio(
                f"El plano {plano.value} del objeto "
                f"'{objeto.identificador}' no tiene canal de ejecución "
                "configurado."
            )
        return canal

    def _ValidarCanal(self, canal, nombre):
        """Valida que el canal recibido implemente el contrato unificado.

        Args:
            canal (Canal): canal recibido por el constructor.
            nombre (str): nombre del parámetro, para el mensaje de error.

        Raises:
            ErrorDominio: si el canal no es una instancia de `Canal`.
        """
        if not isinstance(canal, Canal):
            raise ErrorDominio(
                f"El {nombre} debe implementar el contrato Canal; "
                f"se recibió {type(canal).__name__}."
            )
