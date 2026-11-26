# Design

## Context

Ver la motivación en `proposal.md` (¿por qué?). Este documento explica el cómo de C8, ajustado a la arquitectura real del repo. Cierra el inventario del plano de control sobre el pipeline ya existente: el contrato unificado `Canal`/`CanalControl` (`canales/contratos.py`), la inyección del canal del plano de control al pipeline (`pipeline/enrutador.py`), la matriz declarativa que ya cubre los tipos `DATABRICK_APP` (`CAN_USE`, `CAN_MANAGE`) y `USO_TOKEN` (`CAN_USE`), las fases `plan -> pre-flight -> ejecutar -> verificar -> reporte`, la resolución de privilegios efectivos y el split ejecutable/bloqueado del llamante (C3), los lotes 1 a N / N a 1 con resultados parciales (C5), el canal real `CanalControlComputo` y el adaptador SDK `ClientePermisosSdk` ya contrastado contra los workspaces (C7), y `CanalControlSimulado` para pruebas.

C7 dejó explícitamente fuera de su `RECURSO_PERMISOS_POR_TIPO_OBJETO` los recursos `apps` y `authorization/tokens`, y su `CanalControlComputo` rechaza esos tipos con `ErrorCanal` ("el tipo no tiene recurso en la Permissions API, change grants-apps-tokens", `canal_control_computo.py`). El objetivo de C8 es exactamente extender ese canal con esos dos tipos —reusando el adaptador SDK ya instalado y validado— sin crear un canal nuevo, sin tocar el canal SQL del plano de datos, el pipeline, el dominio, la matriz, el resolutor ni el enrutador.

## Goals / Non-Goals

**Goals:**

- Extender `CanalControlComputo(CanalControl)` de C7 con los dos tipos restantes del plano de control (Databricks Apps y uso de personal access tokens), reusando el adaptador SDK, el puerto de permisos, los patrones de error, la escritura aditiva y la verificación post-grant ya establecidos en C7.
- Otorgamiento y revocación aditivos por otorgatario sobre la Permissions API del recurso `apps`, y sobre la Token Permissions API del recurso `authorization/tokens` (singleton de workspace, identificador vacío).
- Traducción de errores por caso (permiso denegado, objeto/principal inexistente, feature de token permissions no habilitada) con mensajes específicos en español, manteniendo la regla fail-safe.
- Regla No HardCoded mantenida mediante transporte y credencial inyectados, y datos declarativos (recursos, patrones, prefijo de rutas).
- Suite TDD en las cuatro capas: unitarias del canal extendido, funcionales del flujo con transporte simulado y bitácora, integrales por entorno con instantánea y restauración de la ACL (con `andresAzureDev` como fallback obligatorio de los casos que no estén disponibles en `andresFree`), y aceptación trazable 1:1 a los escenarios del spec.

**Non-Goals:**

- Crear un canal nuevo hermano (`CanalControlAppsTokens`); los nuevos tipos se añaden al `CanalControlComputo` existente por extensión del mismo módulo y de su `RECURSO_PERMISOS_POR_TIPO_OBJETO` (D1).
- Crear, renombrar, eliminar o descubrir Databricks Apps, así como activar features del workspace (la activación de Token Permissions API y de cualquier otra previa son decisiones manuales del administrador, fuera de la app, igual que D9/D7 de C7).
- Cualquier nueva dependencia: este change reutiliza `databricks-sdk`, ya instalada y autorizada en C7 (ver `requirements.txt`); la IA no instala nada sin permiso expreso del humano.
- Modificar `CanalControlSimulado`, `CanalSqlDatos`, el pipeline, el dominio (`dominio/`), la matriz (`matriz/`), el resolutor (`resolucion/`) ni el enrutador (`pipeline/enrutador.py`); sí se extiende `canal_control_computo.py` con el alcance definido en este change.
- Atributos nuevos en `config/app_properties.json` o tablas nuevas: este change no agrega configuración de catálogo ni persistencia.
- Cambios en UI (C9) o en generación de informes (C10).

## Decisions

### D1 — Extender `CanalControlComputo` con los recursos `apps` y `authorization/tokens`

