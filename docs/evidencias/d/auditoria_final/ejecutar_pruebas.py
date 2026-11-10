"""Reejecuta suites aisladas sin regenerar la demostracion oficial del prompt 9."""
import importlib.util
from pathlib import Path
import sys

raiz=Path(__file__).resolve().parents[4]
p=raiz/'docs/evidencias/d/e2e_oficial/probar_suites.py'
spec=importlib.util.spec_from_file_location('suites_auditoria',p)
modulo=importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)
anterior=modulo.e.EVIDENCIAS
destino=Path(__file__).parent/anterior.name
anterior.rename(destino)
modulo.e.EVIDENCIAS=destino
raise SystemExit(modulo.main())
