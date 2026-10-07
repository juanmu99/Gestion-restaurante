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
from datetime import date
from typing import Optional

from inventario import Inventario, convertir
from servicios import Servicio
from recetario import Recetario


class ItemCompra:
    """Un ingrediente concreto que hay que comprar, con su estado."""

    def __init__(
        self, ingrediente: str, cantidad: float, unidad: str, proveedor: str, precio_unitario_estimado: float,
        para: Optional[list[int]] = None, bajo_minimo: bool = False, a_mano: float = 0.0,
    ):
        self.ingrediente = ingrediente
        self.cantidad = cantidad
        self.unidad = unidad
        self.proveedor = proveedor
        self.precio_unitario_estimado = precio_unitario_estimado
        self.comprado = False
        # Para qué es: los servicios que lo piden, si es para reponer el
        # mínimo, y cuánto se añadió A MANO (se suma a lo calculado y se
        # respeta al volver a generar la lista).
        self.para: list[int] = sorted(set(para or []))
        self.bajo_minimo = bajo_minimo
        self.a_mano = a_mano

    def motivo(self) -> str:
        """Para qué es: 'servicios #4, #7 · bajo mínimo · a mano (2)'."""
        partes = []
        if self.para:
            partes.append(("servicio " if len(self.para) == 1 else "servicios ") + ", ".join(f"#{i}" for i in self.para))
        if self.bajo_minimo:
            partes.append("bajo mínimo")
        if self.a_mano > 0:
            partes.append(f"a mano ({self.a_mano:g})")
        return " · ".join(partes) or "—"

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
            "para": self.para,
            "bajo_minimo": self.bajo_minimo,
            "a_mano": self.a_mano,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "ItemCompra":
        item = cls(
            datos["ingrediente"], datos["cantidad"], datos["unidad"],
            datos["proveedor"], datos["precio_unitario_estimado"],
            datos.get("para"), datos.get("bajo_minimo", False), datos.get("a_mano", 0.0),
        )
        # "comprado" no es parámetro del constructor (siempre empieza en
        # False), así que lo restauramos aparte, igual que hicimos con el
        # id de Servicio.
        item.comprado = datos["comprado"]
        return item


def _cubrir(producto, demandas: list, hoy: date) -> tuple[list, list]:
    """
    Simula (SIN tocar nada) gastar los lotes de `producto` para cubrir sus
    `demandas` [(fecha, cantidad, servicio_id)], por orden de fecha y
    sacando primero de los lotes que caducan antes. Un lote solo sirve si
    sigue bueno ese día (y como pronto, hoy: lo ya caducado no sirve).

    Devuelve (faltas, caducados):
    - faltas: [(fecha, cantidad, servicio_id)] lo que el stock no cubre.
    - caducados: [(lote, cantidad, servicio_id, fecha)] lotes a los que les
      quedaba stock pero no sirvieron para una necesidad por caducar antes.
    """
    lotes = producto.lotes_ordenados() if producto else []
    queda = {l.id: l.cantidad for l in lotes}
    faltas, caducados = [], []
    for fecha, cantidad, servicio_id in sorted(demandas, key=lambda d: d[0]):
        dia = max(fecha, hoy)
        pendiente = cantidad
        for lote in lotes:
            if pendiente <= 1e-9:
                break
            if lote.esta_caducado(dia) or queda[lote.id] <= 1e-9:
                continue
            sale = min(pendiente, queda[lote.id])
            queda[lote.id] -= sale
            pendiente -= sale
        if pendiente > 1e-9:
            faltas.append((fecha, pendiente, servicio_id))
            caducados += [(l, round(queda[l.id], 3), servicio_id, fecha) for l in lotes
                          if queda[l.id] > 1e-9 and l.esta_caducado(dia)]
    return faltas, caducados


