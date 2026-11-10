# Persona D — Auditoría final de requisitos y entrega

Fecha: 10/11/2026. Alcance: revisión del código, contratos, pruebas, documentación,
evidencia oficial y estado local de entrega de Persona D. No certifica las
funcionalidades de A/B/C ni la entrega académica completa del equipo.

**Dictamen:** la contribución funcional de D está implementada y preparada para
integración. No se detectaron errores bloqueantes de D. El cierre del equipo
requiere integrar el texto al informe PDF/README, validar Codespaces alojado y
completar/revisar los servicios de los otros integrantes. No se agregaron nuevas
funcionalidades ni se cambiaron contratos compartidos durante esta auditoría.

## Fuentes, prioridad y trazabilidad

1. Se leyó completa la copia local de **TPO_FarmaRed.pdf**, siete páginas, localizada
   a partir de la referencia de docs/informe/a_infra_y_carga.md. No estaba en el
   repositorio. La extracción reproducible se conserva en
   [consigna_extraida.json](../evidencias/d/auditoria_final/consigna_extraida.json),
   con número de página y SHA-256 del PDF. Es el texto normativo académico utilizado.
2. Se revisó **FarmaRed_Plan_Definitivo_TPO_BD2.md**, versión 3.0, 08/11/2026,
   también disponible como archivo local externo al repositorio. Las secciones 5,
   7, 8 y 13 proponen modelo, sincronización, consultas y trabajo de D. Es un plan,
   no evidencia de implementación ni reemplazo de la consigna.
3. **FarmaRed_reparto_equipo_4_personas.md**, citado por A, no se localizó en el
   repositorio ni en Downloads. No se afirma haberlo revisado. La asignación de
   D se toma del pedido explícito del usuario, consistente con el plan; cambios
   de responsabilidad del resto del equipo requieren el reparto formal.
4. Los prompts del usuario establecen los contratos adicionales de proyección,
   outbox, seguridad y recuperación. No se atribuyen estas decisiones a un mandato
   textual del PDF. Los contratos vigentes son los de src/farmared/contratos.py.

[Identificación y hashes de fuentes](../evidencias/d/auditoria_final/fuentes_requisitos.json).
No se depende de la ruta personal del PDF para ejecutar FarmaRed: la extracción
y esta identificación quedan en la entrega.

Convenciones de la matriz: **cumplido** = implementación y evidencia verificadas;
**parcial** = solo parte demostrada o integración conjunta pendiente;
**pendiente** = entregable identificado que aún falta; **no verificable** = fuente
o comprobación requerida no disponible. El estado es respecto del alcance indicado,
no una garantía universal de consistencia o escalabilidad.

## Matriz de requisitos de Persona D

Abreviaturas de evidencia: [E2E](../evidencias/d/e2e_oficial/README.md) = oficiales
más adicionales; [T9](../evidencias/d/e2e_oficial/ejecucion_20261110T200857_407e5f2d/pruebas.json)
= pruebas reales previas; T10 se enlaza en la sección de pruebas de esta auditoría.
Los nombres de tests son localizables en tests/d_grafo/; sus fixtures se identifican
como sintéticos y no se presentan como resultados oficiales.

