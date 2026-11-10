# Evidencia de portabilidad — prompt 8

Fecha: 2026-11-10. No se ejecutó seed, reconstrucción Neo4j o E2E.

- [Diagnóstico inicial completo](diagnostico_antes.json): once errores reales, fuentes,
  configuración Git y variantes aisladas que separan sus causas.
- [Validación posterior](validacion_despues.json): cero errores, conteos y hashes antes/después.
- [Suite Windows](pruebas_windows.json): grupos carga/infra/D y suite completa.
- [Suite Linux](pruebas_linux.json): imagen del Dockerfile existente, montaje de solo lectura,
  validación real y suite completa, sin motores de negocio.
- [Invariantes finales](control_final.json): bytes iguales a HEAD, atributos efectivos,
  huella Windows/Linux idéntica y git diff de datos vacío.
- [Explicación y límites de seguridad](../../portabilidad_datasets.md).

## Once diagnósticos iniciales

Todos son reales y conservan el archivo/campo/código devuelto por el validador.

| Archivo | Campo | Código | Causa |
| --- | --- | --- | --- |
| data\adicionales\manifiesto.json | huella_originales | GENERACION | Se requieren los originales vinculados por el manifiesto, sin cambios. |
| data\adicionales\manifiesto.json | perfil | GENERACION | El manifiesto no corresponde al perfil determinista de esa fecha/originales/versión. |
| data\adicionales\manifiesto.json | clientes | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | sucursales | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | farmaceuticos | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | proveedores | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | productos | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | stock_lotes | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | recetas | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | ventas | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |
| data\adicionales\manifiesto.json | detalle_ventas | GENERACION | Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar. |

## Comparación completa de hashes

Después, cada SHA-256 coincide con HEAD. En los nueve adicionales coincide también
con el hash del manifiesto, sin editar su referencia. En el JSON se preservaron
los valores; se restauraron exclusivamente sus bytes originales LF.

| Archivo | SHA-256 antes, CRLF | SHA-256 después, LF = HEAD |
| --- | --- | --- |
| data/originales/clientes.csv | `e79217742f1536f8ddb2ed3472da2716d7335df437dd533b92dece01ed66c6f5` | `afaddcaa8762b619dd46b3e21acd4544b0f034550493b76832e774a4ef21d9ed` |
| data/originales/detalle_ventas.csv | `55140f0e6265cadbfd95f23695892778b0460fa9312ea0ad924b7f5818652636` | `cb57f070e1e2a12727d19ec799a2002398fc5ddc686ba370c6d9f14f654d085d` |
| data/originales/farmaceuticos.csv | `5facf310e65fb66ddf326893d57ab696855e2dbbd1879574fa8419d1e6735fec` | `03db193b616a41954589703a349ba5b427e05c8ee431ca5c18f1f7dc3f31e021` |
| data/originales/productos.csv | `adefa18abb0f941ba3de813fa9b0322c6c61d0bb43187b693b090b2054b8f34c` | `cd0bde7d1da5de4cb96ccbd9b7a0218e670e075e4c75179145bbd2a9c572f0f8` |
| data/originales/proveedores.csv | `f9403cc274dc5a5ab3b4d1c99b69b766a07771abd8877a00a95ba446bf45a632` | `609b89e2038ae7ce586baa2cbac24f54b76d6610792844028a3d8543a1beeb23` |
| data/originales/recetas.csv | `590ef23335b57075ee1458c470b99a67fdcda613684c7cb3f15a86b0fb1da898` | `021f56ef49addd28b71076d44bdeabbcf3ffde0f04a9a7c950e792c3e8213ec9` |
| data/originales/stock_lotes.csv | `cb33f64fa56b373ec9a6305fa9ae86210bb8bce3922be386ef18f7db3cb35654` | `7dc07e052cabede0cdfa425315699d38de88f921d9a11e061bd377d6842e30ad` |
| data/originales/sucursales.csv | `1a2cb1121a0c395428d338ddc6b65a394ad0f7669f88b82529b12ee396ff6629` | `89210e743de64f168c684a51cde82b3feeda27d794b5dd586f57b102b6d1e7b7` |
| data/originales/ventas.csv | `6f6e7ee3cdb4626e87371dc04bf800c6116a1ec07e780c0f68ca7600e73dd0ff` | `a8009f4bccdccd7b0679c7518935cb985f31a9bbdb6788172a58998a1f230ab8` |
| data/adicionales/clientes.csv | `1feab7c5d15bc7139c5fa03dba0aaf57850b349101f670af0a23e45b6c96ff9e` | `80bd39404be0b45f3579b1f23eafa7a6b544a45e8054b100a5d18cc59f428b1a` |
| data/adicionales/detalle_ventas.csv | `deeb0194091c121a088e04a7079eae08d5d7166cdb96b19406cdb3a744ffa28f` | `cb6d2a748a51247cc053c38920bb0974c2b8ddcb203f6ea361af7b00fd503b9b` |
| data/adicionales/farmaceuticos.csv | `1ed849536a70f4d9fe943e0398f777212fa4ae0d5159bc58d2079a3a7dee19ea` | `9810b0c81b89356388ef55d1be3f9b635a8d8d7a958171d6b536ac9ef641b2da` |
| data/adicionales/productos.csv | `44c4ca7041d638c8ee7a83309466ff692186a2bbb7fa9a1573f138c7c85ea711` | `3307fb35a8548b0326ea97ae27c15419448d1b270a241e9b78fcc324c3383652` |
| data/adicionales/proveedores.csv | `7d59fe71fc16b48300887c47994d7f4ffbaec5cddeeccc0a7244fd0297a05d6d` | `d1299690f249f733d7b090a7c601263802a4ff1c272d6dfb68ba4f562c0caf18` |
| data/adicionales/recetas.csv | `b41be49d4993dc5fba6dc5ccedc8090164886bda8fe3fa229df2a87dba70679e` | `c5108fdfca6442aba6ba6bd8571d951c78fb68a59ae6c0c180ddc986987f7ac5` |
| data/adicionales/stock_lotes.csv | `0cd29e7d05770957735426fb26a050b9fa5563f5916484ae729e8fa3e9e1b9f1` | `4bfc407afb8dfbaf70507df99288952eebf0f756b3c7e9e29d616c1bd8ce781a` |
| data/adicionales/sucursales.csv | `6a9be1aa58e2f3f7f2a299a239be7457ab5007c2f755c6d8a4ea9a6353140f9c` | `533a8ad3025ec4417f59ef474a76eea160bbf21dbaee73c7188f7aa5c8874dbf` |
| data/adicionales/ventas.csv | `8ad3e48dfc6163f07c92650bd9f7fe86fc97cf6e9b2644cbc8950906f98ff933` | `697e1995fbd914e8b20f9b517177f54d6fb1ad9cd9b77cdab6cb0d94f7349fa7` |
| data/adicionales/manifiesto.json | `4009200e1b88693fd5856cc650f0686bfc6c18e891b433e857dbd926383ac423` | `db74749e2a29a1e4d09c8be2dd18f7e54817c86d0f2c31a77ff3e4e106a9175c` |

## Resultado

Validación exit code 0, errores=[], 207 registros CSV / 169 documentos de negocio.
Windows: 408 aprobadas, 144 omitidas, 0 fallidas. Linux: 410 aprobadas, 142 omitidas,
0 fallidas. Las integraciones de motores se desactivaron para respetar esta etapa.
No se presenta la ejecución como una carga de datos ni como un E2E.
