"""Fallos: caída antes del commit, respuesta perdida después del commit y Neo4j apagado."""

import json
import os
import subprocess
import sys

import pytest

from farmared.consultas import q14 as modulo_q14
from farmared.consultas import q15 as modulo_q15
from farmared.consultas.q14 import q14_registrar_venta
from farmared.consultas.q15 import q15_actualizar_stock
from farmared.errores import CodigoError, ErrorDominio

PEDIDO = {"id_venta": "B-VF1", "id_cliente": "B-C001", "id_farmaceutico": "B-F001", "medio_pago": "Débito",
          "id_receta": "B-RC001", "items": [{"id_producto": "B-P003", "cantidad": 2},
                                            {"id_producto": "B-P001", "cantidad": 6}]}


def unidades(db, *ids):
    return tuple(db.stock_lotes.find_one({"_id": i})["unidades"] for i in ids)


def caida(*args, **kwargs):
    raise RuntimeError("caída simulada del proceso antes del commit")


def perder_respuesta(original):
    """La transacción confirma, pero el llamador recibe un error como si se cortara la red."""
    def envoltura(db, operacion):
        original(db, operacion)
        raise ErrorDominio(CodigoError.CONEXION, "respuesta perdida después del commit")
    return envoltura


def pendiente_desde_q14(db, reloj, id_venta):
    """Crea una pendiente válida usando una venta de q14 como molde y revirtiendo sus efectos."""
    q14_registrar_venta(db, {**PEDIDO, "id_venta": "B-MOLDE", "id_receta": None,
                             "items": [{"id_producto": "B-P002", "cantidad": 1}]}, reloj)
    molde = db.ventas.find_one_and_delete({"_id": "B-MOLDE"})
    db.stock_lotes.update_one({"_id": "B-L004"}, {"$inc": {"unidades": 1}})
    db.outbox.delete_many({})
    molde.update(_id=id_venta, estado="Pendiente", stock_aplicado=False, trazabilidad_lotes="no_aplicada",
                 fecha_creacion_pendiente=molde["fecha"])
    molde.pop("request_hash")
    molde["items"][0].update(id_detalle=f"{id_venta}-D1", asignaciones_lotes=[])
    db.ventas.insert_one(molde)


# --- Caída antes del commit --------------------------------------------------

def test_q14_caida_despues_de_descontar_y_dispensar_no_deja_nada(db, escenario, estado_db, reloj, monkeypatch):
    antes = estado_db()
    monkeypatch.setattr(modulo_q14, "registrar_evento", caida)  # stock y receta ya escritos en la sesión
    with pytest.raises(RuntimeError):
        q14_registrar_venta(db, PEDIDO, reloj)
    assert estado_db() == antes

    monkeypatch.undo()  # el proceso se recupera y reintenta con el mismo id
    resultado = q14_registrar_venta(db, PEDIDO, reloj)
    assert resultado["reutilizada"] is False
    assert unidades(db, "B-L001", "B-L002", "B-L005") == (0, 8, 18)


def test_q15_caida_antes_del_commit_deja_la_pendiente_igual(db, escenario, estado_db, reloj, monkeypatch):
    pendiente_desde_q14(db, reloj, "B-VP1")
    antes = estado_db()
    monkeypatch.setattr(modulo_q15, "registrar_evento", caida)
    with pytest.raises(RuntimeError):
        q15_actualizar_stock(db, "B-VP1", reloj)
    assert estado_db() == antes


# --- Respuesta perdida después del commit ------------------------------------

def test_q14_respuesta_perdida_se_recupera_con_el_mismo_id(db, escenario, reloj, monkeypatch):
    monkeypatch.setattr(modulo_q14, "ejecutar_transaccion", perder_respuesta(modulo_q14.ejecutar_transaccion))
    with pytest.raises(ErrorDominio) as exc:
        q14_registrar_venta(db, PEDIDO, reloj)
    assert exc.value.codigo == "CONEXION"
    assert db.ventas.count_documents({"_id": "B-VF1"}) == 1  # sí se confirmó

    monkeypatch.undo()
    reintento = q14_registrar_venta(db, PEDIDO, reloj)
    assert reintento["reutilizada"] is True and reintento["eventos"] == []
    assert unidades(db, "B-L001", "B-L002", "B-L005") == (0, 8, 18)
    assert db.recetas.find_one({"_id": "B-RC001"})["dispensas_realizadas"] == 2
    assert db.outbox.count_documents({}) == 1


def test_q15_respuesta_perdida_se_recupera_con_el_mismo_id(db, escenario, reloj, monkeypatch):
    pendiente_desde_q14(db, reloj, "B-VP1")
    saldo = unidades(db, "B-L004")
    monkeypatch.setattr(modulo_q15, "ejecutar_transaccion", perder_respuesta(modulo_q15.ejecutar_transaccion))
    with pytest.raises(ErrorDominio):
        q15_actualizar_stock(db, "B-VP1", reloj)

    monkeypatch.undo()
    reintento = q15_actualizar_stock(db, "B-VP1", reloj)
    assert reintento["reutilizada"] is True
    assert unidades(db, "B-L004") == (saldo[0] - 1,)
    assert db.outbox.count_documents({}) == 1


# --- Neo4j apagado -------------------------------------------------------------

SCRIPT_SIN_NEO4J = """
import json, sys
from dataclasses import replace
from datetime import UTC, datetime
from farmared.clock import FixedClock
from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.consultas.q14 import q14_registrar_venta

db = obtener_mongo(replace(Config.from_env(), mongo_db=sys.argv[1]))
try:
    r = q14_registrar_venta(db, json.loads(sys.argv[2]), FixedClock(datetime(2026, 11, 10, 15, tzinfo=UTC)))
finally:
    db.client.close()
print(json.dumps({"reutilizada": r["reutilizada"], "eventos": r["eventos"],
                  "neo4j_importado": "neo4j" in sys.modules}))
"""


def test_q14_confirma_con_neo4j_inaccesible_y_deja_evento_pendiente(db, escenario):
    entorno = {**os.environ, "NEO4J_URI": "bolt://127.0.0.1:1", "NEO4J_PASSWORD": ""}
    proceso = subprocess.run([sys.executable, "-c", SCRIPT_SIN_NEO4J, db.name, json.dumps(PEDIDO)],
                             env=entorno, capture_output=True, text=True, timeout=60)
    assert proceso.returncode == 0, proceso.stderr
    salida = json.loads(proceso.stdout)
    assert salida["reutilizada"] is False and salida["neo4j_importado"] is False
    evento = db.outbox.find_one({"_id": salida["eventos"][0]})
    assert evento["procesado"] is False  # queda para que sync lo proyecte al volver Neo4j
    assert db.ventas.find_one({"_id": "B-VF1"})["estado"] == "Completada"