| Requisito / origen | Responsable | Estado | Archivo y función | Prueba verificadora | Evidencia | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| Uso persistente de grafos, PDF §3.1 y §3.2 | D / equipo | Cumplido | grafo/proyecciones.py: proyectar_documentos; consultas/q*.py | test_modelo_completo_y_consultas_reales | E2E 09, 11–13 | Neo4j responde consultas reales; no se afirma superioridad de rendimiento |
| Seis etiquetas e identidad estable, plan §5 / prompts | D | Cumplido | grafo/mapeos.py: ETIQUETAS, mapear_documento | test_mapeo_campos_tipos_y_sin_mutacion | E2E 09 | _id → id string; solo las seis colecciones proyectables |
| Seis unicidades no destructivas | D | Cumplido | grafo/esquema.py: preparar_grafo | test_restricciones_idempotencia_preservacion_y_detalles; test_nombre_incompatible_se_informa_antes_del_ddl | E2E 05–06 | IF NOT EXISTS más inspección real; DDL incremental |
| Relaciones y cardinalidades, PDF §2.10 / plan §5 | D | Cumplido | grafo/mapeos.py: RELACIONES; proyecciones.py: proyectar_documentos | test_modelo_completo_y_consultas_reales; test_venta_reasigna_cliente_y_profesional_sin_tocar_otra_venta | E2E 08–09 | Cardinalidades se mantienen por aplicación, no mediante restricciones relacionales Neo4j |
| Fechas comerciales y opcionales | D | Cumplido | grafo/mapeos.py: fecha_comercial; consultas/q03.py: _fecha_comercial | test_fecha_comercial_antes_de_extraer_dia; test_fecha_invalida_o_sin_zona; test_q03_historial_exacto_neo4j | E2E 08, 11, 14 | UTC → Buenos Aires → date; null retira propiedad; no se inventa nombre histórico |
| Importes enteros y precios históricos, PDF §2.9 / §2.11 | D | Cumplido | grafo/mapeos.py: _entero, mapear_documento | test_opcionales_ausentes_y_bson_int64; test_modelo_completo_y_consultas_reales | E2E 11, resumen y referencias | bool no se acepta como cantidad; sin usar precio actual de catálogo |
| Líneas repetidas independientes | D | Cumplido | grafo/proyecciones.py: reconciliación CONTIENE | test_reconciliar_items_producto_receta_y_aislar_otras_ventas | T9 / T10 | Identidad lógica venta/id_detalle; CREATE por línea después de retirar estado previo |
| Sin nodos incompletos o referencias silenciosas, PDF §3.3 / prompts | D | Cumplido | mapeos.py; proyecciones.py: _exigir_dependencia, _exigir_uno | test_dependencia_faltante_rollback_completo; test_dependencia_incompleta_no_se_adopta | T9 / T10 | Requiere documentos completos; si falla debe abortarse el callback, no capturar y confirmar |
| Reconciliar relaciones propias sin borrar otras entidades | D | Cumplido | grafo/proyecciones.py: proyectar_documentos | test_farmaceutico_cambia_sucursal_sin_usar_venta_id_sucursal; test_receta_reasigna_titular_y_quita_fecha_opcional | T9 / T10 | Reemplaza REALIZO, ATENDIDA_POR, USA_RECETA, CONTIENE, TIENE_RECETA o TRABAJA_EN del agregado correspondiente |
| Q03: historial completo por argumento, PDF p.6 #3 / p.7 | D | Cumplido | consultas/q03.py: q03_historial, CYPHER | test_resultados_exactos_y_conversion_de_fechas; test_q03_historial_exacto_neo4j | E2E 11, 14, 16 | Incluye todos los estados y clientes inactivos; inexistente/vacío → [] |
| Q03: sin producto cartesiano, ítems ordenados | D | Cumplido | consultas/q03.py: UNION ALL, collect, ORDER BY global | casos_q03 y test_q03_historial_exacto_neo4j | E2E 11 | Un evento por venta/receta; desempates fecha/tipo/ID e ítems orden/id_detalle |
| Q04: más de una receta y cantidad, PDF p.6 #4 | D | Cumplido | consultas/q04.py: q04_clientes_con_recetas | test_q04_resultado_exacto_orden_y_sin_duplicados; test_q04_cero_una_dos_tres_recetas_e_inactivo | E2E 12, 14 | count(DISTINCT r), sin filtros de estado; cantidad DESC, ID ASC |
| Q10: vía farmacéutico activo o no, PDF p.6 #10 | D | Cumplido | consultas/q10.py: q10_clientes_sucursal | test_q10_resultado_exacto_inactivos_y_todos_los_estados; test_farmaceutico_cambia_sucursal_sin_usar_venta_id_sucursal | E2E 13–15 y quince salidas de sucursal | Usa TRABAJA_EN actual; no ventas.id_sucursal; clientes únicos, ID ASC |
| Consultas de lectura, parámetros y cierre | D | Cumplido | consultas/q03.py, q04.py, q10.py: execute_read | test_consultas_no_modifican_el_grafo; test_errores_reales_se_propagan_y_se_cierra_la_sesion | T9 / T10 | Cypher parametrizado; Q03 valida ID; Q10 recibe argumento y CLI valida no vacío; no cierra driver del llamador |
| Contrato de outbox emitido por A | D consume / A emite | Cumplido | proyeccion/estado.py: validar_evento; consumidor.py: sincronizar | test_evento_invalido; test_varias_afectadas_sin_duplicar_dependencias | E2E 04, 07 | _id, afectadas[], procesado, creado_en; no campos técnicos nuevos |
| Evento y documentos en una lectura consistente | D | Cumplido | proyeccion/consumidor.py: _leer_snapshot | test_snapshot_real_cambio_concurrente_y_sesion_cerrada | T9 / T10 | Transacción snapshot, primario; lectura finalizada antes de Neo4j |
| Dependencias completas, orden y ciclos | D | Cumplido | proyeccion/dependencias.py: resolver_documentos | test_resuelve_venta_con_productos_repetidos_una_vez_y_orden; test_ciclo_explicito; test_documento_o_dependencia_faltante | T9 / T10 | DFS postorden; no requiere consumir maestros antes; relee estado actual |
| Una transacción Neo4j por evento | D | Cumplido | consumidor.py: sincronizar → execute_write(proyectar_documentos) | test_rollback_real_durante_escritura; test_snapshot_cerrado_commit_neo4j_y_luego_ack | T9 / T10 | No commits por nodo ni transacción Mongo abierta durante escritura Neo4j |
| Ack individual posterior al commit | D | Cumplido | estado.py: confirmar_evento; consumidor.py: sincronizar | test_confirma_resultado_condicional; test_f_commit_neo4j_ack_fallido_y_reentrega | T9 / T10 | Update condicionado a _id y procesado=False; verifica resultado |
| Reintentos convergentes y errores sin bucle infinito | D | Cumplido | consumidor.py: sincronizar; estado.py: diagnostico | test_b_reentrega_idempotente; test_e_estado_actual_incluso_evento_antiguo; test_error_neo4j_sin_ack_y_sin_reintento_infinito | E2E 17–21, T9 / T10 | Un fallo detiene la invocación; nuevo intento explícito; no aplica deltas históricos |
| Exclusión real entre procesos y liberación | D | Cumplido | proyeccion/exclusion.py: exclusion | test_bloqueo_real_otro_proceso_y_liberacion_por_caida; test_g_dos_sincronizaciones_excluidas | T9 / T10 | msvcrt Windows / flock POSIX; mismo archivo obligatorio; no exclusión distribuida |
| Conectividad y diagnóstico sin éxito falso | D | Cumplido | consumidor.py; cli_grafo.py: ejecutar | test_c_neo4j_realmente_inaccesible_y_recuperacion; test_error_mongo_lectura_sin_neo4j; test_errores_reales_no_son_exito_ni_exponen_credenciales | T9 / T10 | Mongo real disponible; caída física Mongo no inyectada: su error de lectura se prueba con dobles |
| Reconstruir todas las entidades, independiente de outbox | D | Cumplido | proyeccion/fuente.py: leer_fuente; reconstruccion.py: reconstruir_grafo | test_c_outbox_historica_procesada_no_se_reinicia; test_seis_colecciones_snapshot_y_orden_sin_outbox | E2E 22–26 | Seis colecciones completas; no consulta ni cambia outbox |
| Guardas administrativas y destino dedicado | D | Cumplido | reconstruccion.py: _validar_destino, reconstruir_grafo; cli_grafo.py | test_destino_ajeno_y_restricciones_conservadas; test_rebuild_sin_todas_confirmaciones_no_conecta | T9 / T10 | Rechaza datos/restricciones ajenos o sobrantes; no hay purga ni DELETE de nodos |
| Verificación posterior y habilitable | D | Cumplido | reconstruccion.py: _reconstruir_tx; verificacion.py: comparar | test_a_inicial_todas_entidades_consultas_y_g_detalles; test_e_falla_durante_escrituras_rollback_y_recuperacion | E2E 22–26 | Comparación dentro de la transacción; habilitable solo tras commit conocido y verificación exitosa |
| Reentrega posterior y protección MongoDB | D | Cumplido | reconstruccion.py; consumidor.py | test_f_reentrega_pendientes_tras_reconstruccion; test_e_falla_durante_escrituras_rollback_y_recuperacion | E2E resumen: huellas Mongo/outbox intactas | Sin marcas masivas ni mutación de documentos de negocio |
| Diagnóstico de equivalencia de contenido y tipos | D | Cumplido | verificacion.py: leer_grafo, comparar, verificar_proyeccion | test_d_diferencias_exactas_reales; test_misma_cantidad_no_es_equivalencia_y_fecha_incorrecta; test_detalle_duplicado_entre_productos_distintos | E2E 08, 21, 23 | Nodos, relaciones, extras, duplicados, precios y fechas; no expone valores personales completos |
| CLI registrada, fechas ISO, errores y seguridad | D / punto de entrada A | Cumplido | cli_grafo.py: registrar_comandos, ejecutar; __main__.py: main | test_registro_y_ayuda_sin_importar_drivers; test_argumentos_requeridos_e_invalidos; test_consultas_delegacion_y_fechas_iso; test_cli_real_compose_y_evidencia_fixture | E2E comandos.json | Siete comandos; 0 éxito, 1 operación/diagnóstico no certificado, 2 argparse; sin dependencias B/C |
| Resultados oficiales y recuperación aislada | D | Cumplido | docs/evidencias/d/e2e_oficial/ejecutar.py | Comparaciones/asserts del runner E2E | E2E resumen, referencias, limpieza | No se regeneró esta evidencia en la auditoría; fuentes conservadas |
| Informe técnico y resumen para integrar | D | Cumplido | d_grafo_y_sincronizacion.md; d_resumen_para_integracion.md | Revisión documental y enlaces | Esta auditoría | Texto antiguo corregido; resultados históricos rotulados |

