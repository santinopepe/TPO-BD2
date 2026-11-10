# A — Infraestructura y carga (avance: partes 1–5)

## Fuentes y decisiones

Se leyeron completos `TPO_FarmaRed.pdf` (7 páginas),
`FarmaRed_Plan_Definitivo_TPO_BD2.md` (versión 3.0) y
`FarmaRed_reparto_equipo_4_personas.md` (9/11/2026), disponibles en Downloads.
Los documentos son especificaciones de trabajo, no evidencia de implementación.

La consigna manda sobre requisitos; el reparto precisa responsabilidades y contratos;
el plan orienta la arquitectura. Se conserva MongoDB como autoridad y Neo4j como
proyección. No se agrega UI ni motores adicionales.

Diferencias resueltas por esa precedencia:

- El plan asignaba q13 a B y el modelado MongoDB a B; el reparto posterior asigna
  q13 a C y el esquema base a A. Se adopta el reparto sin cambiar sus interfaces.
- El plan combina seed y proyección inicial; el reparto separa `cargar_mongo` de
  `sincronizar`. Seed emitirá outbox y el setup completo podrá llamar al sync de D.
  No se declarará el grafo actualizado sin ejecutar y verificar esa sincronización.
- El reparto sugiere otra rama; el pedido explícito exige `infra-carga` y se respeta.
- La consigna indica grupos de cuatro en p. 1 y participación de tres en p. 7.
  Se mantiene el reparto de cuatro; la aclaración académica sigue pendiente.

La primera base del reparto se subdivide según la instrucción de entregas pequeñas:
paquete/contratos primero, infraestructura/conexiones después y esquema base tercero.

## Parte 1 implementada

Paquete instalable mediante PEP 517, layout `src`, entrada `farmared` y
`python -m farmared`. Dependencias directas fijadas, lock de transitivas y hashes.
No se introducen repositorios abstractos ni un framework común que bloquee al equipo.

El router importa solo el adaptador elegido. Un comando todavía no integrado
termina con código 3 y su responsable; `estado` continúa disponible sin B/C/D ni
conexiones. Un error interno del adaptador conserva su excepción para diagnóstico.

`Clock` permite inyectar un reloj. El reloj real calcula el día de Buenos Aires;
el fijo deriva el día de un instante explícito con zona. `inicio_dia_utc` convierte
fechas comerciales a UTC; los eventos técnicos usarán instantes UTC sin truncar.
La fecha de referencia de la consigna no se usa como hoy.

Los contratos preservan strings para identificadores y los literales oficiales.
El dinero se verifica como entero no negativo de rango int64, rechazando booleanos
y floats. No se fija un esquema MongoDB mediante estos tipos: falta su entrega.

## Inspección inicial y límites

Repositorio inicial: rama `main`, README mínimo y `.gitignore`; sin AGENTS.md en
el proyecto ni ancestros inspeccionados, sin dependencias ni código previo.
Se preservaron la exclusión previa `datasets_farmared/` y el `.DS_Store` sin rastrear.
No se hicieron commits ni se movieron/modificaron los originales.

Los nueve CSV están presentes con los conteos declarados en el plan. Se observaron
cabeceras y valores de enums reales. No se afirma todavía integridad referencial,
coherencia histórica, validación de totales, carga, idempotencia, persistencia ni
conectividad. No hay motores ni garantías transaccionales probados en esta parte.

El diagrama documental, los ejemplos persistidos, la guía de bases aisladas y el
ensamblador PDF se completarán con sus respectivas entregas de esquema/infra/informe.

## Parte 2: motores, conexiones y entorno de desarrollo

Compose fija por tag y digest MongoDB 8.0.15 y Neo4j Community 5.26.12. El
devcontainer fija Python 3.12.12 y uv 0.13.7; usa el lock de la primera entrega.
Los paquetes auxiliares Debian no se fijan a un snapshot; no se afirma identidad
binaria completa de cada reconstrucción del contenedor de desarrollo.

MongoDB usa `rs0` de un miembro, suficiente para transacciones de desarrollo pero
sin alta disponibilidad. Un servicio separado inicia la configuración solo cuando
recibe NotYetInitialized, verifica la existente y espera `isWritablePrimary`.
No hay inicialización dentro de healthchecks ni reconfiguración automática.
Neo4j valida readiness con una consulta autenticada. Las dependencias del servicio
de desarrollo exigen ambos healthchecks y salida exitosa del inicializador.

El preparador genera un secreto local aleatorio sin sobrescribir `.env` y mantiene
un enlace ignorado `infra/.env`: la CLI de Dev Containers ejecuta Compose desde
el directorio del primer archivo y allí busca la configuración. Las conexiones
internas usan nombres de servicio; el host usa loopback y `directConnection=true`
en MongoDB para evitar descubrir un nombre de contenedor no resoluble desde fuera.

