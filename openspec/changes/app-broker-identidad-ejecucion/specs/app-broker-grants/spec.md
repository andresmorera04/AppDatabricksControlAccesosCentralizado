# Spec Delta

## Purpose

Permite que la Databricks App cubra toda la gestión de accesos del proyecto separando la autorización (siempre evaluada con la identidad y privilegios efectivos del llamante) de la ejecución (identidad del service principal de la App solo donde el token OBO no tiene scopes suficientes), sin convertir la App en una vía de elevación no autorizada.

## ADDED Requirements

### Requirement: Autorización por llamante previa a toda ejecución elevada

En modo broker, toda operación ejecutada con la identidad de la App SHALL estar precedida, en la misma acción, de una validación de que el llamante posee el privilegio efectivo requerido sobre el objeto; sin esa validación la operación SHALL NO ejecutarse, aunque el service principal sea capaz de realizarla.

#### Scenario: Escritura autorizada por el llamante

- **WHEN** el llamante tiene el privilegio efectivo requerido sobre el objeto y confirma la operación
- **THEN** la operación se ejecuta con la identidad de la App y su resultado se verifica

#### Scenario: Escritura sin autoridad del llamante

- **WHEN** el llamante carece del privilegio efectivo requerido sobre el objeto
- **THEN** la operación queda bloqueada con su motivo, no se ejecuta con la identidad de la App y queda registrada como bloqueada en el reporte

#### Scenario: Revalidación al confirmar

- **WHEN** los privilegios del llamante cambian entre la previsualización y la confirmación
- **THEN** la ejecución repite la validación y bloquea los ítems que ya no estén autorizados

### Requirement: Cobertura del plano de control con identidad de App

En modo broker, el sistema SHALL listar principals (usuarios, grupos y service principals) y leer y escribir ACLs de SQL warehouses, clusters, serverless compute objects, Databricks Apps y tokens con la identidad de la App, sin depender de scopes OBO que la plataforma no otorga.

#### Scenario: Descubrimiento de principals con la App

- **WHEN** la interfaz necesita opciones de usuarios, grupos o service principals
- **THEN** los listados se obtienen con la identidad de la App y se presentan como opciones seleccionables

#### Scenario: ACL de warehouse con la App

- **WHEN** se gestiona CAN_USE sobre un SQL warehouse
- **THEN** la lectura y la escritura de la ACL usan la identidad de la App, previa autorización del llamante

#### Scenario: ACL de tokens con la App

- **WHEN** se gestiona CAN_USE sobre los tokens del workspace
- **THEN** la operación usa la identidad de la App, previa autorización del llamante, con workspace admin cuando la plataforma lo exija

### Requirement: Preservación de OBO donde es viable

El sistema SHALL mantener la ejecución con la credencial OBO del llamante para los grants UC vía SQL y para las ACL de Databricks Apps cuando el scope `apps` lo permita, limitando la ejecución elevada a las superficies donde OBO es inviable.

#### Scenario: Grants UC con credencial OBO

- **WHEN** se otorgan privilegios sobre objetos de Unity Catalog
- **THEN** la sentencia SQL se ejecuta con la credencial OBO del llamante mediante la API de ejecución de sentencias, no con la identidad de la App

#### Scenario: ACL de Apps con credencial OBO

- **WHEN** el scope `apps` permite la operación sobre una Databricks App
- **THEN** la ACL se gestiona con la credencial OBO del llamante, sin elevar a la identidad de la App

### Requirement: Privilegios mínimos del service principal de la App

El service principal de la App SHALL recibir los privilegios mínimos necesarios por superficie, documentados como recurso de despliegue; el uso de workspace admin SHALL justificarse y limitarse a lo que la plataforma exija.

#### Scenario: Asignación de privilegios documentada

- **WHEN** se despliega el modo broker
- **THEN** los privilegios del service principal quedan registrados por superficie (lectura SCIM, CAN_MANAGE por objeto, admin solo donde se exija)

#### Scenario: Endurecimiento de una superficie

- **WHEN** una superficie puede operar sin workspace admin
- **THEN** el despliegue la configura con privilegios reducidos en lugar de admin global

### Requirement: Aislamiento entre llamantes y auditoría con usuario OBO

El sistema SHALL resolver la autorización con la identidad y grupos del llamante autenticado, SHALL NO compartir autorizaciones entre llamantes y SHALL registrar cada cambio en la bitácora con el usuario OBO que lo provoca.

#### Scenario: Dos llamantes con autoridad distinta

- **WHEN** dos usuarios utilizan la App con privilegios efectivos diferentes
- **THEN** cada uno solo ejecuta lo que su propia autorización valida, aunque la ejecución use la misma identidad de App

#### Scenario: Evento con usuario OBO e identidad de ejecución

- **WHEN** se ejecuta un cambio en modo broker
- **THEN** la bitácora registra el usuario OBO del llamante y el detalle del evento indica que la ejecución usó la identidad de la App

### Requirement: Ruta CLI y lote sin cambios

El modo broker SHALL aplicar exclusivamente al despliegue como Databricks App; la ruta CLI/lote SHALL seguir ejecutando toda operación con la credencial del llamante, sin broker ni identidad de App.

#### Scenario: Operación CLI con credencial del llamante

- **WHEN** se procesa una solicitud por la ruta CLI/lote
- **THEN** la ejecución usa la credencial del llamante exactamente como antes de este change