## Requisitos generales y dependencias del equipo

| Requisito / origen | Responsable | Estado | Archivo / implementación | Prueba o revisión | Evidencia | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| Dos motores NoSQL justificados, PDF §3.1 | Equipo; aporte D | Cumplido | Compose A; modelo Mongo A; modelo Neo4j D | salud y ejecución E2E | E2E 02, 08–13; resumen de integración | Comprobado uso real de ambos; no certifica las otras consultas |
| CSV, adicionales y carga reproducible, PDF §2 y §3.3 | A; uso D | Cumplido | carga/validacion.py, carga/mongo.py | validar-datasets, seed y suite de carga | E2E 01, 04; auditoría SHA | 207 registros, 169 documentos; ningún CSV/manifiesto modificado |
| Codespaces completamente operativo, PDF §3.3 / §5.1 | A / equipo | Parcial | .devcontainer/, infra/ y README.md | Configuración disponible; pruebas Windows/Docker y registros previos Linux | Portabilidad y E2E | No se ejecutó Codespace alojado; verificar con otro integrante antes de entregar |
| q01–q15 y servicios atómicos q14/q15, PDF §4 | B/C y equipo; D solo 3/4/10 | Parcial | __main__.py registra otras consultas como PENDIENTES | No se certifica implementación ajena | Código CLI actual | No ampliar D para completar servicios ajenos; validar integración emisora de outbox |
| Setup conjunto y README con todas las consultas, PDF §5.1 | A/C/D coordinados | Parcial | cli/setup.py, README.md; bloque D preparado | Comandos D independientes verificados | d_bloque_readme.md | setup general aún requiere orquestación conjunta; no reescribir README ajeno |
| PDF final con 15 consultas y evidencia, PDF §5.2 | Equipo | Pendiente | Informe técnico D y resumen listos; PDF final no localizado | Inventario de archivos | d_resumen_para_integracion.md | Integrar carátula, otras personas, código/salidas y conclusiones |
| Reparto formal vigente | Equipo | No verificable | Archivo citado por A no localizado | Búsqueda repo y Downloads | fuentes_requisitos.json | La asignación de D sí es explícita en el pedido del usuario |
| Historial de commits y número de integrantes, PDF pp.1 y 7 | Equipo | No verificable | No se hizo auditoría de autoría/remoto ni commits | Revisión local de cambios únicamente | revision_entrega.json | PDF dice cuatro en p.1 y tres en p.7; aclaración académica del equipo |

