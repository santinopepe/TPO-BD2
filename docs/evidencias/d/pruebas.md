# Pruebas ejecutadas — etapa CLI D

Fecha de ejecución: 2026-11-10, host Windows con Python 3.14.10.

| Ejecución | Resultado observado |
| --- | --- |
| Unitarias CLI D + test_base de A + test_cli_setup de A | 78 aprobadas en 4.52 s (37 nuevas D) |
| CLI real contra Compose de A, fixture sintético | 1 aprobada en 58.29 s, 19 comandos reales |
| Suite general con FARMARED_TEST_GRAFO=1, FARMARED_TEST_SYNC=1 y FARMARED_TEST_CLI=1 | 443 aprobadas, 83 omitidas y 1 fallida en 229.27 s |
| Persona D, incluida en la suite general | 271 aprobadas, incluidas 59 integraciones reales |

Comandos:

```powershell
uv run --locked pytest tests/d_grafo/test_cli_grafo.py tests/carga/test_base.py tests/infra/test_cli_setup.py -q
$env:FARMARED_TEST_CLI = '1'
uv run --locked pytest tests/d_grafo/test_cli_grafo_integracion.py -q -s
$env:FARMARED_TEST_GRAFO = '1'
$env:FARMARED_TEST_SYNC = '1'
uv run --locked pytest -q
```

La única falla sigue en tests/infra/test_conexiones.py:149: la prueba existente de
permisos espera POSIX 0600 y Windows informa 0666. No se modificó para ocultarla.
Las 83 omisiones son integraciones opt-in de A que no se activaron.
No se observaron nuevas regresiones. No se probaron Codespaces alojados.

Las duraciones son tiempos de ejecución de pytest observados, no benchmarks de
rendimiento de consultas. Los resultados CLI JSON proceden del fixture identificado;
la demostración con oficiales + adicionales sigue bloqueada por la validación.