Las conexiones son independientes. `obtener_mongo(config)` devuelve Database y
su cliente compartido para sesiones, con decodificación UTC consciente de zona y
write concern majority. `obtener_neo4j(config)` devuelve Driver verificado. El
llamador cierra los recursos. Los errores añaden el código `CONEXION`, sin cambiar
los códigos mínimos acordados ni mostrar credenciales. `salud` comprueba los motores
seleccionados y no afirma que el grafo esté sincronizado.

Los puertos se limitan a loopback; el MongoDB de desarrollo no tiene autenticación.
Neo4j conserva autenticación. Los volúmenes, red y puertos son configurables por
proyecto. El entorno virtual Linux vive fuera del `.venv` del host. Las pruebas
reales crean únicamente bases/IDs aleatorios de infraestructura y limpian esos
recursos; no usan un reset global ni servicios q13/q14/q15.

Fuentes técnicas consultadas para estas decisiones:

- [Docker: condiciones de arranque](https://docs.docker.com/compose/how-tos/startup-order/).
- [PyMongo: replica set en Docker y directConnection](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-targets/).
- [Neo4j: conexión y verify_connectivity](https://neo4j.com/docs/python-manual/current/connect/).
- [Neo4j: compatibilidad del driver 6 con servidor 5](https://neo4j.com/docs/python-manual/current/install/).
- [Dev Containers: referencia de configuración](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md).

Las evidencias reales y los límites de la validación local/Codespaces se registran
en `docs/evidencias/a/parte_02.md`. El esquema de negocio y la carga permanecen
pendientes para sus entregas respectivas.

## Parte 3: modelo documental base y garantías del motor

`preparar_mongo_base(db)` crea o asegura `clientes`, `sucursales`, `farmaceuticos`,
`proveedores`, `productos`, `stock_lotes`, `recetas`, `ventas` y `outbox`. La cabecera
de venta y sus ítems comparten documento; los maestros/lotes/recetas se referencian
por string. El diagrama está en `docs/diagramas/modelo_mongo.mmd`; los objetos
embebidos del diagrama no son colecciones independientes.

Se aplican validadores `strict/error` para campos requeridos, tipos BSON, enums,
rangos e ítems. Los importes admiten int32/int64 no negativos y rechazan float;
fechas comerciales y técnicas usan Date, con conversión normalizada a cargo de
la carga/servicios. Se exigen marcas de efectos/origen/trazabilidad en ventas;
hash de pedido y fecha original de pendiente son opcionales. No se exige un hash
ficticio ni una asignación de lotes para historia. Como no hay enum acordado para
`trazabilidad_lotes`, se valida texto no vacío sin imponer nuevos valores públicos.
Se permiten propiedades adicionales para metadata propia de los otros frentes.

Los índices únicos de DNI y matrícula incluyen inactivos. Se crean además los
índices comunes FEFO y pendientes de outbox. No se hace único global `nro_lote`;
un producto puede aparecer en dos líneas de una venta. La unicidad de `id_detalle`
dentro de cada venta usa una expresión del validador: un índice multikey único
no resolvería repeticiones internas. Los índices de lecturas/vista q11 siguen a
cargo de C; este inicializador no invoca ni copia su módulo.

El esquema no reemplaza claves foráneas, sumas entre campos, cobertura coherente,
FEFO ni reglas transaccionales de receta/venta. La prueba deja explícito que
un documento con tipos correctos y referencia inexistente/total incorrecto puede
persistirse: esos rechazos pertenecen a la validación de carga y servicios.

El preflight global revisa documentos y definiciones existentes antes de comenzar
DDL. Adopta colecciones válidas sin validator y reutiliza índices equivalentes;
rechaza datos inválidos, duplicados y definiciones incompatibles. No corrige datos,
reemplaza validadores ajenos ni elimina índices. Requiere escritores pausados;
DDL entre colecciones no es atómico y no se promete rollback ante falla del motor.
Una repetición correcta conserva datos operacionales y catálogo.

Se agregaron nueve ejemplos Extended JSON **ficticios y separados del dataset**,
con prueba de inserción real y guía de base aislada en `docs/esquema_mongo.md`.
Las fechas de esos ejemplos son ilustrativas, no el hoy del sistema. El router
expone `preparar-mongo --base <destino>`, sin requerir Neo4j; `setup` completo
permanece pendiente. La evidencia está en `docs/evidencias/a/parte_03.md`.

Referencias: [schema validation](https://www.mongodb.com/docs/manual/core/schema-validation/),
[modificación de validadores](https://www.mongodb.com/docs/manual/core/schema-validation/update-schema-validation/)
y [unicidad en MongoDB](https://www.mongodb.com/docs/manual/core/index-unique/).

## Parte 4: fuentes, conversiones y validación antes de persistir

Se incorporaron los nueve CSV oficiales en `data/originales/`, con los mismos bytes
y SHA-256 que `datasets_farmared/`, conservado intacto e ignorado. Los conteos reales
son 8 clientes, 5 sucursales, 7 profesionales, 5 proveedores, 13 productos, 18 lotes,
9 recetas, 16 ventas y 22 detalles. La validación confirma encabezados, tipos,
obligatorios, PK/DNI/matrícula únicos, diez referencias y totales históricos.

El lector UTF-8 usa `csv.reader` con comas, comillas y detección de estructura;
convierte explícitamente booleanos, enteros ARS con rango int64, nulos permitidos
y fechas comerciales a medianoche Buenos Aires expresada en UTC. IDs, DNI, CUIT
y teléfonos siguen strings. No se recortan espacios ni reemplazan precios de detalle
por catálogo; también se verifica overflow de subtotales y totales.

Se conserva archivo y línea física por fila. `ErrorDatasets` reúne errores
localizables por campo y no entrega un dataset parcial listo para carga. La CLI
`validar-datasets --directorio ...` no requiere motores ni `.env`; un directorio
repetido permite validar fuentes originales/adicionales juntas, con unicidad y
referencias cruzadas. No se afirma todavía cantidad mínima de adicionales.

El análisis separa integridad del snapshot de elegibilidad operacional actual.
No se rechazan ventas históricas por actividad actual o recetas ya consumidas,
ni se inventa una historia de lotes/traslados/catálogo. Los originales arrojan tres
avisos explícitos: F004 inactivo en V001, PRD012 inactivo en D019 y RC002 con fecha
15/09/2026 en lugar de última venta completada +30 días (14/09). Se preservan los
valores; no se simula que la discrepancia histórica fue corregida o reconstruida.

Cada fuente lleva SHA-256 de los bytes efectivamente leídos, tamaño y filas leídas.
La huella de conjunto canónica incluye versión de interpretación, tabla, orden y
hashes; ignora ubicaciones para ser portable y cambia ante bytes distintos. Es una
preparación para el manifiesto del loader, no idempotencia de persistencia probada.

Contrato y límites: `docs/validacion_datasets.md`. Evidencia de ejecución:
`docs/evidencias/a/parte_04.md` y `validacion_originales.json`. No se efectuaron
escrituras MongoDB/Neo4j ni descuentos, dispensas o eventos de importación.

## Parte 5: carga autoritativa atómica e idempotente

`cargar_mongo(db, rutas)` valida primero, transforma documentos y prepara catálogo
antes de abrir una transacción MongoDB snapshot/majority con sesión del cliente
compartido. Inserta las ocho colecciones de negocio, outbox inicial y manifiesto
en el mismo commit. No importa ni ejecuta servicios B/C/D o conecta a Neo4j.

Se preservan IDs, fechas y precios. Los 22 detalles originales se embeben en 16
ventas. Una completada marca stock aplicado y receta aplicada cuando tiene receta,
sin volver a afectar saldos/contadores; los lotes históricos quedan desconocidos.
Pendientes/anuladas no tienen efectos aplicados. Se añade procedencia de archivo/
fila/huella, sin inventar request_hash ni traslados históricos del farmacéutico.

La colección técnica `manifiestos_carga` conserva versiones, huellas, conteos e
identidades iniciales, eventos, avisos, instante UTC y base_date comercial de la
primera carga. El singleton coordina reintentos; solo se confirma como completa
junto con documentos/eventos. Fecha base e instante se conservan al repetir.

Una repetición lee y verifica identidades en snapshot, sin reemplazar documentos
desde CSV ni reactivar eventos procesados. Fuentes/versiones distintas exigen otra
base o migración; datos previos sin manifiesto no se adoptan. Identidades/eventos
faltantes o manifiesto dañado generan error, no una reparación histórica automática.

Se emiten 58 eventos reales para las seis colecciones proyectables: un UUIDv5
estable por entidad/fuente. No se emiten deltas ni eventos para stock/proveedores.
Hay 81 documentos de negocio y un manifiesto; las estructuras técnicas no se
rellenan artificialmente para sumar registros. El grafo permanece no comprobado.

Las pruebas usan MongoDB replica set real: segunda carga tras modificar stock,
receta y cliente; evento procesado; fuente cambiada; rollback/reintento tras fallas
inyectadas; manifiesto corrupto; dos clientes/snapshots concurrentes; y ACK perdido
inyectado después de un commit efectivo. Las inyecciones no se presentan como una
prueba de SIGKILL o corte físico de red. No se probaron servicios operacionales
q13/q14/q15: los cambios previos al segundo seed son fixtures explícitos.

DDL queda fuera del commit, requiere bootstrap sin escritores y puede dejar
catálogo vacío ante fallo. La transacción única es apropiada al dataset pequeño;
no se promete un cargador masivo ni disponibilidad de un replica set de un miembro.
Los adicionales/manifiesto de generación y su coordinación de base_date siguen
para la parte 6; cambiar el conjunto cargado no se trata como un seed incremental.

Contrato: `docs/carga_mongo.md`. Evidencia: `docs/evidencias/a/parte_05.md` y
`carga_originales.json`. Referencia técnica:
[transacciones PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/).
