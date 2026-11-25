# Spec Delta

## REMOVED Requirements

### Requirement: Objetos fuera del alcance de este change

**Reason**: El requisito estaba acotado al alcance del change `grants-uc-datos` (C4), que soportaba únicamente los ocho tipos del plano de datos y declaraba explícitamente external location y connection como "aún no soportadas". El change `grants-uc-externos` (C6) incorpora ambos tipos al canal SQL, por lo que el requisito queda obsoleto y contradice el comportamiento real: el canal ya no rechaza esos objetos.

**Migration**: La cobertura del canal SQL y el rechazo de los objetos ajenos a él pasan a estar declarados en la capability `uc-external-object-grants`, requisito "Cobertura completa del plano de datos": el canal soporta los diez tipos del plano de datos (los ocho de C4 más external location y connection) y un ítem del plano de control que llegue al canal se reporta `fallido` con mensaje explícito de tipo no soportado, sin ejecutar instrucción alguna. Los dos escenarios del requisito eliminado quedan cubiertos allí: "External location aún no soportada" se sustituye por el procesamiento con la palabra clave `EXTERNAL LOCATION`/`CONNECTION` (requisitos "Instrucción de otorgamiento para objetos externos" e "Instrucción de revocación para objetos externos"), y "Objeto del plano de control fuera de este canal" se conserva con el mismo comportamiento en el escenario "Objeto del plano de control fuera del canal".
