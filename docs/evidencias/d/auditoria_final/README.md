# Auditoría final de Persona D — evidencias del prompt 10

Se revisaron implementación, pruebas, contratos y documentación. No se repitió
seed ni se regeneraron las salidas oficiales del prompt 9.

- [Consigna extraída, siete páginas y SHA-256](consigna_extraida.json): TPO_FarmaRed.pdf,
  copia local externa al repositorio localizada por la referencia del informe A.
- [Fuentes normativas y plan revisados](fuentes_requisitos.json): prioridad y ausencia
  del reparto formal, sin confundir propuesta con obligación académica.
- [Git, ignorados, hashes y búsqueda heurística](revision_entrega.json): las rutas
  personales en evidencia histórica de portabilidad son metadatos; las URI con
  credenciales en pruebas de A son literales ficticios para probar ocultamiento.
- [Ejecutor de suites aisladas](ejecutar_pruebas.py): reutiliza el runner de pruebas
  del prompt 9 y dirige sus resultados aquí, sin cambiar la demostración oficial.
- [Registro de suites con integraciones habilitadas](ejecucion_20261110T202933_5446fa05/pruebas.json).
- [Auditoría final y matriz](../../../informe/d_auditoria_final.md).
- [Texto preparado para informe general](../../../informe/d_resumen_para_integracion.md).

La extracción del PDF se hizo con pypdf en un entorno efímero de uv --no-project:
no se agregó dependencia ni se cambió pyproject.toml o uv.lock. Su texto contiene
los requisitos revisados, no resultados ejecutables ni evidencia de otras personas.
Las suites usan fixtures sintéticos sobre contenedores propios; sus resultados se
distinguen de las [salidas oficiales](../e2e_oficial/README.md).

No se mide cobertura porcentual ni se afirma ausencia matemática de secretos.
La revisión de patrones se complementó con inspección de los hallazgos. Los archivos
ignorados de caches y entornos no son necesarios para publicar la contribución;
los módulos, pruebas y documentos D sin seguimiento sí deben incorporarse mediante
la revisión y el commit explícitos del equipo.

Resultado de la reejecución de auditoría (prompt 10): Persona D 271 aprobadas,
cero omitidas/fallidas; suite general 550 aprobadas, dos omitidas por plataforma
Windows, cero fallidas. Registro completo en auditoria_final/ejecucion_20261110T202933_5446fa05/pruebas.json.
Los contenedores y volúmenes propios fueron retirados y los recursos previos
conservados. Las evidencias oficiales del prompt 9 no se regeneraron.

[Cierre verificable](cierre.json): diff --check sin errores, fuentes y Compose
conservados, enlaces comprobados, cero contenedores activos y recursos previos
intactos. No hubo cambios productivos, tests modificados, commits ni push.