## Revisión del modelo y las consultas

Se comprobaron las seis etiquetas y sus unicidades; las referencias tienen
cardinalidad N:1 para sucursal del farmacéutico, titular de receta, cliente y
farmacéutico de venta, y 0..1 para receta de venta. Cliente tiene 0..N ventas y
recetas; Venta tiene 1..N detalles en los documentos fuente válidos. La consulta
Q03 tolera además un fixture de venta sin detalles devolviendo items=[]. Producto
puede ser destino de varias líneas incluso en una misma venta. La aplicación
reconcilia estas cardinalidades; usuarios que escriban directamente en Neo4j pueden
violarlas. Q03 no valida múltiples USA_RECETA al consultar: esa corrupción se
previene por proyección y se detecta con verificar_proyeccion.

Q03 usa UNION ALL de eventos independientes y agrega ítems antes de combinar;
no multiplica ventas por recetas. Conserva precios, cantidades, estados, fecha
comercial y receta opcional. Q04 cuenta recetas, no dispensas; DISTINCT tolera
vínculos repetidos sin incrementar cantidad. Q10 recorre TRABAJA_EN y ATENDIDA_POR,
con DISTINCT de clientes. Las tres tienen orden determinista y no filtran actividad,
estados ni fechas recientes. Las pruebas reales cubren recetas Vigente/Completada/
Vencida, ventas Pendiente/Completada/Anulada, clientes y farmacéuticos inactivos,
casos vacíos e identidades inexistentes. Los dobles unitarios prueban delegación,
conversión y errores; el resultado Cypher se valida en integración, no en mocks.

