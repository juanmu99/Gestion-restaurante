"""
Módulo: historial.py
---------------------
El HISTORIAL DE SERVICIOS: todo lo que pasó en cada servicio completado,
reunido en un solo sitio. No guarda datos propios: los saca de lo que ya
registran los demás módulos.

- servicios.py  -> fecha, cliente, lugar, comensales, cobro, valoración y
                   la copia del menú tal y como era al completarlo.
- inventario.py -> lo que salió de cada lote para ese servicio (su número
                   queda apuntado en cada movimiento).
- gastos.py     -> gastos del servicio (gasolina, personal, imprevistos...)
                   y su rentabilidad.
- materiales.py -> el material que se llevó, el que volvió y las roturas.
"""

from datetime import date
from typing import Optional

from gastos import RegistroGastos, resumen_servicio
from inventario import Inventario
from materiales import RegistroMaterial
from recetario import Recetario
from servicios import RegistroServicios, Servicio


def filtrar_servicios(
    registro: RegistroServicios,
    desde: date,
    hasta: date,
    menu: Optional[str] = None,
    cliente: Optional[str] = None,
    texto: str = "",
    incluir_cancelados: bool = False,
) -> list[Servicio]:
    """
    Los servicios completados (y, si se pide, también los cancelados) entre
    dos fechas, los más recientes primero. `texto` busca, sin distinguir
    mayúsculas, en el cliente, el lugar, el menú, las notas y la valoración.
    """
    estados = ("completado", "cancelado") if incluir_cancelados else ("completado",)
    texto = texto.strip().lower()
    resultado = []
    for s in registro.servicios:
        if s.estado not in estados or not (desde <= s.fecha <= hasta):
            continue
        if menu and s.menu != menu:
            continue
        if cliente and s.cliente != cliente:
            continue
        if texto and texto not in " ".join((s.cliente, s.lugar, s.menu, s.notas, s.valoracion)).lower():
            continue
        resultado.append(s)
    return sorted(resultado, key=lambda s: (s.fecha, s.hora), reverse=True)


def clientes(registro: RegistroServicios) -> list[str]:
    """Todos los clientes que aparecen en algún servicio, por orden alfabético."""
    return sorted({s.cliente for s in registro.servicios if s.cliente})


def _nombre_elaboracion(receta: str) -> str:
    return f"{receta} (preparada)"


def previsto(servicio: Servicio, inventario: Optional[Inventario] = None) -> dict[str, float]:
    """
    Lo que pedía el menú (tal y como era al completar el servicio) para
    sus comensales: ingredientes y consumibles. Vacío si no hay copia del
    menú (servicios completados antes de existir el historial).

    Si se usaron raciones ya preparadas (elaboraciones), esas raciones no
    gastan ingredientes: aparecen como "<receta> (preparada)", en raciones.
    """
    foto = servicio.menu_completado
    if not foto:
        return {}
    preparadas: dict[str, float] = {}
    if inventario is not None:
        for uso in inventario.elaboraciones.usos_de_servicio(servicio.id):
            preparadas[uso.receta] = preparadas.get(uso.receta, 0) + uso.raciones
    totales: dict[str, float] = {}
    for receta in foto.get("recetas", []):
        hechas = preparadas.get(receta["nombre"], 0)
        if hechas:
            totales[_nombre_elaboracion(receta["nombre"])] = round(hechas, 3)
        restantes = max(0.0, servicio.comensales - hechas)
        for nombre, cantidad in receta["ingredientes_por_comensal"].items():
            totales[nombre] = round(totales.get(nombre, 0) + cantidad * restantes, 3)
    for nombre, cantidad in foto.get("consumibles_por_comensal", {}).items():
        totales[nombre] = round(totales.get(nombre, 0) + cantidad * servicio.comensales, 3)
    return totales


def consumos(servicio: Servicio, inventario: Inventario) -> list[dict]:
    """
    Todo lo que salió del inventario para este servicio, movimiento a
    movimiento: producto, tipo, cantidad, unidad, lote y coste real (lo
    pagado, con IVA, y también sin IVA).
    """
    filas = [{
        "producto": _nombre_elaboracion(u.receta),
        "tipo": "elaboración",
        "cantidad": u.raciones,
        "unidad": "raciones",
        "lote": f"Tanda {u.tanda_id}",
        "coste": u.coste,
        "coste_sin_iva": u.coste_sin_iva,
    } for u in inventario.elaboraciones.usos_de_servicio(servicio.id)]
    return filas + [{
        "producto": m.producto_nombre,
        "tipo": m.tipo_producto,
        "cantidad": m.cantidad,
        "unidad": m.unidad,
        "lote": m.lote or "—",
        "coste": m.valor(),
        "coste_sin_iva": m.valor_sin_iva(),
    } for m in inventario.historial if m.servicio_id == servicio.id and m.tipo == "salida"]


