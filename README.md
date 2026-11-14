# FarmaRed

Proyecto de Bases de Datos II para administrar una red de farmacias con MongoDB
y Neo4j. Incluye una consola web local y una CLI para cargar datos, ejecutar
consultas, gestionar clientes, registrar ventas y mantener una proyección en grafo.

MongoDB conserva los datos de negocio. Neo4j representa clientes, profesionales,
sucursales, productos, recetas y ventas, con sus relaciones. Los servicios de
escritura generan eventos en un **outbox** de MongoDB; la sincronización aplica esos
eventos a Neo4j y los marca como procesados después de confirmar el cambio.

## Requisitos

- Python **3.11 a 3.14**.
- **uv 0.13.7**, versión usada por el Dockerfile y la configuración de CI.
- Docker con el daemon activo y **Docker Compose v2.24 o posterior**.
- Puertos locales disponibles: `27017` para MongoDB, `7474` y `7687` para Neo4j,
  y `8000` para la consola web.

Las imágenes de desarrollo están fijadas en [infra/docker-compose.yml](infra/docker-compose.yml):
MongoDB **8.0.15** y Neo4j Community **5.26.12**. MongoDB funciona como un replica set
`rs0` de un miembro para permitir transacciones. Las dependencias Python y sus
versiones se definen en [pyproject.toml](pyproject.toml) y [uv.lock](uv.lock).
La UI usa el mismo entorno Python; no requiere Node ni instalar un frontend aparte.

## Inicio rápido

Ejecutar desde la raíz del repositorio.

### 1. Instalar y configurar

```bash
uv sync --locked
python3 infra/preparar_env.py
```

El preparador crea `.env` con una contraseña aleatoria de Neo4j y enlaza
`infra/.env` para Docker Compose y Dev Containers. Conserva un `.env` existente.
Si se creó copiando [.env.example](.env.example), completar `NEO4J_PASSWORD`
antes de iniciar los motores. Los archivos con secretos están ignorados por Git.

