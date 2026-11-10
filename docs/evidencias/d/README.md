# Evidencia vigente: integración oficial completada

Ver [datasets oficiales y adicionales](e2e_oficial/README.md). Los registros siguientes son históricos y sintéticos.

# Evidencias D: CLI real y bloqueo de datasets

> Registro histórico del prompt 7. El bloqueo de validación fue corregido en el
> prompt 8; ver [evidencia de portabilidad](../portabilidad/README.md). Estas salidas
> originales se conservan sin alterar. El E2E oficial se completó posteriormente en el prompt 9.

La demostración oficial + adicionales NO se ejecutó: la validación real terminó
con exit code 1 y 11 errores. No se ejecutó seed con esas fuentes ni se modificaron
CSV o manifiestos.

Los resultados siguientes proceden de un fixture sintético insertado transaccionalmente
en un proyecto Docker Compose nuevo, usando infra/docker-compose.yml sin cambios.
No son resultados del dataset oficial.

- [Validación fallida](validacion_datasets.json).
- [Diagnóstico de hashes](diagnostico_hashes.json): 9 blobs HEAD coinciden con el manifiesto;
  los 9 archivos del checkout no y contienen CRLF. La comparación CRLF→LF es solo
  diagnóstica: no se usó para modificar o cargar datos.
- [Comandos y salidas CLI reales](cli_integracion_fixture.json), con fecha, versiones,
  conteos y proyecto aislado. Sin contraseñas ni URI con secretos.
- [Restricciones reales](restricciones_fixture.json).
- [Modelo del contrato](modelo.md), no una captura del servidor.

## Ejecución registrada

Fecha: 2026-11-10T16:01:47.025184-03:00. Origen: fixture_sintetico_CLI_no_dataset_oficial.

| Paso | Comando | Exit code |
| --- | --- | --- |
| 1 | `python -m farmared salud` | 0 |
| 2 | `python -m farmared preparar-mongo --base farmared_test_d_cli` | 0 |
| 3 | `python -m farmared grafo-init` | 0 |
| 4 | `python -m farmared grafo-verify --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO> --confirmar-escrituras-pausadas` | 1 |
| 5 | `python -m farmared sync --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 0 |
| 6 | `python -m farmared grafo-verify --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO> --confirmar-escrituras-pausadas` | 0 |
| 7 | `python -m farmared grafo-verify --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 1 |
| 8 | `python -m farmared q03 --id-cliente CLI-C` | 0 |
| 9 | `python -m farmared q04` | 0 |
| 10 | `python -m farmared q10 --id-sucursal CLI-S` | 0 |
| 11 | `python -m farmared sync --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 0 |
| 12 | `python -m farmared q03 --id-cliente INEXISTENTE` | 0 |
| 13 | `python -m farmared q10 --id-sucursal INEXISTENTE` | 0 |
| 14 | `python -m farmared sync --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 1 |
| 15 | `python -m farmared sync --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 0 |
| 16 | `python -m farmared grafo-verify --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO> --confirmar-escrituras-pausadas` | 0 |
| 17 | `python -m farmared grafo-rebuild --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO>` | 1 |
| 18 | `python -m farmared grafo-rebuild --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO> --confirmar-entorno-aislado --confirmar-escrituras-pausadas --confirmar-sincronizador-pausado` | 1 |
| 19 | `python -m farmared grafo-rebuild --base farmared_test_d_cli --lock-path <LOCK_COMPARTIDO> --confirmar-entorno-aislado --confirmar-escrituras-pausadas --confirmar-sincronizador-pausado --confirmar-actualizacion-existente` | 0 |

El fallo de conexión se produjo usando, solo para esa invocación, una URI hacia un
puerto local reservado sin listener. No se afirma una caída física de Neo4j. El
evento siguió pendiente; al volver a la URI válida se procesó una reentrega y la
verificación siguió equivalente.

grafo-verify sin confirmación de pausa sale con 1 incluso si no encuentra diferencias:
su alcance es diagnóstico puntual. grafo-rebuild sin confirmaciones, o con destino
existente sin confirmar actualización, también sale con 1. Son rechazos esperados,
no fallas de la prueba.

## Consultas ejecutadas: datos de prueba

### python -m farmared q03 --id-cliente CLI-C

```json
{
    "consulta":  "q03",
    "id_cliente":  "CLI-C",
    "proyeccion":  "eventualmente_consistente",
    "resultados":  [
                       {
                           "detalle":  {
                                           "dispensas_autorizadas":  1,
                                           "dispensas_realizadas":  1,
                                           "medico":  "Médico prueba",
                                           "proxima_dispensa":  null,
                                           "tipo":  "Simple"
                                       },
                           "estado":  "Completada",
                           "fecha":  "2026-01-01",
                           "id_registro":  "CLI-R",
                           "tipo_evento":  "RECETA"
                       },
                       {
                           "detalle":  {
                                           "dispensas_autorizadas":  1,
                                           "dispensas_realizadas":  1,
                                           "medico":  "Médico prueba",
                                           "proxima_dispensa":  null,
                                           "tipo":  "Simple"
                                       },
                           "estado":  "Completada",
                           "fecha":  "2026-01-01",
                           "id_registro":  "CLI-R2",
                           "tipo_evento":  "RECETA"
                       },
                       {
                           "detalle":  {
                                           "id_receta":  "CLI-R",
                                           "items":  [
                                                         {
                                                             "cantidad":  2,
                                                             "id_detalle":  "D1",
                                                             "id_producto":  "CLI-P",
                                                             "nombre_al_vender":  "Nombre anterior",
                                                             "orden":  0,
                                                             "precio_unit":  100,
                                                             "subtotal":  200
                                                         },
                                                         {
                                                             "cantidad":  1,
                                                             "id_detalle":  "D2",
                                                             "id_producto":  "CLI-P",
                                                             "nombre_al_vender":  null,
                                                             "orden":  1,
                                                             "precio_unit":  120,
                                                             "subtotal":  120
                                                         }
                                                     ],
                                           "medio_pago":  "Efectivo",
                                           "tipo":  "Con receta",
                                           "total":  320
                                       },
                           "estado":  "Pendiente",
                           "fecha":  "2026-01-02",
                           "id_registro":  "CLI-V",
                           "tipo_evento":  "VENTA"
                       }
                   ]
}
```

### python -m farmared q04

```json
{
    "consulta":  "q04",
    "proyeccion":  "eventualmente_consistente",
    "resultados":  [
                       {
                           "apellido":  "Prueba",
                           "cantidad":  2,
                           "id_cliente":  "CLI-C",
                           "nombre":  "Ana"
                       }
                   ]
}
```

### python -m farmared q10 --id-sucursal CLI-S

```json
{
    "consulta":  "q10",
    "id_sucursal":  "CLI-S",
    "proyeccion":  "eventualmente_consistente",
    "resultados":  [
                       {
                           "apellido":  "Prueba",
                           "id_cliente":  "CLI-C",
                           "nombre":  "Ana"
                       }
                   ]
}
```

No se capturaron imágenes ni se inventaron benchmarks. La validación y el E2E
oficial deben repetirse después de que A resuelva los bytes/finales de línea del
checkout. Estas evidencias quedan condicionadas a su origen declarado.



La [auditoría final del prompt 10](../../informe/d_auditoria_final.md) contiene la
matriz de requisitos, límites y material listo para integrar al informe general.
La contribución funcional de D está implementada; este cierre no certifica todavía
la entrega completa de las otras personas ni el PDF final del equipo.
