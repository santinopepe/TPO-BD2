from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any, get_args

from farmared.contratos import ObraSocial
from farmared.errores import CodigoError, ErrorDominio
from farmared.servicios.clientes.contratos import (
    CAMPOS_ALTA_OBLIGATORIOS,
    CAMPOS_ALTA_PERMITIDOS,
    CAMPOS_MODIFICABLES,
    CambiosCliente,
    DatosAltaCliente,
)

OBRAS_SOCIALES = frozenset(get_args(ObraSocial))
CAMPOS_NULOS = frozenset({"email", "telefono", "nro_afiliado"})


def _validar_campos(datos, permitidos, obligatorios=frozenset()) -> None:
    if not isinstance(datos, Mapping):
        raise ErrorDominio(CodigoError.VALIDACION, "Los datos del cliente deben ser un objeto con campos.")
    claves = set(datos)
    desconocidos = claves - permitidos
    if desconocidos:
        campos = ", ".join(sorted(map(str, desconocidos)))
        raise ErrorDominio(CodigoError.VALIDACION, f"Campos de cliente no permitidos: {campos}.")
    faltantes = obligatorios - claves
    if faltantes:
        campos = ", ".join(sorted(faltantes))
        raise ErrorDominio(CodigoError.VALIDACION, f"Faltan campos obligatorios: {campos}.")


def _normalizar_texto(valor, campo: str, admite_nulo=False) -> str | None:
    if valor is None and admite_nulo:
        return None
    if not isinstance(valor, str):
        tipo_esperado = "un string o nulo" if admite_nulo else "un string"
        raise ErrorDominio(CodigoError.VALIDACION, f"{campo} debe ser {tipo_esperado}.")
    texto = valor.strip()
    if not texto:
        if admite_nulo:
            return None
        raise ErrorDominio(CodigoError.VALIDACION, f"{campo} no puede estar vacío.")
    return texto


def _normalizar_campo(campo: str, valor) -> str | None:
    texto = _normalizar_texto(valor, campo, admite_nulo=campo in CAMPOS_NULOS)
    if campo == "dni" and re.fullmatch(r"[0-9]+", texto) is None:
        raise ErrorDominio(CodigoError.VALIDACION, "dni debe contener únicamente dígitos ASCII.")
    if campo == "obra_social" and texto not in OBRAS_SOCIALES:
        raise ErrorDominio(CodigoError.VALIDACION, "obra_social no pertenece a las coberturas permitidas.")
    return texto


def validar_cobertura(datos: Mapping[str, Any]) -> None:
    if not isinstance(datos, Mapping):
        raise ErrorDominio(CodigoError.VALIDACION, "La cobertura debe recibirse como campos de un objeto.")
    obra_social = datos.get("obra_social")
    afiliado = datos.get("nro_afiliado")
    if not isinstance(obra_social, str) or obra_social not in OBRAS_SOCIALES:
        raise ErrorDominio(CodigoError.VALIDACION, "obra_social no pertenece a las coberturas permitidas.")
    if obra_social == "Sin cobertura":
        if afiliado is not None:
            raise ErrorDominio(CodigoError.VALIDACION, "Sin cobertura exige nro_afiliado nulo.")
    elif not isinstance(afiliado, str) or not afiliado.strip():
        raise ErrorDominio(CodigoError.VALIDACION, "Una obra social exige nro_afiliado no vacío.")


def normalizar_alta(datos: Mapping[str, Any]) -> DatosAltaCliente:
    _validar_campos(datos, CAMPOS_ALTA_PERMITIDOS, CAMPOS_ALTA_OBLIGATORIOS)
    normalizados = {campo: _normalizar_campo(campo, datos.get(campo))
                    for campo in CAMPOS_ALTA_PERMITIDOS}
    validar_cobertura(normalizados)
    return normalizados


def normalizar_cambios(cambios: Mapping[str, Any]) -> CambiosCliente:
    _validar_campos(cambios, CAMPOS_MODIFICABLES)
    if not cambios:
        raise ErrorDominio(CodigoError.VALIDACION, "La modificación debe incluir al menos un campo.")
    return {campo: _normalizar_campo(campo, valor) for campo, valor in cambios.items()}


def combinar_cambios(cliente: Mapping[str, Any], cambios: Mapping[str, Any]) -> dict:
    if not isinstance(cliente, Mapping):
        raise ErrorDominio(CodigoError.INTEGRIDAD, "El cliente actual no es un documento válido.")
    normalizados = normalizar_cambios(cambios)
    resultado = deepcopy(dict(cliente))
    resultado.update(normalizados)
    validar_cobertura(resultado)
    return resultado


def validar_id_cliente(id_cliente: str) -> str:
    if not isinstance(id_cliente, str) or not id_cliente.strip() or id_cliente != id_cliente.strip():
        raise ErrorDominio(CodigoError.VALIDACION, "id_cliente debe ser un string no vacío, sin espacios exteriores.")
    return id_cliente