def previsto_frente_a_real(servicio: Servicio, inventario: Inventario) -> list[dict]:
    """
    Por cada producto: cuánto pedía el menú, cuánto salió de verdad del
    inventario y la diferencia (negativa = salió menos de lo previsto,
    normalmente porque faltaba stock).
    """
    plan = previsto(servicio, inventario)
    real: dict[str, float] = {}
    unidades: dict[str, str] = {}
    for c in consumos(servicio, inventario):
        real[c["producto"]] = round(real.get(c["producto"], 0) + c["cantidad"], 3)
        unidades[c["producto"]] = c["unidad"]
    filas = []
    for nombre in list(plan) + [n for n in real if n not in plan]:
        producto = inventario.buscar_producto(nombre)
        unidad = unidades.get(nombre) or (producto.unidad if producto else "")
        if not unidad and nombre.endswith(" (preparada)"):
            unidad = "raciones"
        filas.append({
            "producto": nombre,
            "unidad": unidad,
            "previsto": plan.get(nombre, 0.0),
            "real": real.get(nombre, 0.0),
            "diferencia": round(real.get(nombre, 0.0) - plan.get(nombre, 0.0), 3),
        })
    return filas


def ficha(
    servicio: Servicio, inventario: Inventario, recetario: Recetario,
    registro_gastos: RegistroGastos, registro_material: RegistroMaterial,
) -> dict:
    """Todo lo que pasó en un servicio, listo para mostrar."""
    rentabilidad = resumen_servicio(servicio, inventario, recetario, registro_gastos, registro_material)
    return {
        "servicio": servicio,
        "consumos": consumos(servicio, inventario),
        "previsto_frente_a_real": previsto_frente_a_real(servicio, inventario),
        "gastos": registro_gastos.gastos_de_servicio(servicio.id),
        "salidas_material": registro_material.salidas_de(servicio.id),
        "incidencias_material": [i for i in registro_material.incidencias if i.servicio_id == servicio.id],
        "rentabilidad": rentabilidad,
        "coste_por_comensal": round(rentabilidad["coste_total"] / servicio.comensales, 2),
    }


def resumen_periodo(
    servicios: list[Servicio], inventario: Inventario, recetario: Recetario,
    registro_gastos: RegistroGastos, registro_material: RegistroMaterial,
) -> dict:
    """
    Cifras de un grupo de servicios (normalmente los de un periodo).
    Solo cuentan los completados. El margen medio solo puede calcularse
    con los servicios que tienen precio de cobro.
    """
    completados = [s for s in servicios if s.estado == "completado"]
    filas = [(s, resumen_servicio(s, inventario, recetario, registro_gastos, registro_material)) for s in completados]
    comensales = sum(s.comensales for s in completados)
    coste = round(sum(r["coste_total"] for _, r in filas), 2)
    con_cobro = [(s, r) for s, r in filas if r["cobrado"] is not None]
    facturado = round(sum(r["cobrado"] for _, r in con_cobro), 2)
    margen = round(sum(r["margen"] for _, r in con_cobro), 2)

    veces: dict[str, int] = {}
    margen_por_menu: dict[str, list[float]] = {}
    for s, r in filas:
        veces[s.menu] = veces.get(s.menu, 0) + 1
        if r["margen"] is not None:
            margen_por_menu.setdefault(s.menu, []).append(r["margen"] / s.comensales)
    medias = {m: sum(v) / len(v) for m, v in margen_por_menu.items()}
    return {
        "servicios": len(completados),
        "comensales": comensales,
        "facturado": facturado,
        "coste": coste,
        "margen": margen if con_cobro else None,
        "margen_porcentaje": (margen / facturado) if facturado else None,
        "coste_por_comensal": round(coste / comensales, 2) if comensales else None,
        "menu_mas_repetido": max(veces, key=veces.get) if veces else None,
        "menu_mas_rentable": max(medias, key=medias.get) if medias else None,
        "servicios_sin_cobro": len(completados) - len(con_cobro),
    }


def repetir_servicio(registro: RegistroServicios, original: Servicio, fecha: date, hora) -> Servicio:
    """Crea un servicio NUEVO igual que `original` (menú, comensales, precio, cliente y lugar) en otra fecha."""
    nuevo = Servicio(
        fecha, hora, original.comensales, original.menu, notas=f"Repetición del servicio #{original.id}",
        precio_cobrado=original.precio_cobrado, cliente=original.cliente, lugar=original.lugar,
    )
    registro.agregar_servicio(nuevo)
    return nuevo
