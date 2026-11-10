# Integración real — datasets oficiales y adicionales

Ejecución: 10/11/2026, Windows. MongoDB 8.0.15, replica set rs0; Neo4j Community
5.26.12. Se reutilizó infra/docker-compose.yml sin cambios, con proyectos UUID,
puertos locales dinámicos y volúmenes independientes. No se insertaron documentos
sintéticos en esta demostración.

[Resumen verificado](ejecucion_20261110T200351_47f54ba4/resumen.json) y
[comandos completos, parámetros y salidas](ejecucion_20261110T200351_47f54ba4/comandos.json).
Las credenciales se generaron con el mecanismo de A, en archivos temporales.

| Paso | Evidencia | Resultado |
| --- | --- | --- |
| validar-datasets | [Validación](ejecucion_20261110T200351_47f54ba4/01_validacion.json) | 207 registros CSV, cero errores |
| salud | [Motores disponibles](ejecucion_20261110T200351_47f54ba4/02_salud.json) | Ambos disponibles |
| preparar-mongo / seed | [Carga de A](ejecucion_20261110T200351_47f54ba4/04_seed.json) | 169 documentos de negocio |
| grafo-init | [Restricciones](ejecucion_20261110T200351_47f54ba4/06_restricciones.json) | Seis restricciones; grafo vacío |
| sync | [Primera sincronización](ejecucion_20261110T200351_47f54ba4/07_sync_inicial.json) | 120 procesados, cero fallidos y pendientes |
| grafo-verify | [Equivalencia](ejecucion_20261110T200351_47f54ba4/08_verificacion.json) | Sin diferencias |
| sync repetido | [Idempotencia](ejecucion_20261110T200351_47f54ba4/17_sync_repetida.json) | Cero procesados; grafo y consultas idénticos |
| grafo-rebuild | [Otro Neo4j vacío](ejecucion_20261110T200351_47f54ba4/22_reconstruccion.json) | habilitable=true |
| grafo-verify recuperado | [Equivalencia posterior](ejecucion_20261110T200351_47f54ba4/23_verificacion_recuperada.json) | Sin diferencias |

MongoDB: clientes 18, sucursales 15, farmacéuticos 17, proveedores 15, productos 23,
stock_lotes 34, recetas 19 y ventas 28. Los 38 detalles están embebidos en ventas.items.
Neo4j: 120 nodos y 142 relaciones: REALIZO 28, TIENE_RECETA 19, TRABAJA_EN 17,
ATENDIDA_POR 28, CONTIENE 38 y USA_RECETA 12. No proyecta proveedores ni stock_lotes.

## Consultas reales

Las [referencias independientes MongoDB](ejecucion_20261110T200351_47f54ba4/14_referencias_mongo.json)
incluyen agregaciones y resultados: coincidencia exacta, no solo de cantidades.

- `python -m farmared q03 --id-cliente C001`: [salida completa](ejecucion_20261110T200351_47f54ba4/11_q03.json).
  Seis eventos: RC001 y V003 (10/09), V015 anulada (25/09), V013 (02/10), RC008 y V010
  (08/10), todos de 2026. Cuatro ventas y dos recetas, precios históricos, detalles
  y ventas sin receta. C008 existe y devuelve [historial vacío](ejecucion_20261110T200351_47f54ba4/16_q03_sin_historial.json).
- `python -m farmared q04`: [salida completa](ejecucion_20261110T200351_47f54ba4/12_q04.json).
  A-C001, A-C008, C001, C002 y C006: dos recetas cada uno.
- `python -m farmared q10 --id-sucursal A-S002`: [salida completa](ejecucion_20261110T200351_47f54ba4/13_q10.json).
  A-C002, A-C003 y A-C009. La [selección](ejecucion_20261110T200351_47f54ba4/10_seleccion_identificadores.json)
  registra farmacéuticos inactivos y estados de ventas. Se contrastaron también
  [las 15 sucursales](ejecucion_20261110T200351_47f54ba4/15_auditoria_q10.json), según la sucursal
  actual del farmacéutico, sin filtrar activo ni estado.

