# Bloque propuesto para README — Persona D

Este bloque puede incorporarse al README general por A; no se modificó ese archivo.

## Neo4j y comandos D

Q03/Q04/Q10 consultan exclusivamente Neo4j, una proyección persistente eventualmente
consistente. sync consume outbox bajo demanda; no hay worker continuo ni autorización
de ventas en Neo4j. Las fechas se presentan en JSON ISO 8601.

| Comando | Parámetros |
| --- | --- |
| grafo-init | Sin parámetros; crea/verifica restricciones, sin datos ficticios |
| q03 | --id-cliente ID obligatorio |
| q04 | Sin parámetros obligatorios |
| q10 | --id-sucursal ID obligatorio |
| sync | --base BASE; --max-eventos N opcional (0 solo observa); --lock-path RUTA opcional |
| grafo-verify | --base BASE; --lock-path RUTA opcional; --confirmar-escrituras-pausadas para certificar equivalencia declarada |
| grafo-rebuild | --base BASE; --confirmar-entorno-aislado; --confirmar-escrituras-pausadas; --confirmar-sincronizador-pausado; --confirmar-actualizacion-existente si ya contiene nodos; --lock-path RUTA opcional |

La ruta de bloqueo por defecto es ~/.farmared/sync.lock, fija para los comandos D
del mismo usuario aunque cambie el directorio actual. Si varios usuarios, hosts o
contenedores comparten Neo4j, deben indicar el mismo archivo/volumen con --lock-path;
los archivos locales separados no ofrecen exclusión distribuida. El padre de una
ruta explícita debe existir. No borrar el archivo de lock mientras haya consumidores.

Desde el host, usar las URI locales configuradas en .env y el secreto de A:

```powershell
uv run --locked --env-file .env farmared grafo-init
uv run --locked --env-file .env farmared sync --base farmared_demo_d --max-eventos 100
uv run --locked --env-file .env farmared q03 --id-cliente C001
uv run --locked --env-file .env farmared q04
uv run --locked --env-file .env farmared q10 --id-sucursal S001
```

En Codespaces/Dev Containers las URI ya se inyectan desde la configuración existente
(mongodb:27017 y neo4j:7687): ejecutar sin --env-file. No sustituirlas por localhost.
La ejecución alojada en Codespaces no se verificó en esta entrega; se inspeccionó
su configuración y se probó Compose desde Windows en un proyecto aislado.

Con escrituras pausadas de verdad y sin otro sincronizador, verificar:

```powershell
uv run --locked --env-file .env farmared grafo-verify --base farmared_demo_d --confirmar-escrituras-pausadas
```

Sin esa confirmación se permite un diagnóstico de lectura, pero su exit code es 1,
aun si no encuentra diferencias. Una diferencia también produce 1; un fallo de
conexión se distingue mediante CONEXION en stderr. sync devuelve 1 si informa errores.
Las consultas vacías son resultados válidos. Errores de argumentos producen 2.

La reconstrucción es administrativa. Usar solamente un destino Neo4j dedicado,
retirado del uso normal, con escritores de MongoDB y sincronizador pausados:

```powershell
uv run --locked --env-file .env farmared grafo-rebuild --base farmared_demo_d --confirmar-entorno-aislado --confirmar-escrituras-pausadas --confirmar-sincronizador-pausado
```

Si el destino ya tiene nodos propios, se requiere además
--confirmar-actualizacion-existente. No hay una opción de purga: los datos ajenos o
sobrantes se rechazan. Solo habilitarlo cuando habilitable=true. La reconstrucción
no modifica MongoDB ni outbox. La pausa y dedicación son declaraciones administrativas,
no algo que el lock pueda demostrar por sí solo.

**Estado actual (prompt 9):** E2E real ejecutado con originales y adicionales:
207 filas CSV, 169 documentos MongoDB, 120 eventos procesados sin errores,
120 nodos y 142 relaciones Neo4j; equivalencia confirmada. Q03 C001 produjo seis
eventos, Q04 cinco clientes y Q10 A-S002 tres clientes. Sync repetido procesó cero
eventos; reconstrucción en otro Neo4j vacío terminó habilitable=true sin modificar
MongoDB ni outbox. Ver [evidencias oficiales](../evidencias/d/e2e_oficial/README.md).
Se conservaron los registros históricos sintéticos y la validación de portabilidad.

Pruebas finales del prompt 9, con integraciones reales habilitadas: Persona D
271 aprobadas; general 550 aprobadas, dos omitidas por plataforma Windows y cero
fallidas. Los contenedores y volúmenes exclusivos fueron retirados; se conservaron
los recursos preexistentes. No hay sincronizadores continuos.
