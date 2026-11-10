"""Identidad portable de fuentes; conserva el hash v1 de datasets sin generación."""

import hashlib
import json

from farmared.carga.modelos import VERSION_VALIDACION


def huella_fuentes(fuentes, generaciones=()):
    identidad = {
        "version_validacion": VERSION_VALIDACION,
        "fuentes": [{"tabla": f.tabla, "orden": f.orden, "sha256": f.sha256} for f in fuentes],
    }
    if generaciones:
        identidad["generaciones"] = [{"orden": g.orden, "sha256": g.sha256} for g in generaciones]
    return hashlib.sha256(json.dumps(identidad, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