Fechas JSON en ISO 8601. Se conserva stderr: notificaciones Neo4j 01N52 por tokens
en un grafo vacío o nombre_al_vender opcional ausente no impiden ejecución ni
comparación exacta. Los avisos del validador se conservan; no son errores.

## Reproducción y seguridad

```powershell
.venv/Scripts/python.exe -X utf8 docs/evidencias/d/e2e_oficial/ejecutar.py
.venv/Scripts/python.exe -X utf8 docs/evidencias/d/e2e_oficial/probar_suites.py
```

[ejecutar.py](ejecutar.py) usa el loader de A y la CLI integrada, aborta si falla
la validación y crea otra carpeta de resultados en cada ejecución. El lock temporal
es común a sync, verify y rebuild. Se declara pausa efectiva de escritores y se
exigen las tres confirmaciones administrativas para reconstruir en otro Neo4j vacío.
No se borró el grafo original ni se alteró manualmente outbox.

Se comprobaron hashes de los 18 CSV y manifiesto antes/después, cantidades y precios
contra detalle_ventas, stock importado, huella de documentos de negocio durante
sync y huella de MongoDB incluida outbox durante rebuild. El grafo original quedó
intacto. Los proyectos propios y volúmenes fueron retirados; se conservaron todos
los recursos preexistentes. Las bases temporales ya no están disponibles; persisten
las salidas completas para revisión.

## Pruebas automatizadas separadas

[probar_suites.py](probar_suites.py) habilita todas las integraciones sobre otro
proyecto aislado. Sus fixtures sintéticos se distinguen del dataset de arriba.
[Registro de suites](ejecucion_20261110T200857_407e5f2d/pruebas.json).

Se corrigió solo el aislamiento del fixture CLI de D: Compose prioriza variables
heredadas sobre --env-file. El fixture pasa su clave y puertos efímeros explícitamente.
[Reproducción sin secretos](aislamiento_fixture_cli.json), mediante compose config.
No se cambió lógica de negocio ni infraestructura.

La sincronización sigue siendo bajo demanda. La equivalencia requiere estado fuente
estable y ausencia de sincronizadores superpuestos. No se verificó Codespaces alojado
ni se implementó sincronización continua o transacción distribuida.

[Auditoría final de fuentes](ejecucion_20261110T200351_47f54ba4/auditoria_final_fuentes.json):
los 19 archivos son byte a byte iguales a HEAD, sus SHA-256 no cambiaron durante
la ejecución y Compose permanece intacto. Git puede conservar marcas de checkout
por la corrección previa de EOL; no hay diferencias de contenido en data/.

Resultado final de pruebas (integraciones habilitadas):

| Suite | Aprobadas | Omitidas | Fallidas |
| --- | ---: | ---: | ---: |
| Persona D | 271 | 0 | 0 |
| General | 550 | 2 | 0 |

Las dos omisiones son específicas de Windows: modo POSIX 0600 y privilegio de
symlink ausente. No hay fallas ni regresiones nuevas. Se habilitaron explícitamente
FARMARED_TEST_GRAFO, FARMARED_TEST_SYNC, FARMARED_TEST_CLI, FARMARED_TEST_MONGO y
FARMARED_TEST_INTEGRACION. La limpieza terminó correctamente: cero contenedores
activos de esta ejecución y únicamente los tres volúmenes preexistentes conservados.

Archivos de este prompt: ejecutar.py, probar_suites.py, este índice, registros JSON
de ambas ejecuciones y aislamiento_fixture_cli.json; actualización del índice D,
informe y bloque propuesto para README. Única corrección de código: entorno propio
en tests/d_grafo/test_cli_grafo_integracion.py. No se cambiaron módulos productivos,
CLI común, infraestructura, CSV ni manifiesto durante este prompt. Los cambios
previos que ya estaban en el workspace se conservaron sin sobrescribirlos.