C8 extiende `CanalControlComputo(CanalControl)` de C7 añadiendo dos entradas al mapa declarativo `RECURSO_PERMISOS_POR_TIPO_OBJETO` (`DATABRICK_APP` → `apps`, `USO_TOKEN` → `authorization/tokens`) y la rama singleton para `authorization/tokens` (identificador vacío, sin segmento de id en la ruta de la Permissions API). El canal queda como única puerta del plano de control para permisos SDK/REST, soportando los tres tipos de cómputo de C7 más los dos tipos restantes. Reusa los demás mecanismos del módulo: contrato unificado con el pipeline (inyección de `canal_control`), misma traducción de excepciones a resultados por ítem, mismo `registrador_errores` opcional, mismas pruebas de unitarias/funcionales aplicadas a los tipos nuevos. La cobertura del canal pasa de 3 a 5 tipos: `COMPUTO_CLASICO`, `COMPUTO_SERVERLESS`, `SQL_WAREHOUSE`, `DATABRICK_APP` y `USO_TOKEN`. Un tipo del plano de datos o cualquier tipo no declarado en el mapa se rechaza con `ErrorCanal` que identifica el tipo recibido (los códigos de error y mensajes ya están en español en C7).

- *Alternativa:* crear un canal nuevo hermano `CanalControlAppsTokens(CanalControl)` con su propio módulo y sus propias pruebas. *Descartada:* el principio del proyecto es una familia por canal, y el `CanalControlComputo` ya cubre cómputo con tres tipos cualitativamente distintos entre sí (per‑instance de cluster, per‑instance de serverless, per‑instance de warehouse); añadir Databricks Apps y `authorization/tokens` mantiene la simetría (cinco tipos, una familia, un módulo). Separar introduce duplicación de pruebas, traducción de errores y bitácora sin reducir el alcance del cambio. La naturaleza singleton de `authorization/tokens` se maneja como una rama interna del método correspondiente, localizada y cubierta por su unitaria determinista, sin necesidad de un canal paralelo.
- *Alternativa:* reusar la misma clase con un factory por tipo. *Descartada:* introduce ramas y condicionales por familia que duplican la traducción de errores y la verificación.

### D2 — Recurso de la Permissions API declarado por tipo de objeto y alcance singleton para tokens

El mapa declarativo `RECURSO_PERMISOS_POR_TIPO_OBJETO` ya extendido asocia `DATABRICK_APP` con `apps` y `USO_TOKEN` con `authorization/tokens`. Para Databricks Apps la ruta completa incluye el id de la App (`/api/2.0/permissions/apps/<id>`); para uso de tokens el canal reconoce el tipo y omite el id (`authorization/tokens` es singleton del workspace), construyendo la ruta `/api/2.0/permissions/authorization/tokens` con el identificador vacío. Los datos se contrastan contra los workspaces en el *spike* de la fase 6 y se ajustan como datos sin tocar lógica.

- *Alternativa:* resolver el recurso con condicionales por tipo dentro de cada operación. *Descartada por D2 de C7:* dispersa la misma decisión en tres métodos y contradice el estándar declarativo del proyecto.
- *Alternativa:* que el canal decida el singleton vs. por instancia inspeccionando un flag del objeto. *Descartada:* el dominio ya separa los dos tipos (`TipoObjeto.DATABRICK_APP` vs `TipoObjeto.USO_TOKEN`), y declarar dos rutas claras en el módulo evita lógica adicional de despacho.

### D3 — Reutilización del adaptador SDK y del puerto de permisos de C7

El canal depende del mismo puerto inyectado (`EntradaAcl`, `LeerAcl`, `EscribirAcl`) ya establecido por C7, y en producción del mismo `ClientePermisosSdk` sobre `WorkspaceClient.permissions`, construyendo el cliente con las credenciales del entorno de la app y el token on-behalf-of del llamante. La integración con el SDK reusa el método `permissions.get`/`update` con los `request_object_type` declarados (`apps` con id, `authorization/tokens` con id vacío), y el puerto no expone tipos del SDK al canal. En unitarias y funcionales se inyecta un transporte simulado que reproduce respuestas y errores reales, y en las integrales el mismo adaptador SDK se construye con el perfil CLI del workspace (`andresFree` / `andresAzureDev`), sin tokens ni credenciales en el código ni en las fixtures. Así el canal no contiene host, token, ids ni niveles de permiso, y se ejercita por completo sin workspace.

- *Alternativa:* implementar una clase nueva del puerto adaptada a `apps`/`authorization/tokens`. *Descartada:* duplica Mantenimiento y rompe la regla del proyecto (el puerto agrupa cualquier recurso de la Permissions API, ya validado en C7).
- *Alternativa:* hacer llamadas REST propias sin SDK. *Descartada por la decisión del humano en C7 (`databricks-sdk` 0.170.0 autorizado):* el SDK ya está disponible y tipado.

### D4 — Escritura aditiva por otorgatario, misma regla de D4 de C7

