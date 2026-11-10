
import argparse
import sys
from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import version

from farmared.errores import ErrorDominio

COMANDOS = {
    "estado": ("farmared.cli.estado", "ejecutar"),
    "salud": ("farmared.cli.salud", "ejecutar"),
    "preparar-mongo": ("farmared.cli.preparar_mongo", "ejecutar"),
    "validar-datasets": ("farmared.cli.validar_datasets", "ejecutar"),
    "seed": ("farmared.cli.seed", "ejecutar"),
    "generar-adicionales": ("farmared.cli.generar_adicionales", "ejecutar"),
    "setup": ("farmared.cli.setup", "ejecutar"),
    "reset-demo": ("farmared.cli.reset_demo", "ejecutar"),
}
PENDIENTES = {
    **{f"q{i:02}": "D" if i in (3, 4, 10) else "B" if i in (14, 15) else "C"
       for i in range(1, 16)},
    "sync": "D", "demo-transaccion": "B",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="farmared", description="FarmaRed — TPO BD2")
    parser.add_argument("--version", action="version", version=version("farmared"))
    subparsers = parser.add_subparsers(dest="comando", required=True)
    subparsers.add_parser("estado", help="Versión y reloj local; no comprueba motores.")
    salud = subparsers.add_parser("salud", help="Comprueba primario MongoDB y/o conectividad Neo4j.")
    salud.add_argument("--motor", choices=("mongo", "neo4j", "ambos"), default="ambos")
    preparar = subparsers.add_parser("preparar-mongo", help="Crea/asegura el esquema base; requiere escritores pausados.")
    preparar.add_argument("--base", required=True, help="Nombre explícito de la base destino.")
    validar = subparsers.add_parser("validar-datasets", help="Valida los nueve CSV sin escribir en motores.")
    validar.add_argument("--directorio", required=True, action="append", help="Directorio con nueve CSV; repetible para validar su unión.")
    seed = subparsers.add_parser("seed", help="Carga MongoDB de forma idempotente; no sincroniza Neo4j.")
    seed.add_argument("--base", required=True, help="Nombre explícito de la base destino.")
    seed.add_argument("--directorio", required=True, action="append", help="Directorio con nueve CSV; repetible.")
    adicionales = subparsers.add_parser("generar-adicionales", help="Genera o verifica nueve CSV propios sin motores.")
    adicionales.add_argument("--directorio", required=True, help="Directorio nuevo de destino o generación existente para verificar.")
    adicionales.add_argument("--originales", default="data/originales", help="Directorio de los nueve CSV originales.")
    adicionales.add_argument("--base-date", help="Fecha ISO explícita; por defecto hoy solo al crear.")
    setup = subparsers.add_parser("setup", help="Prepara/carga MongoDB; integración completa C/D pendiente.")
    setup.add_argument("--base", required=True, help="Nombre explícito de la base destino.")
    setup.add_argument("--directorio", required=True, action="append", help="Directorio con nueve CSV; repetible.")
    setup.add_argument("--solo-mongo", action="store_true", help="Ejecuta solo el bootstrap de A, sin vistas C ni grafo/sync D.")
    reset = subparsers.add_parser("reset-demo", help="Vista previa o borrado confirmado de una base farmared_demo_*. PAUSAR escritores.")
    reset.add_argument("--base", required=True, help="Base farmared_demo_* que se inspecciona o elimina.")
    reset.add_argument("--solo-mongo", required=True, action="store_true", help="Alcance explícito: Neo4j no se reinicia.")
    reset.add_argument("--confirmar-base", help="Repetir exactamente --base para borrar toda esa base. Sin esta opción: vista previa.")
    for comando, responsable in PENDIENTES.items():
        subparsers.add_parser(comando, help=f"Pendiente de implementación/integración ({responsable}).")
    args = parser.parse_args(argv)
    if args.comando in PENDIENTES:
        print(
            f"NO_IMPLEMENTADO: {args.comando} pendiente de implementación/integración "
            f"por Persona {PENDIENTES[args.comando]}; no se ejecutó ninguna operación.",
            file=sys.stderr,
        )
        return 3
    modulo, funcion = COMANDOS[args.comando]
    try:
        handler = getattr(import_module(modulo), funcion)
        return handler(args)
    except ErrorDominio as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
