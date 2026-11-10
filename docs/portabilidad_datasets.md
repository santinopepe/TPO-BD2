# Portabilidad e integridad de los datasets FarmaRed

Verificación realizada el 2026-11-10. No se ejecutó seed, reconstrucción Neo4j ni
integración end-to-end en esta etapa.

## Diagnóstico de los once errores

Git tenía core.autocrlf=true y no existía .gitattributes. Los 18 CSV y el manifiesto
estaban en LF en HEAD, pero el checkout los había convertido a CRLF. Se compararon
SHA-256 de bytes, finales de línea y registros CSV completos: no había cambios de
IDs, cantidades, precios, fechas, columnas ni registros, solo finales de línea.
Los errores reales tienen código GENERACION y apuntan a manifiesto.json:

- Nueve controles de hash/conteo: los conteos eran correctos, pero los bytes CRLF de
  cada adicional no coincidían con su SHA-256 de referencia LF.
- huella_originales: también los nueve originales tenían bytes CRLF. Su huella era
  bb01ed1c5a62615868d0bfb211989ea3be171d955aba65018da2318f5f3f9d7a y el manifiesto
  referencia e08cdbc0108e00916bddf3b26a9c28cfedf009792ff21ae74e623b4a66407407.
- perfil: el validador calcula el perfil determinista con la huella observada de los
  originales. Como esa huella era distinta, el perfil no coincidía. Usando la huella
  de referencia, el perfil y el manifiesto de HEAD sí coincidían exactamente.

Se aislaron las causas en copias temporales, sin alterar fuentes ni cargar motores:

| Bytes examinados | Errores |
| --- | --- |
| Checkout inicial CRLF | 11 |
| Solo adicionales restaurados a LF | 2: huella_originales y perfil |
| Solo originales restaurados a LF | 9 hashes adicionales |
| Ambos conjuntos CSV en LF | 0 |
| CSV y manifiesto originales de Git, LF | 0 y huella global reproducible |

Los once diagnósticos completos, código, archivo y causa, y las comparaciones están
en [diagnostico_antes.json](evidencias/portabilidad/diagnostico_antes.json).

## Corrección mínima

Se agregó únicamente esta política versionable, sin cambiar la configuración global:

```gitattributes
data/originales/*.csv text eol=lf
data/adicionales/*.csv text eol=lf
data/adicionales/manifiesto.json text eol=lf
```

Fue necesario incluir originales: dejarlos CRLF mantiene los dos errores vinculados
a su huella. El manifiesto JSON también debe tener bytes estables porque su SHA-256
forma parte de la huella de generación/dataset. Aunque su formato CRLF se pueda
parsear como el mismo JSON, produciría una identidad global distinta entre plataformas.

Se restauraron los 19 archivos desde sus blobs HEAD, solo después de verificar que
el contenido actual correspondía a esos blobs cambiando exclusivamente CRLF por LF.
Se comprobaron hashes otra vez antes de escribir para no sobrescribir un cambio
concurrente. No se regeneraron adicionales ni se reescribieron valores/hashes del
manifiesto. Los 19 archivos finales coinciden byte a byte con HEAD; git diff -- data
está vacío. El estado de archivos puede reflejar la restauración física del checkout,
pero no existe un cambio de contenido de negocio versionado.

No se modificaron validacion.py, metadatos.py, huellas.py, adicionales.py ni el loader.
El SHA-256 sigue calculándose sobre read_bytes(), antes de decodificar CSV, sin una
normalización silenciosa. Un CRLF introducido después de este arreglo sigue siendo
una alteración de bytes y se rechaza. No se acepta por equivalencia de registros.

La política actúa en nuevos checkouts. En copias existentes Git no reescribe archivos
solo por crear .gitattributes: inspeccionar primero hashes y cambios de trabajo antes
de restaurar bytes. No usar reset --hard, clean, regeneraciones o restauraciones
indiscriminadas que puedan descartar ediciones de otros integrantes. No se ejecutó
add --renormalize ni se cambiaron contenidos/staging de trabajo previo para este arreglo.

## Resultado de validación real

```powershell
uv run --locked farmared validar-datasets --directorio data/originales --directorio data/adicionales
```

Exit code 0, errores=[], 18 fuentes, 207 registros CSV. Los 38 detalles se embeben
en ventas: corresponden a 169 documentos de negocio, sin efectuar una carga.

| Tabla | Registros unidos |
| --- | --- |
| clientes | 18 |
| sucursales | 15 |
| farmaceuticos | 17 |
| proveedores | 15 |
| productos | 23 |
| stock_lotes | 34 |
| recetas | 19 |
| ventas | 28 |
| detalle_ventas | 38 |

La huella global obtenida tanto en Windows como en Linux es:

```text
c2bbc4cb4e97de5cef6c17d09522ef172041e8ee08a2a6a8529533cf4f31e2e0
```

Los avisos históricos propios de las fuentes siguen presentes en el resultado:
no se borraron datos ni se modificaron reglas para ocultarlos. Cada adicional
conserva al menos diez registros nuevos. El perfil en memoria reproduce exactamente
los nueve CSV y el manifiesto publicados, sin regenerarlos sobre el directorio.

