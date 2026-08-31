"""
Módulo: inventario.py
----------------------
Gestiona el inventario de un restaurante: productos, categorías, stock,
proveedores, precios y fechas de caducidad.

Conceptos de Python nuevos que usamos aquí:
- Clases y objetos (POO): __init__, self, métodos, __str__
- El módulo `datetime` para trabajar con fechas
- `typing.Optional` para indicar que un dato puede ser None
"""

from datetime import date
from typing import Optional


def _es_numero(texto: str) -> bool:
    """True si `texto` se puede interpretar como un número (ej: '123', '45.6')."""
    try:
        float(texto)
        return True
    except ValueError:
        return False


# Factor por el que multiplicar una cantidad para pasar de la unidad de la
# IZQUIERDA a la de la DERECHA. Ej: 2 kg -> gramos = 2 * 1000 = 2000 g.
# Vive aquí (no en main.py) porque tanto la consola como cualquier otra
# interfaz que construyamos (como la gráfica) necesitan la MISMA tabla --
# una sola fuente de verdad, en vez de dos copias que podrían desincronizarse.
FACTORES_CONVERSION = {
    ("kg", "g"): 1000,
    ("g", "kg"): 1 / 1000,
    ("litros", "ml"): 1000,
    ("ml", "litros"): 1 / 1000,
}


