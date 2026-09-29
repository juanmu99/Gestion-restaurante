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

# Unidades en las que se puede pesar algo. Los productos con merma y sus
# derivados se miden siempre en peso (o en unidades con un peso por unidad),
# porque el rendimiento se calcula comparando pesos.
UNIDADES_PESO = ("kg", "g")


def convertir(cantidad: float, desde: str, hasta: str) -> float:
    """Convierte una cantidad entre dos unidades compatibles (kg <-> g, litros <-> ml)."""
    if desde == hasta:
        return cantidad
    factor = FACTORES_CONVERSION.get((desde, hasta))
    if factor is None:
        raise ValueError(f"No se puede convertir de '{desde}' a '{hasta}'.")
    return cantidad * factor


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

    # Motivos que una persona puede elegir a mano al sacar stock.
    MOTIVOS_SALIDA = ("consumo", "desperdicio", "otro")
    # "limpieza" NO se elige a mano: solo lo usa Inventario.limpiar_producto().
    # Marca tanto la salida del producto en bruto como la entrada del limpio
    # y sus derivados, para que no se confundan con consumo ni con compras.
    MOTIVOS_SALIDA_VALIDOS = MOTIVOS_SALIDA + ("limpieza",)
    MOTIVOS_ENTRADA = ("compra", "limpieza")

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
        if tipo == "salida" and motivo not in self.MOTIVOS_SALIDA_VALIDOS:
            raise ValueError(f"motivo debe ser uno de: {', '.join(self.MOTIVOS_SALIDA_VALIDOS)}")
        if tipo == "entrada":
            # Las sesiones guardadas antes de existir las limpiezas no tienen
            # motivo en las entradas: entonces toda entrada era una compra.
            motivo = motivo or "compra"
            if motivo not in self.MOTIVOS_ENTRADA:
                raise ValueError(f"motivo de entrada debe ser uno de: {', '.join(self.MOTIVOS_ENTRADA)}")

        self.producto_nombre = producto_nombre
        self.categoria = categoria
        self.tipo = tipo
        self.cantidad = cantidad
        self.unidad = unidad
        self.precio_unitario = precio_unitario
        self.fecha = fecha or date.today()
        self.motivo = motivo

    def es_compra(self) -> bool:
        """True solo para entradas que son dinero gastado (no para lo que sale de una limpieza)."""
        return self.tipo == "entrada" and self.motivo == "compra"

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
        tiene_merma: bool = False,
        peso_unitario: Optional[float] = None,
        origen: Optional[str] = None,
        es_subproducto: bool = False,
    ):
        """
        Campos relacionados con la merma (todos opcionales):

        - tiene_merma: el producto se limpia o despieza antes de usarse
          (una pata de cerdo, un pescado entero...). Solo de estos productos
          se pueden obtener derivados.
        - peso_unitario: peso EN BRUTO de cada unidad, en kg. Solo hace falta
          si el producto con merma se compra por unidades ("3 patas"),
          porque el rendimiento se calcula comparando pesos.
        - origen: para el producto LIMPIO principal (ej: "Carne de cerdo
          limpia"), el nombre del producto en bruto del que se obtiene. Es
          lo que permite a la lista de la compra pedir el bruto.
        - es_subproducto: lo que se aprovecha de la merma (huesos para un
          fondo, grasa...). Su coste es 0: todo el coste lo carga el limpio.
        """
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
        _validar_merma(unidad, tiene_merma, peso_unitario)
        if (origen or es_subproducto) and unidad not in UNIDADES_PESO:
            raise ValueError("Un producto obtenido de una limpieza debe medirse en kg o g.")

        self.nombre = nombre
        self.categoria = categoria
        self.stock = stock
        self.unidad = unidad  # kg, litros, unidades, etc.
        self.precio_unitario = precio_unitario
        self.proveedor = proveedor
        self.stock_minimo = stock_minimo
        self.fecha_caducidad = fecha_caducidad
        self.tiene_merma = tiene_merma
        self.peso_unitario = peso_unitario if unidad == "unidades" else None
        self.origen = origen
        self.es_subproducto = es_subproducto

    def peso_kg(self, cantidad: float) -> float:
        """Cuántos kg pesa `cantidad` de este producto (en su propia unidad)."""
        if self.unidad == "unidades":
            if not self.peso_unitario:
                raise ValueError(f"'{self.nombre}' no tiene peso por unidad definido.")
            return cantidad * self.peso_unitario
        return convertir(cantidad, self.unidad, "kg")

    def tipo_descripcion(self) -> str:
        """Etiqueta corta para listados: qué papel tiene este producto respecto a la merma."""
        if self.es_subproducto:
            return "Subproducto"
        if self.origen:
            return f"Limpio (de {self.origen})"
        if self.tiene_merma:
            return "Con merma"
        return ""

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
        texto = (
            f"{self.nombre} | {self.categoria} | "
            f"Stock: {self.stock} {self.unidad} (mínimo: {self.stock_minimo}) | "
            f"Precio: {self.precio_unitario}€/{self.unidad} | "
            f"Proveedor: {self.proveedor}"
        )
        if self.tiene_merma:
            texto += " | Con merma"
            if self.peso_unitario:
                texto += f" ({self.peso_unitario} kg/unidad en bruto)"
        if self.origen:
            texto += f" | Se obtiene de: {self.origen}"
        if self.es_subproducto:
            texto += " | Subproducto"
        return texto

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
            "tiene_merma": self.tiene_merma,
            "peso_unitario": self.peso_unitario,
            "origen": self.origen,
            "es_subproducto": self.es_subproducto,
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
            # .get(): las sesiones guardadas antes de existir la merma no
            # tienen estos campos -- se cargan como productos normales.
            tiene_merma=datos.get("tiene_merma", False),
            peso_unitario=datos.get("peso_unitario"),
            origen=datos.get("origen"),
            es_subproducto=datos.get("es_subproducto", False),
        )


