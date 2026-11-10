"""Contenedor Neo4j exclusivo, reutilizado por las integraciones de D."""

from pathlib import Path
from copy import deepcopy
from dataclasses import replace
import re
import shutil
import subprocess
from time import monotonic, sleep
from uuid import uuid4

import pytest

from farmared.config import Config
from farmared.conexiones import obtener_mongo
from farmared.esquema.base_mongo import preparar_mongo_base
from farmared.conexiones import obtener_neo4j
from farmared.errores import ErrorDominio

def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()


@pytest.fixture(scope="module")
def driver():
    if not shutil.which("docker"):
        pytest.skip("Docker no está disponible; integración no ejecutada.")
    compose = Path(__file__).resolve().parents[2] / "infra/docker-compose.yml"
    imagen = re.search(r"image: (neo4j:\S+)", compose.read_text(encoding="utf-8"))[1]
    clave = uuid4().hex
    # --pull=never evita descargas implícitas. No se monta ningún volumen.
    contenedor = docker("run", "--pull=never", "--rm", "-d", "--memory=1536m",
                        "-p", "127.0.0.1::7687", "-e", f"NEO4J_AUTH=neo4j/{clave}",
                        "-e", "NEO4J_server_memory_heap_max__size=512m",
                        "-e", "NEO4J_server_memory_pagecache_size=256m", imagen)
    try:
        puerto = docker("port", contenedor, "7687/tcp").rsplit(":", 1)[1]
        config = Config(neo4j_uri=f"bolt://127.0.0.1:{puerto}",
                        neo4j_password=clave, db_timeout_ms=1000)
        limite = monotonic() + 90
        while True:
            try:
                conexion = obtener_neo4j(config)
                break
            except ErrorDominio:
                if monotonic() >= limite:
                    raise
                sleep(1)
        with conexion:
            yield conexion
    finally:
        docker("stop", contenedor)



@pytest.fixture(scope="module")
def casos_q03():
    """Resultados esperados de datos sintéticos; fechas Python y dinero entero."""
    from datetime import date

    def receta(id, dia, estado, proxima=None):
        return dict(fecha=date(2026, 1, dia), tipo_evento="RECETA", id_registro=id,
                    estado=estado, detalle=dict(tipo="Simple", medico="Médica de prueba",
                    dispensas_realizadas=1, dispensas_autorizadas=2, proxima_dispensa=proxima))

    def item(id, producto, orden, cantidad, precio, nombre=None):
        return dict(id_detalle=id, id_producto=producto, orden=orden, cantidad=cantidad,
                    precio_unit=precio, subtotal=cantidad * precio, nombre_al_vender=nombre)

    def venta(id, dia, estado, items, receta=None):
        return dict(fecha=date(2026, 1, dia), tipo_evento="VENTA", id_registro=id,
                    estado=estado, detalle=dict(tipo="Con receta" if receta else "Venta libre",
                    total=sum(i["subtotal"] for i in items), medio_pago="Efectivo",
                    id_receta=receta, items=items))

    r1 = receta("Q03-R1", 1, "Completada")
    r2 = receta("Q03-R2", 3, "Vencida", date(2026, 2, 1))
    v1 = venta("Q03-V1", 2, "Pendiente", [
        item("D1", "Q03-P1", 0, 2, 100, "Nombre histórico"),
        item("D2", "Q03-P1", 0, 1, 120),
        item("D3", "Q03-P2", 1, 3, 50),
    ], "Q03-R1")
    v2 = venta("Q03-V2", 3, "Anulada", [])
    return {
        "Q03-COMPLETO": [r1, v1, r2, v2],
        "Q03-RECETAS": [receta("Q03-R3", 4, "Vigente")],
        "Q03-VENTAS": [venta("Q03-V3", 4, "Completada", [])],
        "Q03-EMPATES": [receta("Q03-R4", 5, "Vencida"),
                        receta("Q03-R5", 5, "Completada"),
                        venta("Q03-V4", 5, "Pendiente", []),
                        venta("Q03-V5", 5, "Anulada", [])],
        "Q03-VACIO": [],
        "Q03-INEXISTENTE": [],
    }


