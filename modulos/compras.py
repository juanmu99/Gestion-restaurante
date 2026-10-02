"""
Módulo: compras.py
--------------------
Genera listas de la compra consolidadas a partir de varios servicios,
comparando las necesidades totales de ingredientes contra el inventario
real, y las agrupa por proveedor para facilitar el pedido.

Conecta con:
- inventario.py -> para consultar stock, proveedor y precio de cada producto
- servicios.py  -> lista de servicios a cubrir
- recetario.py  -> para calcular cuánto ingrediente hace falta por servicio

Conceptos de Python nuevos en este módulo:
- Consolidar/acumular datos de varias fuentes en un solo diccionario antes
  de comparar (evita "usar el mismo stock dos veces")
- dict.setdefault(clave, valor_por_defecto) -> patrón muy común para
  agrupar elementos en listas dentro de un diccionario
"""

import math
from typing import Optional

from inventario import Inventario, convertir
from servicios import Servicio
from recetario import Recetario


class ItemCompra:
    """Un ingrediente concreto que hay que comprar, con su estado."""

    def __init__(self, ingrediente: str, cantidad: float, unidad: str, proveedor: str, precio_unitario_estimado: float):
        self.ingrediente = ingrediente
        self.cantidad = cantidad
        self.unidad = unidad
        self.proveedor = proveedor
        self.precio_unitario_estimado = precio_unitario_estimado
        self.comprado = False

    def costo_estimado(self) -> float:
        return round(self.cantidad * self.precio_unitario_estimado, 2)

    def marcar_comprado(self) -> None:
        self.comprado = True

    def __str__(self) -> str:
        estado = "✅ comprado" if self.comprado else "⏳ pendiente"
        return (
            f"{self.ingrediente}: {self.cantidad} {self.unidad} "
            f"(proveedor: {self.proveedor}, ≈{self.costo_estimado()}€) - {estado}"
        )

    def to_dict(self) -> dict:
        return {
            "ingrediente": self.ingrediente,
            "cantidad": self.cantidad,
            "unidad": self.unidad,
            "proveedor": self.proveedor,
            "precio_unitario_estimado": self.precio_unitario_estimado,
            "comprado": self.comprado,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "ItemCompra":
        item = cls(
            datos["ingrediente"], datos["cantidad"], datos["unidad"],
            datos["proveedor"], datos["precio_unitario_estimado"],
        )
        # "comprado" no es parámetro del constructor (siempre empieza en
        # False), así que lo restauramos aparte, igual que hicimos con el
        # id de Servicio.
        item.comprado = datos["comprado"]
        return item


class GestorCompras:
    """Genera y gestiona la lista de la compra consolidada."""

    def __init__(self):
        self.items: list[ItemCompra] = []

    def generar_lista_desde_servicios(
        self, servicios: list[Servicio], recetario: Recetario, inventario: Inventario
    ) -> list[str]:
        """
        Consolida las necesidades de ingredientes de VARIOS servicios y
        genera items de compra solo para lo que realmente falta.

        Paso 1: sumar TODAS las necesidades de TODOS los servicios primero.
        Paso 2: lo que falta de un producto LIMPIO no se compra tal cual:
                se convierte en producto EN BRUTO usando su rendimiento medio
                (faltan 2 kg de carne limpia y rinde un 64 % -> 3,13 kg de pata).
        Paso 3: comparar esa suma contra el stock, UNA sola vez.
        (Si se comparara servicio por servicio, el mismo stock parecería
        cubrir el déficit de varios servicios a la vez, lo cual es incorrecto.)

        Paso 4: los productos que estaban PENDIENTES en la lista y que ya no
                hacen falta (por ejemplo, porque se compraron registrándolos
                directamente en el inventario) se quitan de la lista.

        Devuelve una lista de avisos para quien la muestre (consola o
        interfaz), por ejemplo cuando un producto aún no tiene limpiezas
        registradas y no se conoce su rendimiento.
        """
        avisos: list[str] = []
        necesidades_acumuladas: dict[str, float] = {}

        # Raciones ya PREPARADAS (elaboraciones): se reparten entre los
        # servicios por orden de fecha, y solo se compra para el resto. Una
        # tanda que habrá caducado el día del servicio no cuenta.
        ya_asignadas: dict[str, float] = {}
        for servicio in sorted(servicios, key=lambda s: (s.fecha, s.hora)):
            menu = recetario.buscar_menu(servicio.menu)
            if menu is None:
                print(f"⚠️  Menú '{servicio.menu}' no encontrado, se omite el servicio #{servicio.id}")
                continue
            preparadas: dict[str, float] = {}
            for receta in menu.recetas:
                libres = inventario.elaboraciones.raciones_disponibles(receta.nombre, servicio.fecha) \
                    - ya_asignadas.get(receta.nombre, 0)
                usar = min(servicio.comensales, max(0.0, libres))
                if usar > 0:
                    preparadas[receta.nombre] = usar
                    ya_asignadas[receta.nombre] = ya_asignadas.get(receta.nombre, 0) + usar
                    avisos.append(
                        f"Servicio #{servicio.id}: hay {usar:g} raciones preparadas de '{receta.nombre}'; "
                        f"solo se compra para las {servicio.comensales - usar:g} restantes."
                    )
            # Ingredientes Y consumibles: los dos se compran.
            necesidades = recetario.necesidades_servicio(servicio, preparadas)
            for ingrediente, cantidad in necesidades.items():
                necesidades_acumuladas[ingrediente] = round(
                    necesidades_acumuladas.get(ingrediente, 0) + cantidad, 3
                )

        # --- Paso 2: productos limpios y subproductos ---
        no_se_compran: set[str] = set()
        for ingrediente in list(necesidades_acumuladas):
            producto = inventario.buscar_producto(ingrediente)
            if producto is None:
                continue
            faltante = necesidades_acumuladas[ingrediente] - producto.stock
            if faltante <= 1e-9:
                continue

            if producto.es_subproducto:
                no_se_compran.add(ingrediente)
                avisos.append(
                    f"Faltan {round(faltante, 3)} {producto.unidad} de '{ingrediente}': es un subproducto "
                    "(sale de limpiar otros productos), así que no se añade a la lista."
                )
                continue

            origen = inventario.buscar_producto(producto.origen) if producto.origen else None
            if origen is None:
                continue  # se compra tal cual (o su bruto ya no existe)

            rendimiento = inventario.rendimiento_medio(origen.nombre)
            if rendimiento is None:
                rendimiento = 1.0
                avisos.append(
                    f"'{origen.nombre}' todavía no tiene limpiezas registradas: se calcula como si no tuviera "
                    "merma. Compra algo más de lo indicado."
                )
            kg_bruto = producto.peso_kg(faltante) / rendimiento
            if origen.unidad == "unidades":
                cantidad_bruto = kg_bruto / origen.peso_unitario
            else:
                cantidad_bruto = convertir(kg_bruto, "kg", origen.unidad)

            no_se_compran.add(ingrediente)
            necesidades_acumuladas[origen.nombre] = necesidades_acumuladas.get(origen.nombre, 0) + cantidad_bruto
            avisos.append(
                f"Faltan {round(faltante, 3)} {producto.unidad} de '{ingrediente}': salen de limpiar "
                f"~{round(cantidad_bruto, 2)} {origen.unidad} de '{origen.nombre}' (rendimiento {rendimiento:.0%})."
            )

        # --- Paso 3: comparar contra el stock ---
        hacen_falta: set[str] = set()
        for ingrediente, cantidad_necesaria in necesidades_acumuladas.items():
            if ingrediente in no_se_compran:
                continue
            producto = inventario.buscar_producto(ingrediente)
            stock_actual = producto.stock if producto else 0
            faltante = round(cantidad_necesaria - stock_actual, 3)

            if faltante <= 0:
                continue  # hay suficiente stock, no hace falta comprar nada de esto

            unidad = producto.unidad if producto else ""
            if unidad == "unidades":
                # No se compran 0,4 patas: se redondea hacia arriba a unidades enteras.
                faltante = math.ceil(faltante - 1e-9)

            proveedor = producto.proveedor if producto else "Desconocido"
            precio = producto.precio_unitario if producto else 0
            self.agregar_item(ItemCompra(ingrediente, faltante, unidad, proveedor, precio))
            hacen_falta.add(ingrediente)

        # --- Paso 4: quitar lo pendiente que ya no hace falta ---
        for item in list(self.items_pendientes()):
            if item.ingrediente not in hacen_falta:
                self.items.remove(item)
                avisos.append(
                    f"'{item.ingrediente}' ya no hace falta comprarlo (hay stock suficiente para estos servicios): "
                    "se ha quitado de la lista."
                )

        for aviso in avisos:
            print(f"ℹ️  {aviso}")
        return avisos

    def agregar_item(self, item: ItemCompra) -> None:
        # generar_lista_desde_servicios() SIEMPRE recalcula el hueco TOTAL
        # (necesario - stock actual) para los servicios dados, no un hueco
        # "adicional" desde la última vez. Por eso, si ya hay un item
        # PENDIENTE con este mismo ingrediente, hay que REEMPLAZAR su
        # cantidad por la recién calculada, no sumarle esta encima —
        # sumar duplicaría el hueco cada vez que regeneres la lista sin
        # que la necesidad real haya cambiado.
        # Ojo: solo se reemplaza un item PENDIENTE; uno ya comprado se
        # queda como registro de esa compra ya hecha, aparte.
        for existente in self.items:
            if existente.ingrediente == item.ingrediente and not existente.comprado:
                existente.cantidad = item.cantidad
                existente.unidad = item.unidad
                existente.proveedor = item.proveedor
                existente.precio_unitario_estimado = item.precio_unitario_estimado
                print(f"🛒 Actualizado en la lista de compra: {existente}")
                return

        self.items.append(item)
        print(f"🛒 Añadido a la lista de compra: {item}")

    def items_pendientes(self) -> list[ItemCompra]:
        return [i for i in self.items if not i.comprado]

    def pendiente_de(self, ingrediente: str) -> Optional[ItemCompra]:
        """El item PENDIENTE de la lista para ese ingrediente, o None si no está pendiente."""
        return next((i for i in self.items if i.ingrediente == ingrediente and not i.comprado), None)

    def marcar_comprado(self, ingrediente: str, cantidad_comprada: Optional[float] = None) -> None:
        """
        Marca un item pendiente como comprado. Si `cantidad_comprada` se
        indica, SOBRESCRIBE la cantidad del item con la que realmente se
        compró (que no tiene por qué coincidir con la calculada como
        necesaria -- puedes comprar de más, o menos si no había en la
        tienda). Si no se indica, se deja la cantidad calculada tal cual.
        """
        for item in self.items:
            if item.ingrediente == ingrediente and not item.comprado:
                if cantidad_comprada is not None:
                    item.cantidad = cantidad_comprada
                item.marcar_comprado()
                print(f"✅ Marcado como comprado: {ingrediente}")
                return
        print(f"❌ No se encontró '{ingrediente}' pendiente en la lista de compra")

    def agrupar_por_proveedor(self) -> dict[str, list[ItemCompra]]:
        """Agrupa los items pendientes por proveedor, para facilitar el pedido."""
        agrupado: dict[str, list[ItemCompra]] = {}
        for item in self.items_pendientes():
            # setdefault: si el proveedor aún no tiene lista, crea una vacía []
            # y la devuelve; si ya existe, devuelve la lista ya creada.
            agrupado.setdefault(item.proveedor, []).append(item)
        return agrupado

    def costo_total_pendiente(self) -> float:
        return round(sum(i.costo_estimado() for i in self.items_pendientes()), 2)

    def mostrar_lista_por_proveedor(self) -> None:
        agrupado = self.agrupar_por_proveedor()
        if not agrupado:
            print("No hay compras pendientes 🎉")
            return
        for proveedor, items in agrupado.items():
            print(f"\n📋 Proveedor: {proveedor}")
            for item in items:
                print(f"  - {item.cantidad} {item.unidad} de {item.ingrediente} (≈{item.costo_estimado()}€)")

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, datos: dict) -> "GestorCompras":
        gestor = cls()
        gestor.items = [ItemCompra.from_dict(d) for d in datos["items"]]
        return gestor