**Semántica de Q10:** PDF p.6 #10 exige atención en sucursal a través del profesional
que registró la venta, activo o no; PDF p.2 define una sucursal por farmacéutico.
No exige historial de traslados. El plan §5.1 adopta expresamente sucursal actual.
La implementación coincide con esa interpretación y con las instrucciones del
usuario. ventas.id_sucursal es una captura histórica añadida en MongoDB, no una
relación que deba sustituir TRABAJA_EN. No se detectó discrepancia que justifique
cambiar el modelo. Si se requiriera ubicación histórica tras traslados, sería un
nuevo requisito: acordar semántica antes de alterar contratos y resultados.

La evidencia oficial contrasta resultados completos con referencias MongoDB: Q03
C001 produce seis eventos; Q04 cinco clientes con dos recetas cada uno; Q10 A-S002
produce A-C002/A-C003/A-C009, de profesionales inactivos e incluyendo una venta
pendiente. Las quince sucursales se auditaron. C008 existente no tiene historial.
Se verificaron precios de todos los detalles contra CSV y equivalencia integral,
no solamente cantidades de nodos. No se inventaron resultados ni benchmarks.

## Garantías y riesgos residuales de sincronización

- Cada lectura de evento y dependencias usa la misma transacción snapshot MongoDB.
  Es el estado visible en esa lectura; no una reconstrucción del commit histórico
  del evento. Sesión y transacción cierran antes de execute_write Neo4j.
- El orden creado_en/_id es determinista para seleccionar, pero no prueba orden
  global de commits. Un único consumidor relee estado actual; la convergencia
  requiere escritores que emitan todos los cambios relevantes en outbox atómica,
  retención de eventos pendientes y ausencia de escrituras de negocio en Neo4j.
- El commit Neo4j precede al ack condicional majority en MongoDB. No hay exactamente
  una entrega: un ack perdido admite reentrega y proyección idempotente. Si el ack
  se persistió pero se perdió su respuesta, el próximo intento observará el estado
  realmente persistido. No hay transacción distribuida ni serializabilidad conjunta.
- Se distingue evento/documento inválido, dependencia ausente, conectividad Mongo,
  error Neo4j y confirmación outbox. Los diagnósticos identifican evento y causa
  sin volcar documentos o credenciales. Un evento fallido bloquea esa ejecución;
  debe corregirse la causa y reintentarse explícitamente. No hay cuarentena,
  dead-letter, métricas persistentes ni progreso garantizado frente a un evento
  permanentemente inválido. Es una política simple aceptada por los prompts.
- El lock lo libera el SO al cerrar/caer. Solo coordina procesos que comparten el
  mismo archivo; no se debe borrar/reemplazar durante uso. Alias, usuarios o hosts
  con locks distintos pueden romper la precondición de consumidor único.
- Las consultas anuncian proyección eventualmente consistente, pero no inspeccionan
  outbox al ejecutar para señalar el último error o calcular lag. El plan propone
  más información de frescura; no la exige el PDF. La CLI sync/verify permite al
  operador comprobar estado. No se promete frescura inmediata ni se añade esa
  funcionalidad en una auditoría de cierre.

## Reconstrucción y verificación

leer_fuente materializa las seis colecciones bajo snapshot, sin consultar outbox.
Se validan dependencias antes de escribir. El destino dedicado se inspecciona para
rechazar nodos ajenos/sobrantes, propiedades y restricciones ajenas; sobre datos
propios existentes se necesita confirmación adicional. No existe purga global ni
borrado automático de nodos. Las confirmaciones son declaraciones administrativas,
no demostración técnica de que todo escritor de negocio esté detenido.

