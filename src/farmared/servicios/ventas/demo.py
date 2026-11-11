"""Demostración de q14/q15 sobre el dataset de entrega, con antes/después de cada paso.

Requiere una base cargada con originales + adicionales (setup --solo-mongo). Usa
ids fijos `B-DEMO-*`: repetirla no duplica efectos (los pasos exitosos se
reconocen como reutilizados), pero el antes/después útil es el de la primera
ejecución sobre una base recién cargada.

Los resultados dependen del día comercial del reloj: con la fecha base de los
adicionales, A-L002 vence ese mismo día y todavía se dispensa.
"""

from farmared.clock import Clock
from farmared.consultas.q14 import q14_registrar_venta
from farmared.consultas.q15 import q15_actualizar_stock
from farmared.errores import CodigoError, ErrorDominio

LOTES_DEMO = ["A-L001", "A-L002", "A-L003", "A-L004", "A-L006", "A-L016"]

PASOS = [
    {
        "paso": "q14_exito_receta_fefo",
        "descripcion": "Venta Completada con receta de tratamiento prolongado: FEFO omite vencidos, "
                       "usa primero el lote que vence antes y consume una dispensa.",
        "operacion": "q14",
        "parametros": {"id_venta": "B-DEMO-V1", "id_cliente": "A-C001", "id_farmaceutico": "A-F001",
                       "id_receta": "A-RC001", "medio_pago": "Obra social",
                       "items": [{"id_producto": "A-PRD003", "cantidad": 6},
                                 {"id_producto": "A-PRD001", "cantidad": 2}]},
        "observar": {"stock_lotes": LOTES_DEMO, "recetas": ["A-RC001"], "ventas": ["B-DEMO-V1"]},
    },
    {
        "paso": "q14_rechazo_stock",
        "descripcion": "Un ítem alcanza y otro no: se rechaza toda la venta; ni lotes ni receta cambian.",
        "operacion": "q14",
        "parametros": {"id_venta": "B-DEMO-V2", "id_cliente": "A-C001", "id_farmaceutico": "A-F001",
                       "id_receta": "A-RC001", "medio_pago": "Efectivo",
                       "items": [{"id_producto": "A-PRD003", "cantidad": 1},
                                 {"id_producto": "A-PRD001", "cantidad": 1000}]},
        "observar": {"stock_lotes": LOTES_DEMO, "recetas": ["A-RC001"], "ventas": ["B-DEMO-V2"]},
    },
    {
        "paso": "q14_rechazo_cliente_inactivo",
        "descripcion": "Cliente dado de baja (C008): rechazo por validación sin efectos.",
        "operacion": "q14",
        "parametros": {"id_venta": "B-DEMO-V3", "id_cliente": "C008", "id_farmaceutico": "F001",
                       "medio_pago": "Efectivo", "items": [{"id_producto": "PRD001", "cantidad": 1}]},
        "observar": {"stock_lotes": ["L001"], "ventas": ["B-DEMO-V3"]},
    },
    {
        "paso": "q14_reintento_idempotente",
        "descripcion": "Reintento del primer pedido con el mismo id: devuelve la venta confirmada sin nuevos efectos.",
        "operacion": "q14",
        "parametros": None,  # se completa con el pedido del primer paso
        "observar": {"stock_lotes": LOTES_DEMO, "recetas": ["A-RC001"]},
    },
    {
        "paso": "q15_exito_pendiente",
        "descripcion": "Pendiente V011 (receta simple RC006): se completa hoy, con FEFO en la sucursal "
                       "del farmacéutico (S004) y la receta pasa a Completada.",
        "operacion": "q15",
        "parametros": {"id_venta": "V011"},
        "observar": {"stock_lotes": ["L014"], "recetas": ["RC006"], "ventas": ["V011"]},
    },
    {
        "paso": "q15_rechazo_pendiente",
        "descripcion": "Pendiente V012: su farmacéutico (F005) está en S003, sin lotes de sus productos. "
                       "Se rechaza y la pendiente queda igual.",
        "operacion": "q15",
        "parametros": {"id_venta": "V012"},
        "observar": {"ventas": ["V012"]},
    },
]
PASOS[3]["parametros"] = PASOS[0]["parametros"]

REQUERIDOS = {"clientes": ["A-C001", "C008"], "farmaceuticos": ["A-F001", "F001"],
              "recetas": ["A-RC001", "RC006"], "ventas": ["V011", "V012"]}


def _foto(db, observar: dict) -> dict:
    return {coleccion: {i: db[coleccion].find_one({"_id": i}) for i in ids} for coleccion, ids in observar.items()}


def ejecutar_demo(db, clock: Clock) -> dict:
    """Ejecuta los pasos en orden y devuelve antes/después y resultado de cada uno."""
    for coleccion, ids in REQUERIDOS.items():
        if db[coleccion].count_documents({"_id": {"$in": ids}}) != len(ids):
            raise ErrorDominio(CodigoError.NO_EXISTE, "La demo requiere originales + adicionales cargados "
                               "(farmared setup --solo-mongo con ambos directorios).")
    pasos = []
    for paso in PASOS:
        antes = _foto(db, paso["observar"])
        try:
            if paso["operacion"] == "q14":
                r = q14_registrar_venta(db, paso["parametros"], clock)
            else:
                r = q15_actualizar_stock(db, paso["parametros"]["id_venta"], clock)
            resultado = {"estado": "ok", "reutilizada": r["reutilizada"], "eventos": r["eventos"]}
        except ErrorDominio as error:
            resultado = {"estado": "rechazo", "codigo": error.codigo, "mensaje": error.mensaje}
        pasos.append({**{k: paso[k] for k in ("paso", "descripcion", "operacion", "parametros")},
                      "resultado": resultado, "antes": antes, "despues": _foto(db, paso["observar"])})
    return {"base": db.name, "fecha_comercial": clock.today().isoformat(),
            "instante_utc": clock.now_utc().isoformat(), "pasos": pasos}
