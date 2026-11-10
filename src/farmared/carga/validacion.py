"""Snapshot en memoria de fuentes CSV: valida sin importar drivers ni escribir archivos."""

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from farmared.carga.formatos import CAMPOS, convertir
from farmared.carga.modelos import DatasetValidado, DiagnosticoCSV, ErrorDatasets, FilaCSV, FuenteCSV, VERSION_VALIDACION
from farmared.carga.reglas import validar_relaciones

RutasDataset = Mapping[str, Sequence[str | Path] | str | Path]


def rutas_desde_directorios(*directorios: str | Path) -> dict[str, tuple[Path, ...]]:
    """Cada directorio debe aportar los nueve CSV; se valida la unión de sus filas."""
    return {nombre: tuple(Path(d) / f"{nombre}.csv" for d in directorios) for nombre in CAMPOS}


def _leer(tabla, ruta, orden, errores):
    archivo = str(ruta)
    try:
        contenido = ruta.read_bytes()
    except OSError as error:
        errores.append(DiagnosticoCSV(archivo, 0, "archivo", "LECTURA", f"No se pudo leer ({type(error).__name__})."))
        return [], None, False
    sha = hashlib.sha256(contenido).hexdigest()
    filas = []
    leidas = 0
    completo = True
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        errores.append(DiagnosticoCSV(archivo, 0, "archivo", "CODIFICACION", "Se requiere UTF-8."))
        return [], FuenteCSV(tabla, orden, archivo, sha, len(contenido), 0), False
    reader = csv.reader(io.StringIO(texto, newline=""), strict=True)
    try:
        cabecera = next(reader, [])
        if len(cabecera) != len(set(cabecera)) or set(cabecera) != set(CAMPOS[tabla]):
            faltan = sorted(set(CAMPOS[tabla]) - set(cabecera))
            sobran = sorted(set(cabecera) - set(CAMPOS[tabla]))
            errores.append(DiagnosticoCSV(archivo, 1, "cabecera", "ESTRUCTURA", f"Cabecera inválida: faltan={faltan}, sobran={sobran}; no se permiten columnas repetidas."))
            completo = False
        else:
            while True:
                linea = reader.line_num + 1
                valores = next(reader, None)
                if valores is None:
                    break
                if not valores:  # Líneas vacías de los originales; no son registros.
                    continue
                leidas += 1
                if len(valores) != len(cabecera):
                    errores.append(DiagnosticoCSV(archivo, linea, "fila", "ESTRUCTURA", f"Se esperaban {len(cabecera)} columnas; se recibieron {len(valores)}."))
                    completo = False
                    continue
                datos = {}
                for campo, valor in zip(cabecera, valores):
                    try:
                        datos[campo] = convertir(tabla, campo, valor)
                    except ValueError as error:
                        errores.append(DiagnosticoCSV(archivo, linea, campo, "VALOR", str(error)))
                filas.append(FilaCSV(archivo, linea, datos))
    except csv.Error:
        errores.append(DiagnosticoCSV(archivo, max(1, reader.line_num), "fila", "ESTRUCTURA", "CSV mal formado o campo mayor al límite del lector."))
        completo = False
    return filas, FuenteCSV(tabla, orden, archivo, sha, len(contenido), leidas), completo


def validar_datasets(rutas: RutasDataset) -> DatasetValidado:
    """Solo devuelve filas listas si no hay errores. Los avisos no alteran el histórico.

    Las claves de rutas son los nueve nombres sin .csv; cada valor es una secuencia
    de paths, en orden de origen. La huella ignora paths absolutos y usa los bytes
    efectivamente leídos, no una segunda lectura de las fuentes.
    """
    errores, fuentes = [], []
    filas = {nombre: [] for nombre in CAMPOS}
    completas = set()
    for desconocida in sorted(set(rutas) - set(CAMPOS)):
        errores.append(DiagnosticoCSV(str(desconocida), 0, "archivo", "ESTRUCTURA", "Tabla no reconocida."))
    for tabla in CAMPOS:
        paths = rutas.get(tabla, ())
        if isinstance(paths, (str, Path)):
            paths = (paths,)
        if not paths:
            errores.append(DiagnosticoCSV(f"{tabla}.csv", 0, "archivo", "LECTURA", "No se indicó ninguna fuente para esta tabla."))
            continue
        completa = True
        for orden, path in enumerate(paths):
            leidas, fuente, ok = _leer(tabla, Path(path), orden, errores)
            filas[tabla].extend(leidas)
            if fuente is not None:
                fuentes.append(fuente)
            completa = completa and ok
        if completa:
            completas.add(tabla)
            if not filas[tabla]:
                errores.append(DiagnosticoCSV(str(paths[0]), 0, "fila", "VACIO", "La tabla no contiene registros."))
    avisos = validar_relaciones(filas, completas, errores)
    if errores:
        raise ErrorDatasets(errores, fuentes, avisos)
    identidad = {
        "version_validacion": VERSION_VALIDACION,
        "fuentes": [{"tabla": f.tabla, "orden": f.orden, "sha256": f.sha256} for f in fuentes],
    }
    huella = hashlib.sha256(json.dumps(identidad, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return DatasetValidado(filas, tuple(fuentes), huella, tuple(avisos))
