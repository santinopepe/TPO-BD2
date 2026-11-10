"""Integridad del snapshot CSV y avisos históricos; no ejecuta servicios de venta."""

from collections import defaultdict
from datetime import timedelta

from farmared.carga.formatos import CLAVES
from farmared.carga.modelos import DiagnosticoCSV
from farmared.contratos import MAX_IMPORTE_ARS
from farmared.clock import ZONA_COMERCIAL, inicio_dia_utc

REFERENCIAS = (
    ("farmaceuticos", "id_sucursal", "sucursales"),
    ("productos", "id_proveedor", "proveedores"),
    ("stock_lotes", "id_producto", "productos"),
    ("stock_lotes", "id_sucursal", "sucursales"),
    ("recetas", "id_cliente", "clientes"),
    ("ventas", "id_cliente", "clientes"),
    ("ventas", "id_farmaceutico", "farmaceuticos"),
    ("ventas", "id_receta", "recetas"),
    ("detalle_ventas", "id_venta", "ventas"),
    ("detalle_ventas", "id_producto", "productos"),
)


def _anotar(lista, fila, campo, codigo, motivo):
    lista.append(DiagnosticoCSV(fila.archivo, fila.fila, campo, codigo, motivo))


def _indices(filas, errores):
    indices = {nombre: {} for nombre in filas}
    for nombre, registros in filas.items():
        campos = [CLAVES[nombre]]
        if nombre == "clientes":
            campos.append("dni")
        if nombre == "farmaceuticos":
            campos.append("matricula")
        for campo in campos:
            vistos = {}
            for fila in registros:
                valor = fila.datos.get(campo)
                if valor is None:
                    continue
                if valor in vistos:
                    previa = vistos[valor]
                    _anotar(errores, fila, campo, "DUPLICADO", f"Valor repetido; primera aparición en {previa.archivo}:{previa.fila}.")
                else:
                    vistos[valor] = fila
            if campo == CLAVES[nombre]:
                indices[nombre] = vistos
    return indices


def _validar_maestros(filas, errores):
    for fila in filas["clientes"]:
        d = fila.datos
        if {"obra_social", "nro_afiliado"} <= d.keys():
            if (d["obra_social"] == "Sin cobertura") != (d["nro_afiliado"] is None):
                _anotar(errores, fila, "nro_afiliado", "COHERENCIA", "Sin cobertura exige afiliado nulo; una cobertura exige afiliado no vacío.")
    for fila in filas["recetas"]:
        d = fila.datos
        if {"dispensas_realizadas", "dispensas_autorizadas", "tipo", "estado", "proxima_dispensa"} <= d.keys():
            real, autorizadas = d["dispensas_realizadas"], d["dispensas_autorizadas"]
            if real > autorizadas:
                _anotar(errores, fila, "dispensas_realizadas", "COHERENCIA", "Supera dispensas autorizadas.")
            if d["tipo"] in {"Simple", "Archivada"} and autorizadas != 1:
                _anotar(errores, fila, "dispensas_autorizadas", "COHERENCIA", "Receta simple/archivada admite una única dispensa.")
            if d["estado"] == "Completada" and (real != autorizadas or d["proxima_dispensa"] is not None):
                _anotar(errores, fila, "estado", "COHERENCIA", "Completada exige dispensas agotadas y próxima dispensa nula.")
            if d["estado"] == "Vigente" and real >= autorizadas:
                _anotar(errores, fila, "estado", "COHERENCIA", "Una receta vigente debe tener dispensas disponibles.")
            if d["tipo"] in {"Simple", "Archivada"} and d["proxima_dispensa"] is not None:
                _anotar(errores, fila, "proxima_dispensa", "COHERENCIA", "No corresponde próxima dispensa para simple/archivada.")
            if d["tipo"] == "Tratamiento prolongado" and d["estado"] == "Vigente" and real > 0 and d["proxima_dispensa"] is None:
                _anotar(errores, fila, "proxima_dispensa", "COHERENCIA", "Tratamiento vigente ya dispensado requiere próxima fecha.")
        if d.get("proxima_dispensa") is not None and "fecha_emision" in d:
            if d["proxima_dispensa"] < d["fecha_emision"]:
                _anotar(errores, fila, "proxima_dispensa", "COHERENCIA", "No puede ser anterior a la emisión.")


def _totales(filas, completas, errores):
    detalles = defaultdict(list)
    for fila in filas["detalle_ventas"]:
        if "id_venta" in fila.datos:
            detalles[fila.datos["id_venta"]].append(fila)
        if {"cantidad", "precio_unit"} <= fila.datos.keys():
            subtotal = fila.datos["cantidad"] * fila.datos["precio_unit"]
            if subtotal > MAX_IMPORTE_ARS:
                _anotar(errores, fila, "precio_unit", "RANGO", "cantidad × precio_unit excede int64 ARS.")
    if "detalle_ventas" in completas:
        for fila in filas["ventas"]:
            d = fila.datos
            if "id_venta" not in d:
                continue
            lineas = detalles[d["id_venta"]]
            if not lineas:
                _anotar(errores, fila, "id_venta", "DETALLE", "La venta debe tener al menos un ítem.")
            elif all({"cantidad", "precio_unit"} <= item.datos.keys() for item in lineas):
                total = sum(item.datos["cantidad"] * item.datos["precio_unit"] for item in lineas)
                if total > MAX_IMPORTE_ARS:
                    _anotar(errores, fila, "total", "RANGO", "La suma de subtotales excede int64 ARS.")
                elif "total" in d and total != d["total"]:
                    _anotar(errores, fila, "total", "TOTAL", "No coincide con suma(cantidad × precio_unit) de sus detalles históricos.")
    return detalles


