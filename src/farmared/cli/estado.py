"""Información local del paquete, sin prometer disponibilidad de los motores."""

import argparse
import json
from importlib.metadata import version

from farmared.clock import SystemClock, ZONA_COMERCIAL


def ejecutar(args: argparse.Namespace) -> int:
    instante = SystemClock().now_utc()
    print(json.dumps({
        "version": version("farmared"),
        "fecha_comercial": instante.astimezone(ZONA_COMERCIAL).date().isoformat(),
        "instante_utc": instante.isoformat(),
        "motores": "no_comprobados",
        "proyeccion": "no_comprobada",
    }, ensure_ascii=False))
    return 0
