"""
Módulo: dashboard.py
----------------------
Consolida en un único resumen las alertas importantes de los demás
módulos: próximos servicios, stock bajo mínimo, productos próximos a
caducar, compras pendientes y valor total del inventario.

Conecta con:
- inventario.py -> stock bajo, caducidad, valor total
- servicios.py  -> próximos servicios
- compras.py    -> compras pendientes y su coste

Conceptos de Python en este módulo:
- Patrón "fachada": una clase que no tiene datos propios, solo GUARDA
  referencias a otros objetos y los consulta para dar una vista conjunta.
- Listas de strings como forma sencilla de acumular "mensajes" antes de
  mostrarlos o (más adelante) exportarlos a un archivo.
"""

from inventario import Inventario
from servicios import RegistroServicios
from compras import GestorCompras
from metricas import Metricas


class Dashboard:
    """
    No almacena productos, servicios ni compras: simplemente GUARDA
    referencias a los gestores que ya conoces y los consulta bajo demanda.
    """

    def __init__(self, inventario: Inventario, registro_servicios: RegistroServicios, gestor_compras: GestorCompras):
        self.inventario = inventario
        self.registro_servicios = registro_servicios
        self.gestor_compras = gestor_compras

    def generar_alertas(self, dias_servicios: int = 7, dias_caducidad: int = 7) -> list[str]:
        """Consolida TODAS las alertas en una lista de textos, lista para mostrar o exportar."""
        alertas: list[str] = []

        for s in self.registro_servicios.servicios_proximos(dias_servicios):
            alertas.append(f"📅 Servicio próximo: {s}")

        for p in self.inventario.productos_bajo_minimo():
            alertas.append(f"⚠️  Stock bajo mínimo: {p.nombre} ({p.stock} {p.unidad}, mínimo {p.stock_minimo})")

        for p, lote in self.inventario.lotes_caducados():
            alertas.append(f"🗑️  Caducado: {p.nombre} ({lote.cantidad} {p.unidad}, {lote.etiqueta()})")

        for p, lote in self.inventario.lotes_proximos_a_caducar(dias_caducidad):
            alertas.append(
                f"⏳ Caduca en {lote.dias_para_caducar()} día(s): {p.nombre} ({lote.cantidad} {p.unidad}, {lote.etiqueta()})"
            )

        pendientes = self.gestor_compras.items_pendientes()
        if pendientes:
            costo = self.gestor_compras.costo_total_pendiente()
            alertas.append(f"🛒 {len(pendientes)} producto(s) pendientes de comprar (≈{costo}€)")

        # Proyección basada en el ritmo de consumo reciente -- distinta de
        # "stock bajo mínimo" (que es un umbral fijo que tú defines): esto
        # avisa aunque el stock siga POR ENCIMA del mínimo, si el ritmo al
        # que se está gastando indica que se acabará pronto de todos modos.
        proximos_agotarse = Metricas(self.inventario).productos_proximos_a_agotarse(dias_aviso=dias_caducidad)
        for nombre, dias in proximos_agotarse:
            alertas.append(f"📉 Se agotará en ~{dias} día(s) al ritmo actual de consumo: {nombre}")

        return alertas

    def mostrar_resumen(self) -> None:
        print("=" * 50)
        print("  DASHBOARD — RESUMEN GENERAL")
        print("=" * 50)

        alertas = self.generar_alertas()
        if not alertas:
            print("\n✅ Todo en orden, no hay alertas pendientes.")
        else:
            print(f"\n{len(alertas)} alerta(s):\n")
            for alerta in alertas:
                print(f"  {alerta}")

        print(f"\n💰 Valor total del inventario: {self.inventario.valor_total_inventario()} €")
        print("=" * 50)


if __name__ == "__main__":
    from datetime import date, time
    from inventario import Producto
    from servicios import Servicio
    from compras import ItemCompra

    # --- Inventario con varias situaciones a propósito ---
    inventario = Inventario()
    inventario.agregar_producto(Producto(
        "Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2
    ))
    inventario.agregar_producto(Producto(
        "Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5
    ))
    inventario.agregar_producto(Producto(
        "Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2,
        fecha_caducidad=date(2026, 9, 1),  # caduca pronto
    ))
    inventario.agregar_producto(Producto(
        "Queso manchego", "Lácteos", 10, "kg", 12.5, "Quesos La Mancha", stock_minimo=3,
        fecha_caducidad=date(2026, 9, 20),  # sin problema, no debería generar alerta
    ))

    # --- Servicios: uno próximo (7 días), otro lejano (no debería alertar) ---
    registro = RegistroServicios()
    registro.agregar_servicio(Servicio(date(2026, 9, 2), time(21, 0), 8, "Menú del día"))
    registro.agregar_servicio(Servicio(date(2026, 9, 15), time(21, 0), 12, "Menú de bodas"))

    # --- Compras pendientes (simulando que el Módulo 4 ya generó esta lista) ---
    gestor_compras = GestorCompras()
    gestor_compras.agregar_item(ItemCompra("Harina de trigo", 1.4, "kg", "Harinas del Sur", 1.2))
    gestor_compras.agregar_item(ItemCompra("Tomate", 1.1, "kg", "Huerta Local", 2.1))

    print()  # separa los mensajes de creación del resumen final
    dashboard = Dashboard(inventario, registro, gestor_compras)
    dashboard.mostrar_resumen()
