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

import copy
from datetime import date, timedelta
from typing import Optional

from elaboraciones import PreparacionBase
from inventario import ConNotas, Inventario
from servicios import Servicio


def _coste_de_filas(filas: list[dict], inventario: Inventario) -> tuple[float, float]:
    """Lo que cuestan los lotes elegidos en `filas` (ver filas_necesidades): (con IVA, sin IVA)."""
    coste = coste_sin_iva = 0.0
    for f in filas:
        producto = inventario.buscar_producto(f["ingrediente"])
        for lote_id, cantidad in f["reparto"]:
            lote = producto.buscar_lote(lote_id)
            coste += lote.precio_unitario * cantidad
            coste_sin_iva += lote.precio_base * cantidad
    return coste, coste_sin_iva


class Receta(ConNotas):
    """
    Representa UN plato. Los ingredientes se guardan "por comensal" para
    poder escalar la receta a cualquier número de comensales.
    """

    def __init__(
        self, nombre: str, categoria: str, ingredientes_por_comensal: dict[str, float],
        vida_util_dias: Optional[int] = None,
    ):
        # ingredientes_por_comensal, ejemplo:
        # {"Harina de trigo": 0.15, "Aceite de oliva": 0.01}
        # -> significa: 0.15 kg de harina y 0.01 litros de aceite POR CADA comensal.
        # IMPORTANTE: los nombres deben coincidir exactamente con los nombres
        # de producto usados en el Inventario, y las cantidades deben estar
        # en la MISMA unidad que ese producto (kg, litros...).
        self.nombre = nombre
        self.categoria = categoria
        self.ingredientes_por_comensal = ingredientes_por_comensal
        # Cuántos días dura este plato una vez preparado (opcional). Sirve
        # para proponer la caducidad de cada tanda que se prepare.
        if vida_util_dias is not None and vida_util_dias < 0:
            raise ValueError("La vida útil no puede ser negativa.")
        self.vida_util_dias = vida_util_dias

    def caducidad_propuesta(self, fecha_preparacion: date) -> Optional[date]:
        """Fecha de preparación + vida útil (None si la receta no tiene vida útil)."""
        if self.vida_util_dias is None:
            return None
        return fecha_preparacion + timedelta(days=self.vida_util_dias)

    def calcular_ingredientes(self, comensales: int) -> dict[str, float]:
        """Escala los ingredientes de la receta al número de comensales dado."""
        return {
            ingrediente: round(cantidad * comensales, 3)
            for ingrediente, cantidad in self.ingredientes_por_comensal.items()
        }

    def costo_por_comensal(self, inventario: Inventario, sin_iva: bool = False, redondear: bool = True) -> float:
        """
        Coste estimado de esta receta POR COMENSAL, según los precios
        ACTUALES del inventario (no una foto guardada, como en
        MovimientoStock -- aquí interesa saber "cuánto me costaría hacer
        esto hoy", no lo que costó en el pasado). Si algún ingrediente ya
        no existe en el inventario, se ignora en el cálculo.
        Con IVA (lo pagado), o sin él si `sin_iva` (rentabilidad cuando se recupera el IVA).
        """
        total = 0.0
        for nombre_ingrediente, cantidad in self.ingredientes_por_comensal.items():
            total += cantidad * inventario.precio_de(nombre_ingrediente, sin_iva)
        # Redondeado a céntimos para mostrarlo; para multiplicar por los
        # comensales se pide sin redondear (si no, el error se multiplica).
        return round(total, 2) if redondear else total

    def __str__(self) -> str:
        detalle = ", ".join(f"{c} {i}/comensal" for i, c in self.ingredientes_por_comensal.items())
        return f"{self.nombre} ({self.categoria}) — {detalle}"

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "categoria": self.categoria,
            "ingredientes_por_comensal": self.ingredientes_por_comensal,
            "vida_util_dias": self.vida_util_dias,
            **self._notas_dict(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Receta":
        receta = cls(
            datos["nombre"], datos["categoria"], datos["ingredientes_por_comensal"], datos.get("vida_util_dias"),
        )
        receta._cargar_notas(datos)
        return receta

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


class Menu(ConNotas):
    """
    Un menú es una COMPOSICIÓN de recetas: simplemente guarda una lista
    de objetos Receta que lo forman.

    Además puede llevar CONSUMIBLES por comensal (servilletas, vasos
    desechables...): {"Servilletas de papel": 2} = 2 servilletas por
    comensal. Se descuentan al completar el servicio y entran en la lista
    de la compra igual que los ingredientes, pero se guardan aparte para
    que el menú siga "hablando" de comida a simple vista.

    Y MATERIAL por comensal (platos, copas, cubiertos...): no se gasta,
    sirve para proponer la lista de carga del servicio (ver materiales.py).
    """

    def __init__(
        self,
        nombre: str,
        recetas: list[Receta],
        consumibles_por_comensal: Optional[dict[str, float]] = None,
        materiales_por_comensal: Optional[dict[str, float]] = None,
    ):
        self.nombre = nombre
        self.recetas = recetas
        self.consumibles_por_comensal = dict(consumibles_por_comensal or {})
        self.materiales_por_comensal = dict(materiales_por_comensal or {})

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

    def foto(self) -> dict:
        """
        Copia completa de cómo es el menú AHORA (con las recetas dentro, no
        solo sus nombres), para guardarla en un servicio al completarlo.
        """
        # deepcopy: una copia INDEPENDIENTE de todo, también de los
        # diccionarios de dentro. Con una copia normal, la foto compartiría
        # los ingredientes con la receta y, al cambiar la receta después,
        # también cambiaría el historial.
        return copy.deepcopy({
            "nombre": self.nombre,
            "recetas": [r.to_dict() for r in self.recetas],
            "consumibles_por_comensal": self.consumibles_por_comensal,
            "materiales_por_comensal": self.materiales_por_comensal,
            **self._notas_dict(),
        })

    def calcular_consumibles(self, comensales: int) -> dict[str, float]:
        """Los consumibles del menú, ya escalados al número de comensales."""
        return {nombre: round(cantidad * comensales, 3) for nombre, cantidad in self.consumibles_por_comensal.items()}

    def calcular_necesidades_totales(self, comensales: int) -> dict[str, float]:
        """TODO lo que se gasta del inventario en un servicio: ingredientes + consumibles."""
        totales = self.calcular_ingredientes_totales(comensales)
        for nombre, cantidad in self.calcular_consumibles(comensales).items():
            totales[nombre] = round(totales.get(nombre, 0) + cantidad, 3)
        return totales

    def ingredientes_por_comensal(self) -> dict[str, float]:
        """Los ingredientes de todas sus recetas, sumados, por comensal (para verlos de un vistazo)."""
        return self.calcular_ingredientes_totales(1)

    def costo_por_comensal(self, inventario: Inventario, sin_iva: bool = False, redondear: bool = True) -> float:
        """Coste de la COMIDA por comensal: suma de sus recetas -- ver Receta.costo_por_comensal()."""
        total = sum(r.costo_por_comensal(inventario, sin_iva, redondear=False) for r in self.recetas)
        return round(total, 2) if redondear else total

    def costo_consumibles_por_comensal(self, inventario: Inventario, sin_iva: bool = False,
                                       redondear: bool = True) -> float:
        """Coste de los consumibles por comensal, a los precios actuales."""
        total = 0.0
        for nombre, cantidad in self.consumibles_por_comensal.items():
            total += cantidad * inventario.precio_de(nombre, sin_iva)
        return round(total, 2) if redondear else total

    def __str__(self) -> str:
        platos = ", ".join(r.nombre for r in self.recetas)
        return f"{self.nombre}: {platos}"

    def to_dict(self) -> dict:
        # Guardamos solo los NOMBRES de las recetas, no la receta completa,
        # para no duplicar datos que ya viven en Recetario.recetas.
        return {
            "nombre": self.nombre,
            "recetas": [r.nombre for r in self.recetas],
            "consumibles_por_comensal": self.consumibles_por_comensal,
            "materiales_por_comensal": self.materiales_por_comensal,
            **self._notas_dict(),
        }

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
        # .get(): los menús guardados antes de los consumibles no los tienen.
        menu = cls(
            datos["nombre"], recetas, datos.get("consumibles_por_comensal", {}), datos.get("materiales_por_comensal", {}),
        )
        menu._cargar_notas(datos)
        return menu

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
        """True si TODO lo que gasta este menú (ingredientes y consumibles) alcanza en stock para `comensales`."""
        necesarios = self.calcular_necesidades_totales(comensales)
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

    @staticmethod
    def _nombre_libre(nombre: str, existentes: dict, que: str, llamado: str) -> str:
        """
        Comprueba que el nombre no está vacío ni repetido (sin distinguir
        mayúsculas ni espacios de más). Lo devuelve sin espacios sobrantes.
        que: "una receta" / "un menú"; llamado: "llamada" / "llamado".
        """
        nombre = (nombre or "").strip()
        if not nombre:
            raise ValueError(f"Ponle un nombre a {que}.")
        repetido = next((n for n in existentes if n.strip().lower() == nombre.lower()), None)
        if repetido is not None:
            raise ValueError(f"Ya existe {que} {llamado} «{repetido}». Ponle otro nombre "
                             "(si es una versión nueva, por ejemplo «… v2»).")
        return nombre

    def agregar_receta(self, receta: Receta) -> None:
        # Un nombre repetido SUSTITUÍA la receta sin avisar, y los menús seguían
        # usando la vieja hasta reiniciar: ahora se rechaza.
        receta.nombre = self._nombre_libre(receta.nombre, self.recetas, "una receta", "llamada")
        self.recetas[receta.nombre] = receta
        print(f"✅ Receta añadida: {receta.nombre}")

    def agregar_menu(self, menu: Menu) -> None:
        menu.nombre = self._nombre_libre(menu.nombre, self.menus, "un menú", "llamado")
        self.menus[menu.nombre] = menu
        print(f"✅ Menú añadido: {menu.nombre}")

    def renombrar_producto(self, antiguo: str, nuevo: str) -> list[str]:
        """
        Al renombrar un producto del inventario, lo renombra también en las
        recetas (como ingrediente) y en los menús (como consumible),
        conservando las cantidades. Devuelve los nombres de lo que se ha
        actualizado. (Los menús no guardan copia de sus recetas, solo una
        referencia, así que ven el cambio de las recetas automáticamente.)
        """
        actualizados = []
        for receta in self.recetas.values():
            if antiguo in receta.ingredientes_por_comensal:
                receta.ingredientes_por_comensal = {
                    (nuevo if n == antiguo else n): c for n, c in receta.ingredientes_por_comensal.items()
                }
                actualizados.append(receta.nombre)
        for menu in self.menus.values():
            if antiguo in menu.consumibles_por_comensal:
                menu.consumibles_por_comensal = {
                    (nuevo if n == antiguo else n): c for n, c in menu.consumibles_por_comensal.items()
                }
                actualizados.append(f"menú {menu.nombre}")
        return actualizados

    def renombrar_material(self, antiguo: str, nuevo: str) -> list[str]:
        """Como renombrar_producto(), pero para el material de los menús."""
        actualizados = []
        for menu in self.menus.values():
            if antiguo in menu.materiales_por_comensal:
                menu.materiales_por_comensal = {
                    (nuevo if n == antiguo else n): c for n, c in menu.materiales_por_comensal.items()
                }
                actualizados.append(menu.nombre)
        return actualizados

    def buscar_menu(self, nombre: str) -> Optional[Menu]:
        return self.menus.get(nombre)

    # ---------- Qué se gasta: filas por ingrediente, con sus lotes ----------

    @staticmethod
    def filas_necesidades(
        necesidades: dict[str, float], inventario: Inventario, elecciones: Optional[dict[str, list[int]]] = None,
    ) -> list[dict]:
        """
        Para cada ingrediente de `necesidades` ({nombre: cantidad}), calcula
        SIN tocar nada de qué lotes saldría. Lo usan tanto completar un
        servicio como preparar una elaboración.

        `elecciones` dice, para cada ingrediente, de qué lotes sale y en qué
        orden: {"Secreto": [2, 1]} = "primero del lote 2 y, lo que no llegue,
        del lote 1". Lo decide quien usa el programa. Si un ingrediente no
        aparece, se propone su lote BUENO que caduca antes (solo como
        sugerencia); los caducados se proponen solo si no queda otro.

        Cada fila es un diccionario con:
        - necesario, en_stock, a_descontar, faltante (lo que no había en
          ningún lote), unidad, existe, tipo.
        - lotes_elegidos: los lotes que se usarán, en orden.
        - reparto: lista de (lote_id, cantidad) que se sacaría.
        - sin_asignar: cantidad que SÍ hay en stock pero que los lotes
          elegidos no cubren. Mientras sea > 0, hay que elegir otro lote
          (de lotes_restantes) para completarla.
        - lotes_restantes: lotes todavía no elegidos que tienen stock.
        - caducados: [(lote_id, cantidad, fecha_caducidad)] de lo que se
          sacaría de lotes YA CADUCADOS (para avisar antes de usarlos).

        Si en TOTAL no hay stock suficiente, se usan todos los lotes.
        """
        elecciones = elecciones or {}
        filas = []
        for ingrediente, necesario in necesidades.items():
            if necesario <= 1e-9:
                continue
            producto = inventario.buscar_producto(ingrediente)
            en_stock = producto.stock if producto else 0
            # Sin round() a propósito: redondear podría dar un número
            # ligeramente MAYOR que el stock real, y la salida se
            # rechazaría por "stock insuficiente".
            a_descontar = min(necesario, en_stock)
            fila = {
                "ingrediente": ingrediente,
                "tipo": producto.tipo if producto else "alimento",
                "unidad": producto.unidad if producto else "",
                "necesario": necesario,
                "en_stock": en_stock,
                "a_descontar": a_descontar,
                "faltante": round(necesario - a_descontar, 3),
                "existe": producto is not None,
                "lotes_elegidos": [],
                "reparto": [],
                "sin_asignar": 0.0,
                "lotes_restantes": [],
                "caducados": [],
            }
            if producto is not None and a_descontar > 0:
                ordenados = [l.id for l in producto.lotes_para_usar()]
                if necesario >= en_stock - 1e-9:
                    elegidos = ordenados  # no llega ni con todo: se usa todo
                else:
                    elegidos = [i for i in elecciones.get(ingrediente, []) if i in ordenados] or ordenados[:1]
                reparto, sin_asignar = inventario.repartir(ingrediente, a_descontar, elegidos)
                fila["lotes_elegidos"] = elegidos
                fila["reparto"] = reparto
                fila["sin_asignar"] = sin_asignar
                fila["lotes_restantes"] = [i for i in ordenados if i not in elegidos]
                for lote_id, cantidad in reparto:
                    lote = producto.buscar_lote(lote_id)
                    if lote.esta_caducado():
                        fila["caducados"].append((lote_id, cantidad, lote.fecha_caducidad))
            filas.append(fila)
        return filas

    # ---------- Elaboraciones (recetas preparadas por adelantado) ----------

    def plan_elaboraciones(
        self, servicio: Servicio, inventario: Inventario, plan: Optional[dict[str, list[int]]] = None,
    ) -> dict[str, dict]:
        """
        Para cada receta del menú de la que haya raciones preparadas, qué
        tandas se usarían en este servicio. `plan` dice, para cada receta, de
        qué tandas sale y en qué orden ({"Ensalada": [3, 1]}); una lista
        vacía = no usar raciones preparadas. Si una receta no aparece en
        `plan`, se proponen todas sus tandas que no habrán caducado el día
        del servicio, primero las que caducan antes.

        Devuelve {receta: {"tandas": [ids disponibles en orden], "elegidas",
        "reparto": [(tanda_id, raciones)], "raciones": cubiertas,
        "restantes": raciones que se hacen con ingredientes en crudo}}.
        """
        menu = self.buscar_menu(servicio.menu)
        resultado: dict[str, dict] = {}
        if menu is None:
            return resultado
        plan = plan or {}
        for receta in menu.recetas:
            disponibles = [t.id for t in inventario.elaboraciones.tandas_de(receta.nombre)]
            if not disponibles:
                continue
            if receta.nombre in plan:
                elegidas = [t for t in plan[receta.nombre] if t in disponibles]
            else:
                elegidas = [t.id for t in inventario.elaboraciones.tandas_de(receta.nombre, servicio.fecha)]
            reparto, restantes = inventario.elaboraciones.repartir(receta.nombre, servicio.comensales, elegidas)
            resultado[receta.nombre] = {
                "tandas": disponibles, "elegidas": elegidas, "reparto": reparto,
                "raciones": round(servicio.comensales - restantes, 6), "restantes": restantes,
            }
        return resultado

    def necesidades_servicio(
        self, servicio: Servicio, raciones_preparadas: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        """
        Lo que hay que sacar del inventario para un servicio: los ingredientes
        de las raciones que NO salen de elaboraciones ya preparadas
        (`raciones_preparadas` = {receta: raciones}), más los consumibles.
        """
        menu = self.buscar_menu(servicio.menu)
        if menu is None:
            return {}
        raciones_preparadas = raciones_preparadas or {}
        totales: dict[str, float] = {}
        for receta in menu.recetas:
            restantes = max(0.0, servicio.comensales - raciones_preparadas.get(receta.nombre, 0.0))
            if restantes <= 0:
                continue
            for ingrediente, cantidad in receta.ingredientes_por_comensal.items():
                totales[ingrediente] = round(totales.get(ingrediente, 0) + round(cantidad * restantes, 3), 3)
        for nombre, cantidad in menu.calcular_consumibles(servicio.comensales).items():
            totales[nombre] = round(totales.get(nombre, 0) + cantidad, 3)
        return totales

    def previsualizar_elaboracion(
        self, nombre_receta: str, raciones: float, inventario: Inventario,
        elecciones: Optional[dict[str, list[int]]] = None,
    ) -> list[dict]:
        """Qué ingredientes (y de qué lotes) se gastarían al preparar `raciones` de una receta."""
        receta = self.recetas.get(nombre_receta)
        if receta is None:
            raise ValueError(f"No existe la receta '{nombre_receta}'.")
        necesidades = {i: round(c * raciones, 3) for i, c in receta.ingredientes_por_comensal.items()}
        return self.filas_necesidades(necesidades, inventario, elecciones)

    def preparar_elaboracion(
        self, nombre_receta: str, raciones: float, inventario: Inventario,
        elecciones: Optional[dict[str, list[int]]] = None, fecha_caducidad: Optional[date] = None,
        fecha_preparacion: Optional[date] = None,
    ):
        """
        Prepara `raciones` de una receta por adelantado:
        1. Saca los ingredientes del inventario, de los lotes elegidos
           (motivo "elaboración").
        2. Crea una tanda con su caducidad y su coste real por ración.
        Comprueba todo antes de tocar nada. Si no hay ingredientes
        suficientes, no se prepara nada (lanza ValueError diciendo qué falta).
        Devuelve la tanda creada.
        """
        if raciones <= 0:
            raise ValueError("Las raciones deben ser más de 0.")
        filas = self.previsualizar_elaboracion(nombre_receta, raciones, inventario, elecciones)
        faltan = [f"{f['ingrediente']} ({f['faltante']:g} {f['unidad']})" if f["existe"] else f"{f['ingrediente']} (no existe)"
                  for f in filas if f["faltante"] > 1e-9 or not f["existe"]]
        if faltan:
            raise ValueError("No hay ingredientes suficientes. Falta: " + ", ".join(faltan))
        pendientes = [f["ingrediente"] for f in filas if f["sin_asignar"] > 1e-9]
        if pendientes:
            raise ValueError(
                "Los lotes elegidos no cubren lo que hace falta de: " + ", ".join(pendientes)
                + ". Elige de qué otro lote sale lo que falta."
            )
        coste, coste_sin_iva = _coste_de_filas(filas, inventario)
        for f in filas:
            inventario.salida_repartida(f["ingrediente"], f["reparto"], "elaboración")
        return inventario.elaboraciones.nueva_tanda(
            nombre_receta, raciones, coste / raciones, fecha_caducidad, fecha_preparacion,
            coste_por_racion_sin_iva=coste_sin_iva / raciones,
        )

    # ---------- Elaboraciones BASE (sofritos, fondos, salsas, masas...) ----------

    def previsualizar_base(
        self, nombre_base: str, cantidad: float, inventario: Inventario,
        elecciones: Optional[dict[str, list[int]]] = None,
    ) -> list[dict]:
        """Qué ingredientes (y de qué lotes) se gastarían al preparar `cantidad` de una elaboración base."""
        producto = inventario.buscar_producto(nombre_base)
        if producto is None or not producto.es_base():
            raise ValueError(f"'{nombre_base}' no es una elaboración base.")
        return self.filas_necesidades(producto.ingredientes_para(cantidad), inventario, elecciones)

    def preparar_base(
        self, nombre_base: str, cantidad_prevista: float, cantidad_obtenida: float, inventario: Inventario,
        elecciones: Optional[dict[str, list[int]]] = None, fecha_caducidad: Optional[date] = None,
        fecha_preparacion: Optional[date] = None,
    ):
        """
        Prepara una elaboración base (un sofrito, un fondo...):
        1. Saca de los lotes elegidos los ingredientes que pide la fórmula
           para `cantidad_prevista` (motivo "elaboración").
        2. Mete en el inventario lo que salió DE VERDAD (`cantidad_obtenida`)
           como un lote nuevo de la base, con su caducidad y su coste real
           (lo que costaron los ingredientes / lo obtenido).
        3. Apunta la preparación (prevista, obtenida, diferencia y coste).
        Comprueba todo antes de tocar nada. Devuelve el registro creado.
        """
        if cantidad_prevista <= 0:
            raise ValueError("La cantidad a preparar debe ser más de 0.")
        if cantidad_obtenida is None or cantidad_obtenida <= 0:
            raise ValueError("Indica cuánto ha salido de verdad (más de 0).")
        producto = inventario.buscar_producto(nombre_base)
        filas = self.previsualizar_base(nombre_base, cantidad_prevista, inventario, elecciones)
        faltan = [f"{f['ingrediente']} ({f['faltante']:g} {f['unidad']})" if f["existe"] else f"{f['ingrediente']} (no existe)"
                  for f in filas if f["faltante"] > 1e-9 or not f["existe"]]
        if faltan:
            raise ValueError("No hay ingredientes suficientes. Falta: " + ", ".join(faltan))
        pendientes = [f["ingrediente"] for f in filas if f["sin_asignar"] > 1e-9]
        if pendientes:
            raise ValueError(
                "Los lotes elegidos no cubren lo que hace falta de: " + ", ".join(pendientes)
                + ". Elige de qué otro lote sale lo que falta."
            )
        coste, coste_sin_iva = _coste_de_filas(filas, inventario)
        for f in filas:
            inventario.salida_repartida(f["ingrediente"], f["reparto"], "elaboración")
        fecha_preparacion = fecha_preparacion or date.today()
        if fecha_caducidad is None:
            fecha_caducidad = producto.caducidad_propuesta(fecha_preparacion)
        # El lote guarda lo pagado (con IVA) y, como "IVA", la parte de IVA que
        # llevaban sus ingredientes: así se puede separar igual que en una compra.
        iva_efectivo = (coste / coste_sin_iva - 1) * 100 if coste_sin_iva > 0 else 0.0
        lote = inventario.entrada_stock(
            nombre_base, cantidad_obtenida, round(coste / cantidad_obtenida, 6), "Elaboración propia",
            fecha_caducidad, motivo="elaboración", iva=round(iva_efectivo, 6),
        )
        registro = PreparacionBase(
            nombre_base, producto.unidad, cantidad_prevista, cantidad_obtenida, coste,
            lote.id if lote else None, fecha_preparacion,
        )
        inventario.elaboraciones.preparaciones_base.append(registro)
        return registro

    # ---------- Completar un servicio ----------

    def previsualizar_consumo(
        self, servicio: Servicio, inventario: Inventario, elecciones: Optional[dict[str, list[int]]] = None,
        plan_elaboraciones: Optional[dict[str, list[int]]] = None,
    ) -> Optional[list[dict]]:
        """
        Calcula, SIN tocar nada todavía, qué se descontaría del inventario
        al completar este servicio. Devuelve None si el menú del servicio
        no existe en el recetario.

        Las raciones que salen de elaboraciones ya preparadas (ver
        plan_elaboraciones) no gastan ingredientes: solo se descuentan los
        ingredientes de las raciones restantes, y los consumibles.

        Devuelve las filas de filas_necesidades() (ver allí). Si en TOTAL no
        hay stock suficiente de algo, se descuenta todo lo que hay (se dejan
        los lotes a 0) en vez de no descontar nada: si el servicio se hizo,
        lo que había se gastó -- y lo que faltaba tuvo que salir de algún
        sitio que no estaba registrado.
        """
        if self.buscar_menu(servicio.menu) is None:
            return None
        plan = self.plan_elaboraciones(servicio, inventario, plan_elaboraciones)
        preparadas = {receta: p["raciones"] for receta, p in plan.items()}
        return self.filas_necesidades(self.necesidades_servicio(servicio, preparadas), inventario, elecciones)

    def completar_servicio(
        self, servicio: Servicio, inventario: Inventario, elecciones: Optional[dict[str, list[int]]] = None,
        plan_elaboraciones: Optional[dict[str, list[int]]] = None,
    ) -> Optional[list[dict]]:
        """
        Marca el servicio como completado y descuenta del inventario lo que
        se gastó (motivo "consumo", así cuenta en Métricas): las raciones de
        las elaboraciones elegidas (`plan_elaboraciones`) y los ingredientes
        del resto, de los lotes indicados en `elecciones` (ver
        previsualizar_consumo). Devuelve el mismo detalle que
        previsualizar_consumo(). Devuelve None si el menú no existe (en ese
        caso NO toca ni el servicio ni el inventario: decide quien llama).

        Lanza ValueError, sin tocar nada, si para algún ingrediente los
        lotes elegidos no cubren lo que hace falta y hay otros lotes con
        los que completarlo: hay que elegirlos primero.

        Vive aquí (y no en main.py ni en app.py) para que la consola y la
        interfaz gráfica usen EXACTAMENTE la misma lógica.
        """
        if servicio.estado in ("completado", "cancelado"):
            # Sin esto, completar dos veces el mismo servicio descontaría
            # el stock dos veces.
            raise ValueError(f"El servicio #{servicio.id} ya está {servicio.estado}.")

        filas = self.previsualizar_consumo(servicio, inventario, elecciones, plan_elaboraciones)
        if filas is None:
            return None

        pendientes = [f["ingrediente"] for f in filas if f["sin_asignar"] > 1e-9]
        if pendientes:
            raise ValueError(
                "Los lotes elegidos no cubren lo que hace falta de: " + ", ".join(pendientes)
                + ". Elige de qué otro lote sale lo que falta."
            )

        plan = self.plan_elaboraciones(servicio, inventario, plan_elaboraciones)
        for p in plan.values():
            if p["reparto"]:
                inventario.elaboraciones.usar(p["reparto"], servicio.id)
        for fila in filas:
            if fila["reparto"]:
                inventario.salida_repartida(fila["ingrediente"], fila["reparto"], "consumo", servicio.id)
        servicio.menu_completado = self.buscar_menu(servicio.menu).foto()
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

        necesarios = menu.calcular_necesidades_totales(servicio.comensales)

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