class MovimientoStock:
    """
    Registra UN movimiento de stock (una entrada o una salida) para poder
    consultar el historial más adelante: cuánto se ha consumido, cuánto
    se ha desperdiciado, cuánto se ha gastado...

    Guardamos `categoria` y `precio_unitario` como una FOTO del momento
    del movimiento, no como una referencia al Producto en directo -- si
    mañana cambias el precio o la categoría de un producto, los
    movimientos ya registrados no deben cambiar de significado con
    efecto retroactivo (igual que una factura antigua no cambia de
    precio porque hoy el proveedor suba tarifas).
    """

    MOTIVOS_SALIDA = ("consumo", "desperdicio", "otro")

    def __init__(
        self,
        producto_nombre: str,
        categoria: str,
        tipo: str,
        cantidad: float,
        unidad: str,
        precio_unitario: float,
        fecha: Optional[date] = None,
        motivo: Optional[str] = None,
    ):
        if tipo not in ("entrada", "salida"):
            raise ValueError("tipo debe ser 'entrada' o 'salida'")
        if tipo == "salida" and motivo not in self.MOTIVOS_SALIDA:
            raise ValueError(f"motivo debe ser uno de: {', '.join(self.MOTIVOS_SALIDA)}")

        self.producto_nombre = producto_nombre
        self.categoria = categoria
        self.tipo = tipo
        self.cantidad = cantidad
        self.unidad = unidad
        self.precio_unitario = precio_unitario
        self.fecha = fecha or date.today()
        self.motivo = motivo if tipo == "salida" else None

    def valor(self) -> float:
        """Valor económico de este movimiento (cantidad x precio en ese momento)."""
        return round(self.cantidad * self.precio_unitario, 2)

    def __str__(self) -> str:
        flecha = "➕" if self.tipo == "entrada" else "➖"
        extra = f" ({self.motivo})" if self.motivo else ""
        return f"{self.fecha.strftime('%d/%m/%Y')} {flecha} {self.cantidad} {self.unidad} {self.producto_nombre}{extra}"

    def to_dict(self) -> dict:
        return {
            "producto_nombre": self.producto_nombre,
            "categoria": self.categoria,
            "tipo": self.tipo,
            "cantidad": self.cantidad,
            "unidad": self.unidad,
            "precio_unitario": self.precio_unitario,
            "fecha": self.fecha.isoformat(),
            "motivo": self.motivo,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "MovimientoStock":
        return cls(
            producto_nombre=datos["producto_nombre"],
            categoria=datos["categoria"],
            tipo=datos["tipo"],
            cantidad=datos["cantidad"],
            unidad=datos["unidad"],
            precio_unitario=datos["precio_unitario"],
            fecha=date.fromisoformat(datos["fecha"]),
            motivo=datos.get("motivo"),
        )


class Producto:
    """
    Representa UN producto del inventario (ej: "Harina de trigo").

    Una CLASE es un molde. Cada vez que escribimos Producto(...) creamos
    un OBJETO nuevo (una instancia) con sus propios datos.
    """

    # Igual que ESTADOS_VALIDOS en Servicio: un conjunto CERRADO de valores
    # permitidos, para no acabar con "Kg", "kilos", "KILOGRAMOS"... todos
    # distintos entre sí aunque signifiquen lo mismo.
    UNIDADES_VALIDAS = ("kg", "g", "litros", "ml", "unidades")

    def __init__(
        self,
        nombre: str,
        categoria: str,
        stock: float,
        unidad: str,
        precio_unitario: float,
        proveedor: str,
        stock_minimo: float = 0,
        fecha_caducidad: Optional[date] = None,
    ):
        # __init__ es el "constructor": se ejecuta automáticamente
        # al crear un Producto nuevo. `self` es el propio objeto que
        # se está creando: guardamos cada dato dentro de él.

        # Igual que hicimos con `comensales` en Servicio: esta es una regla
        # de negocio real, no una comodidad de la consola, así que vive
        # aquí y se aplica sin importar de dónde vengan los datos.
        if not categoria.strip() or _es_numero(categoria):
            raise ValueError("La categoría debe ser texto descriptivo, no puede estar vacía ni ser un número")
        if not proveedor.strip() or _es_numero(proveedor):
            raise ValueError("El proveedor debe ser texto descriptivo, no puede estar vacío ni ser un número")
        if unidad not in Producto.UNIDADES_VALIDAS:
            raise ValueError(f"Unidad no válida: '{unidad}'. Debe ser una de: {', '.join(Producto.UNIDADES_VALIDAS)}")

        self.nombre = nombre
        self.categoria = categoria
        self.stock = stock
        self.unidad = unidad  # kg, litros, unidades, etc.
        self.precio_unitario = precio_unitario
        self.proveedor = proveedor
        self.stock_minimo = stock_minimo
        self.fecha_caducidad = fecha_caducidad

    def valor_total(self) -> float:
        """Valor económico del stock actual de este producto."""
        return round(self.stock * self.precio_unitario, 2)

    def esta_bajo_minimo(self) -> bool:
        """True si el stock actual está por debajo del mínimo definido."""
        return self.stock < self.stock_minimo

    def dias_para_caducar(self) -> Optional[int]:
        """Días que quedan para caducar. None si no tiene fecha de caducidad."""
        if self.fecha_caducidad is None:
            return None
        return (self.fecha_caducidad - date.today()).days

    def esta_caducado(self) -> bool:
        """True si la fecha de caducidad ya pasó. False si no tiene fecha o no ha caducado."""
        dias = self.dias_para_caducar()
        if dias is None:
            return False  # sin fecha de caducidad no puede estar caducado
        return dias < 0

    def __str__(self) -> str:
        # __str__ define qué se muestra al hacer print(producto)
        return (
            f"{self.nombre} | {self.categoria} | "
            f"Stock: {self.stock} {self.unidad} (mínimo: {self.stock_minimo}) | "
            f"Precio: {self.precio_unitario}€/{self.unidad} | "
            f"Proveedor: {self.proveedor}"
        )

    def to_dict(self) -> dict:
        """
        Convierte el objeto a un diccionario "plano" (solo texto, números,
        listas...) para poder guardarlo en JSON. JSON no sabe qué es una
        fecha, así que la convertimos a texto con .isoformat() (ej: "2026-09-01").
        """
        return {
            "nombre": self.nombre,
            "categoria": self.categoria,
            "stock": self.stock,
            "unidad": self.unidad,
            "precio_unitario": self.precio_unitario,
            "proveedor": self.proveedor,
            "stock_minimo": self.stock_minimo,
            "fecha_caducidad": self.fecha_caducidad.isoformat() if self.fecha_caducidad else None,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Producto":
        """
        Reconstruye un Producto a partir de un diccionario (el camino inverso
        de to_dict). Es un @classmethod: en vez de operar sobre un objeto ya
        creado (como los métodos normales, con `self`), CREA el objeto nuevo
        él mismo y lo devuelve — por eso recibe `cls` (la propia clase) en
        vez de `self`.
        """
        fecha = date.fromisoformat(datos["fecha_caducidad"]) if datos["fecha_caducidad"] else None
        return cls(
            nombre=datos["nombre"],
            categoria=datos["categoria"],
            stock=datos["stock"],
            unidad=datos["unidad"],
            precio_unitario=datos["precio_unitario"],
            proveedor=datos["proveedor"],
            stock_minimo=datos["stock_minimo"],
            fecha_caducidad=fecha,
        )


class Inventario:
    """Gestiona una colección de productos: altas, bajas, consultas..."""

    def __init__(self):
        # Diccionario para acceder rápido a un producto por su nombre.
        # Clave = nombre del producto, Valor = objeto Producto
        self.productos: dict[str, Producto] = {}
        # Registro de TODOS los movimientos de stock, para poder calcular
        # métricas más adelante (consumo, desperdicio, gasto...).
        self.historial: list[MovimientoStock] = []

    def agregar_producto(self, producto: Producto) -> None:
        if producto.nombre in self.productos:
            print(f"⚠️  Ya existe '{producto.nombre}'. Usa actualizar_stock() para modificarlo.")
            return
        self.productos[producto.nombre] = producto
        print(f"✅ Producto añadido: {producto.nombre}")

    def eliminar_producto(self, nombre: str) -> None:
        if nombre in self.productos:
            del self.productos[nombre]
            print(f"🗑️  Producto eliminado: {nombre}")
        else:
            print(f"❌ No existe el producto '{nombre}'.")

    def actualizar_stock(
        self,
        nombre: str,
        cantidad: float,
        sumar: bool = True,
        nueva_fecha_caducidad: Optional[date] = None,
        motivo_salida: Optional[str] = None,
    ) -> bool:
        """
        Modifica el stock de un producto.
        sumar=True  -> añade cantidad (ej: entra mercancía del proveedor)
        sumar=False -> resta cantidad (ej: se consume en un servicio)

        nueva_fecha_caducidad: si se indica (y sumar=True), reemplaza la
        fecha de caducidad guardada por la del lote nuevo que acaba de
        entrar. Se ignora si sumar=False.

        motivo_salida: OBLIGATORIO si sumar=False. Debe ser uno de
        MovimientoStock.MOTIVOS_SALIDA ("consumo", "desperdicio", "otro")
        -- es lo que permite luego distinguir cuánto se ha consumido de
        verdad frente a cuánto se ha tirado.

        Devuelve True si el cambio se aplicó, False si se rechazó (producto
        inexistente, motivo no válido, o stock insuficiente) -- así quien
        llama a este método puede saberlo con certeza, sin tener que
        deducirlo comparando el stock antes/después.
        """
        producto = self.productos.get(nombre)
        if producto is None:
            print(f"❌ No existe el producto '{nombre}'.")
            return False

        if not sumar and motivo_salida not in MovimientoStock.MOTIVOS_SALIDA:
            print(f"❌ Motivo no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_SALIDA)}")
            return False

        if not sumar and cantidad > producto.stock:
            print(
                f"❌ Stock insuficiente de '{nombre}': hay {producto.stock} {producto.unidad}, "
                f"intentas restar {cantidad}. El stock nunca puede quedar en negativo."
            )
            return False

        producto.stock += cantidad if sumar else -cantidad
        print(f"📦 Stock actualizado: {nombre} -> {producto.stock} {producto.unidad}")

        if sumar and nueva_fecha_caducidad is not None:
            producto.fecha_caducidad = nueva_fecha_caducidad
            print(f"📅 Fecha de caducidad renovada: {nueva_fecha_caducidad.strftime('%d/%m/%Y')}")

        # Se registra SIEMPRE, tanto entradas como salidas -- por eso el
        # historial nunca puede desincronizarse: es imposible cambiar el
        # stock sin dejar constancia de por qué.
        self.historial.append(MovimientoStock(
            producto_nombre=producto.nombre,
            categoria=producto.categoria,
            tipo="entrada" if sumar else "salida",
            cantidad=cantidad,
            unidad=producto.unidad,
            precio_unitario=producto.precio_unitario,
            motivo=motivo_salida if not sumar else None,
        ))
        return True

    def editar_producto(
        self,
        nombre_actual: str,
        nuevo_nombre: Optional[str] = None,
        categoria: Optional[str] = None,
        stock: Optional[float] = None,
        precio_unitario: Optional[float] = None,
        proveedor: Optional[str] = None,
        stock_minimo: Optional[float] = None,
        fecha_caducidad: Optional[date] = None,
        borrar_fecha_caducidad: bool = False,
    ) -> bool:
        """
        Corrige directamente los datos de un producto YA existente -- a
        diferencia de actualizar_stock() (que solo SUMA/RESTA cantidades
        y solo toca la fecha de caducidad al entrar mercancía nueva),
        aquí se puede corregir cualquier campo, incluido el propio nombre.

        Cualquier parámetro que dejes en None (el valor por defecto) NO
        se modifica -- así puedes cambiar solo el precio sin tener que
        repetir todos los demás datos.

        La fecha de caducidad es un caso especial: None podría significar
        tanto "no la toques" como "bórrala" (un producto SIN fecha es un
        estado válido), así que hace falta un parámetro aparte para
        distinguirlo. borrar_fecha_caducidad=True tiene prioridad sobre
        cualquier valor que pases en fecha_caducidad.

        Devuelve True si el cambio se aplicó, False si se abortó (por
        ejemplo, si el nuevo nombre ya lo usa otro producto) -- así quien
        llame a este método puede saber si debe encadenar otras acciones
        (como actualizar recetas que usen el nombre antiguo).
        """
        producto = self.productos.get(nombre_actual)
        if producto is None:
            print(f"❌ No existe el producto '{nombre_actual}'.")
            return False

        categoria_final = categoria if categoria is not None else producto.categoria
        proveedor_final = proveedor if proveedor is not None else producto.proveedor
        # Misma regla que en Producto.__init__: no confiamos en que quien
        # llama a este método ya haya validado los datos por su cuenta.
        if not categoria_final.strip() or _es_numero(categoria_final):
            raise ValueError("La categoría debe ser texto descriptivo, no puede estar vacía ni ser un número")
        if not proveedor_final.strip() or _es_numero(proveedor_final):
            raise ValueError("El proveedor debe ser texto descriptivo, no puede estar vacío ni ser un número")

        if nuevo_nombre is not None and nuevo_nombre != nombre_actual:
            if nuevo_nombre in self.productos:
                print(f"❌ Ya existe otro producto llamado '{nuevo_nombre}'.")
                return False
            # El nombre es la CLAVE del diccionario -- cambiarlo exige
            # mover la entrada entera, no solo el atributo .nombre.
            del self.productos[nombre_actual]
            producto.nombre = nuevo_nombre
            self.productos[nuevo_nombre] = producto

        producto.categoria = categoria_final
        producto.proveedor = proveedor_final
        if stock is not None:
            producto.stock = stock
        if precio_unitario is not None:
            producto.precio_unitario = precio_unitario
        if stock_minimo is not None:
            producto.stock_minimo = stock_minimo

        if borrar_fecha_caducidad:
            producto.fecha_caducidad = None
        elif fecha_caducidad is not None:
            producto.fecha_caducidad = fecha_caducidad

        print(f"✏️  Producto actualizado: {producto}")
        return True

    def buscar_producto(self, nombre: str) -> Optional[Producto]:
        return self.productos.get(nombre)

    def listar_por_categoria(self, categoria: str) -> list[Producto]:
        return [p for p in self.productos.values() if p.categoria == categoria]

    def productos_por_proveedor(self, proveedor: str) -> list[Producto]:
        """Todos los productos que vienen de un proveedor concreto."""
        return [p for p in self.productos.values() if p.proveedor == proveedor]

    def productos_bajo_minimo(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.esta_bajo_minimo()]

    def productos_proximos_a_caducar(self, dias: int = 7) -> list[Producto]:
        resultado = []
        for p in self.productos.values():
            restantes = p.dias_para_caducar()
            # p.stock > 0: si no queda nada físicamente, no tiene sentido
            # avisar de que "va a caducar" — no hay nada que se eche a perder.
            if restantes is not None and 0 <= restantes <= dias and p.stock > 0:
                resultado.append(p)
        return resultado

    def valor_total_inventario(self) -> float:
        return round(sum(p.valor_total() for p in self.productos.values()), 2)

    def listar_todos(self) -> None:
        if not self.productos:
            print("El inventario está vacío.")
            return
        for producto in self.productos.values():
            print(producto)

    def to_dict(self) -> dict:
        """El inventario se convierte en una LISTA de productos y otra de movimientos, ya convertidos."""
        return {
            "productos": [p.to_dict() for p in self.productos.values()],
            "historial": [m.to_dict() for m in self.historial],
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Inventario":
        inventario = cls()
        for datos_producto in datos["productos"]:
            producto = Producto.from_dict(datos_producto)
            inventario.productos[producto.nombre] = producto
        # .get(..., []): compatibilidad con sesiones guardadas ANTES de que
        # existiera el historial -- si la clave no está, empezamos vacío en
        # vez de fallar con un KeyError.
        for datos_mov in datos.get("historial", []):
            inventario.historial.append(MovimientoStock.from_dict(datos_mov))
        return inventario


if __name__ == "__main__":
    # --- DEMO: esto solo se ejecuta si corres ESTE archivo directamente ---
    inventario = Inventario()

    inventario.agregar_producto(Producto(
        nombre="Harina de trigo",
        categoria="Panadería",
        stock=5,
        unidad="kg",
        precio_unitario=1.2,
        proveedor="Harinas del Sur",
        stock_minimo=10,
    ))

    inventario.agregar_producto(Producto(
        nombre="Aceite de oliva",
        categoria="Aceites",
        stock=20,
        unidad="litros",
        precio_unitario=4.5,
        proveedor="Oleícola Andaluza",
        stock_minimo=5,
        fecha_caducidad=date(2026, 8, 25),
    ))

    print("\n--- Inventario completo ---")
    inventario.listar_todos()

    print("\n--- Productos bajo mínimo ---")
    for p in inventario.productos_bajo_minimo():
        print(p)

    print("\n--- Próximos a caducar (7 días) ---")
    for p in inventario.productos_proximos_a_caducar():
        print(p)

    print(f"\n💰 Valor total del inventario: {inventario.valor_total_inventario()} €")

    # --- EJERCICIO 1: añadir un producto nuevo ---
    inventario.agregar_producto(Producto(
        nombre="Tomate",
        categoria="Verduras",
        stock=8,
        unidad="kg",
        precio_unitario=2.1,
        proveedor="Huerta Local",
        stock_minimo=5,
        fecha_caducidad=date(2026, 8, 20),  # fecha ya pasada, para probar esta_caducado()
    ))

    # --- EJERCICIO 2: productos_por_proveedor() ---
    print("\n--- Productos de 'Harinas del Sur' ---")
    for p in inventario.productos_por_proveedor("Harinas del Sur"):
        print(p)

    # --- EJERCICIO 3: esta_caducado() ---
    print("\n--- ¿Qué productos están caducados? ---")
    for p in inventario.productos.values():
        print(f"{p.nombre}: {'CADUCADO ❌' if p.esta_caducado() else 'OK ✅'}")