### 2. Iniciar los motores

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d mongodb neo4j
docker compose --env-file .env -f infra/docker-compose.yml run --rm mongodb-init
docker compose --env-file .env -f infra/docker-compose.yml up -d --wait --wait-timeout 180 mongodb neo4j
uv run --locked --env-file .env farmared salud
```

`mongodb-init` inicializa `rs0` si falta y espera que exista un primario. Los
contenedores conservan los datos en volúmenes persistentes.

### 3. Abrir la UI

```bash
uv run --locked --env-file .env farmared ui
```

Abrir [http://127.0.0.1:8000](http://127.0.0.1:8000). Para cargar los datos incluidos:

1. Entrar en **Cargar CSVs**.
2. Elegir **CSVs del proyecto → Originales + adicionales**.
3. Presionar **Validar archivos** y revisar los conteos y avisos.
4. Presionar **Importar datos**.

La importación carga MongoDB, prepara sus índices y la vista mensual, prepara las
restricciones de Neo4j y sincroniza los eventos pendientes. Después se pueden
usar las consultas de ambos motores. Iniciar la UI por sí solo no carga datos.

Para elegir otra base MongoDB o un puerto distinto:

```bash
uv run --locked --env-file .env farmared ui --base farmared_demo_pruebas --puerto 8080
```

La UI escucha únicamente en `127.0.0.1`. Ctrl+C detiene el servidor. `--base`
cambia la fuente MongoDB; el grafo sigue siendo el de la conexión Neo4j configurada.
Cambiar de base MongoDB no crea un grafo independiente.

## Funcionalidades de la UI

### Consultas del TPO

La barra lateral permite elegir **Q01–Q15**. Q03 pide el ID del cliente y Q10 el ID
de la sucursal. Q13–Q15 incluyen un editor JSON para los datos de la operación.

Los resultados se muestran como tabla o JSON, con duración y cantidad de filas.
Los objetos anidados se pueden abrir para ver el documento completo, y la
respuesta se puede exportar a JSON. El atajo **Ctrl/⌘ + Enter** ejecuta la consulta.

### Consulta libre

Al cambiar a **Consulta libre**, se carga el filtro, pipeline o Cypher de la
consulta seleccionada, junto con el motor y sus parámetros. Se puede editar y
volver a ejecutar. El selector de ejemplos incluye lecturas, inserciones,
actualizaciones y borrados.

Las fechas de las plantillas Q05, Q06 y Q12 se calculan al cargar la página.
Q11 muestra el pipeline que define la vista de ingresos mensuales. Las consultas
predefinidas se ejecutan con sus implementaciones originales y el reloj del momento.

Se pueden mostrar hasta **500 filas por ejecución**. En las consultas predefinidas,
el límite se aplica después de calcular el resultado. En las escrituras, limita
la respuesta que se muestra, no la cantidad de documentos o nodos afectados.

#### MongoDB

El editor recibe JSON y admite Extended JSON para valores como fechas y ObjectId.
Ejemplo de lectura:

```json
{
  "coleccion": "productos",
  "filtro": {"activo": true},
  "orden": {"nombre": 1}
}
```

Para una agregación, usar `pipeline`:

```json
{
  "coleccion": "ventas",
  "pipeline": [
    {"$group": {"_id": "$estado", "cantidad": {"$sum": 1}}}
  ]
}
```

Las escrituras directas se indican mediante `operacion`:

- `insertOne`: recibe `documento`.
- `insertMany`: recibe `documentos`, con hasta 500 objetos por petición.
- `updateOne` y `updateMany`: reciben `filtro` y `actualizacion`.
- `replaceOne`: recibe `filtro` y `documento`.
- `deleteOne` y `deleteMany`: reciben `filtro`.

Las actualizaciones y reemplazos admiten `upsert: true`. En modificaciones y
borrados se exige un filtro explícito; `{}` selecciona todos los documentos.
Por ejemplo, para modificar un documento previamente insertado en `pruebas_ui`:

```json
{
  "coleccion": "pruebas_ui",
  "operacion": "updateOne",
  "filtro": {"_id": "UI-001"},
  "actualizacion": {"$set": {"nombre": "Actualizado"}}
}
```

Para usar los servicios de negocio desde el editor:

- Q13: `operacion: "q13"`, `accion: "alta"`, `"modificar"` o `"baja"`, y los campos
  `datos` e `id_cliente` según corresponda.
- Q14: `operacion: "q14"` y `pedido`.
- Q15: `operacion: "q15"` e `id_venta`.

Las plantillas de la barra lateral muestran la estructura de cada pedido.
**Las escrituras directas MongoDB no generan eventos outbox.** Q13–Q15 sí mantienen
las reglas de negocio y generan los eventos necesarios para actualizar el grafo.
Después de usar esos servicios, presionar **Sincronizar Neo4j** para proyectarlos.

#### Neo4j

El editor recibe Cypher y los parámetros se completan en un objeto JSON separado.
Por ejemplo:

```cypher
MATCH (c:Cliente {id: $id_cliente})
RETURN c.id AS id, c.nombre AS nombre, c.apellido AS apellido
```

```json
{"id_cliente": "C001"}
```

Admite lecturas y escrituras de datos, como `CREATE`, `MERGE`, `SET`, `REMOVE` y
`DELETE`. Las escrituras se confirman y se muestran sus contadores de cambios.
Las operaciones directas afectan únicamente al motor seleccionado.

El editor rechaza JavaScript MongoDB, etapas `$out`/`$merge`, procedimientos
Cypher `CALL`, `LOAD CSV` y comandos administrativos. Sí admite las subconsultas
`CALL { … }` y `CALL (variables) { … }` utilizadas por Q03.

### Explorar datos

Permite seleccionar una colección o vista MongoDB y revisar:

- Documentos paginados, de 50 en 50.
- Cantidad de documentos.
- Índices de las colecciones.
- Validadores y opciones del esquema.

**Consultar colección** abre una lectura de esa colección en el editor libre.

### Cargar CSVs

Se puede elegir el dataset del proyecto o **Mis archivos** para subir archivos y
carpetas de tu computadora. Los nueve nombres esperados son:

```text
clientes.csv         sucursales.csv       farmaceuticos.csv
proveedores.csv      productos.csv        stock_lotes.csv
recetas.csv          ventas.csv           detalle_ventas.csv
```

El formato usa UTF-8, columnas originales separadas por comas, fechas
`YYYY-MM-DD`, booleanos `True`/`False` e importes enteros. Se validan cabeceras,
valores y referencias entre archivos como un conjunto. Los detalles se incorporan
en `ventas.items`; no se crea una colección separada de detalles.

Para subir originales y adicionales juntos, seleccionar la carpeta `data` completa
para conservar sus subcarpetas y `adicionales/manifiesto.json`. Se admiten hasta
**100 archivos y 10 MiB** por carga. Los bytes se preservan para verificar hashes;
los archivos subidos se procesan temporalmente y se eliminan al terminar.

La validación muestra errores y avisos con archivo, fila, campo y motivo, además
de las filas CSV y los documentos MongoDB resultantes. Solo una validación correcta
habilita **Importar datos**. La huella se comprueba nuevamente al importar.

La primera carga requiere las colecciones de negocio y el outbox vacíos. Si las
mismas fuentes ya fueron cargadas, se verifican y reutilizan sin duplicar registros
ni restablecer stock o recetas modificados. Una fuente diferente o datos ajenos se
rechazan: para probar otro dataset, usar otra base MongoDB.

Pausar escritores externos durante la preparación inicial. La UI serializa las
consultas, importaciones y sincronizaciones de su propia instancia.

### Estado de los motores y sincronización

Muestra la disponibilidad de cada motor, los conteos MongoDB, los eventos outbox
pendientes y los conteos Neo4j por etiqueta y tipo de relación. **Actualizar estado**
vuelve a consultar ambos motores.

La importación CSV sincroniza Neo4j automáticamente. Si ese paso falla, MongoDB
permanece cargado y la UI muestra el diagnóstico de sincronización pendiente.
**Sincronizar Neo4j**, disponible en Cargar CSVs y Estado de los motores, permite
reintentar sin volver a subir los archivos. Repetir la importación también reintenta
los eventos pendientes. La UI procesa tandas de hasta 500 eventos y continúa hasta
agotarlas o encontrar un error.

La sincronización usa `~/.farmared/sync.lock`, compartido con la CLI. Confirma cada
evento en MongoDB después de confirmar la escritura Neo4j. Cero eventos pendientes
es una observación de la cola; la comparación completa del contenido se realiza
con `grafo-verify`.

## Uso por CLI

Consultar la ayuda general o la de cualquier comando:

```bash
uv run --locked farmared --help
uv run --locked farmared q13 --help
uv run --locked farmared grafo-rebuild --help
```

`Config.from_env()` lee variables de entorno y no carga `.env` por sí misma. En los
comandos locales que conectan a motores, usar `--env-file .env` como en los ejemplos.

### Cargar y sincronizar sin UI

Este es el recorrido completo por CLI para una base nueva:

```bash
uv run --locked farmared validar-datasets --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared seed --base farmared --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared preparar-mongo --base farmared
uv run --locked --env-file .env farmared grafo-init
uv run --locked --env-file .env farmared sync --base farmared
```

- `validar-datasets` valida sin conectar a motores ni escribir datos.
- `seed` prepara el esquema base y carga MongoDB de manera idempotente.
- `preparar-mongo` asegura también los índices de consultas y la vista de Q11.
- `grafo-init` prepara las restricciones de unicidad de Neo4j.
- `sync` procesa el outbox de la base MongoDB indicada.

`seed` y `setup --solo-mongo` no sincronizan Neo4j ni preparan la vista de Q11 por
sí solos. `setup --solo-mongo` es una alternativa a `seed` con los mismos argumentos
de base y directorios. **El comando `setup` sin `--solo-mongo` todavía no implementa
el recorrido completo y termina con código 3.** Para una carga completa, usar la UI
o la secuencia anterior.

### Consultas Q01–Q15

Consultas de lectura MongoDB; todas reciben `--base`:

- **Q01:** productos activos con los datos de su proveedor.
- **Q02:** ventas pendientes con farmacéutico, sucursal y total.
- **Q05:** farmacéuticos activos y cantidad de ventas no anuladas de los últimos
  60 días comerciales, incluidos los que no tuvieron ventas.
- **Q06:** recetas prolongadas vigentes con una dispensa prevista antes de hoy,
  junto con el cliente.
- **Q07:** cinco productos con más unidades en ventas completadas.
- **Q08:** lotes con menos de 50 unidades y datos de producto, proveedor y sucursal.
- **Q09:** ventas libres menores a $5000, excluyendo anuladas.
- **Q11:** ingresos del mes actual por farmacéutico, mediante la vista mensual.
- **Q12:** clientes sin ventas registradas en el último año, de cualquier estado.

```bash
uv run --locked --env-file .env farmared q01 --base farmared
uv run --locked --env-file .env farmared q08 --base farmared
uv run --locked --env-file .env farmared q11 --base farmared
```

Consultas de lectura Neo4j:

- **Q03:** historial cronológico de ventas y recetas de un cliente.
- **Q04:** clientes con más de una receta registrada.
- **Q10:** clientes atendidos por profesionales de una sucursal.

```bash
uv run --locked --env-file .env farmared q03 --id-cliente C001
uv run --locked --env-file .env farmared q04
uv run --locked --env-file .env farmared q10 --id-sucursal S001
```

Estas consultas usan la base Neo4j predeterminada del driver y requieren el grafo
sincronizado. `--base` en `sync` elige la fuente MongoDB, no un destino Neo4j.

#### Q13: clientes

Alta, modificación de contacto/cobertura y baja lógica:

```bash
uv run --locked --env-file .env farmared q13 --base farmared alta --datos docs/ejemplos/q13_alta_cliente.json
uv run --locked --env-file .env farmared q13 --base farmared modificar --id-cliente "ID_CLIENTE" --datos docs/ejemplos/q13_cambios_cliente.json
uv run --locked --env-file .env farmared q13 --base farmared baja --id-cliente "ID_CLIENTE"
```

Reemplazar `ID_CLIENTE` por `documento._id` devuelto por el alta. `--datos -` permite
leer JSON desde stdin. El alta requiere nombre, apellido, DNI, ciudad, provincia y
obra social. El DNI es un string de dígitos y debe ser único, incluso entre clientes
inactivos. `Sin cobertura` exige `nro_afiliado: null`; otras coberturas requieren un
afiliado no vacío. La baja conserva las ventas y recetas del cliente.

La modificación admite email, teléfono, ciudad, provincia, obra social y número de
afiliado. Los campos omitidos se conservan. Repetir una modificación equivalente
o una baja ya aplicada no genera eventos nuevos.

#### Q14: registrar una venta

El pedido incluye cliente, farmacéutico, medio de pago e ítems. Los identificadores
deben existir y cumplir las reglas de actividad, receta y stock en la fecha de uso.
Ejemplo para el dataset completo:

```bash
uv run --locked --env-file .env farmared q14 --base farmared --pedido - <<'JSON'
{
  "id_venta": "DEMO-UI-V001",
  "id_cliente": "A-C001",
  "id_farmaceutico": "A-F001",
  "medio_pago": "Efectivo",
  "items": [{"id_producto": "A-PRD001", "cantidad": 1}]
}
JSON
```

`--pedido` también acepta una ruta de archivo JSON. La CLI genera `id_venta` si se
omite y lo devuelve en la respuesta. Para reintentar sin duplicar, conservar ese ID.
La UI y la función de servicio requieren que el pedido incluya `id_venta`.

La operación calcula el total con precios actuales, descuenta stock por FEFO
(primero vence, primero sale), aplica la dispensa cuando corresponde y confirma
venta, lotes, receta y outbox en una sola transacción. Un rechazo revierte esa
transacción. Repetir el mismo pedido con el mismo `id_venta` reutiliza la venta;
usar ese ID con otro pedido produce un conflicto.

#### Q15: completar una venta pendiente

```bash
uv run --locked --env-file .env farmared q15 --base farmared --id-venta V011
```

Revalida la venta, aplica FEFO y la dispensa correspondiente, y la deja completada.
Una venta completada con stock ya aplicado no vuelve a descontarse. Una venta
anulada o inconsistente se rechaza. Q14 ya aplica este descuento dentro de su propia
transacción; Q15 permite procesar una venta que seguía pendiente.

Después de Q13, Q14 o Q15, actualizar la proyección:

```bash
uv run --locked --env-file .env farmared sync --base farmared
```

### Salud, verificación y reconstrucción

```bash
uv run --locked farmared estado
uv run --locked --env-file .env farmared salud
uv run --locked --env-file .env farmared salud --motor mongo
uv run --locked --env-file .env farmared salud --motor neo4j
uv run --locked --env-file .env farmared sync --base farmared --max-eventos 0
uv run --locked --env-file .env farmared grafo-verify --base farmared
```

`estado` informa la versión y el reloj, sin comprobar conexiones. `salud` verifica
los motores seleccionados, pero no certifica la proyección. `sync --max-eventos 0`
solo observa los pendientes; otros valores limitan cuántos eventos se procesan.

`grafo-verify` compara propiedades, tipos, nodos y relaciones. Sin una declaración
de escritores pausados, el resultado es un diagnóstico puntual y el comando sale
con código 1. Cuando los escritores estén efectivamente pausados, se puede ejecutar:

```bash
uv run --locked --env-file .env farmared grafo-verify --base farmared --confirmar-escrituras-pausadas
```

Para reconstruir un grafo en un **entorno aislado**, con escritores y sincronizador
pausados:

```bash
uv run --locked --env-file .env farmared grafo-rebuild --base farmared --confirmar-entorno-aislado --confirmar-escrituras-pausadas --confirmar-sincronizador-pausado
```

Si ya contiene entidades propias de la proyección, la reconstrucción requiere
además `--confirmar-actualizacion-existente`. Revisar el destino antes de usarla.
`sync`, `grafo-verify` y `grafo-rebuild` admiten `--lock-path` para usar un archivo de
exclusión alternativo cuyo directorio ya exista. Todos los consumidores del mismo
entorno deben compartir el lock; la UI usa la ruta predeterminada.

### Demo de transacciones y reinicio de una base de prueba

La demo requiere una base `farmared_demo_` con sufijo y los dos conjuntos CSV:

```bash
uv run --locked --env-file .env farmared seed --base farmared_demo_pruebas --directorio data/originales --directorio data/adicionales
uv run --locked --env-file .env farmared demo-transaccion --base farmared_demo_pruebas
```

Muestra escenarios de éxito, rechazo y reintento, con estados antes y después.
`--salida /tmp/farmared-demo.json` guarda la evidencia en un archivo nuevo.
La demo modifica ventas, stock y recetas. Sus resultados dependen del reloj y de
los vencimientos del dataset; el recorrido de ventas puede usarse sin Neo4j.

Para inspeccionar el destino de un reset, sin borrar:

```bash
uv run --locked --env-file .env farmared reset-demo --solo-mongo --base farmared_demo_pruebas
```

Para **borrar toda esa base MongoDB**, pausar escritores y sincronizador y confirmar
el nombre exacto:

```bash
uv run --locked --env-file .env farmared reset-demo --solo-mongo --base farmared_demo_pruebas --confirmar-base farmared_demo_pruebas
```

El reset solo admite bases `farmared_demo_` con sufijo. No elimina Neo4j, archivos
ni volúmenes, ni vuelve a cargar datos. Si el grafo conservaba la proyección de esa
base, revisar o reconstruir ese destino antes de volver a usarlo.

## Datasets

- `data/originales/`: nueve CSVs con 81 documentos de negocio y 58 eventos iniciales.
- `data/adicionales/`: nueve CSVs y un manifiesto reproducible con fecha base
  **2026-11-10**.
- Ambos conjuntos: **169 documentos de negocio y 120 eventos iniciales**. Los 38
  detalles se incorporan en las 28 ventas.

La carga inicial registra también un manifiesto técnico. Los conteos anteriores no incluyen
el outbox, el manifiesto ni las vistas. Son conteos del dataset inicial, no del
estado actual después de ejecutar operaciones de escritura.

Para verificar los adicionales incluidos o generar otros relativos a una fecha:

```bash
uv run --locked farmared generar-adicionales --directorio data/adicionales
uv run --locked farmared generar-adicionales --directorio data/adicionales_nuevos --base-date 2026-11-14
uv run --locked farmared validar-datasets --directorio data/originales --directorio data/adicionales_nuevos
```

Usar un directorio nuevo para otra generación y otra base para cargar fuentes
diferentes. Omitir `--base-date` usa el día actual al crear los archivos. Las fuentes
existentes se verifican y conservan; no se sobrescriben. Las consultas temporales
usan el día comercial de `America/Argentina/Buenos_Aires`, por lo que sus respuestas
y los escenarios de ventas pueden cambiar con el tiempo.

## Configuración

Las claves de conexión están documentadas en [.env.example](.env.example):

- `MONGO_URI`: URI del replica set; desde el host incluye `directConnection=true`.
- `MONGO_DB`: base MongoDB predeterminada; por defecto, `farmared`.
- `NEO4J_URI`: conexión Bolt; por defecto, `bolt://localhost:7687`.
- `NEO4J_USER` y `NEO4J_PASSWORD`: credenciales de Neo4j.
- `DB_TIMEOUT_MS`: timeout de conexión/operaciones, de 1 a 300000 ms; por defecto,
  10000 ms.