def _validar_merma(unidad: str, tiene_merma: bool, peso_unitario: Optional[float]) -> None:
    """Reglas de un producto con merma (compartidas por el alta y la edición)."""
    if not tiene_merma:
        return
    if unidad not in UNIDADES_PESO + ("unidades",):
        raise ValueError("Un producto con merma debe medirse en kg, g o unidades.")
    if unidad == "unidades" and (peso_unitario is None or peso_unitario <= 0):
        raise ValueError("Un producto con merma que se compra por unidades necesita el peso en bruto de cada unidad.")


class Limpieza:
    """
    Registro de UNA limpieza o despiece: qué producto en bruto se limpió,
    cuánto pesaba, cuánto producto limpio salió, qué derivados se
    aprovecharon y cuánta merma quedó.

    Es la base del rendimiento medio de cada producto y queda en el
    historial para siempre. Todos los pesos se guardan en kg, sea cual sea
    la unidad de cada producto, para poder comparar y promediar limpiezas.
    """

    def __init__(
        self,
        producto_origen: str,
        cantidad_origen: float,
        unidad_origen: str,
        peso_bruto_kg: float,
        producto_limpio: str,
        peso_limpio_kg: float,
        derivados_kg: dict[str, float],
        coste: float,
        fecha: Optional[date] = None,
    ):
        self.producto_origen = producto_origen
        self.cantidad_origen = cantidad_origen  # en la unidad del producto (ej: 2 unidades)
        self.unidad_origen = unidad_origen
        self.peso_bruto_kg = peso_bruto_kg
        self.producto_limpio = producto_limpio
        self.peso_limpio_kg = peso_limpio_kg
        self.derivados_kg = derivados_kg
        self.coste = coste  # todo el coste del bruto; lo carga el producto limpio
        self.fecha = fecha or date.today()

    @property
    def merma_kg(self) -> float:
        """Lo que no se aprovechó: bruto - limpio - derivados. Se calcula, no se guarda."""
        return round(max(0.0, self.peso_bruto_kg - self.peso_limpio_kg - sum(self.derivados_kg.values())), 3)

    @property
    def rendimiento(self) -> float:
        """Fracción del bruto que acaba como producto limpio (0.64 = 64 %)."""
        return self.peso_limpio_kg / self.peso_bruto_kg if self.peso_bruto_kg else 0.0

    def __str__(self) -> str:
        derivados = ", ".join(f"{n} {round(kg, 3)} kg" for n, kg in self.derivados_kg.items()) or "ninguno"
        return (
            f"{self.fecha.strftime('%d/%m/%Y')} | {self.cantidad_origen} {self.unidad_origen} de {self.producto_origen} "
            f"({round(self.peso_bruto_kg, 3)} kg bruto) -> {round(self.peso_limpio_kg, 3)} kg de {self.producto_limpio} "
            f"| Derivados: {derivados} | Merma: {self.merma_kg} kg | Rendimiento: {self.rendimiento:.0%}"
        )

    def to_dict(self) -> dict:
        return {
            "producto_origen": self.producto_origen,
            "cantidad_origen": self.cantidad_origen,
            "unidad_origen": self.unidad_origen,
            "peso_bruto_kg": self.peso_bruto_kg,
            "producto_limpio": self.producto_limpio,
            "peso_limpio_kg": self.peso_limpio_kg,
            "derivados_kg": self.derivados_kg,
            "coste": self.coste,
            "fecha": self.fecha.isoformat(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Limpieza":
        return cls(
            producto_origen=datos["producto_origen"],
            cantidad_origen=datos["cantidad_origen"],
            unidad_origen=datos["unidad_origen"],
            peso_bruto_kg=datos["peso_bruto_kg"],
            producto_limpio=datos["producto_limpio"],
            peso_limpio_kg=datos["peso_limpio_kg"],
            derivados_kg=datos["derivados_kg"],
            coste=datos["coste"],
            fecha=date.fromisoformat(datos["fecha"]),
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
        # Registro de todas las limpiezas/despieces (base del rendimiento medio).
        self.limpiezas: list[Limpieza] = []

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
        motivo_entrada: str = "compra",
        peso_unitario_lote: Optional[float] = None,
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

        motivo_entrada: "compra" (por defecto) o "limpieza". Solo las
        compras cuentan como dinero gastado en Métricas.

        peso_unitario_lote: para productos con merma que se compran por
        unidades, el peso en bruto (kg) de cada unidad del lote que entra.
        Se mezcla con el peso de las unidades que ya había (media
        ponderada), porque no todas las patas pesan lo mismo.

        Devuelve True si el cambio se aplicó, False si se rechazó (producto
        inexistente, motivo no válido, o stock insuficiente) -- así quien
        llama a este método puede saberlo con certeza, sin tener que
        deducirlo comparando el stock antes/después.
        """
        producto = self.productos.get(nombre)
        if producto is None:
            print(f"❌ No existe el producto '{nombre}'.")
            return False

        if cantidad <= 0:
            print("❌ La cantidad debe ser mayor que 0.")
            return False

        if not sumar and motivo_salida not in MovimientoStock.MOTIVOS_SALIDA_VALIDOS:
            print(f"❌ Motivo no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_SALIDA)}")
            return False

        if sumar and motivo_entrada not in MovimientoStock.MOTIVOS_ENTRADA:
            print(f"❌ Motivo de entrada no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_ENTRADA)}")
            return False

        # Pequeño margen (1e-9) para que los decimales de coma flotante no
        # impidan sacar exactamente todo lo que hay (ej: 0.30000000000000004).
        if not sumar and cantidad > producto.stock + 1e-9:
            print(
                f"❌ Stock insuficiente de '{nombre}': hay {producto.stock} {producto.unidad}, "
                f"intentas restar {cantidad}. El stock nunca puede quedar en negativo."
            )
            return False

        if sumar and peso_unitario_lote is not None and producto.unidad == "unidades":
            if peso_unitario_lote <= 0:
                print("❌ El peso por unidad debe ser mayor que 0.")
                return False
            if producto.stock > 0 and producto.peso_unitario:
                total_kg = producto.stock * producto.peso_unitario + cantidad * peso_unitario_lote
                producto.peso_unitario = round(total_kg / (producto.stock + cantidad), 4)
            else:
                producto.peso_unitario = peso_unitario_lote
            print(f"⚖️  Peso medio por unidad: {producto.peso_unitario} kg")

        producto.stock = round(producto.stock + (cantidad if sumar else -cantidad), 6)
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
            motivo=motivo_salida if not sumar else motivo_entrada,
        ))
        return True

    # ---------- Limpieza / despiece ----------

    def limpiar_producto(
        self,
        nombre_origen: str,
        cantidad: float,
        producto_limpio: str,
        peso_limpio: float,
        derivados: Optional[dict[str, float]] = None,
        unidad_peso: str = "kg",
        caducidades: Optional[dict[str, date]] = None,
    ) -> Limpieza:
        """
        Limpia o despieza `cantidad` de un producto con merma.

        - Sale del inventario `cantidad` del producto en bruto (en su unidad:
          kg, g o unidades).
        - Entra `peso_limpio` del producto limpio, que carga con TODO el
          coste del bruto.
        - Entra cada derivado aprovechado de `derivados` ({nombre: peso}) a
          coste 0.
        - Lo que no se ha asignado a nada es merma, y queda registrado.

        Los pesos de salida se indican en `unidad_peso` ("kg" o "g"). Los
        productos de salida que no existan se crean solos. `caducidades`
        ({nombre: fecha}) es opcional, para cualquiera de los productos de
        salida.

        Lanza ValueError con un mensaje claro si algo no cuadra, ANTES de
        tocar nada: o se aplica la limpieza entera o no se aplica nada.
        """
        caducidades = caducidades or {}
        origen = self.productos.get(nombre_origen)
        if origen is None:
            raise ValueError(f"No existe el producto '{nombre_origen}'.")
        if not origen.tiene_merma:
            raise ValueError(
                f"'{nombre_origen}' no está marcado como producto con merma: no se puede limpiar "
                "ni obtener derivados de él. Márcalo en 'Editar producto' si debería."
            )
        if unidad_peso not in UNIDADES_PESO:
            raise ValueError("Los pesos del resultado deben indicarse en kg o g.")
        if cantidad <= 0:
            raise ValueError("La cantidad a limpiar debe ser mayor que 0.")
        if cantidad > origen.stock + 1e-9:
            raise ValueError(f"Solo hay {origen.stock} {origen.unidad} de '{nombre_origen}'.")

        producto_limpio = producto_limpio.strip()
        if not producto_limpio:
            raise ValueError("Indica el nombre del producto limpio.")
        if peso_limpio <= 0:
            raise ValueError("El peso del producto limpio debe ser mayor que 0.")

        derivados_limpios: dict[str, float] = {}
        for nombre, peso in (derivados or {}).items():
            nombre = nombre.strip()
            if not nombre or peso == 0:
                continue  # fila vacía: no es un derivado
            if peso < 0:
                raise ValueError(f"El peso de '{nombre}' no puede ser negativo.")
            if nombre in derivados_limpios:
                raise ValueError(f"'{nombre}' aparece dos veces entre los derivados.")
            derivados_limpios[nombre] = peso

        if producto_limpio == nombre_origen or nombre_origen in derivados_limpios:
            raise ValueError("Un producto no puede obtenerse de sí mismo.")
        if producto_limpio in derivados_limpios:
            raise ValueError(f"'{producto_limpio}' no puede ser a la vez el producto limpio y un derivado.")

        peso_bruto_kg = origen.peso_kg(cantidad)
        peso_limpio_kg = convertir(peso_limpio, unidad_peso, "kg")
        derivados_kg = {n: convertir(p, unidad_peso, "kg") for n, p in derivados_limpios.items()}
        total_kg = peso_limpio_kg + sum(derivados_kg.values())
        if total_kg > peso_bruto_kg + 1e-6:
            raise ValueError(
                f"El limpio más los derivados ({round(total_kg, 3)} kg) pesan más que el bruto "
                f"({round(peso_bruto_kg, 3)} kg). Revisa los pesos."
            )

        principal = self.productos.get(producto_limpio)
        if principal is not None:
            if principal.unidad not in UNIDADES_PESO:
                raise ValueError(f"'{producto_limpio}' ya existe y no se mide en kg o g.")
            if principal.es_subproducto:
                raise ValueError(f"'{producto_limpio}' está registrado como subproducto, no como producto limpio.")
            if principal.origen and principal.origen != nombre_origen:
                raise ValueError(f"'{producto_limpio}' ya se obtiene de '{principal.origen}'.")
        for nombre in derivados_kg:
            existente = self.productos.get(nombre)
            if existente is not None:
                if existente.unidad not in UNIDADES_PESO:
                    raise ValueError(f"'{nombre}' ya existe y no se mide en kg o g.")
                if existente.origen:
                    raise ValueError(
                        f"'{nombre}' es el producto limpio de '{existente.origen}', no puede ser un subproducto."
                    )

        # --- A partir de aquí todo está validado: se aplica la limpieza ---
        unidad_nueva = origen.unidad if origen.unidad in UNIDADES_PESO else "kg"
        coste = round(cantidad * origen.precio_unitario, 2)

        if principal is None:
            principal = Producto(
                producto_limpio, origen.categoria, 0, unidad_nueva, 0, "Elaboración propia", origen=nombre_origen
            )
            self.agregar_producto(principal)
        elif principal.origen is None:
            # Ya existía (quizá se compraba limpio): desde ahora se sabe que también sale de aquí.
            principal.origen = nombre_origen
        for nombre in derivados_kg:
            if nombre not in self.productos:
                self.agregar_producto(Producto(
                    nombre, origen.categoria, 0, unidad_nueva, 0, "Elaboración propia", es_subproducto=True
                ))

        self.actualizar_stock(nombre_origen, cantidad, sumar=False, motivo_salida="limpieza")

        # El limpio carga con todo el coste: su precio pasa a ser la media
        # ponderada entre lo que ya había y lo que acaba de salir.
        cantidad_limpio = round(convertir(peso_limpio_kg, "kg", principal.unidad), 6)
        principal.precio_unitario = round(
            (principal.stock * principal.precio_unitario + coste) / (principal.stock + cantidad_limpio), 4
        )
        self.actualizar_stock(
            producto_limpio, cantidad_limpio, sumar=True, motivo_entrada="limpieza",
            nueva_fecha_caducidad=caducidades.get(producto_limpio),
        )

        # Los derivados entran a coste 0 (si ya había stock con precio, se
        # abarata en proporción, igual que haría una media ponderada).
        for nombre, kg in derivados_kg.items():
            derivado = self.productos[nombre]
            cantidad_derivado = round(convertir(kg, "kg", derivado.unidad), 6)
            derivado.precio_unitario = round(
                derivado.stock * derivado.precio_unitario / (derivado.stock + cantidad_derivado), 4
            )
            self.actualizar_stock(
                nombre, cantidad_derivado, sumar=True, motivo_entrada="limpieza",
                nueva_fecha_caducidad=caducidades.get(nombre),
            )

        limpieza = Limpieza(
            producto_origen=nombre_origen,
            cantidad_origen=cantidad,
            unidad_origen=origen.unidad,
            peso_bruto_kg=round(peso_bruto_kg, 6),
            producto_limpio=producto_limpio,
            peso_limpio_kg=round(peso_limpio_kg, 6),
            derivados_kg={n: round(kg, 6) for n, kg in derivados_kg.items()},
            coste=coste,
        )
        self.limpiezas.append(limpieza)
        print(f"🔪 Limpieza registrada: {limpieza}")
        return limpieza

    def limpiezas_de(self, nombre_origen: str) -> list[Limpieza]:
        return [l for l in self.limpiezas if l.producto_origen == nombre_origen]

    def rendimiento_medio(self, nombre_origen: str) -> Optional[float]:
        """
        Rendimiento medio de un producto con merma según TODAS sus limpiezas
        registradas. None si todavía no se ha limpiado nunca.

        Se calcula como total limpio / total bruto (no como la media de los
        porcentajes), para que una pieza grande pese más que una pequeña.
        """
        limpiezas = self.limpiezas_de(nombre_origen)
        bruto = sum(l.peso_bruto_kg for l in limpiezas)
        if bruto <= 0:
            return None
        return sum(l.peso_limpio_kg for l in limpiezas) / bruto

    def producto_limpio_de(self, nombre_origen: str) -> Optional[str]:
        """El producto limpio que se obtiene habitualmente de este bruto (para rellenar formularios)."""
        for p in self.productos.values():
            if p.origen == nombre_origen:
                return p.nombre
        return None

    def derivados_habituales(self, nombre_origen: str) -> list[str]:
        """
        Todos los derivados que se han aprovechado alguna vez de este
        producto (los más recientes primero), para proponerlos la próxima vez.
        Solo los que siguen existiendo en el inventario.
        """
        nombres: list[str] = []
        for limpieza in reversed(self.limpiezas_de(nombre_origen)):
            for nombre in limpieza.derivados_kg:
                if nombre not in nombres and nombre in self.productos:
                    nombres.append(nombre)
        return nombres

    def productos_con_merma(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.tiene_merma]

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
        tiene_merma: Optional[bool] = None,
        peso_unitario: Optional[float] = None,
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
        merma_final = tiene_merma if tiene_merma is not None else producto.tiene_merma
        peso_final = peso_unitario if peso_unitario is not None else producto.peso_unitario
        _validar_merma(producto.unidad, merma_final, peso_final)

        if nuevo_nombre is not None and nuevo_nombre != nombre_actual:
            if nuevo_nombre in self.productos:
                print(f"❌ Ya existe otro producto llamado '{nuevo_nombre}'.")
                return False
            # El nombre es la CLAVE del diccionario -- cambiarlo exige
            # mover la entrada entera, no solo el atributo .nombre.
            del self.productos[nombre_actual]
            producto.nombre = nuevo_nombre
            self.productos[nuevo_nombre] = producto
            self._renombrar_referencias(nombre_actual, nuevo_nombre)

        producto.tiene_merma = merma_final
        if producto.unidad == "unidades":
            producto.peso_unitario = peso_final
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

    def _renombrar_referencias(self, antiguo: str, nuevo: str) -> None:
        """
        Al renombrar un producto, actualiza todo lo que lo nombra dentro del
        inventario: el origen de sus productos limpios, las limpiezas y los
        movimientos del historial. Sin esto, renombrar la pata de cerdo haría
        "desaparecer" su rendimiento medio y sus métricas anteriores.
        """
        for p in self.productos.values():
            if p.origen == antiguo:
                p.origen = nuevo
        for l in self.limpiezas:
            if l.producto_origen == antiguo:
                l.producto_origen = nuevo
            if l.producto_limpio == antiguo:
                l.producto_limpio = nuevo
            if antiguo in l.derivados_kg:
                l.derivados_kg = {(nuevo if n == antiguo else n): kg for n, kg in l.derivados_kg.items()}
        for m in self.historial:
            if m.producto_nombre == antiguo:
                m.producto_nombre = nuevo

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
            "limpiezas": [l.to_dict() for l in self.limpiezas],
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
        for datos_limpieza in datos.get("limpiezas", []):
            inventario.limpiezas.append(Limpieza.from_dict(datos_limpieza))
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
