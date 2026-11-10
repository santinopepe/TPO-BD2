"""Adaptador CLI de B (q14, q15, demo-transaccion); la lógica vive en consultas/ y servicios/ventas/.

Integración en `__main__.py` (archivo de A), igual que `cli_grafo` de D:
    from farmared.cli_ventas import COMANDOS_VENTAS, registrar_comandos as registrar_ventas
    COMANDOS = {**COMANDOS_GRAFO, **COMANDOS_VENTAS, ...}
    # quitar q14, q15 y demo-transaccion de PENDIENTES
    registrar_ventas(subparsers)

No importa PyMongo al registrar: los módulos de venta se cargan al ejecutar.
Los ErrorDominio se propagan; `__main__` los imprime y sale con código 1.
"""

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from farmared.clock import ZONA_COMERCIAL, SystemClock, inicio_dia_utc
from farmared.config import Config
from farmared.errores import CodigoError, ErrorDominio

COMANDOS_VENTAS = {nombre: ("farmared.cli_ventas", "ejecutar") for nombre in ("q14", "q15", "demo-transaccion")}
PREFIJO_DEMO = "farmared_demo_"


def _no_vacio(valor: str) -> str:
    if not valor.strip() or valor != valor.strip():
        raise argparse.ArgumentTypeError("Se requiere un valor no vacío, sin espacios al inicio/final.")
    return valor


def registrar_comandos(subparsers) -> None:
    q14 = subparsers.add_parser("q14", help="Registra una venta Completada (FEFO + receta, transacción MongoDB).")
    q14.add_argument("--base", required=True, type=_no_vacio, help="Base MongoDB explícita.")
    q14.add_argument("--pedido", required=True, help="Archivo JSON del pedido, o '-' para leerlo de stdin.")
    q15 = subparsers.add_parser("q15", help="Aplica FEFO a una venta Pendiente y la completa.")
    q15.add_argument("--base", required=True, type=_no_vacio, help="Base MongoDB explícita.")
    q15.add_argument("--id-venta", required=True, type=_no_vacio)
    demo = subparsers.add_parser("demo-transaccion",
                                 help="Demostración q14/q15 con antes/después; solo bases farmared_demo_*.")
    demo.add_argument("--base", required=True, type=_no_vacio, help="Base farmared_demo_* ya cargada.")
    demo.add_argument("--salida", help="Archivo JSON nuevo donde guardar la evidencia (no se sobrescribe).")


def ejecutar(args: argparse.Namespace) -> int:
    if args.comando == "demo-transaccion" and (not args.base.startswith(PREFIJO_DEMO) or args.base == PREFIJO_DEMO):
        raise ErrorDominio(CodigoError.VALIDACION, "demo-transaccion modifica datos: solo admite bases farmared_demo_<sufijo>.")
    if getattr(args, "salida", None):
        # Se verifica antes de conectar: la demo modifica datos y la evidencia no debe perderse.
        if Path(args.salida).exists():
            raise ErrorDominio(CodigoError.VALIDACION, f"{args.salida} ya existe; no se sobrescribe evidencia.")
        if not Path(args.salida).resolve().parent.is_dir():
            raise ErrorDominio(CodigoError.VALIDACION, f"No existe la carpeta de {args.salida}; crearla antes de ejecutar la demo.")
    pedido = _leer_pedido(args.pedido) if args.comando == "q14" else None

    from farmared.conexiones import obtener_mongo

    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        if args.comando == "q14":
            generado = "id_venta" not in pedido
            if generado:
                pedido = {**pedido, "id_venta": str(uuid4())}
            from farmared.consultas.q14 import q14_registrar_venta
            salida = _salida_escritura("q14", db.name, q14_registrar_venta(db, pedido, SystemClock()))
            salida["id_venta_generado"] = generado
            if generado:
                salida["aviso"] = "id_venta generado; para reintentar sin duplicar, reenviar con este id."
        elif args.comando == "q15":
            from farmared.consultas.q15 import q15_actualizar_stock
            salida = _salida_escritura("q15", db.name, q15_actualizar_stock(db, args.id_venta, SystemClock()))
        else:
            from farmared.servicios.ventas.demo import ejecutar_demo
            salida = ejecutar_demo(db, SystemClock())
            if args.salida:
                _guardar(Path(args.salida), salida)
                salida = {"base": db.name, "evidencia": args.salida, "pasos": [
                    {"paso": p["paso"], **p["resultado"]} for p in salida["pasos"]]}
    finally:
        db.client.close()
    print(a_json(salida))
    return 0


def _leer_pedido(origen: str) -> dict:
    try:
        texto = sys.stdin.read() if origen == "-" else Path(origen).read_text(encoding="utf-8")
        pedido = json.loads(texto)
    except OSError:
        raise ErrorDominio(CodigoError.VALIDACION, f"No se pudo leer el pedido {origen}.") from None
    except json.JSONDecodeError as error:
        raise ErrorDominio(CodigoError.VALIDACION, f"El pedido no es JSON válido (línea {error.lineno}).") from None
    if not isinstance(pedido, dict):
        raise ErrorDominio(CodigoError.VALIDACION, "El pedido debe ser un objeto JSON.")
    return pedido


def _salida_escritura(operacion: str, base: str, resultado: dict) -> dict:
    return {"operacion": operacion, "base": base, "reutilizada": resultado["reutilizada"],
            "eventos": resultado["eventos"], "venta": resultado["documento"],
            "proyeccion": "pendiente_sync"}


def _guardar(ruta: Path, contenido: dict) -> None:
    try:
        with ruta.open("x", encoding="utf-8") as archivo:
            archivo.write(a_json(contenido, indent=2) + "\n")
    except FileExistsError:
        raise ErrorDominio(CodigoError.VALIDACION, f"{ruta} ya existe; no se sobrescribe evidencia.") from None
    except OSError:
        raise ErrorDominio(CodigoError.VALIDACION, f"No se pudo escribir {ruta}.") from None


def _fecha(valor: datetime) -> str:
    """Inicio de día comercial → 'YYYY-MM-DD'; otro instante → ISO 8601 UTC."""
    dia = valor.astimezone(ZONA_COMERCIAL).date()
    return dia.isoformat() if valor == inicio_dia_utc(dia) else valor.isoformat()


def a_json(valor, indent=None) -> str:
    def convertir(obj):
        if isinstance(obj, datetime):
            return _fecha(obj)
        raise TypeError(f"No serializable: {type(obj).__name__}")
    return json.dumps(valor, ensure_ascii=False, default=convertir, indent=indent)