class GestorCompras:
    """Genera y gestiona la lista de la compra consolidada."""

    def __init__(self):
        self.items: list[ItemCompra] = []

    def generar_lista_desde_servicios(
        self, servicios: list[Servicio], recetario: Recetario, inventario: Inventario,
        hoy: Optional[date] = None,
    ) -> list[str]:
        """
        Consolida las necesidades de ingredientes de VARIOS servicios y
        genera items de compra solo para lo que realmente falta.

        Cada necesidad se apunta con la FECHA del servicio que la pide. Así,
        al compararla con el stock, solo cuentan los lotes que seguirán
        buenos ese día: 2 kg de tomate que caducan el 10 no sirven para un
        servicio del 12 (y se avisa). Los servicios se cubren por orden de
        fecha, gastando primero los lotes que caducan antes, y el mismo
        stock nunca cubre dos servicios a la vez.

        Paso 0: las raciones ya PREPARADAS (tandas) se reparten tanda a tanda
                por orden de fecha; solo se compra para el resto.
        Paso 1: necesidades de cada servicio (ingredientes y consumibles).
        Paso 1b: lo que falta de una elaboración BASE no se compra: se
                prepara, así que se compran sus ingredientes.
        Paso 2: lo que falta de un producto LIMPIO no se compra tal cual:
                se convierte en producto EN BRUTO usando su rendimiento medio
                (faltan 2 kg de carne limpia y rinde un 64 % -> 3,13 kg de pata).
        Paso 2b: los productos de limpieza y mantenimiento por debajo de su
                mínimo se añaden también (no dependen de los servicios).
        Paso 3: comparar contra el stock bueno y crear los items.
        Paso 4: los productos que estaban PENDIENTES en la lista y que ya no
                hacen falta (por ejemplo, porque se compraron registrándolos
                directamente en el inventario) se quitan de la lista.

        Devuelve una lista de avisos para quien la muestre (consola o
        interfaz), por ejemplo cuando un producto aún no tiene limpiezas
        registradas y no se conoce su rendimiento.
        """
        hoy = hoy or date.today()
        avisos: list[str] = []
        # {producto: [(fecha, cantidad, id del servicio o None)]}
        demandas: dict[str, list[tuple[date, float, Optional[int]]]] = {}
        avisados: set = set()

        def pedir(nombre: str, fecha: date, cantidad: float, servicio_id: Optional[int]) -> None:
            if cantidad > 1e-9:
                demandas.setdefault(nombre, []).append((fecha, cantidad, servicio_id))

        def faltas_de(nombre: str) -> list[tuple[date, float, Optional[int]]]:
            """Lo que el stock bueno NO cubre de las necesidades de `nombre` (y avisa de lo caducado)."""
            producto = inventario.buscar_producto(nombre)
            faltas, caducados = _cubrir(producto, demandas.get(nombre, []), hoy)
            for lote, cantidad, servicio_id, fecha in caducados:
                if (nombre, lote.id) in avisados:
                    continue
                avisados.add((nombre, lote.id))
                caduca = lote.fecha_caducidad.strftime("%d/%m/%Y")
                if lote.esta_caducado(hoy):
                    avisos.append(
                        f"⚠️ '{nombre}': el lote {lote.id} ({cantidad:g} {producto.unidad}) ya está caducado "
                        f"(cad. {caduca}), así que no se cuenta. Si ya no sirve, deséchalo en el Inventario."
                    )
                else:
                    para = f"del servicio #{servicio_id} ({fecha.strftime('%d/%m/%Y')})" if servicio_id is not None \
                        else f"del {fecha.strftime('%d/%m/%Y')}"
                    avisos.append(
                        f"⚠️ '{nombre}': {cantidad:g} {producto.unidad} del lote {lote.id} caducan el {caduca}, "
                        f"antes {para}: no se cuentan para él."
                    )
            return faltas

        # --- Pasos 0 y 1: raciones preparadas y necesidades de cada servicio ---
        quedan_en_tanda = {t.id: t.raciones for t in inventario.elaboraciones.tandas}
        for servicio in sorted(servicios, key=lambda s: (s.fecha, s.hora)):
            menu = recetario.buscar_menu(servicio.menu)
            if menu is None:
                avisos.append(f"⚠️ Servicio #{servicio.id} ({servicio.fecha.strftime('%d/%m/%Y')}): su menú "
                              f"'{servicio.menu}' no existe en el Recetario, así que NO se ha tenido en cuenta. "
                              "Cámbiale el menú.")
                continue
            dia = max(servicio.fecha, hoy)
            preparadas: dict[str, float] = {}
            for receta in menu.recetas:
                # Tanda a tanda: primero las que caducan antes y siguen buenas ese día.
                usar = 0.0
                for tanda in inventario.elaboraciones.tandas_de(receta.nombre, dia):
                    if usar >= servicio.comensales - 1e-9:
                        break
                    sale = min(servicio.comensales - usar, quedan_en_tanda.get(tanda.id, 0.0))
                    if sale > 1e-9:
                        quedan_en_tanda[tanda.id] -= sale
                        usar += sale
                if usar > 1e-9:
                    preparadas[receta.nombre] = usar
                    avisos.append(
                        f"Servicio #{servicio.id}: hay {usar:g} raciones preparadas de '{receta.nombre}'; "
                        f"solo se compra para las {servicio.comensales - usar:g} restantes."
                    )
            # Ingredientes Y consumibles: los dos se compran.
            for ingrediente, cantidad in recetario.necesidades_servicio(servicio, preparadas).items():
                pedir(ingrediente, servicio.fecha, cantidad, servicio.id)

        # --- Paso 1b: elaboraciones BASE (sofritos, fondos...) ---
        # Una base puede llevar otra dentro (un fondo dentro de una salsa):
        # cada base se calcula cuando ya se han calculado todas las que la
        # llevan, para que le lleguen también sus necesidades.
        no_se_compran: set[str] = set()
        bases = [p.nombre for p in inventario.bases()]
        hechas: set[str] = set()
        while len(hechas) < len(bases):
            lista = [b for b in bases if b not in hechas
                     and not any(otra not in hechas and inventario._lleva(otra, b) for otra in bases if otra != b)]
            if not lista:  # las fórmulas no pueden ir en círculo; esto es solo un seguro
                break
            for base in lista:
                hechas.add(base)
                faltas = faltas_de(base) if base in demandas else []
                total = round(sum(c for _, c, _ in faltas), 3)
                if total <= 1e-9:
                    continue
                producto = inventario.buscar_producto(base)
                no_se_compran.add(base)
                for fecha, cantidad, servicio_id in faltas:
                    for otro, c in producto.ingredientes_para(cantidad).items():
                        pedir(otro, fecha, c, servicio_id)
                avisos.append(
                    f"Faltan {total:g} {producto.unidad} de '{base}' (elaboración base): hay que prepararlo, "
                    f"así que se compran sus ingredientes ({', '.join(producto.formula['ingredientes'])})."
                )

        # --- Paso 1c: alimentos y consumibles por debajo de su mínimo ---
        # Aunque ningún servicio los pida, se reponen hasta el mínimo (igual
        # que la limpieza y el mantenimiento). Las bases no (se preparan) ni
        # los subproductos (salen de limpiar otros productos).
        por_minimo: set[str] = set()
        for producto in inventario.alimentos() + inventario.consumibles():
            if (producto.stock_minimo <= 0 or producto.es_base() or producto.es_subproducto
                    or producto.nombre in no_se_compran):
                continue
            if producto.stock_bueno < producto.stock_minimo - 1e-9:
                ya = sum(c for _, c, _ in demandas.get(producto.nombre, []))
                if ya < producto.stock_minimo - 1e-9:
                    pedir(producto.nombre, hoy, producto.stock_minimo - ya, None)
                por_minimo.add(producto.nombre)
                avisos.append(
                    f"'{producto.nombre}' está por debajo de su mínimo ({producto.stock_bueno:g} de "
                    f"{producto.stock_minimo:g} {producto.unidad}): se repone hasta el mínimo."
                )

        # --- Paso 2: productos limpios y subproductos ---
        for ingrediente in list(demandas):
            producto = inventario.buscar_producto(ingrediente)
            if producto is None or ingrediente in no_se_compran:
                continue
            if not producto.es_subproducto and not producto.origen:
                continue
            faltas = faltas_de(ingrediente)
            faltante = round(sum(c for _, c, _ in faltas), 3)
            if faltante <= 1e-9:
                continue

            if producto.es_subproducto:
                no_se_compran.add(ingrediente)
                avisos.append(
                    f"Faltan {faltante} {producto.unidad} de '{ingrediente}': es un subproducto "
                    "(sale de limpiar otros productos), así que no se añade a la lista."
                )
                continue

            origen = inventario.buscar_producto(producto.origen)
            if origen is None:
                continue  # se compra tal cual (su bruto ya no existe)

            rendimiento = inventario.rendimiento_medio(origen.nombre)
            if rendimiento is None:
                rendimiento = 1.0
                avisos.append(
                    f"'{origen.nombre}' todavía no tiene limpiezas registradas: se calcula como si no tuviera "
                    "merma. Compra algo más de lo indicado."
                )

            def en_bruto(cantidad: float) -> float:
                kg_bruto = producto.peso_kg(cantidad) / rendimiento
                if origen.unidad == "unidades":
                    return kg_bruto / origen.peso_unitario
                return convertir(kg_bruto, "kg", origen.unidad)

            no_se_compran.add(ingrediente)
            for fecha, cantidad, servicio_id in faltas:
                pedir(origen.nombre, fecha, en_bruto(cantidad), servicio_id)
            if ingrediente in por_minimo:
                por_minimo.add(origen.nombre)
            avisos.append(
                f"Faltan {faltante} {producto.unidad} de '{ingrediente}': salen de limpiar "
                f"~{round(en_bruto(faltante), 2)} {origen.unidad} de '{origen.nombre}' (rendimiento {rendimiento:.0%})."
            )

        # --- Paso 2b: limpieza y mantenimiento ---
        # No dependen de los servicios: se reponen cuando bajan del mínimo
        # (se pide lo que falta para volver a llegar a él).
        for producto in inventario.mantenimiento():
            if producto.stock_minimo > 0 and producto.stock < producto.stock_minimo - 1e-9:
                ya = sum(c for _, c, _ in demandas.get(producto.nombre, []))
                pedir(producto.nombre, hoy, producto.stock_minimo - ya, None)
                por_minimo.add(producto.nombre)
                avisos.append(
                    f"'{producto.nombre}' (limpieza y mantenimiento) está por debajo de su mínimo "
                    f"({producto.stock:g} de {producto.stock_minimo:g} {producto.unidad}): se repone hasta el mínimo."
                )

        # --- Paso 3: comparar contra el stock bueno ---
        hacen_falta: set[str] = set()
        for ingrediente in demandas:
            if ingrediente in no_se_compran:
                continue
            producto = inventario.buscar_producto(ingrediente)
            faltas = faltas_de(ingrediente)
            faltante = round(sum(c for _, c, _ in faltas), 3)

            if faltante <= 0:
                continue  # hay suficiente stock, no hace falta comprar nada de esto
            para = [sid for _, _, sid in faltas if sid is not None]

            unidad = producto.unidad if producto else ""
            if unidad == "unidades":
                # No se compran 0,4 patas: se redondea hacia arriba a unidades enteras.
                faltante = math.ceil(faltante - 1e-9)

            proveedor = producto.proveedor if producto else "Desconocido"
            precio = producto.precio_unitario if producto else 0
            self.agregar_item(ItemCompra(ingrediente, faltante, unidad, proveedor, precio, para,
                                         bajo_minimo=ingrediente in por_minimo))
            hacen_falta.add(ingrediente)

        # --- Paso 4: quitar lo pendiente que ya no hace falta ---
        # (Lo añadido a mano se queda: solo deja de contar lo calculado.)
        for item in list(self.items_pendientes()):
            if item.ingrediente not in hacen_falta and item.a_mano > 0:
                item.cantidad, item.para, item.bajo_minimo = item.a_mano, [], False
            elif item.ingrediente not in hacen_falta:
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
                existente.cantidad = round(item.cantidad + existente.a_mano, 6)  # lo añadido a mano se suma
                existente.unidad = item.unidad
                existente.proveedor = item.proveedor
                existente.precio_unitario_estimado = item.precio_unitario_estimado
                existente.para = item.para
                existente.bajo_minimo = item.bajo_minimo
                print(f"🛒 Actualizado en la lista de compra: {existente}")
                return

        self.items.append(item)
        print(f"🛒 Añadido a la lista de compra: {item}")

    def agregar_a_mano(
        self, ingrediente: str, cantidad: float, unidad: str, proveedor: str, precio_unitario: float = 0.0,
    ) -> ItemCompra:
        """
        Añade a la lista algo que no sale de ningún servicio ("papel de horno,
        2 rollos"). Si ya está pendiente, se suma. Al volver a generar la
        lista, lo añadido a mano se respeta (se suma a lo calculado).
        """
        ingrediente = (ingrediente or "").strip()
        if not ingrediente:
            raise ValueError("Indica qué hay que comprar.")
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que 0.")
        if precio_unitario < 0:
            raise ValueError("El precio no puede ser negativo.")
        existente = self.pendiente_de(ingrediente)
        if existente is not None:
            existente.cantidad = round(existente.cantidad + cantidad, 6)
            existente.a_mano = round(existente.a_mano + cantidad, 6)
            return existente
        item = ItemCompra(ingrediente, cantidad, unidad, (proveedor or "").strip() or "Sin proveedor",
                          precio_unitario, a_mano=cantidad)
        self.items.append(item)
        return item

    def quitar_pendiente(self, ingrediente: str) -> None:
        """Quita de la lista un artículo pendiente (si vuelve a hacer falta, saldrá al generar la lista)."""
        self.items = [i for i in self.items if i.ingrediente != ingrediente or i.comprado]

    def cambiar_cantidad(self, ingrediente: str, cantidad: float) -> None:
        """Cambia la cantidad de un artículo pendiente (al volver a generar la lista, se recalcula)."""
        item = self.pendiente_de(ingrediente)
        if item is None:
            raise ValueError(f"'{ingrediente}' no está pendiente en la lista.")
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que 0 (para quitarlo, usa 'Quitar').")
        if item.a_mano >= item.cantidad - 1e-9:  # solo era lo añadido a mano
            item.a_mano = cantidad
        item.cantidad = cantidad

    def quitar_producto(self, nombre: str) -> None:
        """Quita de la lista lo PENDIENTE de un producto (por ejemplo, al borrarlo). Lo ya comprado se queda."""
        self.items = [i for i in self.items if i.ingrediente != nombre or i.comprado]

    def renombrar_producto(self, antiguo: str, nuevo: str) -> None:
        """Al renombrar un producto, la lista de la compra pasa a usar el nombre nuevo."""
        for item in self.items:
            if item.ingrediente == antiguo:
                item.ingrediente = nuevo

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
