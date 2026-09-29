"""
Módulo: recetario.py
---------------------
Calcula las cantidades de ingredientes necesarias para un servicio según
el número de comensales, y las compara con el inventario real para saber
qué hay que comprar.

Conecta con:
- inventario.py -> para consultar y comparar stock real
- servicios.py  -> un Servicio indica cuántos comensales y qué menú

Conceptos de Python nuevos en este módulo:
- COMPOSICIÓN: un Menu "contiene" una lista de objetos Receta. Es una
  relación muy distinta a la herencia (que veremos más adelante): aquí
  un objeto simplemente GUARDA otros objetos dentro, no "es un tipo de".
- Comprehensions de diccionario: {clave: valor for ... in ...}
- Importar clases de otros módulos propios (from inventario import ...)
"""

from typing import Optional

from inventario import Inventario
from servicios import Servicio


class Receta:
    """
    Representa UN plato. Los ingredientes se guardan "por comensal" para
    poder escalar la receta a cualquier número de comensales.
    """

    def __init__(self, nombre: str, categoria: str, ingredientes_por_comensal: dict[str, float]):
        # ingredientes_por_comensal, ejemplo:
        # {"Harina de trigo": 0.15, "Aceite de oliva": 0.01}
        # -> significa: 0.15 kg de harina y 0.01 litros de aceite POR CADA comensal.
        # IMPORTANTE: los nombres deben coincidir exactamente con los nombres
        # de producto usados en el Inventario, y las cantidades deben estar
        # en la MISMA unidad que ese producto (kg, litros...).
        self.nombre = nombre
        self.categoria = categoria
        self.ingredientes_por_comensal = ingredientes_por_comensal

    def calcular_ingredientes(self, comensales: int) -> dict[str, float]:
        """Escala los ingredientes de la receta al número de comensales dado."""
        return {
            ingrediente: round(cantidad * comensales, 3)
            for ingrediente, cantidad in self.ingredientes_por_comensal.items()
        }

    def costo_por_comensal(self, inventario: Inventario) -> float:
        """
        Coste estimado de esta receta POR COMENSAL, según los precios
        ACTUALES del inventario (no una foto guardada, como en
        MovimientoStock -- aquí interesa saber "cuánto me costaría hacer
        esto hoy", no lo que costó en el pasado). Si algún ingrediente ya
        no existe en el inventario, se ignora en el cálculo.
        """
        total = 0.0
        for nombre_ingrediente, cantidad in self.ingredientes_por_comensal.items():
            producto = inventario.buscar_producto(nombre_ingrediente)
            if producto is not None:
                total += cantidad * producto.precio_unitario
        return round(total, 2)

    def __str__(self) -> str:
        detalle = ", ".join(f"{c} {i}/comensal" for i, c in self.ingredientes_por_comensal.items())
        return f"{self.nombre} ({self.categoria}) — {detalle}"

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "categoria": self.categoria,
            "ingredientes_por_comensal": self.ingredientes_por_comensal,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Receta":
        return cls(datos["nombre"], datos["categoria"], datos["ingredientes_por_comensal"])

    def urgencia_caducidad(self, inventario: Inventario, dias: int = 7) -> float:
        """
        "Puntuación" de cuánto interesa preparar esta receta AHORA para
        aprovechar ingredientes que están a punto de caducar. 0 = ningún
        ingrediente en riesgo. Cuanto más alta, más urgente -- un
        ingrediente que caduca MAÑANA pesa más que uno que caduca en
        6 días, aunque los dos entren dentro de la ventana de `dias`.
        """
        urgencia_total = 0.0
        for nombre_ingrediente in self.ingredientes_por_comensal:
            producto = inventario.buscar_producto(nombre_ingrediente)
            if producto is None or producto.stock <= 0:
                continue
            dias_restantes = producto.dias_para_caducar()
            if dias_restantes is not None and 0 <= dias_restantes <= dias:
                # Restando de `dias` invertimos la escala: cuantos MENOS
                # días quedan, MÁS puntos suma (más urgente).
                urgencia_total += (dias - dias_restantes + 1)
        return urgencia_total

    def urgencia_stock(self, inventario: Inventario) -> float:
        """
        "Puntuación" de cuánto interesa preparar esta receta para
        aprovechar ingredientes de los que hay MUCHO stock por encima de
        su mínimo -- evita acumular producto de más. 0 = ningún
        ingrediente tiene excedente.

        Medimos el exceso en PROPORCIÓN al mínimo, no en cantidad bruta:
        "5 de más sobre un mínimo de 2" es más significativo que "5 de
        más sobre un mínimo de 50", aunque el número absoluto sea igual.
        """
        urgencia_total = 0.0
        for nombre_ingrediente in self.ingredientes_por_comensal:
            producto = inventario.buscar_producto(nombre_ingrediente)
            if producto is None or producto.stock_minimo <= 0:
                continue
            exceso = producto.stock - producto.stock_minimo
            if exceso > 0:
                urgencia_total += exceso / producto.stock_minimo
        return urgencia_total


