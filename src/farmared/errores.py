
from enum import StrEnum


class CodigoError(StrEnum):
    NO_EXISTE = "NO_EXISTE"
    VALIDACION = "VALIDACION"
    DNI_DUPLICADO = "DNI_DUPLICADO"
    STOCK_INSUFICIENTE = "STOCK_INSUFICIENTE"
    RECETA_INVALIDA = "RECETA_INVALIDA"
    CONFLICTO_ID = "CONFLICTO_ID"
    INTEGRIDAD = "INTEGRIDAD"
    SYNC_EN_CURSO = "SYNC_EN_CURSO"


class ErrorDominio(Exception):
    """Error esperado. `codigo` es estable; `mensaje` explica el rechazo."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        self.codigo = str(codigo)
        self.mensaje = mensaje
        super().__init__(mensaje)

    def __str__(self) -> str:
        return f"{self.codigo}: {self.mensaje}"
