from typing import NotRequired, TypedDict

from farmared.contratos import ObraSocial
from farmared.errores import CodigoError


class DatosAltaCliente(TypedDict):
    nombre: str
    apellido: str
    dni: str
    ciudad: str
    provincia: str
    obra_social: ObraSocial
    email: NotRequired[str | None]
    telefono: NotRequired[str | None]
    nro_afiliado: NotRequired[str | None]


class CambiosCliente(TypedDict, total=False):
    email: str | None
    telefono: str | None
    ciudad: str
    provincia: str
    obra_social: ObraSocial
    nro_afiliado: str | None


CAMPOS_ALTA_OBLIGATORIOS = DatosAltaCliente.__required_keys__
CAMPOS_ALTA_PERMITIDOS = CAMPOS_ALTA_OBLIGATORIOS | DatosAltaCliente.__optional_keys__
CAMPOS_MODIFICABLES = CambiosCliente.__optional_keys__
CODIGOS_ERROR_CLIENTES = frozenset({
    CodigoError.VALIDACION,
    CodigoError.DNI_DUPLICADO,
    CodigoError.NO_EXISTE,
    CodigoError.CONFLICTO_ID,
    CodigoError.INTEGRIDAD,
    CodigoError.CONEXION,
})