def _ventas(filas, indices, detalles, errores, avisos):
    completadas = defaultdict(list)
    for fila in filas["ventas"]:
        d = fila.datos
        receta = indices["recetas"].get(d.get("id_receta"))
        if {"tipo", "id_receta"} <= d.keys():
            if (d["tipo"] == "Con receta") != (d["id_receta"] is not None):
                _anotar(errores, fila, "id_receta", "COHERENCIA", "Con receta requiere referencia; Venta libre exige nulo.")
        if receta:
            r = receta.datos
            if "id_cliente" in d and "id_cliente" in r and d["id_cliente"] != r["id_cliente"]:
                _anotar(errores, fila, "id_receta", "COHERENCIA", "La receta pertenece a otro cliente.")
            if "fecha" in d and "fecha_emision" in r and d["fecha"] < r["fecha_emision"]:
                _anotar(errores, fila, "fecha", "COHERENCIA", "La venta es anterior a la emisión de su receta.")
            if d.get("estado") == "Completada":
                completadas[d["id_receta"]].append(fila)
        for campo, tabla in (("id_cliente", "clientes"), ("id_farmaceutico", "farmaceuticos")):
            entidad = indices[tabla].get(d.get(campo))
            if entidad and entidad.datos.get("activo") is False:
                _anotar(avisos, fila, campo, "HISTORICO", "Referencia actualmente inactiva; no se revalida la actividad de una operación histórica.")
        profesional = indices["farmaceuticos"].get(d.get("id_farmaceutico"))
        sucursal = indices["sucursales"].get(profesional.datos.get("id_sucursal")) if profesional else None
        if sucursal and sucursal.datos.get("tipo") == "Droguería":
            _anotar(avisos, fila, "id_farmaceutico", "HISTORICO", "La asignación actual apunta a droguería; revisar historia de sucursal sin inventar traslados.")
        condiciones = []
        for item in detalles.get(d.get("id_venta"), []):
            producto = indices["productos"].get(item.datos.get("id_producto"))
            if producto:
                condicion = producto.datos.get("condicion_venta")
                if condicion is not None:
                    condiciones.append(condicion)
                if producto.datos.get("activo") is False:
                    _anotar(avisos, item, "id_producto", "HISTORICO", "Producto actualmente inactivo; se conserva el detalle histórico.")
        if condiciones and "tipo" in d:
            requiere = any(c != "Venta libre" for c in condiciones)
            if requiere != (d["tipo"] == "Con receta"):
                _anotar(avisos, fila, "tipo", "HISTORICO", "El tipo no coincide con condiciones del catálogo actual; no se reconstruye el catálogo pasado.")
    for id_receta, ventas in completadas.items():
        receta = indices["recetas"][id_receta]
        r = receta.datos
        realizadas = r.get("dispensas_realizadas")
        if realizadas is not None and len(ventas) > realizadas:
            _anotar(avisos, receta, "dispensas_realizadas", "HISTORICO", "Las ventas completadas visibles superan el contador informado; requiere revisión, sin recomputarlo.")
        fechas = [v.datos["fecha"] for v in ventas if "fecha" in v.datos]
        if r.get("tipo") == "Tratamiento prolongado" and r.get("estado") == "Vigente" and r.get("proxima_dispensa") is not None:
            if fechas and len(fechas) == len(ventas) == realizadas:
                try:
                    esperada = inicio_dia_utc(max(fechas).astimezone(ZONA_COMERCIAL).date() + timedelta(days=30))
                except OverflowError:
                    _anotar(avisos, receta, "proxima_dispensa", "HISTORICO", "La fecha +30 días excede el calendario soportado; se conserva la informada.")
                    continue
                if r["proxima_dispensa"] != esperada:
                    _anotar(avisos, receta, "proxima_dispensa", "HISTORICO", f"Fecha informada {r['proxima_dispensa'].date()} distinta de última venta +30 días ({esperada.date()}); se conserva sin corregir.")


def validar_relaciones(filas, completas, errores):
    avisos = []
    indices = _indices(filas, errores)
    for origen, campo, destino in REFERENCIAS:
        if origen not in completas or destino not in completas:
            continue
        for fila in filas[origen]:
            referencia = fila.datos.get(campo)
            if referencia is not None and referencia not in indices[destino]:
                _anotar(errores, fila, campo, "REFERENCIA", f"No existe la entidad referenciada en {destino}.csv.")
    _validar_maestros(filas, errores)
    detalles = _totales(filas, completas, errores)
    _ventas(filas, indices, detalles, errores, avisos)
    return avisos