@pytest.fixture
def documentos_proyeccion():
    """Documentos sintéticos con la forma proyectada de MongoDB, sin conectar Mongo."""
    from datetime import UTC, datetime
    from uuid import uuid4

    prefijo = 'PROY-' + uuid4().hex
    def id(sufijo):
        return prefijo + '-' + sufijo
    return {
        'clientes': {'_id': id('C'), 'nombre': 'Ana', 'apellido': 'Prueba', 'activo': False,
                     'importacion': {'ignorada': True}},
        'sucursales': {'_id': id('S'), 'nombre': 'Sucursal prueba', 'tipo': 'Farmacia'},
        'farmaceuticos': {'_id': id('F'), 'nombre': 'Luis', 'apellido': 'Prueba',
                         'matricula': id('M'), 'activo': False, 'id_sucursal': id('S')},
        'productos': {'_id': id('P'), 'nombre': 'Nombre actual', 'categoria': 'Higiene',
                      'precio_unit': 99999},
        'recetas': {'_id': id('R'), 'id_cliente': id('C'), 'medico': 'Médico prueba',
                    'tipo': 'Simple', 'fecha_emision': datetime(2026, 1, 1, 3, tzinfo=UTC),
                    'proxima_dispensa': None, 'estado': 'Completada',
                    'dispensas_realizadas': 1, 'dispensas_autorizadas': 1},
        'ventas': {'_id': id('V'), 'id_cliente': id('C'), 'id_farmaceutico': id('F'),
                   'id_sucursal': 'NO-USAR-SUCURSAL-HISTORICA', 'id_receta': id('R'),
                   'fecha': datetime(2026, 1, 2, 3, tzinfo=UTC), 'tipo': 'Con receta',
                   'estado': 'Pendiente', 'medio_pago': 'Efectivo', 'total': 320,
                   'items': [
                       {'id_detalle': 'D1', 'id_producto': id('P'), 'cantidad': 2,
                        'precio_unit': 100, 'subtotal': 200, 'nombre_al_vender': 'Nombre anterior'},
                       {'id_detalle': 'D2', 'id_producto': id('P'), 'cantidad': 1,
                        'precio_unit': 120, 'subtotal': 120},
                   ]},
    }



@pytest.fixture(scope='module')
def mongo_config():
    compose = Path(__file__).resolve().parents[2] / 'infra/docker-compose.yml'
    imagen = re.search(r'image: (mongo:\S+)', compose.read_text(encoding='utf-8'))[1]
    contenedor = docker('run', '--pull=never', '--rm', '-d', '--memory=1024m',
                        '-p', '127.0.0.1::27017', imagen, 'mongod', '--replSet', 'rs0', '--bind_ip_all')
    try:
        puerto = docker('port', contenedor, '27017/tcp').rsplit(':', 1)[1]
        limite = monotonic() + 90
        while True:
            try:
                docker('exec', contenedor, 'mongosh', '--quiet', '--eval',
                       'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27017"}]})')
                break
            except subprocess.CalledProcessError:
                if monotonic() >= limite:
                    raise
                sleep(0.2)
        config = Config(mongo_uri=f'mongodb://127.0.0.1:{puerto}/?replicaSet=rs0&directConnection=true',
                        mongo_db='farmared_test_d_sync_arranque', db_timeout_ms=2000)
        while True:
            try:
                temporal = obtener_mongo(config)
                temporal.client.close()
                break
            except ErrorDominio:
                if monotonic() >= limite:
                    raise
                sleep(0.2)
        yield config
    finally:
        docker('stop', contenedor)


@pytest.fixture
def db_sync(mongo_config):
    config = replace(mongo_config, mongo_db='farmared_test_d_sync_' + uuid4().hex)
    database = obtener_mongo(config)
    try:
        preparar_mongo_base(database)
        yield database
    finally:
        assert database.name.startswith('farmared_test_d_sync_')
        database.client.drop_database(database.name)
        database.client.close()


@pytest.fixture
def fuente(documentos_proyeccion):
    docs = deepcopy(documentos_proyeccion)
    docs['clientes'].update(dni=uuid4().hex, email=None, telefono=None, ciudad='Prueba',
                            provincia='Prueba', obra_social='Sin cobertura', nro_afiliado=None)
    docs['sucursales'].update(direccion='Prueba', ciudad='Prueba', provincia='Prueba', telefono=None, activo=True)
    docs['farmaceuticos']['cargo'] = 'Farmacéutico'
    docs['productos'].update(principio_activo=None, presentacion='Unidad', condicion_venta='Venta libre',
                             id_proveedor='PROVEEDOR-NO-PROYECTADO', activo=True)
    docs['recetas']['matricula_medico'] = 'MP-PRUEBA'
    docs['ventas'].update(id_sucursal=docs['sucursales']['_id'], stock_aplicado=False, receta_aplicada=False,
                         origen='servicio', trazabilidad_lotes='no_aplicada')
    for item in docs['ventas']['items']:
        item['asignaciones_lotes'] = []
    return docs
