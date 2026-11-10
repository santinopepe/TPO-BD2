"""Transformación pura: no reproduce servicios de venta ni cambia el snapshot."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from farmared.carga.modelos import ErrorDatasets
from farmared.carga.mongo import _eventos, cargar_mongo
from farmared.carga.transformacion import transformar_mongo
from farmared.carga.validacion import rutas_desde_directorios, validar_datasets

ORIGINALES = Path(__file__).resolve().parents[2] / "data/originales"


def test_transforma_sin_modificar_snapshot_ni_repreciar():
    v = validar_datasets(rutas_desde_directorios(ORIGINALES))
    antes = deepcopy(v.filas)
    docs = transformar_mongo(v)
    assert sum(len(d) for d in docs.values()) == 81
    assert "detalle_ventas" not in docs
    assert v.filas == antes
    venta = docs["ventas"][0]
    assert venta["_id"] == "V001" and "id_venta" not in venta
    assert venta["id_sucursal"] == "S002"
    assert venta["items"][0]["precio_unit"] == 3850
    assert venta["items"][0]["subtotal"] == 3850
    assert venta["items"][0]["importacion"]["fila"] == 2
    assert venta["importacion"]["huella"] == v.huella
    assert next(p for p in docs["productos"] if p["_id"] == "PRD007")["precio_unit"] == 4800
    assert next(l for l in docs["stock_lotes"] if l["_id"] == "L018")["unidades"] == 15
    assert next(r for r in docs["recetas"] if r["_id"] == "RC002")["proxima_dispensa"] == datetime(2026, 9, 15, 3, tzinfo=UTC)


@pytest.mark.parametrize("id_venta,stock,receta,traza", [
    ("V001", True, True, "desconocida"), ("V013", True, False, "desconocida"),
    ("V011", False, False, "no_aplicada"), ("V015", False, False, "no_aplicada"),
])
def test_marcas_historicas(id_venta, stock, receta, traza):
    docs = transformar_mongo(validar_datasets(rutas_desde_directorios(ORIGINALES)))
    venta = next(v for v in docs["ventas"] if v["_id"] == id_venta)
    assert venta["stock_aplicado"] is stock
    assert venta["receta_aplicada"] is receta
    assert venta["trazabilidad_lotes"] == traza
    assert venta["origen"] == "csv" and "request_hash" not in venta
    assert all(i["asignaciones_lotes"] == (None if stock else []) for i in venta["items"])
    if venta["estado"] == "Pendiente":
        assert venta["fecha_creacion_pendiente"] == venta["fecha"]


def test_eventos_reales_estables_solo_entidades_proyectadas():
    v = validar_datasets(rutas_desde_directorios(ORIGINALES))
    docs = transformar_mongo(v)
    instante = datetime(2026, 11, 10, 15, 42, tzinfo=UTC)
    eventos = _eventos(docs, v.huella, instante)
    reintento = _eventos(docs, v.huella, instante + timedelta(days=1))
    assert len(eventos) == 58
    assert len({e["_id"] for e in eventos}) == 58
    assert [e["_id"] for e in eventos] == [e["_id"] for e in reintento]
    for e in eventos:
        assert UUID(e["_id"]).version == 5
        assert e["procesado"] is False and e["creado_en"] == instante
        afectada = e["afectadas"][0]
        assert afectada["coleccion"] not in {"proveedores", "stock_lotes"}
        assert any(d["_id"] == afectada["id"] for d in docs[afectada["coleccion"]])


def test_validacion_falla_antes_de_tocar_database(tmp_path):
    with pytest.raises(ErrorDatasets):
        cargar_mongo(object(), rutas_desde_directorios(tmp_path))
