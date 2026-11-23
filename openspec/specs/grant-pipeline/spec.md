# grant-pipeline Specification

## Purpose

Flujo de procesamiento de solicitudes de grant en fases: planificación, pre-flight, ejecución, verificación y reporte. Garantiza resultados por ítem y que un fallo puntual nunca aborte la operación completa.

## Requirements

### Requirement: Fase de planificación

El pipeline SHALL construir una solicitud de grant estructurada a partir de las entradas recibidas (principal, privilegios, objeto), expandiéndola en ítems atómicos (un ítem por cada par privilegio-objeto a otorgar al principal) que serán la unidad de procesamiento y de reporte en todas las fases.

#### Scenario: Expansión en ítems atómicos

- **WHEN** llega una solicitud con un principal, dos privilegios y un objeto
- **THEN** el pipeline la expande en dos ítems atómicos, uno por privilegio, cada uno procesable y reportable de forma independiente

#### Scenario: Solicitud inválida detectada en planificación

- **WHEN** llega una solicitud que no cumple la forma cardinalidad 1 a 1
- **THEN** el pipeline la rechaza con mensaje explícito y no genera ítems ni ejecuta fase alguna

### Requirement: Fase de pre-flight

Antes de ejecutar nada, el pipeline SHALL evaluar cada ítem contra la matriz de compatibilidad privilegio x tipo de objeto y clasificarlo como ejecutable o bloqueado. Los ítems bloqueados quedan excluidos de la ejecución y pasan directamente al reporte con su motivo.

#### Scenario: Ítem compatible queda ejecutable

- **WHEN** en pre-flight un ítem tiene un privilegio válido para el tipo de su objeto
- **THEN** el pipeline lo clasifica como ejecutable y lo envía a la fase de ejecución

#### Scenario: Ítem incompatible queda bloqueado

- **WHEN** en pre-flight un ítem tiene un privilegio inválido para el tipo de su objeto
- **THEN** el pipeline lo clasifica como bloqueado con el mensaje de error preciso de la matriz, y no lo envía a ejecución

### Requirement: Fase de ejecución por canal sin abortar la operación

El pipeline SHALL ejecutar cada ítem ejecutable mediante el canal correspondiente al plano de su objeto (SQL para el plano de datos; SDK/REST para el plano de control). Un fallo en un ítem NO abortará el procesamiento de los demás ítems de la solicitud.

#### Scenario: Fallo puntual no aborta el resto

- **WHEN** de tres ítems ejecutables el segundo falla durante la ejecución
- **THEN** el pipeline ejecuta y reporta los tres ítems: el fallo del segundo no cancela la ejecución del primero ni del tercero

#### Scenario: Selección de canal por plano del objeto

- **WHEN** se ejecuta un ítem cuyo objeto pertenece al plano de datos
- **THEN** el pipeline lo envía por el canal SQL; y cuando el objeto pertenece al plano de control, lo envía por el canal SDK/REST

### Requirement: Fase de verificación posterior al grant

Después de ejecutar un ítem otorgado, el pipeline SHALL verificar que el privilegio quedó efectivamente concedido (consultando los grants vigentes del objeto), y reportar toda discrepancia entre lo ejecutado y lo verificado como estado `fallido` con el detalle correspondiente.

#### Scenario: Grant verificado con éxito

- **WHEN** un ítem se ejecuta como otorgado y la verificación encuentra el privilegio concedido sobre el objeto
- **THEN** el ítem se reporta con estado `otorgado`

#### Scenario: Discrepancia entre ejecución y verificación

- **WHEN** un ítem se ejecuta como otorgado pero la verificación no encuentra el privilegio concedido
- **THEN** el ítem se reporta con estado `fallido` y un detalle que indica la discrepancia detectada en la verificación

### Requirement: Fase de reporte por ítem

El pipeline SHALL producir un reporte consolidado de la solicitud con un resultado por ítem que incluya: principal, privilegio, objeto, estado final (otorgado, fallido, privilegios insuficientes) y, cuando aplique, el detalle del error o el motivo de bloqueo. El reporte cubre todos los ítems, incluyendo los bloqueados en pre-flight.

#### Scenario: Reporte completo con ítem bloqueado

- **WHEN** una solicitud de dos ítems termina con uno bloqueado en pre-flight y uno otorgado
- **THEN** el reporte incluye ambos ítems: el bloqueado con su motivo y el otorgado con estado `otorgado`

#### Scenario: Reporte con ítems en los tres estados

- **WHEN** una solicitud termina con un ítem otorgado, uno fallido y uno con privilegios insuficientes
- **THEN** el reporte incluye los tres ítems, cada uno con su estado y su detalle correspondiente

### Requirement: Trazabilidad de fases por ítem

El pipeline SHALL permitir reconstruir, para cada ítem del reporte, las fases por las que pasó (planificado, clasificado en pre-flight, ejecutado o bloqueado, verificado) de modo que el reporte explique cómo se llegó al estado final de cada ítem.

#### Scenario: Reconstrucción del recorrido de un ítem bloqueado

- **WHEN** el reporte incluye un ítem bloqueado en pre-flight
- **THEN** el ítem muestra que fue planificado, evaluado en pre-flight y excluido de ejecución, con el motivo de bloqueo
