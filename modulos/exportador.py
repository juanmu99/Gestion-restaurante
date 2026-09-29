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
    columnas = ["Nombre", "Categoría", "Stock", "Unidad", "Precio unitario (€)",
                "Valor total (€)", "Proveedor", "Stock mínimo", "Fecha caducidad",
                "Tipo", "Peso por unidad en bruto (kg)"]
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
        fila += 1

    if fila > 2:
        hoja.cell(row=fila, column=5, value="TOTAL").font = Font(name=FUENTE, bold=True)
        hoja.cell(row=fila, column=6, value=f"=SUM(F2:F{fila - 1})").font = Font(name=FUENTE, bold=True)

    _ajustar_ancho_columnas(hoja)


def _hoja_limpiezas(wb: Workbook, inventario: Inventario) -> None:
    """Historial de limpiezas/despieces: de dónde sale cada kilo limpio y cuánta merma hubo."""
    hoja = wb.create_sheet("Limpiezas")
    columnas = ["Fecha", "Producto en bruto", "Cantidad", "Unidad", "Peso bruto (kg)",
                "Producto limpio", "Peso limpio (kg)", "Derivados aprovechados",
                "Derivados (kg)", "Merma (kg)", "Rendimiento", "Coste (€)"]
    _escribir_cabecera(hoja, columnas)

    fila = 2
    for l in inventario.limpiezas:
        derivados = ", ".join(f"{n} ({round(kg, 3)} kg)" for n, kg in l.derivados_kg.items()) or "—"
        valores = [
            l.fecha.strftime("%d/%m/%Y"), l.producto_origen, l.cantidad_origen, l.unidad_origen,
            l.peso_bruto_kg, l.producto_limpio, l.peso_limpio_kg, derivados,
            round(sum(l.derivados_kg.values()), 3),
            # Fórmulas reales: merma = bruto - limpio - derivados; rendimiento = limpio / bruto
            f"=E{fila}-G{fila}-I{fila}", f"=G{fila}/E{fila}", l.coste,
        ]
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(row=fila, column=columna, value=valor).font = Font(name=FUENTE)
        hoja.cell(row=fila, column=11).number_format = "0.0%"
        fila += 1

    _ajustar_ancho_columnas(hoja, ancho=20)


def _hoja_servicios(wb: Workbook, registro: RegistroServicios) -> None:
    hoja = wb.create_sheet("Servicios")
    columnas = ["ID", "Fecha", "Hora", "Comensales", "Menú", "Estado", "Notas"]
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
) -> str:
    """
    Genera un único archivo Excel con 3 hojas (Inventario, Servicios,
    Lista de compra) dentro de `carpeta_salida`. Devuelve la ruta del
    archivo generado.
    """
    wb = Workbook()
    wb.remove(wb.active)  # quitamos la hoja "Sheet" vacía que crea por defecto

    _hoja_inventario(wb, inventario)
    _hoja_limpiezas(wb, inventario)
    _hoja_servicios(wb, registro_servicios)
    _hoja_lista_compra(wb, gestor_compras)

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
