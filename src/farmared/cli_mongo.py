import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from farmared.clock import SystemClock
from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.errores import CodigoError, ErrorDominio

COMANDOS_MONGO = {nombre: ("farmared.cli_mongo", "ejecutar") for nombre in ("q01", "q02", "q05", "q06", "q07", "q08", "q09", "q11", "q12", "q13")}


def _no_vacio(valor: str) -> str:
    if not valor.strip() or valor != valor.strip():
        raise argparse.ArgumentTypeError("Se requiere un valor no vacío, sin espacios exteriores.")
    return valor


def registrar_comandos(subparsers) -> None:
    q01 = subparsers.add_parser("q01", help="Productos activos con todos los datos de su proveedor (MongoDB).")
    q01.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q02 = subparsers.add_parser("q02", help="Ventas pendientes con farmacéutico, matrícula, sucursal y total (MongoDB).")
    q02.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q05 = subparsers.add_parser("q05", help="Farmacéuticos activos y cantidad de ventas no anuladas en los últimos 60 días (MongoDB).")
    q05.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q06 = subparsers.add_parser("q06", help="Recetas prolongadas vigentes con dispensa anterior a hoy y datos del cliente (MongoDB).")
    q06.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q07 = subparsers.add_parser("q07", help="Top 5 productos por unidades en ventas completadas (MongoDB).")
    q07.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q08 = subparsers.add_parser("q08", help="Lotes con menos de 50 unidades, producto, proveedor y sucursal (MongoDB).")
    q08.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q09 = subparsers.add_parser("q09", help="Ventas libres menores a $5000, excepto anuladas (MongoDB).")
    q09.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q11 = subparsers.add_parser("q11", help="Vista de ingresos por farmacéutico en el mes actual (MongoDB).")
    q11.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q12 = subparsers.add_parser("q12", help="Clientes sin ventas registradas en el último año (MongoDB).")
    q12.add_argument("--base", required=True, help="Base MongoDB explícita.")
    q13 = subparsers.add_parser("q13", help="Alta, modificación de contacto/cobertura y baja lógica de clientes (MongoDB).")
    q13.add_argument("--base", required=True, type=_no_vacio, help="Base MongoDB explícita.")
    acciones = q13.add_subparsers(dest="accion", required=True)
    alta = acciones.add_parser("alta", help="Crea un cliente activo con DNI único.")
    alta.add_argument("--datos", required=True, help="Archivo JSON del cliente o '-' para leer stdin.")
    modificar = acciones.add_parser("modificar", help="Modifica contacto, ubicación y cobertura.")
    modificar.add_argument("--id-cliente", required=True, type=_no_vacio)
    modificar.add_argument("--datos", required=True, help="Archivo JSON de cambios o '-' para leer stdin.")
    baja = acciones.add_parser("baja", help="Da de baja lógica al cliente, conservando su historia.")
    baja.add_argument("--id-cliente", required=True, type=_no_vacio)


def _fecha_json(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()
    raise TypeError(f"Tipo no serializable: {type(valor).__name__}")


def _leer_datos_cliente(origen: str) -> dict:
    try:
        texto = sys.stdin.read() if origen == "-" else Path(origen).read_text(encoding="utf-8")
        datos = json.loads(texto)
    except (OSError, UnicodeError):
        raise ErrorDominio(CodigoError.VALIDACION, f"No se pudieron leer los datos de {origen} como UTF-8.") from None
    except json.JSONDecodeError as error:
        raise ErrorDominio(CodigoError.VALIDACION, f"Los datos no son JSON válido (línea {error.lineno}).") from None
    if not isinstance(datos, dict):
        raise ErrorDominio(CodigoError.VALIDACION, "Los datos del cliente deben ser un objeto JSON.")
    return datos


def _ejecutar_q13(args: argparse.Namespace) -> int:
    datos = _leer_datos_cliente(args.datos) if args.accion != "baja" else None
    from farmared.consultas.q13 import q13_alta, q13_baja, q13_modificar

    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        clock = SystemClock()
        if args.accion == "alta":
            resultado = q13_alta(db, datos, clock=clock)
        elif args.accion == "modificar":
            resultado = q13_modificar(db, args.id_cliente, datos, clock=clock)
        else:
            resultado = q13_baja(db, args.id_cliente, clock=clock)
        salida = {"operacion": "q13", "accion": args.accion, "base": db.name, **resultado,
                  "proyeccion": "pendiente_sync" if resultado["eventos"] else "no_comprobada"}
        print(json.dumps(salida, ensure_ascii=False, default=_fecha_json))
        return 0
    finally:
        db.client.close()


def ejecutar(args: argparse.Namespace) -> int:
    if args.comando == "q13":
        return _ejecutar_q13(args)
    parametros = ()
    if args.comando == "q01":
        from farmared.consultas.q01 import q01_productos_activos as consultar
    elif args.comando == "q02":
        from farmared.consultas.q02 import q02_ventas_pendientes as consultar
    elif args.comando == "q05":
        from farmared.consultas.q05 import q05_ventas_por_farmaceutico as consultar
        parametros = (SystemClock(),)
    elif args.comando == "q06":
        from farmared.consultas.q06 import q06_recetas_prolongadas as consultar
        parametros = (SystemClock(),)
    elif args.comando == "q07":
        from farmared.consultas.q07 import q07_top_productos as consultar
    elif args.comando == "q08":
        from farmared.consultas.q08 import q08_lotes_stock_bajo as consultar
    elif args.comando == "q11":
        from farmared.consultas.q11 import q11_ingresos_mensuales as consultar
    elif args.comando == "q12":
        from farmared.consultas.q12 import q12_clientes_sin_ventas as consultar
        parametros = (SystemClock(),)
    else:
        from farmared.consultas.q09 import q09_ventas_libres as consultar

    db = obtener_mongo(replace(Config.from_env(), mongo_db=args.base))
    try:
        salida = {"consulta": args.comando, "base": db.name,
                  "resultados": consultar(db, *parametros)}
        print(json.dumps(salida, ensure_ascii=False, default=_fecha_json))
        return 0
    finally:
        db.client.close()
