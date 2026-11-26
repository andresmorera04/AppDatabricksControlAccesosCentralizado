# Spec Delta

## MODIFIED Requirements

### Requirement: Identidad del llamante y trazabilidad de cada cambio

La autorización SHALL evaluarse siempre con la identidad del llamante y cada cambio SHALL registrarse en la bitácora de eventos con su usuario y desglose por ítem; los fallos SHALL registrarse en la bitácora de errores. La ejecución SHALL usar la credencial del llamante en CLI/lote; en la Databricks App en modo broker (`app-broker-grants`) SHALL poder usar la identidad de la App solo tras validar la autoridad del llamante en la misma acción.

#### Scenario: Evento con el usuario del llamante

- **WHEN** un llamante con identidad resuelta procesa una solicitud del scope de este change
- **THEN** el evento queda registrado en la bitácora de eventos con el usuario del llamante y el resultado por ítem

#### Scenario: Ejecución broker autorizada sobre ACLs y tokens

- **WHEN** la App opera en modo broker y el llamante tiene validada su autoridad sobre la Databricks App o sobre los tokens
- **THEN** la operación se ejecuta con la identidad de la App y el evento registra el usuario OBO del llamante

#### Scenario: Fallo de ejecución registrado

- **WHEN** una operación del canal falla al ejecutarse contra el workspace
- **THEN** el fallo queda registrado en la bitácora de errores con el detalle del error y el contexto de la operación

#### Scenario: La auditoría no introduce fallos en cascada

- **WHEN** el registro en la bitácora de errores falla mientras se reporta un fallo de ejecución
- **THEN** el ítem conserva su resultado por ítem traducido y el pipeline no recibe excepción alguna del registro

### Requirement: Credenciales y destino inyectados, sin valores embebidos

El canal SHALL recibir por inyección el acceso al workspace (cliente o transporte y credencial de ejecución), sin valores de conexión, identificadores ni niveles de permiso embebidos en el código. La credencial de ejecución SHALL ser la del llamante en la ruta CLI/lote y la de la App en el modo broker, siempre con la autorización del llamante validada previamente. Con un transporte simulado el canal SHALL poder ejercitarse por completo sin conexión externa.

#### Scenario: Canal ejercitado sin workspace alguno

- **WHEN** el canal se construye con un transporte simulado
- **THEN** el otorgamiento, la revocación y la lectura de la ACL se procesan y reportan sin ninguna conexión externa

#### Scenario: Operación enviada al transporte inyectado

- **WHEN** el canal ejecuta el otorgamiento de un ítem
- **THEN** la operación se envía al transporte inyectado con el recurso, el identificador del objeto y el nivel derivados del ítem (con identificador vacío para uso de tokens)
