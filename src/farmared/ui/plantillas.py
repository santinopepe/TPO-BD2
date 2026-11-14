"""Representaciones editables de las consultas originales, sin conectarse a motores."""

from importlib import import_module

from bson import json_util

from farmared.clock import SystemClock

ESCRITURAS = [
    {"id": "q13", "titulo": "Administrar clientes", "descripcion": "Alta, modificación o baja lógica con evento outbox.",
     "motor": "mongo", "parametro": None, "escritura": True,
     "plantilla": {"operacion": "q13", "accion": "alta", "datos": {
         "nombre": "Ana", "apellido": "Pérez", "dni": "12345678", "ciudad": "Buenos Aires",
         "provincia": "Buenos Aires", "obra_social": "Sin cobertura", "nro_afiliado": None}}},
    {"id": "q14", "titulo": "Registrar venta", "descripcion": "Registra la venta, aplica FEFO y actualiza receta y outbox.",
     "motor": "mongo", "parametro": None, "escritura": True,
     "plantilla": {"operacion": "q14", "pedido": {"id_venta": "UI-V001", "id_cliente": "ID_CLIENTE",
         "id_farmaceutico": "ID_FARMACEUTICO", "medio_pago": "Efectivo",
         "items": [{"id_producto": "ID_PRODUCTO", "cantidad": 1}]}}},
    {"id": "q15", "titulo": "Completar venta pendiente", "descripcion": "Completa una venta pendiente y descuenta el stock por FEFO.",
     "motor": "mongo", "parametro": None, "escritura": True,
     "plantilla": {"operacion": "q15", "id_venta": "ID_VENTA_PENDIENTE"}},
]


class _Captura:
    """Recibe el filtro/pipeline que construye la consulta, sin ejecutarlo."""

    def __init__(self):
        self.consulta = None

    def __getitem__(self, nombre):
        self.nombre = nombre
        return self

    def __getattr__(self, nombre):
        return self[nombre]

    def aggregate(self, pipeline):
        self.consulta = {"coleccion": self.nombre, "pipeline": pipeline}
        return []

    def find(self, filtro=None):
        self.consulta = {"coleccion": self.nombre, "filtro": filtro or {}}
        return []


def plantilla(codigo, motor, funcion, parametro):
    modulo = import_module(f"farmared.consultas.{codigo}")
    if motor == "neo4j":
        return {"texto": modulo.CYPHER.strip(), "parametros": {parametro: ""} if parametro else {}}
    captura = _Captura()
    if codigo == "q11":
        captura["ventas"].aggregate(modulo.pipeline_ingresos_mensuales())
    else:
        args = [SystemClock()] if parametro == "reloj" else []
        getattr(modulo, funcion)(captura, *args)
    return {"texto": json_util.dumps(captura.consulta, ensure_ascii=False, indent=2), "parametros": {}}


def catalogo(consultas):
    lecturas = [dict(id=q, titulo=t, descripcion=d, motor=m, escritura=False,
                    parametro=p if p != "reloj" else None, **plantilla(q, m, f, p))
               for q, t, d, m, f, p in consultas]
    escrituras = [{**{k: v for k, v in q.items() if k != "plantilla"},
                   "texto": json_util.dumps(q["plantilla"], ensure_ascii=False, indent=2), "parametros": {}}
                  for q in ESCRITURAS]
    return lecturas + escrituras
