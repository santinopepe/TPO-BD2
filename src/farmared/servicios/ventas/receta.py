"""Reglas de receta de la venta: si se exige, si es válida y cómo cambia al dispensar.

Una dispensa = una venta asociada a receta, no una por ítem. La receta no trae
productos prescriptos, así que no se valida compatibilidad producto–receta.
"""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from farmared.clock import inicio_dia_utc
from farmared.errores import CodigoError, ErrorDominio

CONDICIONES_CON_RECETA = frozenset({"Bajo receta", "Bajo receta archivada"})
DIAS_ENTRE_DISPENSAS = 30


def requiere_receta(productos: Iterable[Mapping]) -> bool:
    """True si algún producto es 'Bajo receta' o 'Bajo receta archivada'."""
    return any(p.get("condicion_venta") in CONDICIONES_CON_RECETA for p in productos)


def tipo_venta(requiere: bool) -> str:
    """Tipo de venta derivado de los productos, no declarado por quien pide."""
    return "Con receta" if requiere else "Venta libre"


def validar_receta(receta: Mapping | None, id_receta: str | None, id_cliente: str, requiere: bool) -> None:
    """Rechaza si la combinación productos/receta no habilita la venta.

    - Requiere receta y no se indicó: RECETA_INVALIDA.
    - No requiere y se indicó: VALIDACION (no se gasta una dispensa sin necesidad).
    - Indicada pero inexistente: NO_EXISTE.
    - De otro cliente, no 'Vigente' o sin dispensas disponibles: RECETA_INVALIDA.
    """
    if not requiere:
        if id_receta is not None:
            raise ErrorDominio(CodigoError.VALIDACION, f"La venta solo tiene productos de venta libre; no corresponde asociar la receta {id_receta}.")
        return
    if id_receta is None:
        raise ErrorDominio(CodigoError.RECETA_INVALIDA, "La venta incluye productos bajo receta y no indica receta.")
    if receta is None:
        raise ErrorDominio(CodigoError.NO_EXISTE, f"No existe la receta {id_receta}.")
    if receta.get("id_cliente") != id_cliente:
        raise ErrorDominio(CodigoError.RECETA_INVALIDA, f"La receta {id_receta} pertenece a otro cliente.")
    if receta.get("estado") != "Vigente":
        raise ErrorDominio(CodigoError.RECETA_INVALIDA, f"La receta {id_receta} está en estado {receta.get('estado')}, no Vigente.")
    realizadas, autorizadas = _contadores(receta)
    if realizadas >= autorizadas:
        raise ErrorDominio(CodigoError.RECETA_INVALIDA, f"La receta {id_receta} no tiene dispensas disponibles.")


def transicion_receta(receta: Mapping, hoy: date) -> dict:
    """Campos nuevos de la receta tras dispensar hoy (una dispensa por venta).

    - Simple/Archivada: se completa con su única dispensa.
    - Tratamiento prolongado: suma una dispensa; si quedan, próxima = hoy + 30
      días; si se alcanzan las autorizadas, Completada y próxima nula.
    """
    realizadas, autorizadas = _contadores(receta)
    nuevas = realizadas + 1
    tipo = receta.get("tipo")
    if tipo in ("Simple", "Archivada") or nuevas >= autorizadas:
        return {"dispensas_realizadas": nuevas, "estado": "Completada", "proxima_dispensa": None}
    if tipo != "Tratamiento prolongado":
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"Tipo de receta desconocido: {tipo}.")
    return {
        "dispensas_realizadas": nuevas,
        "estado": "Vigente",
        "proxima_dispensa": inicio_dia_utc(hoy + timedelta(days=DIAS_ENTRE_DISPENSAS)),
    }


def _contadores(receta: Mapping) -> tuple[int, int]:
    realizadas = receta.get("dispensas_realizadas")
    autorizadas = receta.get("dispensas_autorizadas")
    if type(realizadas) is not int or type(autorizadas) is not int or realizadas < 0 or autorizadas < 1:
        raise ErrorDominio(CodigoError.INTEGRIDAD, f"La receta {receta.get('_id')} tiene contadores de dispensa inválidos.")
    return realizadas, autorizadas