El otorgamiento actualiza únicamente la entrada del otorgatario del ítem al nivel solicitado, conservando intactas las entradas de los demás otorgatarios; la revocación quita ese permiso al mismo otorgatario con la misma regla; un permiso heredado o un permiso que no estaba vigente se tratan como operaciones ya satisfechas, sin alterar otras entradas. La lectura-modificación-escritura se hace acotada a la entrada del otorgatario, con reintento acotado si el workspace reporta conflicto de concurrencia (`RESOURCE_CONFLICT`, `CONCURRENT_MODIFICATION`). En `authorization/tokens` la misma regla aplica sobre la ACL singleton del workspace: la lectura devuelve la lista completa y la escritura sustituye el conjunto completo tras la composición aditiva.

- *Alternativa:* reemplazar la ACL completa del objeto con el resultado de añadir o quitar el permiso. *Descartada por D4 de C7:* un reemplazo total puede borrar permisos de terceros entre lectura y escritura, riesgo inaceptable en un sistema que centraliza accesos.
- *Trade-off asumido:* una lectura extra por ítem en los casos que la API exige estado previo; aceptada a cambio de no pisar ACLs ajenas, igual que en C7.

### D5 — Lectura de la ACL y normalización a otorgamientos del dominio

`ListarGrantsVigentes` lee la ACL del objeto y devuelve un `ItemGrant` por nivel de permiso de cada otorgatario, con el tipo de principal derivado del campo con el que la API lo identifica y el objeto consultado conservado tal cual. Para Databricks Apps el objeto se identifica por nombre/id; para uso de tokens el objeto es el singleton del workspace y se conserva con su identificador vacío. Una entrada sin otorgatario identificable se omite sin inventar principal, y una ACL sin entradas devuelve lista vacía, distinguible de un fallo de lectura. La verificación del pipeline compara principal + privilegio + objeto sobre esa lista, por lo que un otorgamiento no reflejado en la ACL pasa a `fallido` con detalle, sin lógica nueva en el verificador.

- *Alternativa:* devolver la ACL cruda y que el verificador la interprete. *Descartada por D5 de C7:* rompería el contrato unificado y obligaría a bifurcar la verificación por plano.

### D6 — Clasificación de errores por código y patrones declarativos, con regla fail-safe y feature no habilitada para tokens

El canal clasifica la respuesta de error con datos declarativos: el permiso denegado del workspace produce `ErrorPrivilegiosInsuficientes`; el objeto inexistente y el principal inexistente producen `ErrorCanal` con mensaje específico en español; la respuesta del workspace que indica que la Token Permissions API no está habilitada se clasifica como `ErrorCanal` con mensaje específico que identifica la feature (igual trato que en C7 para la feature serverless no disponible); cualquier otra causa produce `ErrorCanal` con el detalle crudo. La regla fail-safe no cambia respecto a C7: un patrón no reconocido cae en `fallido`, nunca en `privilegios_insuficientes`. Los patrones concretos se contrastan contra el workspace en el *spike* de la fase 6 y se ajustan como datos sin tocar lógica; los patrones de C7 para objeto/principal inexistente son punto de partida cuando aplique.

- *Alternativa:* mapear todos los errores HTTP 4xx a privilegios insuficientes. *Descartada por D6 de C7:* confundiría objeto inexistente o feature no habilitada con falta de privilegios y degradaría el reporte al usuario.
- *Decisión del humano en C7 ya contrastada:* el SDK expone `permissions.update` como PATCH, que Databricks rechaza con `NOT_IMPLEMENTED` en objetos con propietario. C8 reusa el mismo truco: escritura por PUT del conjunto completo tras lectura-modificación-escritura acotada, comportamiento ya validado en C7.

### D7 — Bitácora de eventos en el pipeline y bitácora de errores opcional en el canal

El evento de la solicitud, con el usuario del llamante OBO y el desglose por ítem, lo sigue registrando el pipeline ya existente (C2/C3), sin código nuevo de orquestación. El canal acepta un `registrador_errores` opcional, igual que `CanalControlComputo`, y registra cada fallo de ejecución con su detalle y contexto; si no hay registrador o el propio registro falla, el error queda igual traducido a resultado por ítem, de modo que la auditoría nunca introduce fallos en cascada.

- *Alternativa:* registrar eventos también dentro del canal. *Descartada por D7 de C7:* duplicaría eventos por ítem y desdibujaría la responsabilidad única del pipeline sobre la bitácora de eventos.

### D8 — Integrales por entorno, con instantánea y restauración de la ACL, y `.env.example` con `CONTROL_ACCESOS_SP_CLIENT_SECRET`