La función Python exige entorno aislado y escrituras pausadas y toma el mismo
lock. La CLI exige además la confirmación explícita de sincronizador pausado y la
registra. El llamador Python debe respetar las mismas precondiciones operativas;
no se cambió la firma existente para agregar opciones redundantes.

La proyección y comparación se realizan en una sola transacción de datos Neo4j.
Si falla después de escribir pero antes del commit, se revierte y no se declara
habilitable. El DDL de restricciones queda fuera y puede persistir parcialmente.
Una respuesta de commit perdida deja incertidumbre: verificar y repetir sobre el
mismo destino con la confirmación de actualización, sin afirmar que se deshizo
un commit que el cliente no pudo observar. La reentrega de outbox posterior no
altera el estado reconstruido ni duplica líneas.

**Volúmenes grandes:** documentos, estado esperado y observado se materializan en
memoria; se ejecutan múltiples sentencias por agregado dentro de la transacción
única. Límites de memoria, timeout snapshot, tiempo de transacción, heap/transaction
memory Neo4j y reintentos pueden impedir terminar con volúmenes mayores. El E2E
solo acredita 120 nodos y 142 relaciones, no capacidad masiva. No hay batching,
checkpoints ni cambio automático de base; no se agregan porque no hay requisito
explícito que los demande para este dataset. Para ampliarlo se necesita otro diseño
administrativo, no una promesa basada en las pruebas pequeñas.

verificar_proyeccion compara identidades, tipos, propiedades y multiplicidades;
detecta nodos faltantes/sobrantes, relaciones obsoletas, duplicados y diferencias
de fechas/precios. La equivalencia está limitada al modelo proyectado; nodos
enteramente ajenos y desconectados no se incluyen en el diagnóstico, pero el
preflight de reconstrucción sí los rechaza. Sin pausa declarada y lock compartido
es diagnóstico puntual, no certificación. Las consultas normales no tienen una
barrera automática de habilitación: el procedimiento exige mantener el destino
fuera de uso hasta habilitable=true.

## Pruebas y cobertura revisada

Se inspeccionaron todos los archivos de tests/d_grafo/, incluidos fixtures y casos
parametrizados. Hay cobertura relevante de referencias ausentes/incompletas,
reentrega, ack fallido después de commit, recetas actualizadas, reasignación de
titular, cambio de sucursal, reconciliación de ítems/precios y dos líneas del mismo
producto; corrupción de nodos/relaciones/fechas, rollback de reconstrucción desde
destino vacío y existente, confirmaciones, locks, errores CLI y serialización ISO.
No se identificó un caso necesario descubierto que justificara agregar tests.
No se midió cobertura porcentual ni se aumentó el contador con pruebas triviales.

Los casos de fallos inyectados están identificados como fixtures automatizados;
la evidencia oficial no se presenta como caída física de los motores. El ack
fallido se inyecta entre el commit real Neo4j y la marca Mongo; se observa el
subgrafo confirmado, evento pendiente y reentrega convergente. El snapshot real
se prueba con otra transacción Mongo que confirma un cambio durante la lectura.

Resultado de la reejecución del **prompt 10**, con todas las integraciones habilitadas:

| Suite / comando | Aprobadas | Omitidas | Fallidas | Exit code |
| --- | ---: | ---: | ---: | ---: |
| python -m pytest tests/d_grafo -q | 271 | 0 | 0 | 0 |
| python -m pytest -q | 550 | 2 | 0 | 0 |

[Registro íntegro T10](../evidencias/d/auditoria_final/ejecucion_20261110T202933_5446fa05/pruebas.json).
D tardó 233.32 s y la suite general 324.52 s en esta ejecución; son duraciones
observadas de pruebas, no un benchmark de las consultas. Las omisiones son POSIX
0600 y privilegio de symlink ausente en Windows. No hubo fallas ni regresiones
nuevas. No se modificaron tests para lograr estos resultados. Todas las integraciones
MongoDB, Neo4j, sync y CLI se habilitaron explícitamente con las cinco variables
FARMARED_TEST_* utilizadas por el runner existente.

Las suites se ejecutaron en otro Compose UUID aislado y fixtures propios. Se
retiraron sus contenedores/volúmenes, se conservaron todos los recursos previos y
las fuentes permanecieron intactas. No se regeneraron las evidencias oficiales
del prompt 9. Los resultados actuales coinciden con los del cierre anterior.

## Git, portabilidad y preparación de archivos

