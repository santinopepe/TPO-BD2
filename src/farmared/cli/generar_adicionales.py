"""CLI de generación, sin acceso a motores."""

import argparse
import json
from datetime import date

from farmared.carga.adicionales import generar_adicionales
from farmared.carga.modelos import ErrorDatasets


def ejecutar(args: argparse.Namespace) -> int:
    try:
        base = None if args.base_date is None else date.fromisoformat(args.base_date)
        if base is not None and base.isoformat() != args.base_date:
            raise ValueError()
    except ValueError:
        from farmared.errores import ErrorDominio
        raise ErrorDominio("VALIDACION", "--base-date requiere YYYY-MM-DD.") from None
    try:
        resultado = generar_adicionales(args.directorio, args.originales, base_date=base)
    except ErrorDatasets as error:
        print(json.dumps(error.resumen(), ensure_ascii=False))
        return 1
    print(json.dumps(resultado, ensure_ascii=False))
    return 0