## Pruebas de integridad

Se agregaron 23 casos en tests/carga/test_portabilidad.py:

- Unión versionada y conteos exactos; hashes LF y mínimo por cada uno de los nueve CSV.
- Perfil reproducible byte a byte y conservación de todos los registros.
- Modificación de un byte, precio, ID o fecha, línea extra, CRLF y finales mixtos:
  todos se rechazan, incluso cuando la tabla CSV se interpreta igual.
- Un original alterado a CRLF vuelve a provocar huella_originales/perfil inválidos.
- Ruta de rechazo del loader con un doble de Database: no se alcanza ninguna operación
  MongoDB. Esto comprueba que no hay que omitir controles; no ejecuta seed real.
- Checkout real de los 19 archivos en repositorios Git temporales con autocrlf=true,
  false e input. Se comprueban text/eol, bytes exactos y validación completa al terminar.

No se requieren chmod, dos2unix u otras herramientas exclusivas de Linux. La prueba
específica de checkout necesita Git y se omite explícitamente si no está disponible;
se ejecutó realmente con Git en ambos entornos de esta verificación.

## Prueba POSIX y seguridad de .env

El fallo original comparaba st_mode & 0777 con 0600 en Windows. Es una comprobación
POSIX que no mide permisos NTFS; que Windows muestre 0666 no demuestra acceso de
lectura/escritura a todos los usuarios. No se corrigió cambiando a permisos amplios.

La prueba combinada se separó manteniendo todos sus objetivos:

1. Creación con secreto no vacío y no sobrescritura: portable, pasa en Windows y Linux.
2. Modo exacto 0600: prueba POSIX estricta, pasa en Linux y solo ella se omite por
   plataforma en Windows. infra/preparar_env.py conserva O_CREAT | O_EXCL y modo 0600.
3. Enlace de infra/.env idempotente hacia el mismo archivo: pasa en Linux. En este
   Windows CreateSymbolicLink devuelve WinError 1314 por falta del privilegio; solo
   esa capacidad se omite con motivo explícito, sin reemplazar el enlace por copias.
   Otros errores de enlace no se silencian y la protección de archivos preexistentes
   se sigue probando en ambas plataformas.

No se modificó infra/preparar_env.py ni permisos de secretos reales. En Windows la
protección efectiva depende de la ACL heredada del directorio de usuario: esta
función no configura ni certifica una DACL restrictiva equivalente a 0600. Usar un
directorio privado con ACL revisada por el administrador. Para crear symlinks en
Windows hace falta el privilegio correspondiente o modo desarrollador; la función
original continúa informando error si no está disponible. No se agregó un fallback
que duplique secretos o relaje controles. Son limitaciones documentadas, no garantías
universales de seguridad NTFS.

## Entornos y resultados realmente probados

| Ejecución Windows, Python 3.14.10 | Aprobadas | Omitidas | Fallidas |
| --- | --- | --- | --- |
| tests/carga | 165 | 78 | 0 |
| tests/infra | 31 | 7 | 0 |
| tests/d_grafo | 212 | 59 | 0 |
| Suite general | 408 | 144 | 0 |

En Linux Debian Bookworm, dentro de una imagen construida con infra/Dockerfile sin
cambios, Python 3.12.12 y uv 0.13.7: suite general **410 aprobadas, 142 omitidas y
0 fallidas**. El repositorio estuvo montado de solo lectura; el entorno Python y
las pruebas se ejecutaron dentro del contenedor temporal. La validación de fuentes
allí tuvo la misma huella/conteos que Windows. Las pruebas POSIX y symlink explican
las dos aprobaciones adicionales frente a Windows.

Respecto de 443 aprobadas, 83 omitidas y 1 fallida del prompt anterior, esta ejecución
desactivó deliberadamente las 59 integraciones D y las 83 de A: no ejecutar seed,
reconstrucción o E2E es una restricción de esta etapa. Se agregaron 23 casos de
integridad y la prueba original se descompuso en tres (dos casos netos adicionales).
Por eso cambian las aprobadas/omitidas; no es una regresión. Las integraciones de
motores omitidas no se declaran aprobadas en esta etapa.

No se ejecutó un Codespace alojado ni se garantiza compatibilidad de todos los
sistemas de archivos, ACL o versiones posibles. Sí se probaron Windows y Linux
en los entornos indicados, incluida la política de Git en ambas plataformas.

Evidencias completas: [índice](evidencias/portabilidad/README.md),
[validación posterior y hashes](evidencias/portabilidad/validacion_despues.json),
[pruebas Windows](evidencias/portabilidad/pruebas_windows.json),
[pruebas Linux](evidencias/portabilidad/pruebas_linux.json),
[control final](evidencias/portabilidad/control_final.json).

La validación queda desbloqueada. Seed y el E2E oficial se reservan para el próximo
prompt, sin ejecutarlos automáticamente.