[Revisión de entrega](../evidencias/d/auditoria_final/revision_entrega.json) conserva
status, diff --check, revisión de ignorados, fuentes y hallazgos heurísticos. Se
preservaron los cambios sin confirmar ya presentes; no se hizo reset, commit ni
push. Gran parte de la contribución D sigue sin seguimiento en Git: **antes de
entregar, el equipo debe revisar y versionar explícitamente esos archivos**.
Que funcionen en el workspace no equivale a estar publicados en GitHub.

Los 18 CSV y el manifiesto son byte a byte iguales a HEAD y conservan los hashes
de la evidencia oficial. Las marcas M de Git provienen del checkout/EOL ya
registrado; no hay diferencias de contenido en data/. Compose no cambió. El
proyecto resuelve rutas desde archivos, configuración o directorio home; no
requiere el nombre del usuario ni una carpeta absoluta de esta máquina.

La búsqueda de rutas personales en src/, pruebas D y documentación D no encontró
dependencias absolutas. Dos JSON históricos de portabilidad conservan una ruta
de herramienta Git del entorno de aquella ejecución; son metadatos, no comandos
necesarios para correr FarmaRed. No se alteraron esas evidencias para maquillarlas.
Los patrones de URI con credenciales dieron solo literales de prueba en
tests/carga/test_base.py y tests/infra/test_demo.py: usuarios/claves ficticios usados
para comprobar ocultamiento. No se detectaron tokens reales ni claves privadas
en archivos de entrega revisados. Es una revisión heurística, no una garantía
criptográfica ni una auditoría de todo el historial de Git.

.env, .venv, __pycache__, .pytest_cache y archivos compilados quedan ignorados;
.env.example permanece versionable. No se localizaron ignorados adicionales de
entrega fuera de caches/entorno en la revisión. Las evidencias oficiales contienen
salidas completas, versiones, comandos y hashes sin contraseñas publicadas.

## Problemas, correcciones y decisión de cierre

**Bloqueantes de D:** ninguno demostrado en código, pruebas o integración oficial.

**Correcciones de esta auditoría:** redacción desactualizada del informe técnico
que aún anunciaba proyección, consumidor o CLI como futuras; aclaración de etapas
históricas y bloqueos ya resueltos; incorporación de justificación y límites;
creación de matriz, resumen integrable y registros de revisión/pruebas. No se
modificó producción, CLI común, infraestructura, datasets, manifiesto ni módulos
ajenos. No se regeneró el E2E oficial.

**Pendientes de entrega conjunta:** versionar los archivos hoy sin seguimiento,
incorporar el bloque D al README y este resumen al informe PDF, completar servicios
y consultas B/C y comprobar emisión transaccional de outbox por sus escritores;
validar el entorno Codespaces alojado y recuperar el reparto formal. La discrepancia
cuatro/tres integrantes del PDF requiere aclaración del equipo, no cambios D.

**Mejoras opcionales fuera del cierre:** diagnóstico persistente de lag/error,
tratamiento administrativo de eventos permanentemente inválidos, exclusión
multi-host, reconstrucción por lotes/checkpoints para otra escala y validación
más estricta de argumentos de Q10 en la API Python (la CLI ya valida; la consigna
solo exige argumento). No justifican desarrollo adicional para completar el
alcance actual. Cambiar la semántica histórica de sucursal requiere un nuevo acuerdo.

**Integración recomendada:** usar los siete comandos ya registrados; conservar
MongoDB como autoridad; demostrar sync y verify antes de las consultas con estado
estable; mostrar las salidas oficiales enlazadas; presentar las limitaciones sin
prometer sincronización continua. La contribución D está lista para revisión e
integración al trabajo final, condicionada a publicar los archivos y completar
los entregables compartidos del equipo.


## Archivos de esta auditoría

Creados: d_auditoria_final.md, d_resumen_para_integracion.md y el directorio
../evidencias/d/auditoria_final/ con índice, extracción de consigna, identificación
de fuentes, revisión Git/secretos/rutas, cotejo de Cypher, ejecutor reproducible,
registro de suites y cierre. Modificados: d_grafo_y_sincronizacion.md y
../evidencias/d/README.md para corregir estado y enlazar el cierre.

No se editaron módulos productivos, tests, README general, Compose, Codespaces,
contratos compartidos, datasets ni manifiesto. Se preservó el trabajo anterior
sin confirmar. No se hizo commit ni push; la publicación queda a cargo del equipo.
