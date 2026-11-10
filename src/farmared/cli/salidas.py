"""Resumen de carga común a seed y al setup de MongoDB."""

from farmared.clock import ZONA_COMERCIAL


def resumen_carga(base, resultado):
    m = resultado["documento"]
    return {
        "base": base, "carga": m["estado"], "reutilizada": resultado["reutilizada"],
        "huella": m["huella"], "base_date": m["base_date"].astimezone(ZONA_COMERCIAL).date().isoformat(),
        "conteos_iniciales": m["conteos"], "eventos_emitidos": len(resultado["eventos"]),
        "avisos": m["avisos"], "proyeccion": "no_comprobada",
    }
