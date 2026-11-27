# app-broker-grants Specification

## Purpose

Permite que la Databricks App cubra toda la gestión de accesos del proyecto separando la autorización (siempre evaluada con la identidad y privilegios efectivos del llamante) de la ejecución (identidad del service principal de la App solo donde el token OBO no tiene scopes suficientes), sin convertir la App en una vía de elevación no autorizada.

## Requirements

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

### Requirement: Rol y entitlements del service principal de la App en modo broker

El service principal de la Databricks App, en modo broker, SHALL tener asignado por el humano como recurso de despliegue el rol **Workspace admin** sobre el workspace objetivo y los entitlements **Databricks SQL Access**, **Workspace Access** y **Consumer Access**.

#### Scenario: Asignación del rol y de los entitlements en el despliegue

- **WHEN** se despliega el modo broker sobre una Databricks App
- **THEN** el service principal de la App tiene el rol Workspace admin sobre el workspace objetivo y los entitlements Databricks SQL Access, Workspace Access y Consumer Access, y la asignación queda registrada en el change como recurso de despliegue ejecutado por el humano

#### Scenario: Verificación posterior a la asignación

- **WHEN** el humano declara la asignación como completada
- **THEN** la App permanece RUNNING al consultarla con la API de Databricks Apps y el gate broker se ejecuta contra esa configuración documentada

### Requirement: Documentación operativa de los privilegios del SP

La configuración de privilegios del service principal SHALL estar listada textualmente en `config/app_properties.json`, `databricks.yml` y el README (rol de workspace y entitlements), sin valores embebidos de credencial.

#### Scenario: Documentación presente en los recursos de despliegue

- **WHEN** se consulta la configuración del modo broker
- **THEN** los privilegios del service principal aparecen listados en `config/app_properties.json`, `databricks.yml` y el README

### Requirement: Cambios a los privilegios del SP requieren un nuevo change de OpenSpec

Cualquier propuesta de reducir los privilegios documentados del SP (rol Workspace admin o alguno de los entitlements Databricks SQL Access, Workspace Access o Consumer Access) SHALL gestionarse mediante un change de OpenSpec separado con su propia evidencia y SHALL NO aplicarse como ajuste silencioso ni en producción sin trazabilidad.

#### Scenario: Reducción propuesta de privilegios del SP

- **WHEN** una superficie podría operar con privilegios inferiores a los documentados
- **THEN** la propuesta se registra en un nuevo change de OpenSpec con su evidencia y se revisa contra el gate, sin modificar la configuración actual de forma silenciosa

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