class Menu:
    """
    Un menú es una COMPOSICIÓN de recetas: simplemente guarda una lista
    de objetos Receta que lo forman.
    """

    def __init__(self, nombre: str, recetas: list[Receta]):
        self.nombre = nombre
        self.recetas = recetas

    def calcular_ingredientes_totales(self, comensales: int) -> dict[str, float]:
        """Suma los ingredientes de TODAS las recetas del menú, ya escalados."""
        totales: dict[str, float] = {}
        for receta in self.recetas:
            necesidades = receta.calcular_ingredientes(comensales)
            for ingrediente, cantidad in necesidades.items():
                # .get(ingrediente, 0) -> si el ingrediente aún no está en
                # totales, empieza sumando desde 0 en vez de dar error.
                totales[ingrediente] = round(totales.get(ingrediente, 0) + cantidad, 3)
        return totales

    def costo_por_comensal(self, inventario: Inventario) -> float:
        """Suma el coste por comensal de todas sus recetas -- ver Receta.costo_por_comensal()."""
        return round(sum(r.costo_por_comensal(inventario) for r in self.recetas), 2)

    def __str__(self) -> str:
        platos = ", ".join(r.nombre for r in self.recetas)
        return f"{self.nombre}: {platos}"

    def to_dict(self) -> dict:
        # Guardamos solo los NOMBRES de las recetas, no la receta completa,
        # para no duplicar datos que ya viven en Recetario.recetas.
        return {"nombre": self.nombre, "recetas": [r.nombre for r in self.recetas]}

    @classmethod
    def from_dict(cls, datos: dict, recetas_disponibles: dict[str, Receta]) -> "Menu":
        """
        A diferencia de Producto o Servicio, un Menu no puede reconstruirse
        solo con su propio diccionario: aquí sus recetas son solo nombres.
        Por eso este from_dict necesita también el diccionario de recetas
        YA cargadas, para encontrar los objetos Receta reales a partir de
        esos nombres.
        """
        recetas = [
            recetas_disponibles[nombre]
            for nombre in datos["recetas"]
            if nombre in recetas_disponibles
        ]
        return cls(datos["nombre"], recetas)

    def urgencia_caducidad(self, inventario: Inventario, dias: int = 7) -> float:
        """Suma la urgencia de todas sus recetas -- ver Receta.urgencia_caducidad()."""
        return sum(r.urgencia_caducidad(inventario, dias) for r in self.recetas)

    def urgencia_stock(self, inventario: Inventario) -> float:
        """Suma la urgencia de todas sus recetas -- ver Receta.urgencia_stock()."""
        return sum(r.urgencia_stock(inventario) for r in self.recetas)

    def ingredientes_en_exceso(self, inventario: Inventario) -> list:
        """Ingredientes de este menú con stock notablemente por encima de su mínimo (para explicar la recomendación)."""
        productos_exceso = []
        nombres_vistos = set()
        for receta in self.recetas:
            for nombre_ingrediente in receta.ingredientes_por_comensal:
                if nombre_ingrediente in nombres_vistos:
                    continue
                producto = inventario.buscar_producto(nombre_ingrediente)
                if producto and producto.stock_minimo > 0 and producto.stock > producto.stock_minimo:
                    productos_exceso.append(producto)
                    nombres_vistos.add(nombre_ingrediente)
        return productos_exceso

    def ingredientes_en_riesgo(self, inventario: Inventario, dias: int = 7) -> list:
        """
        Qué ingredientes de este menú están a punto de caducar -- para
        poder EXPLICAR una recomendación, no solo dar un número pelado.
        """
        productos_riesgo = []
        nombres_vistos = set()
        for receta in self.recetas:
            for nombre_ingrediente in receta.ingredientes_por_comensal:
                if nombre_ingrediente in nombres_vistos:
                    continue
                producto = inventario.buscar_producto(nombre_ingrediente)
                if producto is None or producto.stock <= 0:
                    continue
                dias_restantes = producto.dias_para_caducar()
                if dias_restantes is not None and 0 <= dias_restantes <= dias:
                    productos_riesgo.append(producto)
                    nombres_vistos.add(nombre_ingrediente)
        return productos_riesgo

    def se_puede_preparar(self, inventario: Inventario, comensales: int) -> bool:
        """True si TODOS los ingredientes de este menú alcanzan en stock para `comensales`, sin comprar nada."""
        necesarios = self.calcular_ingredientes_totales(comensales)
        for ingrediente, cantidad_necesaria in necesarios.items():
            producto = inventario.buscar_producto(ingrediente)
            stock_actual = producto.stock if producto else 0
            if stock_actual < cantidad_necesaria:
                return False
        return True


