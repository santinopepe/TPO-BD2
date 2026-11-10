"""Resultados explícitos: un dataset inválido nunca se devuelve como listo para cargar."""

from dataclasses import asdict, dataclass
from typing import Any

from farmared.errores import CodigoError, ErrorDominio

VERSION_VALIDACION = 1


@dataclass(frozen=True)
class DiagnosticoCSV:
    archivo: str
    fila: int
    campo: str
    codigo: str
    motivo: str


@dataclass(frozen=True)
class FilaCSV:
    archivo: str
    fila: int
    datos: dict[str, Any]


@dataclass(frozen=True)
class FuenteCSV:
    tabla: str
    orden: int
    archivo: str
    sha256: str
    bytes: int
    filas_leidas: int


@dataclass(frozen=True)
class DatasetValidado:
    filas: dict[str, list[FilaCSV]]
    fuentes: tuple[FuenteCSV, ...]
    huella: str
    avisos: tuple[DiagnosticoCSV, ...]

    def resumen(self) -> dict:
        return {
            "valido": True, "version_validacion": VERSION_VALIDACION,
            "conteos": {k: len(v) for k, v in self.filas.items()},
            "huella": self.huella, "fuentes": [asdict(f) for f in self.fuentes],
            "errores": [], "avisos": [asdict(a) for a in self.avisos],
            "escrituras": 0,
        }


class ErrorDatasets(ErrorDominio):
    def __init__(self, errores, fuentes=(), avisos=()):
        self.errores = tuple(errores)
        self.fuentes = tuple(fuentes)
        self.avisos = tuple(avisos)
        super().__init__(CodigoError.VALIDACION, f"Dataset inválido: {len(self.errores)} error(es).")

    def resumen(self) -> dict:
        return {
            "valido": False, "version_validacion": VERSION_VALIDACION, "huella": None,
            "fuentes": [asdict(f) for f in self.fuentes],
            "errores": [asdict(e) for e in self.errores],
            "avisos": [asdict(a) for a in self.avisos], "escrituras": 0,
        }
