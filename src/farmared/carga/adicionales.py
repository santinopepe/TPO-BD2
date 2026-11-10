"""Datos propios reproducibles; nunca regenera sobre un directorio existente."""

import json
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from farmared.carga.datos_adicionales import construir_archivos
from farmared.carga.formatos import CAMPOS
from farmared.carga.metadatos import MARCA_INCOMPLETA, NOMBRE_MANIFIESTO
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
from farmared.clock import Clock, SystemClock
from farmared.errores import CodigoError, ErrorDominio


def generar_adicionales(destino, originales, *, base_date: date | None = None, clock: Clock | None = None):
    """Genera una vez o verifica/reutiliza sin mover fechas ni sobrescribir archivos."""
    destino, originales = Path(destino), Path(originales)
    original = validar_datasets(rutas_desde_directorios(originales))
    if original.generaciones:
        raise ErrorDominio(CodigoError.VALIDACION, "La fuente de originales no puede ser un conjunto generado.")
    if destino.exists():
        if not (destino / NOMBRE_MANIFIESTO).is_file() or (destino / MARCA_INCOMPLETA).exists():
            raise ErrorDominio(CodigoError.CONFLICTO_ID, "Destino existente sin generación completa; se conserva sin sobrescribir.")
        validado = validar_datasets(rutas_desde_directorios(originales, destino))
        generacion = validado.generaciones[0]
        if base_date is not None and base_date != generacion.base_date:
            raise ErrorDominio(CodigoError.CONFLICTO_ID, "Cambió la fecha base; elegir otro directorio para regenerar deliberadamente.")
        return {"directorio": str(destino), "base_date": generacion.base_date.isoformat(), "reutilizada": True,
                "conteos": {f.tabla: f.filas_leidas for f in validado.fuentes if Path(f.archivo).parent.resolve() == destino.resolve()}}
    base = base_date if base_date is not None else (clock or SystemClock()).today()
    if not isinstance(base, date) or isinstance(base, datetime):
        raise ErrorDominio(CodigoError.VALIDACION, "base_date debe ser date sin hora.")
    try:
        contenidos = construir_archivos(base, original.huella)
    except (OverflowError, ValueError):
        raise ErrorDominio(CodigoError.VALIDACION, "La fecha base no permite los desplazamientos del dataset.") from None
    manifiesto = json.loads(contenidos[NOMBRE_MANIFIESTO])
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix=f".{destino.name}-", dir=destino.parent))
    try:
        for nombre, contenido in contenidos.items():
            (temporal / nombre).write_bytes(contenido)
        validar_datasets(rutas_desde_directorios(originales, temporal))
        try:
            destino.mkdir(exist_ok=False)
        except FileExistsError:
            raise ErrorDominio(CodigoError.CONFLICTO_ID, "Otro proceso creó el destino; no se sobrescribe.") from None
        (destino / MARCA_INCOMPLETA).write_text("Generación en curso; no cargar.\n")
        for nombre, contenido in contenidos.items():
            with (destino / nombre).open("xb") as archivo:
                archivo.write(contenido)
        (destino / MARCA_INCOMPLETA).unlink()
    except OSError:
        raise ErrorDominio(CodigoError.INTEGRIDAD, "No se pudo publicar la generación completa; conservar/inspeccionar el destino marcado y elegir otro directorio.") from None
    finally:
        shutil.rmtree(temporal)
    return {"directorio": str(destino), "base_date": base.isoformat(), "reutilizada": False,
            "conteos": {t: manifiesto["archivos"][f"{t}.csv"]["filas"] for t in CAMPOS}}