- `COMPOSE_PROJECT_NAME`, `MONGO_PORT`, `NEO4J_HTTP_PORT` y `NEO4J_BOLT_PORT`:
  proyecto y puertos publicados por Docker Compose.

Si se cambian los puertos publicados, actualizar también las URI del host.
Los servicios se publican en `127.0.0.1`. MongoDB no usa autenticación en este
entorno de desarrollo; Neo4j sí. Su navegador está en
[http://localhost:7474](http://localhost:7474), con las credenciales de `.env`.
Cambiar la contraseña en `.env` no rota la de un volumen Neo4j ya inicializado.

Para detener los motores conservando los volúmenes:

```bash
docker compose --env-file .env -f infra/docker-compose.yml down
```

### Dev Containers

La configuración de [.devcontainer](.devcontainer) prepara `.env`, construye el
entorno con Python y uv, espera los motores y ejecuta la instalación y la comprobación
de salud. Usar **Reopen in Container** en un editor compatible.

Dentro de `/workspaces/farmared`, los servicios reciben las URI internas mediante
variables de entorno; omitir `--env-file .env`:

```bash
uv run --locked farmared salud
uv run --locked farmared ui
```

Para abrir la UI desde el host, reenviar el puerto `8000` mediante la herramienta de
puertos del editor. La configuración solicita automáticamente el puerto `7474` de
Neo4j Browser. El entorno Python del contenedor vive en `/opt/farmared-venv`, separado
de `.venv` del host.

## Pruebas

La ejecución predeterminada omite las integraciones que requieren motores:

```bash
uv run --locked pytest
```

Para pruebas contra los motores de `.env`:

```bash
FARMARED_TEST_MONGO=1 uv run --locked --env-file .env pytest tests/carga tests/c_mongo tests/ventas
FARMARED_TEST_UI=1 uv run --locked --env-file .env pytest tests/ui
FARMARED_TEST_INTEGRACION=1 uv run --locked --env-file .env pytest tests/infra
```

Las pruebas de grafo y sincronización usan contenedores aislados. Requieren Docker
y las imágenes fijadas en el Compose descargadas:

```bash
FARMARED_TEST_GRAFO=1 uv run --locked pytest tests/d_grafo/test_esquema_integracion.py tests/d_grafo/test_proyecciones_integracion.py tests/d_grafo/test_consultas_integracion.py
FARMARED_TEST_SYNC=1 uv run --locked pytest tests/d_grafo/test_consumidor_integracion.py tests/d_grafo/test_reconstruccion_integracion.py tests/d_grafo/test_q13_integracion.py
FARMARED_TEST_CLI=1 uv run --locked pytest tests/d_grafo/test_cli_grafo_integracion.py
FARMARED_TEST_UI_SYNC=1 uv run --locked pytest tests/d_grafo/test_ui_sync_integracion.py
```

Las pruebas de integración crean y limpian sus bases o contenedores de prueba.
Los resúmenes de pytest indican qué casos se ejecutaron y cuáles se omitieron.
La configuración de [CI](.github/workflows/ci.yml) verifica Python 3.11–3.14,
validación de datasets, construcción del paquete e integración con motores.

## Estructura del repositorio

- `src/farmared/ui/`: servidor local, consultas editables, carga CSV y sincronización.
- `src/farmared/consultas/`: consultas y operaciones Q01–Q15.
- `src/farmared/servicios/`: reglas de clientes, ventas, recetas y stock.
- `src/farmared/carga/`: lectura, validación, transformación y carga de CSVs.
- `src/farmared/esquema/`: validadores, índices, manifiestos y vista MongoDB.
- `src/farmared/grafo/` y `src/farmared/proyeccion/`: esquema Neo4j, mapeos y outbox.
- `infra/` y `.devcontainer/`: motores y entorno de desarrollo.
- `data/`: datasets originales y adicionales.
- `tests/`: pruebas unitarias y de integración.
- `docs/`: ejemplos, informes y evidencias complementarias.

## Problemas frecuentes

- **MongoDB no tiene primario:** ejecutar `mongodb-init` y revisar
  `docker compose --env-file .env -f infra/docker-compose.yml ps`.
- **Neo4j no conecta:** revisar la salud del contenedor, la URI y las credenciales.
  Un volumen existente conserva su contraseña anterior.
- **La base está vacía en la UI:** verificar el nombre mostrado en pantalla y cargar
  los CSVs; se puede seleccionar otra base al iniciar con `--base`.
- **MongoDB tiene datos pero Neo4j está vacío:** usar **Sincronizar Neo4j** en la UI,
  o ejecutar `grafo-init` y `sync --base farmared` por CLI. Si falla un evento,
  revisar el diagnóstico y reintentar después de corregir su causa.
- **No hay pendientes pero el grafo difiere:** ejecutar `grafo-verify`. La
  sincronización procesa eventos; no repara por sí sola cambios que se hicieron
  directamente en un motor sin generar eventos.
- **Q11 indica que falta la vista:** ejecutar `preparar-mongo --base farmared`.
- **Una carga informa conflicto:** revisar la base y las fuentes. Para otro dataset,
  elegir otra base; el seed no sobrescribe una carga diferente.
- **El puerto de la UI está ocupado:** usar `farmared ui --puerto 8080` con el
  mismo prefijo `uv run --locked --env-file .env` de los ejemplos.