**Política de cobertura (endurecida):** las integrales corren principalmente en `andresFree` (`marker free`, entorno primario). Todo caso del spec queda ejecutado en `andresFree` o, cuando el *spike* 6.1 confirme que no está disponible allí, su cobertura equivalente corre en `andresAzureDev` (`marker azure_approval`, pre‑aprobado por el humano por ser imposible en Free Edition). `andresAzureDev` opera como **fallback obligatorio** de los casos no disponibles en Free Edition, no como cobertura optativa: no se admite omitir un caso del spec sin alternativa implementada. La cobertura por defecto es `andresFree` y el fallback es `andresAzureDev`, no al revés.

El *spike* 6.1 contrasta en `andresFree`: existencia de Databricks Apps securables, lectura/escritura de su ACL por `apps`, y disponibilidad y forma real de la respuesta de `authorization/tokens`. Si alguno de los dos tipos o niveles **no es posible** en `andresFree`, su cobertura se escribe como integral obligatoria en el archivo `tests/integrales/test_grants_apps_tokens_andresazuredev.py` (tarea 6.4), con la misma instantánea, otorgamiento, verificación, revocación y restauración que las integrales de `andresFree`.

**Otorgatarios de pruebas (decisión del humano, declarados en `tests/integrales/fixtures_computo.py` y `fixtures_uc_datos.py` de cambios previos, nunca en el canal):**
- `andresFree`: service principal con App Id `1738687d-4838-49ef-83fd-521f935a9ec2` y grupo `Desarrollador` para Apps; los mismos para tokens si la feature está habilitada.
- `andresAzureDev`: service principal con App Id `e59aa9cf-ddf5-453a-9abf-98c3b72ab01c` y grupo `desarrollo_regional`.

**Objetos de prueba (decisión del humano):** en `andresFree` se usa una Databricks App existente del workspace (resuelta por nombre o id vía API, sin hardcodear); los otorgatarios y grupos aprobados ya existen en sus workspaces y este change no los crea ni los elimina. Como las ACLs probadas son recursos compartidos del workspace, cada prueba toma una instantánea de la ACL original, otorga al otorgatario de pruebas, verifica, revoca y restaura la ACL en `finally`, dejando constancia de que no quedó estado residual. Para uso de tokens se aplica la misma mecánica sobre la ACL singleton del workspace.

**Variable de entorno para la integral de permiso denegado real (regla estricta del README — "Secretos y datos de entorno de pruebas"):** la integral 6.5 se autentica como el service principal restringido `1738687d-4838-49ef-83fd-521f935a9ec2` mediante OAuth M2M. Su secreto **no se versiona jamás** y se lee de la variable de entorno `CONTROL_ACCESOS_SP_CLIENT_SECRET`. La variable se documenta en `.env.example` con prefijo `CONTROL_ACCESOS_` siguiendo el patrón ya usado por C6 con `CONTROL_ACCESOS_SQLSERVER_*`; el archivo `.env` real (gitignoreado) la contiene con el valor. El control de esta variable es la tarea de preparación **0.1** del `tasks.md`, ubicada antes del bloque 1 por prioridad funcional. Si la variable no está exportada al ejecutar la integral 6.5, la prueba se salta con motivo documentado y el resto de la suite sigue verde, exactamente como en `tests/integrales/fixtures_uc_externos.py` para C6.

- *Alternativa:* crear y destruir una Databricks App por prueba. *Descartada:* se usan las Apps existentes indicadas por el humano, con restauración de su ACL; este change no crea ni elimina Apps.
- *Alternativa:* usar `.env` para credenciales no sensibles y versionarlo. *Descartada:* la regla estricta del README deja `.env` gitignoreado; toda credencial va por variable de entorno.

### D9 — Alcance del canal: solo permisos de instancias existentes y tokens del workspace

El canal solo modifica la ACL de las cinco familias declaradas en D2: clusters clásicos, serverless compute objects, SQL warehouses, Databricks Apps existentes y la ACL singleton del workspace para uso de personal access tokens. En ningún caso crea, renombra ni elimina objetos; en particular para Databricks Apps no descubre ni provisiona Apps, y para `authorization/tokens` no intenta habilitar la Token Permissions API cuando el workspace responde que no está disponible (ese fallo se reporta con su detalle). El plano de datos queda fuera por construcción, al no declarar sus tipos en el mapa de D2.

- *Alternativa:* que la app active la feature de Token Permissions API al primer uso. *Descartada:* el README y el proposal lo dejan explícitamente fuera de la app por ser una decisión manual del administrador del workspace, mismo criterio que aplica C7 al cómputo serverless.

## Risks / Trade-offs

