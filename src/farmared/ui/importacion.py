"""Carga CSV con las mismas validaciones y transacciones del seed oficial."""

import base64
import binascii
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from pymongo import timeout
from pymongo.errors import PyMongoError

from farmared.carga.formatos import CAMPOS
from farmared.carga.modelos import ErrorDatasets
from farmared.carga.mongo import cargar_mongo
from farmared.carga.transformacion import transformar_mongo
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets
from farmared.cli.salidas import resumen_carga
from farmared.errores import ErrorDominio
from farmared.esquema.consultas_mongo import preparar_consultas_mongo

DATOS_PROYECTO = Path(__file__).resolve().parents[3] / "data"
MAX_BYTES = 10 * 1024 * 1024
MAX_CUERPO = 15 * 1024 * 1024
NOMBRES = {f"{tabla}.csv" for tabla in CAMPOS} | {"manifiesto.json", ".generacion_incompleta"}


def _error(mensaje):
    raise ErrorDominio("VALIDACION", mensaje)


def _archivos(datos):
    if datos.get("origen") == "proyecto":
        conjuntos = {"originales": ("originales",), "completo": ("originales", "adicionales")}
        seleccion = datos.get("conjunto", "completo")
        if not isinstance(seleccion, str) or seleccion not in conjuntos:
            _error("Elegí originales o completo como conjunto de CSVs.")
        archivos = []
        for carpeta in conjuntos[seleccion]:
            for nombre in sorted(NOMBRES):
                ruta = DATOS_PROYECTO / carpeta / nombre
                if nombre.endswith(".csv") or ruta.exists():
                    try:
                        contenido = ruta.read_bytes()
                    except OSError:
                        raise ErrorDominio("NO_EXISTE", f"No se encontró data/{carpeta}/{nombre}. Podés subir tus archivos.") from None
                    archivos.append((f"{carpeta}/{nombre}", contenido))
        return archivos
    if datos.get("origen") != "archivos":
        _error("Elegí los CSVs del proyecto o subí archivos.")
    archivos = datos.get("archivos")
    if not isinstance(archivos, list) or not 1 <= len(archivos) <= 100:
        _error("Seleccioná entre 1 y 100 archivos CSV/manifiestos.")
    resultado, nombres, total = [], set(), 0
    for archivo in archivos:
        if not isinstance(archivo, dict):
            _error("Cada archivo debe incluir nombre y contenido_base64.")
        nombre, contenido = archivo.get("nombre"), archivo.get("contenido_base64")
        if (not isinstance(nombre, str) or not nombre or len(nombre) > 500
                or "\\" in nombre or any(ord(c) < 32 for c in nombre)
                or any(p in {"", ".", ".."} for p in nombre.split("/"))):
            _error("El nombre de archivo debe ser una ruta relativa válida.")
        ruta = PurePosixPath(nombre)
        if (ruta.is_absolute() or ruta.name not in NOMBRES or len(ruta.parts) > 10
                or any(parte in NOMBRES for parte in ruta.parts[:-1])):
            _error("Solo se admiten los nueve CSVs de FarmaRed y sus manifiestos, con rutas relativas.")
        if nombre in nombres:
            _error(f"Archivo repetido: {nombre}. Seleccioná carpetas para conservar las rutas de cada conjunto.")
        nombres.add(nombre)
        if not isinstance(contenido, str):
            _error(f"Falta contenido_base64 en {nombre}.")
        try:
            contenido = base64.b64decode(contenido, validate=True)
        except (ValueError, binascii.Error):
            _error(f"El contenido de {nombre} no es Base64 válido.")
        total += len(contenido)
        if total > MAX_BYTES:
            _error("Los archivos superan el límite de 10 MiB por carga.")
        resultado.append((nombre, contenido))
    return resultado


def procesar_csv(consola, datos, *, importar=False):
    archivos = _archivos(datos)
    with TemporaryDirectory(prefix="farmared-csv-") as temporal:
        raiz = Path(temporal)
        carpetas = set()
        for nombre, contenido in archivos:
            destino = raiz / nombre
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(contenido)
            if nombre.endswith(".csv"):
                carpetas.add(destino.parent)
        # Mismo orden que la carga oficial: originales antes de fuentes generadas.
        carpetas = sorted(carpetas, key=lambda p: ((p / "manifiesto.json").exists(), str(p.relative_to(raiz))))
        rutas = rutas_desde_directorios(*carpetas)
        try:
            validado = validar_datasets(rutas)
        except ErrorDatasets as error:
            return _rutas_publicas(error.resumen(), raiz)
        resumen = _rutas_publicas(validado.resumen(), raiz)
        resumen["conteos_documentos"] = {nombre: len(filas) for nombre, filas in transformar_mongo(validado).items()}
        if not importar:
            return resumen
        if datos.get("huella_esperada") != validado.huella:
            _error("Los archivos cambiaron o falta la validación previa. Volvé a validar antes de cargar.")
        db = consola._mongo()
        try:
            with timeout(consola.config.db_timeout_ms / 1000):
                resultado = cargar_mongo(db, rutas)
                carga = _rutas_publicas(resumen_carga(db.name, resultado), raiz)
                try:
                    preparar_consultas_mongo(db)
                    preparacion = {"estado": "lista"}
                except (ErrorDominio, PyMongoError):
                    preparacion = {"estado": "error", "mensaje": "Los datos se cargaron, pero no se pudieron preparar los índices/vista de consultas. Reintentá la misma carga para completar la preparación."}
        finally:
            db.client.close()
        sincronizacion = consola.sincronizar_neo4j()
        return {**resumen, "carga": carga, "preparacion_consultas": preparacion,
                "sincronizacion": sincronizacion}


def _rutas_publicas(valor, raiz):
    """Los diagnósticos muestran los nombres originales, no el directorio temporal."""
    if isinstance(valor, dict):
        return {k: _rutas_publicas(v, raiz) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_rutas_publicas(v, raiz) for v in valor]
    if isinstance(valor, str) and valor.startswith(str(raiz) + "/"):
        return str(Path(valor).relative_to(raiz))
    return valor
