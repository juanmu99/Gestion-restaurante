"""
Módulo: exportador.py
-----------------------
Exporta el estado actual del inventario, los servicios y la lista de
compra a un único archivo Excel (.xlsx), con una hoja por cada uno.

Usa fórmulas de Excel reales para los totales (=C2*E2, =SUM(...)) en
vez de escribir el número ya calculado en Python, para que la hoja se
recalcule sola si alguien edita un valor a mano en el propio Excel.

Conceptos de Python en este módulo:
- Trabajar con una librería externa (openpyxl) en vez de solo la
  librería estándar
- pathlib.Path para construir rutas de archivo de forma segura
- f-strings para construir fórmulas de Excel dinámicamente
"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from inventario import Inventario
from servicios import RegistroServicios
from compras import GestorCompras
from gastos import RegistroGastos, resumen_servicio
from materiales import RegistroMaterial
from recetario import Recetario

FUENTE = "Arial"


def _escribir_cabecera(hoja, columnas: list[str]) -> None:
    for col_idx, titulo in enumerate(columnas, start=1):
        celda = hoja.cell(row=1, column=col_idx, value=titulo)
        celda.font = Font(name=FUENTE, bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="4472C4")
        celda.alignment = Alignment(horizontal="center")


def _ajustar_ancho_columnas(hoja, ancho: int = 18) -> None:
    for columna in hoja.columns:
        hoja.column_dimensions[columna[0].column_letter].width = ancho


def _hoja_inventario(wb: Workbook, inventario: Inventario) -> None:
    hoja = wb.create_sheet("Inventario")
    columnas = ["Nombre", "Categoría", "Stock", "Unidad", "Precio medio (€)",
                "Valor total (€)", "Proveedor habitual", "Stock mínimo", "Próxima caducidad",
                "Tipo", "Peso medio por unidad en bruto (kg)", "Lotes", "Clase"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for producto in inventario.productos.values():
        hoja.cell(row=fila, column=1, value=producto.nombre).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=2, value=producto.categoria).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=3, value=producto.stock).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=4, value=producto.unidad).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=5, value=producto.precio_unitario).font = Font(name=FUENTE)
        # Fórmula real (Stock x Precio), no el número ya calculado en Python
        hoja.cell(row=fila, column=6, value=f"=C{fila}*E{fila}").font = Font(name=FUENTE)
        hoja.cell(row=fila, column=7, value=producto.proveedor).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=8, value=producto.stock_minimo).font = Font(name=FUENTE)
        fecha = producto.fecha_caducidad.strftime("%d/%m/%Y") if producto.fecha_caducidad else "—"
        hoja.cell(row=fila, column=9, value=fecha).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=10, value=producto.tipo_descripcion() or "—").font = Font(name=FUENTE)
        hoja.cell(row=fila, column=11, value=producto.peso_unitario or "—").font = Font(name=FUENTE)
        hoja.cell(row=fila, column=12, value=len(producto.lotes)).font = Font(name=FUENTE)
        clase = "Consumible" if producto.es_consumible() else "Alimento"
        hoja.cell(row=fila, column=13, value=clase).font = Font(name=FUENTE)
        fila += 1

    if fila > 2:
        hoja.cell(row=fila, column=5, value="TOTAL").font = Font(name=FUENTE, bold=True)
        hoja.cell(row=fila, column=6, value=f"=SUM(F2:F{fila - 1})").font = Font(name=FUENTE, bold=True)

    _ajustar_ancho_columnas(hoja)


def _hoja_lotes(wb: Workbook, inventario: Inventario) -> None:
    """Un renglón por lote: qué hay de cada compra, de quién, a qué precio y cuándo caduca."""
    hoja = wb.create_sheet("Lotes")
    columnas = ["Producto", "Lote", "Cantidad", "Unidad", "Precio (€)", "Valor (€)", "Proveedor",
                "Fecha de entrada", "Caducidad", "Procedencia", "Peso por unidad (kg)"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for producto in inventario.productos.values():
        for lote in producto.lotes_ordenados():
            valores = [
                producto.nombre, lote.id, lote.cantidad, producto.unidad, lote.precio_unitario,
                f"=C{fila}*E{fila}", lote.proveedor, lote.fecha_entrada.strftime("%d/%m/%Y"),
                lote.fecha_caducidad.strftime("%d/%m/%Y") if lote.fecha_caducidad else "—",
                lote.procedencia, lote.peso_unitario or "—",
            ]
            for columna, valor in enumerate(valores, start=1):
                hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
            fila += 1

    if fila > 2:
        hoja.cell(row=fila, column=5, value="TOTAL").font = Font(name=FUENTE, bold=True)
        hoja.cell(row=fila, column=6, value=f"=SUM(F2:F{fila - 1})").font = Font(name=FUENTE, bold=True)

    _ajustar_ancho_columnas(hoja)


def _hoja_elaboraciones(wb: Workbook, inventario: Inventario) -> None:
    """Las tandas preparadas por adelantado que quedan, con su caducidad y su valor."""
    hoja = wb.create_sheet("Elaboraciones")
    _escribir_cabecera(hoja, ["Receta", "Tanda", "Raciones que quedan", "Raciones preparadas", "Preparada",
                              "Caducidad", "Coste por ración (€)", "Valor (€)"])
    fila = 2
    for t in sorted(inventario.elaboraciones.tandas, key=lambda t: (t.receta, t.id)):
        valores = [t.receta, t.id, t.raciones, t.raciones_iniciales, t.fecha_preparacion.strftime("%d/%m/%Y"),
                   t.fecha_caducidad.strftime("%d/%m/%Y") if t.fecha_caducidad else "—", t.coste_por_racion,
                   f"=C{fila}*G{fila}"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    _ajustar_ancho_columnas(hoja)


def _fecha_nota(objeto) -> str:
    return objeto.notas_fecha.strftime("%d/%m/%Y") if objeto.notas_fecha else ""


def _celda_texto(hoja, fila: int, columna: int, valor) -> None:
    """Celda que puede llevar texto largo con saltos de línea (las anotaciones)."""
    celda = hoja.cell(row=fila, column=columna, value=valor)
    celda.font = Font(name=FUENTE)
    celda.alignment = Alignment(wrap_text=True, vertical="top")


def _hoja_recetario(wb: Workbook, recetario: Recetario) -> None:
    """Las recetas y los menús, con sus anotaciones (el 'bloc de notas' de cada uno)."""
    hoja = wb.create_sheet("Recetario")
    _escribir_cabecera(hoja, ["Tipo", "Nombre", "Categoría / recetas", "Ingredientes por comensal",
                              "Vida útil (días)", "Anotaciones", "Nota editada"])
    fila = 2
    for r in sorted(recetario.recetas.values(), key=lambda r: r.nombre):
        valores = ["Receta", r.nombre, r.categoria,
                   ", ".join(f"{c:g} {i}" for i, c in r.ingredientes_por_comensal.items()),
                   r.vida_util_dias if r.vida_util_dias is not None else "—", r.notas, _fecha_nota(r)]
        for columna, valor in enumerate(valores, start=1):
            _celda_texto(hoja, fila, columna, valor)
        fila += 1
    for m in sorted(recetario.menus.values(), key=lambda m: m.nombre):
        consumibles = ", ".join(f"{c:g} {n}" for n, c in m.consumibles_por_comensal.items())
        valores = ["Menú", m.nombre, ", ".join(r.nombre for r in m.recetas),
                   ", ".join(f"{c:g} {i}" for i, c in m.ingredientes_por_comensal().items())
                   + (f" | Consumibles: {consumibles}" if consumibles else ""),
                   "—", m.notas, _fecha_nota(m)]
        for columna, valor in enumerate(valores, start=1):
            _celda_texto(hoja, fila, columna, valor)
        fila += 1
    _ajustar_ancho_columnas(hoja)
    hoja.column_dimensions["D"].width = 45
    hoja.column_dimensions["F"].width = 60


def _hoja_bases(wb: Workbook, inventario: Inventario) -> None:
    """Elaboraciones base (sofritos, fondos...): su fórmula y cada preparación (prevista frente a obtenida)."""
    hoja = wb.create_sheet("Elaboraciones base")
    _escribir_cabecera(hoja, ["Elaboración", "Fórmula para", "Unidad", "Ingredientes", "Vida útil (días)", "En stock",
                              "Anotaciones", "Nota editada"])
    fila = 2
    for b in sorted(inventario.bases(), key=lambda b: b.nombre):
        ingredientes = ", ".join(f"{c:g} {i}" for i, c in b.formula["ingredientes"].items())
        valores = [b.nombre, b.formula["cantidad"], b.unidad, ingredientes,
                   b.vida_util_dias if b.vida_util_dias is not None else "—", b.stock,
                   b.notas, _fecha_nota(b)]
        for columna, valor in enumerate(valores, start=1):
            _celda_texto(hoja, fila, columna, valor)
        fila += 1

    fila += 1
    cabecera = ["Fecha", "Elaboración", "Unidad", "Prevista", "Obtenida", "Diferencia", "Coste (€)", "Coste/unidad (€)", "Lote"]
    for columna, texto in enumerate(cabecera, start=1):
        hoja.cell(row=fila, column=columna, value=texto).font = Font(name=FUENTE, bold=True)
    fila += 1
    for p in sorted(inventario.elaboraciones.preparaciones_base, key=lambda p: p.fecha):
        valores = [p.fecha.strftime("%d/%m/%Y"), p.producto, p.unidad, p.prevista, p.obtenida, f"=E{fila}-D{fila}",
                   p.coste, f"=IF(E{fila}=0,0,G{fila}/E{fila})", p.lote_id or "—"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    _ajustar_ancho_columnas(hoja)
    hoja.column_dimensions["G"].width = 50


def _hoja_limpiezas(wb: Workbook, inventario: Inventario) -> None:
    """Historial de limpiezas/despieces: de dónde sale cada kilo limpio y cuánta merma hubo."""
    hoja = wb.create_sheet("Limpiezas")
    columnas = ["Fecha", "Producto en bruto", "Cantidad", "Unidad", "Peso bruto (kg)",
                "Producto limpio", "Peso limpio (kg)", "Derivados aprovechados",
                "Derivados (kg)", "Merma (kg)", "Rendimiento", "Coste (€)", "Lote en bruto"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for l in inventario.limpiezas:
        derivados = ", ".join(f"{n} ({round(kg, 3)} kg)" for n, kg in l.derivados_kg.items()) or "—"
        valores = [
            l.fecha.strftime("%d/%m/%Y"), l.producto_origen, l.cantidad_origen, l.unidad_origen,
            l.peso_bruto_kg, l.producto_limpio, l.peso_limpio_kg, derivados,
            round(sum(l.derivados_kg.values()), 3),
            # Fórmulas reales: merma = bruto - limpio - derivados; rendimiento = limpio / bruto
            f"=E{fila}-G{fila}-I{fila}", f"=G{fila}/E{fila}", l.coste, l.lote_origen or "—",
        ]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=11).number_format = "0.0%"
        fila += 1

    _ajustar_ancho_columnas(hoja, ancho=20)


def _hoja_servicios(wb: Workbook, registro: RegistroServicios) -> None:
    hoja = wb.create_sheet("Servicios")
    columnas = ["ID", "Fecha", "Hora", "Comensales", "Menú", "Estado", "Notas", "Precio de cobro (€)", "Cliente", "Lugar"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for s in sorted(registro.servicios, key=lambda s: (s.fecha, s.hora)):
        hoja.cell(row=fila, column=1, value=s.id).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=2, value=s.fecha.strftime("%d/%m/%Y")).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=3, value=s.hora.strftime("%H:%M")).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=4, value=s.comensales).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=5, value=s.menu).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=6, value=s.estado).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=7, value=s.notas).font = Font(name=FUENTE)
        cobro = s.precio_cobrado if s.precio_cobrado is not None else "—"
        hoja.cell(row=fila, column=8, value=cobro).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=9, value=s.cliente or "—").font = Font(name=FUENTE)
        hoja.cell(row=fila, column=10, value=s.lugar or "—").font = Font(name=FUENTE)
        fila += 1

    _ajustar_ancho_columnas(hoja)


def _hoja_gastos(wb: Workbook, registro_gastos: RegistroGastos) -> None:
    hoja = wb.create_sheet("Gastos")
    _escribir_cabecera(hoja, ["Nº", "Fecha", "Concepto", "Categoría", "Importe (€)", "Servicio", "Notas"])
    fila = 2
    for g in sorted(registro_gastos.gastos, key=lambda g: g.fecha):
        valores = [g.id, g.fecha.strftime("%d/%m/%Y"), g.concepto, g.categoria, g.importe,
                   f"#{g.servicio_id}" if g.servicio_id else "General", g.notas]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    if fila > 2:
        hoja.cell(row=fila, column=4, value="TOTAL").font = Font(name=FUENTE, bold=True)
        hoja.cell(row=fila, column=5, value=f"=SUM(E2:E{fila - 1})").font = Font(name=FUENTE, bold=True)
    _ajustar_ancho_columnas(hoja, ancho=20)


def _hoja_historial(
    wb: Workbook, inventario: Inventario, registro: RegistroServicios, recetario: Recetario,
    registro_gastos: RegistroGastos, registro_material: RegistroMaterial = None,
) -> None:
    """Una fila por servicio completado: quién, dónde, cuántos, cuánto costó y cuánto se ganó, y cómo fue."""
    hoja = wb.create_sheet("Historial")
    _escribir_cabecera(hoja, ["ID", "Fecha", "Completado", "Cliente", "Lugar", "Menú", "Comensales", "Coste (€)",
                              "Cobro (€)", "Margen (€)", "Coste por comensal (€)", "Valoración"])
    fila = 2
    for s in sorted(registro.servicios, key=lambda s: (s.fecha, s.hora)):
        if s.estado != "completado":
            continue
        r = resumen_servicio(s, inventario, recetario, registro_gastos, registro_material)
        valores = [s.id, s.fecha.strftime("%d/%m/%Y"),
                   s.fecha_completado.strftime("%d/%m/%Y") if s.fecha_completado else "—",
                   s.cliente or "—", s.lugar or "—", s.menu, s.comensales, r["coste_total"],
                   r["cobrado"] if r["cobrado"] is not None else "—",
                   f"=I{fila}-H{fila}" if r["cobrado"] is not None else "—", f"=H{fila}/G{fila}", s.valoracion or "—"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    _ajustar_ancho_columnas(hoja, ancho=18)


def _hoja_material(wb: Workbook, registro_material: RegistroMaterial) -> None:
    hoja = wb.create_sheet("Material")
    _escribir_cabecera(hoja, ["Material", "Categoría", "Total", "En uso", "Disponibles",
                              "Precio de reposición (€)", "Valor (€)", "Proveedor"])
    fila = 2
    for m in registro_material.materiales.values():
        valores = [m.nombre, m.categoria, m.cantidad_total, registro_material.en_uso(m.nombre),
                   f"=C{fila}-D{fila}", m.precio_reposicion, f"=C{fila}*F{fila}", m.proveedor or "—"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    fila += 1
    hoja.cell(row=fila, column=1, value="Roturas y pérdidas").font = Font(name=FUENTE, bold=True)
    fila += 1
    for i in registro_material.incidencias:
        valores = [i.fecha.strftime("%d/%m/%Y"), i.tipo, i.material, i.cantidad, i.coste,
                   f"servicio #{i.servicio_id}" if i.servicio_id else "almacén"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    _ajustar_ancho_columnas(hoja, ancho=20)


def _hoja_rentabilidad(
    wb: Workbook, inventario: Inventario, registro: RegistroServicios, recetario: Recetario,
    registro_gastos: RegistroGastos, registro_material: RegistroMaterial = None,
) -> None:
    """Coste y margen de cada servicio (con fórmulas: coste total = suma, margen = cobro - coste)."""
    hoja = wb.create_sheet("Rentabilidad")
    _escribir_cabecera(hoja, ["ID", "Fecha", "Menú", "Estado", "Comida (€)", "Consumibles (€)", "Gastos (€)",
                              "Roturas y pérdidas (€)", "Coste total (€)", "Cobro (€)", "Margen (€)", "Coste estimado"])
    fila = 2
    for s in sorted(registro.servicios, key=lambda s: (s.fecha, s.hora)):
        if s.estado == "cancelado":
            continue
        r = resumen_servicio(s, inventario, recetario, registro_gastos, registro_material)
        valores = [s.id, s.fecha.strftime("%d/%m/%Y"), s.menu, s.estado, r["comida"], r["consumibles"], r["gastos"],
                   r["material"], f"=E{fila}+F{fila}+G{fila}+H{fila}", r["cobrado"] if r["cobrado"] is not None else "—",
                   f"=J{fila}-I{fila}" if r["cobrado"] is not None else "—", "Sí" if r["estimado"] else "No"]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        fila += 1
    _ajustar_ancho_columnas(hoja)


def _hoja_lista_compra(wb: Workbook, gestor_compras: GestorCompras) -> None:
    hoja = wb.create_sheet("Lista de compra")
    columnas = ["Ingrediente", "Cantidad", "Unidad", "Proveedor",
                "Precio unitario estimado (€)", "Coste estimado (€)", "Estado"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for item in gestor_compras.items:
        hoja.cell(row=fila, column=1, value=item.ingrediente).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=2, value=item.cantidad).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=3, value=item.unidad).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=4, value=item.proveedor).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=5, value=item.precio_unitario_estimado).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=6, value=f"=B{fila}*E{fila}").font = Font(name=FUENTE)
        estado = "Comprado" if item.comprado else "Pendiente"
        hoja.cell(row=fila, column=7, value=estado).font = Font(name=FUENTE)
        fila += 1

    if fila > 2:
        hoja.cell(row=fila, column=5, value="TOTAL").font = Font(name=FUENTE, bold=True)
        hoja.cell(row=fila, column=6, value=f"=SUM(F2:F{fila - 1})").font = Font(name=FUENTE, bold=True)

    _ajustar_ancho_columnas(hoja, ancho=22)


def exportar_todo(
    inventario: Inventario,
    registro_servicios: RegistroServicios,
    gestor_compras: GestorCompras,
    carpeta_salida: str,
    registro_gastos: RegistroGastos = None,
    recetario: Recetario = None,
    registro_material: RegistroMaterial = None,
) -> str:
    """
    Genera un único archivo Excel con una hoja para cada cosa (Inventario,
    Lotes, Limpiezas, Servicios, Lista de compra) dentro de `carpeta_salida`. Devuelve la ruta del
    archivo generado.
    """
    wb = Workbook()
    wb.remove(wb.active)  # quitamos la hoja "Sheet" vacía que crea por defecto

    _hoja_inventario(wb, inventario)
    _hoja_lotes(wb, inventario)
    _hoja_elaboraciones(wb, inventario)
    _hoja_bases(wb, inventario)
    if recetario is not None:
        _hoja_recetario(wb, recetario)
    _hoja_limpiezas(wb, inventario)
    _hoja_servicios(wb, registro_servicios)
    _hoja_lista_compra(wb, gestor_compras)
    if registro_material is not None:
        _hoja_material(wb, registro_material)
    if registro_gastos is not None:
        _hoja_gastos(wb, registro_gastos)
        if recetario is not None:
            _hoja_rentabilidad(wb, inventario, registro_servicios, recetario, registro_gastos, registro_material)
            _hoja_historial(wb, inventario, registro_servicios, recetario, registro_gastos, registro_material)

    Path(carpeta_salida).mkdir(parents=True, exist_ok=True)
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"backup_restaurante_{marca_tiempo}.xlsx"
    ruta_completa = str(Path(carpeta_salida) / nombre_archivo)

    wb.save(ruta_completa)
    return ruta_completa


if __name__ == "__main__":
    from datetime import date, time
    from inventario import Producto
    from servicios import Servicio
    from compras import ItemCompra

    inventario = Inventario()
    inventario.agregar_producto(Producto(
        "Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2
    ))
    inventario.agregar_producto(Producto(
        "Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2,
        fecha_caducidad=date(2026, 9, 1),
    ))

    registro = RegistroServicios()
    registro.agregar_servicio(Servicio(date(2026, 9, 2), time(21, 0), 8, "Menú del día"))

    gestor = GestorCompras()
    gestor.agregar_item(ItemCompra("Harina de trigo", 1.4, "kg", "Harinas del Sur", 1.2))

    ruta = exportar_todo(inventario, registro, gestor, carpeta_salida=".")
    print(f"\n📁 Archivo generado en: {ruta}")