- [El workspace de Free Edition no ofrece el control de acceso de Databricks Apps o de tokens] → *spike* previo en `andresFree` (6.1); si la cobertura no está disponible allí, su equivalente corre obligatoriamente en `andresAzureDev` con el `marker azure_approval` (D8), no se admite omitir el caso. La ausencia de algún caso también se cubre en unitarias y funcionales con respuestas de forma real (spec - "Feature no disponible en el workspace" y "Uso de tokens fuera de Free Edition").
- [Las rutas o los códigos de error de la Token Permissions API difieren de lo esperado] → los recursos y patrones son datos declarativos (D2/D6); las integrales los contrastan y se ajustan sin tocar lógica, dejando constancia del contraste como en C7.
- [Una escritura concurrente de otro administrador pisa la ACL entre lectura y escritura] → escritura aditiva por otorgatario y, cuando la API exige estado previo, reintento acotado tras relectura (D4); se evita el reemplazo total de la ACL. La ruta de reintento quedó cubierta por una unitaria determinista en C7; C8 hereda la misma disciplina.
- [Las pruebas integrales dejan permisos residuales sobre Apps o sobre la ACL singleton de tokens] → instantánea de la ACL original y restauración en `finally`, con otorgatario de pruebas dedicado y comprobación final de que la ACL quedó equivalente; para tokens, la mecánica es la misma sobre el singleton (D8).
- [El puerto de permisos de C7 asume que existe `objeto.identificador` en la ruta] → para `authorization/tokens` el id es vacío y la ruta omite el segmento. El canal construye la ruta detectando el tipo, sin tocar el puerto ni el contrato `EntradaAcl`. Riesgo mitigado con unitaria determinista (similar a la prueba de recurso en C7).
- [La verificación post-grant marca falsos `fallido` para permisos heredados] → C7 contrastó la forma real de la ACL y aisló niveles directos vs. heredados; C8 reusa esa lectura: `ListarGrantsVigentes` solo emite otorgamientos directos, y un permiso solo heredado queda fuera de la verificación (mismo criterio).
- [La versión del SDK ya autorizada (`databricks-sdk` 0.170.0) cambia la firma del API de permisos] → C7 fijó la versión y el canal solo ve el puerto propio (D3); cualquier ajuste del SDK se absorbe en el adaptador, sin tocar el canal extendido ni el pipeline.

## Migration Plan

El change es aditivo: extiende el módulo `canal_control_computo.py` con dos entradas nuevas en `RECURSO_PERMISOS_POR_TIPO_OBJETO`, una rama singleton para `USO_TOKEN`, los patrones específicos del caso "Token Permissions API no habilitada" (D6), las pruebas correspondientes y la entrada en `.env.example` (D8, tarea 0.1). No hay migraciones de datos, ni cambios de esquema, ni atributos nuevos en `config/app_properties.json`, ni modificaciones en el canal SQL, `CanalControlSimulado`, el pipeline, el dominio, la matriz, el resolutor ni el enrutador. El despliegue se reduce a reusar la inyección existente de `CanalControlComputo` (único canal del plano de control); la cobertura de `DATABRICK_APP` y `USO_TOKEN` queda activa al actualizar el módulo extendido, sin cambios de cableado. La reversa es igual de simple: revertir el módulo a su estado de C7 (5 entradas vuelven a 3) o, si se requiere paso a paso, retirar las dos entradas del mapa y la rama singleton. No hay estado persistido propio de este change que revertir, y las ACLs modificadas por pruebas quedan restauradas por D8.

## Open Questions

Resueltas por el humano y por el diseño del proyecto: tipos de objeto y matriz (`DATABRICK_APP` con `CAN_USE`/`CAN_MANAGE`, `USO_TOKEN` con `CAN_USE`, ya declarados), transporte de producción reutilizado del adaptador SDK sobre `databricks-sdk` (instalación ya autorizada por el humano en C7), regla singleton de `authorization/tokens` con identificador vacío, escritura por PUT del conjunto completo tras lectura-modificación-escritura acotada (D4 validado en C7), uso de otorgatarios y grupos ya existentes en los workspaces, política de fallback `andresAzureDev` (D8), declaración de `CONTROL_ACCESOS_SP_CLIENT_SECRET` en `.env.example` y `.env` (D8, tarea 0.1), y suite TDD en cuatro capas por ambiente. Resueltas también por patrón: ninguno de los `Open Questions` de C7 obliga a cambiar nada de C8 (C8 hereda y reusa sus decisiones). No quedan dudas diferibles que cambien el spec, el diseño ni el desglose de tareas.
