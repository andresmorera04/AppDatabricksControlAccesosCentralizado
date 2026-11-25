"""Contrato de datos del puerto de permisos del plano de control (capability
`compute-grants`).

Define `EntradaAcl`, la unidad de intercambio entre el canal `CanalControlComputo`
y su transporte inyectado, en un módulo libre de toda biblioteca externa: así el
canal y sus pruebas unitarias no cargan el SDK ni biblioteca de conexión alguna,
cumpliendo la regla del proyecto de que la superficie de dominio y los canales
simulados permanezcan desacoplados de los mecanismos concretos de transporte.
"""

from dataclasses import dataclass

from control_accesos.dominio.modelos import Principal


@dataclass(frozen=True)
class EntradaAcl:
    """Una entrada directa de la ACL del objeto: un principal y su nivel.

    Es el contrato de datos que el canal y el transporte intercambian: la
    lectura devuelve una `EntradaAcl` por nivel directo de cada otorgatario, y
    la escritura recibe la lista completa a aplicar. No expone tipos del SDK.

    Attributes:
        principal (Principal): otorgatario de la entrada.
        nivel (str): nivel de permiso directo en forma `CAN_*` (por ejemplo
            `CAN_USE`, `CAN_MANAGE`), tal como lo reporta el workspace.
    """

    principal: Principal
    nivel: str