if __name__ == "__main__":
    from datetime import date, time
    from inventario import Producto
    from recetario import Receta, Menu

    # --- Inventario con stock escaso a propósito ---
    inventario = Inventario()
    inventario.agregar_producto(Producto("Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2))
    inventario.agregar_producto(Producto("Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5))
    inventario.agregar_producto(Producto("Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2))

    # --- Recetario ---
    pan_casero = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada_tomate = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})

    recetario = Recetario()
    recetario.agregar_receta(pan_casero)
    recetario.agregar_receta(ensalada_tomate)
    recetario.agregar_menu(Menu("Menú del día", [pan_casero, ensalada_tomate]))

    # --- Dos servicios distintos que usan el MISMO menú ---
    servicio1 = Servicio(fecha=date(2026, 9, 10), hora=time(14, 0), comensales=10, menu="Menú del día")
    servicio2 = Servicio(fecha=date(2026, 9, 12), hora=time(21, 0), comensales=6, menu="Menú del día")

    print(f"\n--- Generando lista de compra para {servicio1} y {servicio2} ---")
    gestor = GestorCompras()
    gestor.generar_lista_desde_servicios([servicio1, servicio2], recetario, inventario)

    print("\n--- Lista de compra agrupada por proveedor ---")
    gestor.mostrar_lista_por_proveedor()

    print(f"\n💰 Coste total pendiente: {gestor.costo_total_pendiente()} €")

    gestor.marcar_comprado("Harina de trigo")

    print("\n--- Tras marcar la harina como comprada ---")
    gestor.mostrar_lista_por_proveedor()
    print(f"💰 Coste total pendiente actualizado: {gestor.costo_total_pendiente()} €")
