"""Vincula adicionales, fecha base y originales usando los bytes ya leídos."""

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

from farmared.carga.formatos import CAMPOS, CLAVES
from farmared.carga.datos_adicionales import NOMBRE_MANIFIESTO, VERSION_GENERADOR, construir_archivos
from farmared.carga.huellas import huella_fuentes
from farmared.carga.modelos import DiagnosticoCSV, GeneracionCSV

MARCA_INCOMPLETA = ".generacion_incompleta"


def validar_generaciones(rutas, fuentes, filas, errores):
    padres = []
    for paths in rutas.values():
        if isinstance(paths, (str, Path)):
            paths = (paths,)
        for path in paths:
            padre = Path(path).parent
            if padre.resolve() not in {p.resolve() for p in padres}:
                padres.append(padre)
    con_manifiesto = {p.resolve() for p in padres if (p / NOMBRE_MANIFIESTO).exists()}
    originales = []
    ordenes = defaultdict(int)
    for fuente in fuentes:
        if Path(fuente.archivo).parent.resolve() not in con_manifiesto:
            originales.append(replace(fuente, orden=ordenes[fuente.tabla]))
            ordenes[fuente.tabla] += 1
    huella_original = huella_fuentes(originales)
    generaciones = []
    for padre in padres:
        path = padre / NOMBRE_MANIFIESTO

        def error(campo, motivo):
            errores.append(DiagnosticoCSV(str(path), 0, campo, "GENERACION", motivo))

        if (padre / MARCA_INCOMPLETA).exists():
            error("estado", "La generación no terminó; no se carga ni sobrescribe ese directorio.")
            continue
        if padre.resolve() not in con_manifiesto:
            continue
        try:
            contenido = path.read_bytes()
            m = json.loads(contenido.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            error("archivo", "No se pudo leer un manifiesto JSON UTF-8 válido.")
            continue
        if not isinstance(m, dict) or m.get("tipo") != "farmared_adicionales" or type(m.get("version_generador")) is not int or m["version_generador"] != VERSION_GENERADOR:
            error("version_generador", "Tipo/versión de generación no soportado.")
            continue
        try:
            base = date.fromisoformat(m["base_date"])
            if base.isoformat() != m["base_date"]:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            error("base_date", "Se requiere fecha base ISO YYYY-MM-DD persistida.")
            continue
        if m.get("huella_originales") != huella_original or len(originales) < 9:
            error("huella_originales", "Se requieren los originales vinculados por el manifiesto, sin cambios.")
        try:
            perfil = json.loads(construir_archivos(base, huella_original)[NOMBRE_MANIFIESTO])
        except (OverflowError, ValueError):
            error("base_date", "La fecha base no permite los desplazamientos del perfil.")
            continue
        if m != perfil:
            error("perfil", "El manifiesto no corresponde al perfil determinista de esa fecha/originales/versión.")
        archivos = m.get("archivos")
        if not isinstance(archivos, dict) or set(archivos) != {f"{t}.csv" for t in CAMPOS}:
            error("archivos", "El manifiesto debe describir los nueve CSV adicionales.")
            continue
        propias = [f for f in fuentes if Path(f.archivo).parent.resolve() == padre.resolve()]
        for tabla in CAMPOS:
            seleccion = [f for f in propias if f.tabla == tabla]
            registro = archivos[f"{tabla}.csv"]
            if len(seleccion) != 1 or not isinstance(registro, dict):
                error(tabla, "Se requiere una fuente por cada CSV del manifiesto.")
                continue
            fuente = seleccion[0]
            if (registro.get("sha256") != fuente.sha256 or type(registro.get("filas")) is not int
                    or registro.get("filas") != fuente.filas_leidas):
                error(tabla, "Hash/conteo del CSV no coincide con el manifiesto; no se regenera al cargar.")
            propias_tabla = [f for f in filas[tabla] if Path(f.archivo).parent.resolve() == padre.resolve()]
            if len(propias_tabla) < 10:
                error(tabla, "Se requieren al menos diez filas adicionales en cada CSV.")
            for fila in propias_tabla:
                pk = fila.datos.get(CLAVES[tabla])
                if pk is not None and not pk.startswith("A-"):
                    errores.append(DiagnosticoCSV(fila.archivo, fila.fila, CLAVES[tabla], "GENERACION", "Los IDs adicionales deben tener prefijo A-."))
        orden = propias[0].orden if propias else 0
        generaciones.append(GeneracionCSV(str(path), orden, hashlib.sha256(contenido).hexdigest(), base, m["version_generador"]))
    if len({g.base_date for g in generaciones}) > 1:
        errores.append(DiagnosticoCSV("manifiestos", 0, "base_date", "GENERACION", "Las fuentes generadas deben compartir fecha base."))
    return tuple(generaciones)