class Recetario:
    """Gestiona todas las recetas y menús disponibles del restaurante."""

    def __init__(self):
        self.recetas: dict[str, Receta] = {}
        self.menus: dict[str, Menu] = {}

    def agregar_receta(self, receta: Receta) -> None:
        self.recetas[receta.nombre] = receta
        print(f"✅ Receta añadida: {receta.nombre}")

    def agregar_menu(self, menu: Menu) -> None:
        self.menus[menu.nombre] = menu
        print(f"✅ Menú añadido: {menu.nombre}")

    def buscar_menu(self, nombre: str) -> Optional[Menu]:
        return self.menus.get(nombre)

    def previsualizar_consumo(self, servicio: Servicio, inventario: Inventario) -> Optional[list[dict]]:
        """
        Calcula, SIN tocar nada todavía, qué se descontaría del inventario
        al completar este servicio. Devuelve None si el menú del servicio
        no existe en el recetario.

        Para cada ingrediente: cuánto hace falta, cuánto hay, cuánto se
        descontará de verdad y cuánto faltaba. Si no hay stock suficiente,
        se descuenta TODO lo que hay (se deja a 0) en vez de no descontar
        nada: si el servicio se hizo, lo que había se gastó -- y lo que
        faltaba tuvo que salir de algún sitio que no estaba registrado.
        """
        menu = self.buscar_menu(servicio.menu)
        if menu is None:
            return None

        filas = []
        for ingrediente, necesario in menu.calcular_ingredientes_totales(servicio.comensales).items():
            producto = inventario.buscar_producto(ingrediente)
            en_stock = producto.stock if producto else 0
            # Sin round() a propósito: redondear podría dar un número
            # ligeramente MAYOR que el stock real, y actualizar_stock()
            # lo rechazaría por "stock insuficiente".
            a_descontar = min(necesario, en_stock)
            filas.append({
                "ingrediente": ingrediente,
                "unidad": producto.unidad if producto else "",
                "necesario": necesario,
                "en_stock": en_stock,
                "a_descontar": a_descontar,
                "faltante": round(necesario - a_descontar, 3),
                "existe": producto is not None,
            })
        return filas

    def completar_servicio(self, servicio: Servicio, inventario: Inventario) -> Optional[list[dict]]:
        """
        Marca el servicio como completado y descuenta del inventario los
        ingredientes de su menú (motivo "consumo", así cuenta en Métricas).
        Devuelve el mismo detalle que previsualizar_consumo(), para poder
        informar de lo que faltaba. Devuelve None si el menú no existe (en
        ese caso NO toca ni el servicio ni el inventario: decide quien llama).

        Vive aquí (y no en main.py ni en app.py) para que la consola y la
        interfaz gráfica usen EXACTAMENTE la misma lógica.
        """
        if servicio.estado in ("completado", "cancelado"):
            # Sin esto, completar dos veces el mismo servicio descontaría
            # el stock dos veces.
            raise ValueError(f"El servicio #{servicio.id} ya está {servicio.estado}.")

        filas = self.previsualizar_consumo(servicio, inventario)
        if filas is None:
            return None

        for fila in filas:
            if fila["existe"] and fila["a_descontar"] > 0:
                inventario.actualizar_stock(
                    fila["ingrediente"], fila["a_descontar"], sumar=False, motivo_salida="consumo"
                )
        servicio.completar()
        return filas

    def recomendar_menus(self, inventario: Inventario, dias: int = 7) -> list[tuple[Menu, float]]:
        """
        Ordena los menús disponibles por urgencia TOTAL: caducidad
        próxima + stock por encima de su mínimo. Devuelve pares
        (menu, puntuación) -- una lista vacía si no hay menús.

        Esto es un recomendador "basado en reglas", no una IA real: no
        inventa nada nuevo, solo prioriza entre lo que YA existe según
        una fórmula fija y explicable (a diferencia de un modelo de IA,
        que razonaría de forma más flexible pero menos predecible).
        """
        puntuados = [
            (m, m.urgencia_caducidad(inventario, dias) + m.urgencia_stock(inventario))
            for m in self.menus.values()
        ]
        return sorted(puntuados, key=lambda par: par[1], reverse=True)

    def to_dict(self) -> dict:
        return {
            "recetas": [r.to_dict() for r in self.recetas.values()],
            "menus": [m.to_dict() for m in self.menus.values()],
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Recetario":
        recetario = cls()

        # Las recetas se cargan PRIMERO: los menús las necesitan ya
        # construidas para poder "buscarlas" por nombre.
        for datos_receta in datos["recetas"]:
            receta = Receta.from_dict(datos_receta)
            recetario.recetas[receta.nombre] = receta

        for datos_menu in datos["menus"]:
            menu = Menu.from_dict(datos_menu, recetario.recetas)
            recetario.menus[menu.nombre] = menu

        return recetario

    def necesidades_para_servicio(self, servicio: Servicio, inventario: Inventario) -> dict:
        """
        Cruza un Servicio (comensales + menú) con el Inventario real y
        devuelve, para cada ingrediente: cuánto hace falta, cuánto hay en
        stock, y cuánto falta comprar.
        """
        menu = self.buscar_menu(servicio.menu)
        if menu is None:
            print(f"❌ No se encontró el menú '{servicio.menu}' en el recetario.")
            return {}

        necesarios = menu.calcular_ingredientes_totales(servicio.comensales)

        resultado = {}
        for ingrediente, cantidad_necesaria in necesarios.items():
            producto = inventario.buscar_producto(ingrediente)
            stock_actual = producto.stock if producto else 0
            faltante = max(0, round(cantidad_necesaria - stock_actual, 3))
            resultado[ingrediente] = {
                "necesario": cantidad_necesaria,
                "en_stock": stock_actual,
                "falta_comprar": faltante,
            }
        return resultado

    def mostrar_necesidades(self, resultado: dict) -> None:
        if not resultado:
            print("No hay necesidades que mostrar.")
            return
        for ingrediente, datos in resultado.items():
            if datos["falta_comprar"] == 0:
                estado = "✅ suficiente"
            else:
                estado = f"🛒 falta comprar {datos['falta_comprar']}"
            print(
                f"{ingrediente}: necesario {datos['necesario']}, "
                f"en stock {datos['en_stock']} -> {estado}"
            )


if __name__ == "__main__":
    from datetime import date, time
    from inventario import Producto

    # --- Montamos un inventario de ejemplo (con algo de stock escaso a propósito) ---
    inventario = Inventario()
    inventario.agregar_producto(Producto("Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2))
    inventario.agregar_producto(Producto("Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5))
    inventario.agregar_producto(Producto("Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2))

    # --- Definimos recetas (ingredientes por comensal) ---
    pan_casero = Receta("Pan casero", "Panadería", {
        "Harina de trigo": 0.15,
        "Aceite de oliva": 0.01,
    })

    ensalada_tomate = Receta("Ensalada de tomate", "Entrantes", {
        "Tomate": 0.1,
        "Aceite de oliva": 0.005,
    })

    recetario = Recetario()
    recetario.agregar_receta(pan_casero)
    recetario.agregar_receta(ensalada_tomate)

    menu_del_dia = Menu("Menú del día", [pan_casero, ensalada_tomate])
    recetario.agregar_menu(menu_del_dia)

    # --- Creamos un servicio para 10 comensales con ese menú ---
    servicio = Servicio(
        fecha=date(2026, 9, 10),
        hora=time(14, 0),
        comensales=10,
        menu="Menú del día",
    )

    print(f"\n--- Servicio: {servicio} ---")
    print(f"--- Ingredientes totales del menú para {servicio.comensales} comensales ---")
    print(menu_del_dia.calcular_ingredientes_totales(servicio.comensales))

    print("\n--- Necesidades vs. stock actual ---")
    resultado = recetario.necesidades_para_servicio(servicio, inventario)
    recetario.mostrar_necesidades(resultado)
