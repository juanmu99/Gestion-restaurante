"""
Módulo: inventario.py
----------------------
Gestiona el inventario de un restaurante: productos, categorías, stock,
proveedores, precios y fechas de caducidad. El stock de cada producto se
guarda por LOTES: cada compra es un lote con su cantidad, precio,
proveedor y caducidad propios.

Conceptos de Python nuevos que usamos aquí:
- Clases y objetos (POO): __init__, self, métodos, __str__
- El módulo `datetime` para trabajar con fechas
- `typing.Optional` para indicar que un dato puede ser None
"""

from datetime import date, timedelta
from typing import Optional

from elaboraciones import RegistroElaboraciones


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

    Con los lotes, el precio es el del LOTE concreto que entró o salió, y
    `lote` guarda una descripción de ese lote (número, caducidad y
    proveedor) para que el historial diga exactamente de dónde salió cada cosa.
    """

    # Motivos que una persona puede elegir a mano al sacar stock.
    MOTIVOS_SALIDA = ("consumo", "desperdicio", "otro")
    # "limpieza" NO se elige a mano: solo lo usa Inventario.limpiar_producto().
    # Marca tanto la salida del producto en bruto como la entrada del limpio
    # y sus derivados, para que no se confundan con consumo ni con compras.
    # "elaboración" tampoco: son los ingredientes que se gastan al preparar
    # una receta por adelantado (ver elaboraciones.py).
    MOTIVOS_SALIDA_VALIDOS = MOTIVOS_SALIDA + ("limpieza", "elaboración")
    # "elaboración" (entrada): lo que sale de preparar una elaboración base
    # (un sofrito, un fondo...). No es una compra: no cuenta como gasto.
    MOTIVOS_ENTRADA = ("compra", "limpieza", "elaboración")

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
        lote_id: Optional[int] = None,
        lote: Optional[str] = None,
        tipo_producto: str = "alimento",
        servicio_id: Optional[int] = None,
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
        # Los movimientos anteriores a los lotes no tienen lote (None).
        self.lote_id = lote_id
        self.lote = lote
        # Foto del tipo de producto ("alimento"/"consumible"), para poder
        # separarlos en Métricas.
        self.tipo_producto = tipo_producto
        # Si salió para un servicio (al completarlo), su número: así se sabe
        # lo que costó de verdad cada servicio.
        self.servicio_id = servicio_id

    def es_compra(self) -> bool:
        """True solo para entradas que son dinero gastado (no para lo que sale de una limpieza)."""
        return self.tipo == "entrada" and self.motivo == "compra"

    def valor(self) -> float:
        """Valor económico de este movimiento (cantidad x precio en ese momento)."""
        return round(self.cantidad * self.precio_unitario, 2)

    def __str__(self) -> str:
        flecha = "➕" if self.tipo == "entrada" else "➖"
        extra = f" ({self.motivo})" if self.motivo else ""
        lote = f" [{self.lote}]" if self.lote else ""
        return (
            f"{self.fecha.strftime('%d/%m/%Y')} {flecha} {self.cantidad} {self.unidad} "
            f"{self.producto_nombre}{extra}{lote}"
        )

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
            "lote_id": self.lote_id,
            "lote": self.lote,
            "tipo_producto": self.tipo_producto,
            "servicio_id": self.servicio_id,
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
            lote_id=datos.get("lote_id"),
            lote=datos.get("lote"),
            tipo_producto=datos.get("tipo_producto", "alimento"),
            servicio_id=datos.get("servicio_id"),
        )


class Lote:
    """
    UNA partida concreta de un producto: lo que entró en una compra (o salió
    de una limpieza) en una fecha, de un proveedor, a un precio y con una
    caducidad propios.

    Ejemplo: tienes 1 kg de secreto que caduca el 10/10 y compras 0,8 kg más
    que caducan el 15/10. Son el MISMO producto ("Secreto", 1,8 kg en total)
    con DOS lotes. Así las recetas, la lista de la compra y las métricas
    siguen hablando de "Secreto", pero sabes qué parte caduca antes, de qué
    proveedor vino y cuánto te costó cada parte.

    Cada lote tiene un número (id) que no se repite dentro de su producto,
    aunque los lotes vacíos desaparezcan.
    """

    # De dónde vino el lote: una compra, una limpieza, o el stock con el
    # que se dio de alta el producto (o que ya había antes de existir los lotes).
    PROCEDENCIAS = ("compra", "limpieza", "inicial", "elaboración")

    def __init__(
        self,
        id: int,
        cantidad: float,
        precio_unitario: float,
        proveedor: str,
        fecha_entrada: Optional[date] = None,
        fecha_caducidad: Optional[date] = None,
        peso_unitario: Optional[float] = None,
        procedencia: str = "compra",
    ):
        if cantidad < 0:
            raise ValueError("La cantidad de un lote no puede ser negativa.")
        if precio_unitario < 0:
            raise ValueError("El precio no puede ser negativo.")
        if procedencia not in self.PROCEDENCIAS:
            raise ValueError(f"Procedencia no válida: {procedencia}")
        self.id = id
        self.cantidad = cantidad
        self.precio_unitario = precio_unitario
        self.proveedor = proveedor
        self.fecha_entrada = fecha_entrada or date.today()
        self.fecha_caducidad = fecha_caducidad
        # Solo para productos por unidades: peso en bruto (kg) de cada unidad
        # de ESTE lote (dos compras de patas no pesan lo mismo).
        self.peso_unitario = peso_unitario
        self.procedencia = procedencia

    def valor(self) -> float:
        return round(self.cantidad * self.precio_unitario, 2)

    def dias_para_caducar(self) -> Optional[int]:
        if self.fecha_caducidad is None:
            return None
        return (self.fecha_caducidad - date.today()).days

    def esta_caducado(self) -> bool:
        dias = self.dias_para_caducar()
        return dias is not None and dias < 0

    def etiqueta(self) -> str:
        """Descripción corta para el historial y los desplegables: 'Lote 2 · cad. 15/10/2026 · Carnicería Pepe'."""
        caducidad = f"cad. {self.fecha_caducidad.strftime('%d/%m/%Y')}" if self.fecha_caducidad else "sin caducidad"
        return f"Lote {self.id} · {caducidad} · {self.proveedor}"

    def descripcion(self, unidad: str) -> str:
        """Descripción completa, con la cantidad que queda y el precio."""
        texto = f"{self.etiqueta()} · {_numero(self.cantidad)} {unidad} · {_numero(self.precio_unitario)} €/{unidad}"
        if self.peso_unitario:
            texto += f" · {_numero(self.peso_unitario)} kg/unidad"
        return texto

    def __str__(self) -> str:
        return self.etiqueta()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cantidad": self.cantidad,
            "precio_unitario": self.precio_unitario,
            "proveedor": self.proveedor,
            "fecha_entrada": self.fecha_entrada.isoformat(),
            "fecha_caducidad": self.fecha_caducidad.isoformat() if self.fecha_caducidad else None,
            "peso_unitario": self.peso_unitario,
            "procedencia": self.procedencia,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Lote":
        return cls(
            id=datos["id"],
            cantidad=datos["cantidad"],
            precio_unitario=datos["precio_unitario"],
            proveedor=datos["proveedor"],
            fecha_entrada=date.fromisoformat(datos["fecha_entrada"]),
            fecha_caducidad=date.fromisoformat(datos["fecha_caducidad"]) if datos.get("fecha_caducidad") else None,
            peso_unitario=datos.get("peso_unitario"),
            procedencia=datos.get("procedencia", "compra"),
        )


def _numero(valor: float) -> str:
    """Número sin decimales sobrantes: 2.0 -> '2', 0.8000001 -> '0.8'."""
    return f"{round(valor, 3):g}"


def _clave_caducidad(lote: Lote) -> tuple:
    """Orden 'lo que caduca antes, primero'; los lotes sin caducidad al final."""
    return (lote.fecha_caducidad is None, lote.fecha_caducidad or date.max, lote.id)


class Producto:
    """
    Representa UN producto del inventario (ej: "Harina de trigo").

    Una CLASE es un molde. Cada vez que escribimos Producto(...) creamos
    un OBJETO nuevo (una instancia) con sus propios datos.

    El stock ya no es un único número: el producto guarda una lista de
    LOTES (ver la clase Lote). El stock, el precio y la caducidad del
    producto se CALCULAN a partir de sus lotes (son @property, más abajo),
    así que el resto del programa puede seguir preguntando
    `producto.stock` o `producto.precio_unitario` como siempre.
    """

    # Igual que ESTADOS_VALIDOS en Servicio: un conjunto CERRADO de valores
    # permitidos, para no acabar con "Kg", "kilos", "KILOGRAMOS"... todos
    # distintos entre sí aunque signifiquen lo mismo.
    UNIDADES_VALIDAS = ("kg", "g", "litros", "ml", "unidades")

    # Qué clase de producto es. Los CONSUMIBLES son lo que se gasta pero no
    # se come (servilletas, vasos desechables, film, productos de
    # limpieza...): se compran y se gastan igual que los alimentos, pero van
    # en su propia lista y no tienen caducidad ni merma.
    TIPOS = ("alimento", "consumible")

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
        lotes: Optional[list[Lote]] = None,
        siguiente_lote: int = 1,
        tipo: str = "alimento",
        formula: Optional[dict] = None,
        vida_util_dias: Optional[int] = None,
    ):
        """
        `stock`, `precio_unitario`, `fecha_caducidad` y `peso_unitario` son
        los datos del stock con el que se da de alta el producto: si stock > 0,
        se crea con ellos su primer lote. `proveedor` es el proveedor
        HABITUAL (el que se propone al comprar); cada lote guarda el suyo.

        Campos relacionados con la merma (todos opcionales):

        - tiene_merma: el producto se limpia o despieza antes de usarse
          (una pata de cerdo, un pescado entero...). Solo de estos productos
          se pueden obtener derivados.
        - peso_unitario: peso EN BRUTO de cada unidad, en kg. Solo hace falta
          si el producto con merma se compra por unidades ("3 patas"),
          porque el rendimiento se calcula comparando pesos. Es el peso "de
          referencia" que se propone al comprar; cada lote guarda el suyo.
        - origen: para el producto LIMPIO principal (ej: "Carne de cerdo
          limpia"), el nombre del producto en bruto del que se obtiene. Es
          lo que permite a la lista de la compra pedir el bruto.
        - es_subproducto: lo que se aprovecha de la merma (huesos para un
          fondo, grasa...). Su coste es 0: todo el coste lo carga el limpio.

        tipo: "alimento" (por defecto) o "consumible". Un consumible no
        tiene caducidad ni merma: si se le pasan, se rechazan o se ignoran.

        `lotes` y `siguiente_lote` solo se usan al cargar una sesión guardada.
        """
        # Igual que hicimos con `comensales` en Servicio: esta es una regla
        # de negocio real, no una comodidad de la consola, así que vive
        # aquí y se aplica sin importar de dónde vengan los datos.
        if not categoria.strip() or _es_numero(categoria):
            raise ValueError("La categoría debe ser texto descriptivo, no puede estar vacía ni ser un número")
        if not proveedor.strip() or _es_numero(proveedor):
            raise ValueError("El proveedor debe ser texto descriptivo, no puede estar vacío ni ser un número")
        if unidad not in Producto.UNIDADES_VALIDAS:
            raise ValueError(f"Unidad no válida: '{unidad}'. Debe ser una de: {', '.join(Producto.UNIDADES_VALIDAS)}")
        if stock < 0:
            raise ValueError("El stock no puede ser negativo.")
        if tipo not in Producto.TIPOS:
            raise ValueError(f"Tipo de producto no válido: '{tipo}'. Debe ser uno de: {', '.join(Producto.TIPOS)}")
        if tipo == "consumible" and (tiene_merma or origen or es_subproducto):
            raise ValueError("Un consumible no puede tener merma ni salir de una limpieza.")
        if tipo == "consumible":
            fecha_caducidad = None  # los consumibles no caducan
        _validar_merma(unidad, tiene_merma, peso_unitario)
        if (origen or es_subproducto) and unidad not in UNIDADES_PESO:
            raise ValueError("Un producto obtenido de una limpieza debe medirse en kg o g.")
        if formula is not None:
            _validar_formula(nombre, unidad, formula)
            if tipo != "alimento" or tiene_merma or origen or es_subproducto:
                raise ValueError("Una elaboración base es un alimento sin merma que no sale de una limpieza.")
        if vida_util_dias is not None and vida_util_dias < 0:
            raise ValueError("La vida útil no puede ser negativa.")

        self.nombre = nombre
        self.tipo = tipo
        self.categoria = categoria
        self.unidad = unidad  # kg, litros, unidades, etc.
        self.proveedor = proveedor  # proveedor habitual
        self.stock_minimo = stock_minimo
        self.tiene_merma = tiene_merma
        # Precio de la última entrada: sirve para estimar compras y costes
        # de recetas cuando no queda ningún lote.
        self.precio_referencia = precio_unitario
        self.peso_unitario_referencia = peso_unitario if unidad == "unidades" else None
        self.origen = origen
        self.es_subproducto = es_subproducto
        self.lotes: list[Lote] = lotes if lotes is not None else []
        self.siguiente_lote = siguiente_lote
        # ELABORACIÓN BASE (sofrito, fondo, salsa, masa...): en vez de
        # comprarse, se prepara a partir de otros productos. `formula` dice
        # con qué: {"cantidad": 2, "ingredientes": {"Cebolla": 2.5, ...}} =
        # "para 2 kg de sofrito hacen falta 2,5 kg de cebolla...".
        self.formula = formula
        # Días que dura una vez preparada (para proponer su caducidad).
        self.vida_util_dias = vida_util_dias

        if lotes is None and stock > 0:
            self.nuevo_lote(stock, precio_unitario, proveedor, fecha_caducidad, peso_unitario, "inicial")

    def es_consumible(self) -> bool:
        return self.tipo == "consumible"

    # ---------- Datos calculados a partir de los lotes ----------

    @property
    def stock(self) -> float:
        """Stock total: la suma de todos sus lotes."""
        return round(sum(l.cantidad for l in self.lotes), 6)

    @property
    def precio_unitario(self) -> float:
        """
        Precio medio de lo que hay ahora (media ponderada de los lotes). Sin
        stock, el precio de la última entrada.
        """
        stock = self.stock
        if stock <= 0:
            return self.precio_referencia
        return round(sum(l.cantidad * l.precio_unitario for l in self.lotes) / stock, 4)

    @property
    def fecha_caducidad(self) -> Optional[date]:
        """La caducidad MÁS PRÓXIMA entre sus lotes (None si ninguno caduca)."""
        fechas = [l.fecha_caducidad for l in self.lotes if l.fecha_caducidad]
        return min(fechas) if fechas else None

    @property
    def peso_unitario(self) -> Optional[float]:
        """Peso medio por unidad de los lotes que hay (o el de referencia, si no hay)."""
        if self.unidad != "unidades":
            return None
        con_peso = [l for l in self.lotes if l.peso_unitario]
        unidades = sum(l.cantidad for l in con_peso)
        if unidades <= 0:
            return self.peso_unitario_referencia
        return round(sum(l.cantidad * l.peso_unitario for l in con_peso) / unidades, 4)

    # ---------- Lotes ----------

    def lotes_ordenados(self) -> list[Lote]:
        """Sus lotes, primero los que caducan antes (los sin caducidad al final)."""
        return sorted(self.lotes, key=_clave_caducidad)

    def buscar_lote(self, lote_id: int) -> Optional[Lote]:
        for lote in self.lotes:
            if lote.id == lote_id:
                return lote
        return None

    def nuevo_lote(
        self,
        cantidad: float,
        precio_unitario: float,
        proveedor: str,
        fecha_caducidad: Optional[date] = None,
        peso_unitario: Optional[float] = None,
        procedencia: str = "compra",
    ) -> Lote:
        """Crea un lote nuevo con el siguiente número libre. No registra movimiento (eso lo hace Inventario)."""
        lote = Lote(
            self.siguiente_lote, cantidad, precio_unitario, proveedor,
            fecha_caducidad=None if self.es_consumible() else fecha_caducidad,
            peso_unitario=(peso_unitario or self.peso_unitario_referencia) if self.unidad == "unidades" else None,
            procedencia=procedencia,
        )
        self.siguiente_lote += 1
        self.lotes.append(lote)
        return lote

    def quitar_lotes_vacios(self) -> None:
        """Un lote que llega a 0 desaparece (su número no se vuelve a usar)."""
        self.lotes = [l for l in self.lotes if l.cantidad > 1e-9]

    # ---------- Consultas ----------

    def peso_kg(self, cantidad: float, lote: Optional[Lote] = None) -> float:
        """Cuántos kg pesa `cantidad` de este producto (en su propia unidad)."""
        if self.unidad == "unidades":
            peso = (lote.peso_unitario if lote else None) or self.peso_unitario
            if not peso:
                raise ValueError(f"'{self.nombre}' no tiene peso por unidad definido.")
            return cantidad * peso
        return convertir(cantidad, self.unidad, "kg")

    def es_base(self) -> bool:
        """True si es una elaboración base (se prepara con una fórmula, no se compra)."""
        return self.formula is not None

    def ingredientes_para(self, cantidad: float) -> dict[str, float]:
        """Los ingredientes de la fórmula para preparar `cantidad` (en la unidad de este producto)."""
        if not self.es_base():
            return {}
        factor = cantidad / self.formula["cantidad"]
        return {i: round(c * factor, 3) for i, c in self.formula["ingredientes"].items()}

    def caducidad_propuesta(self, fecha_preparacion: Optional[date] = None) -> Optional[date]:
        """Para una elaboración base: la fecha de preparación + su vida útil (None si no se sabe)."""
        if self.vida_util_dias is None:
            return None
        return (fecha_preparacion or date.today()) + timedelta(days=self.vida_util_dias)

    def tipo_descripcion(self) -> str:
        """Etiqueta corta para listados: qué papel tiene este producto respecto a la merma."""
        if self.es_consumible():
            return ""
        if self.es_base():
            return "Elaboración base"
        if self.es_subproducto:
            return "Subproducto"
        if self.origen:
            return f"Limpio (de {self.origen})"
        if self.tiene_merma:
            return "Con merma"
        return ""

    def valor_total(self) -> float:
        """Valor económico del stock actual: cada lote a su propio precio."""
        return round(sum(l.valor() for l in self.lotes), 2)

    def esta_bajo_minimo(self) -> bool:
        """True si el stock actual está por debajo del mínimo definido."""
        return self.stock < self.stock_minimo

    def dias_para_caducar(self) -> Optional[int]:
        """Días que quedan para que caduque su lote más próximo. None si ninguno tiene fecha."""
        if self.fecha_caducidad is None:
            return None
        return (self.fecha_caducidad - date.today()).days

    def esta_caducado(self) -> bool:
        """True si ALGUNO de sus lotes ya ha caducado."""
        return any(l.esta_caducado() for l in self.lotes)

    def __str__(self) -> str:
        # __str__ define qué se muestra al hacer print(producto)
        texto = (
            f"{self.nombre} | {self.categoria} | "
            f"Stock: {self.stock} {self.unidad} (mínimo: {self.stock_minimo}) | "
            f"Precio medio: {self.precio_unitario}€/{self.unidad} | "
            f"Proveedor habitual: {self.proveedor}"
        )
        if len(self.lotes) > 1:
            texto += f" | {len(self.lotes)} lotes"
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
            "tipo": self.tipo,
            "categoria": self.categoria,
            "unidad": self.unidad,
            "precio_referencia": self.precio_referencia,
            "proveedor": self.proveedor,
            "stock_minimo": self.stock_minimo,
            "tiene_merma": self.tiene_merma,
            "peso_unitario": self.peso_unitario_referencia,
            "origen": self.origen,
            "es_subproducto": self.es_subproducto,
            "lotes": [l.to_dict() for l in self.lotes],
            "siguiente_lote": self.siguiente_lote,
            "formula": self.formula,
            "vida_util_dias": self.vida_util_dias,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Producto":
        """
        Reconstruye un Producto a partir de un diccionario (el camino inverso
        de to_dict). Es un @classmethod: en vez de operar sobre un objeto ya
        creado (como los métodos normales, con `self`), CREA el objeto nuevo
        él mismo y lo devuelve — por eso recibe `cls` (la propia clase) en
        vez de `self`.

        Las sesiones guardadas ANTES de existir los lotes no tienen la clave
        "lotes": su stock, precio y caducidad se convierten en un único lote,
        así que no se pierde nada al actualizar el programa.
        """
        comun = dict(
            nombre=datos["nombre"],
            categoria=datos["categoria"],
            unidad=datos["unidad"],
            proveedor=datos["proveedor"],
            stock_minimo=datos["stock_minimo"],
            # .get(): las sesiones guardadas antes de existir la merma no
            # tienen estos campos -- se cargan como productos normales.
            tiene_merma=datos.get("tiene_merma", False),
            peso_unitario=datos.get("peso_unitario"),
            origen=datos.get("origen"),
            es_subproducto=datos.get("es_subproducto", False),
            # Las sesiones anteriores a los consumibles solo tenían alimentos.
            tipo=datos.get("tipo", "alimento"),
            formula=datos.get("formula"),
            vida_util_dias=datos.get("vida_util_dias"),
        )
        if "lotes" in datos:
            return cls(
                stock=0,
                precio_unitario=datos.get("precio_referencia", 0),
                lotes=[Lote.from_dict(d) for d in datos["lotes"]],
                siguiente_lote=datos.get("siguiente_lote", 1),
                **comun,
            )
        fecha = datos.get("fecha_caducidad")
        return cls(
            stock=datos["stock"],
            precio_unitario=datos["precio_unitario"],
            fecha_caducidad=date.fromisoformat(fecha) if fecha else None,
            **comun,
        )


def _validar_formula(nombre: str, unidad: str, formula: dict) -> None:
    """Reglas de la fórmula de una elaboración base."""
    if unidad not in ("kg", "g", "litros", "ml"):
        raise ValueError("Una elaboración base se mide en kg, g, litros o ml.")
    if not isinstance(formula, dict) or formula.get("cantidad", 0) <= 0:
        raise ValueError("Indica cuánto sale con la fórmula (más de 0).")
    ingredientes = {n: c for n, c in formula.get("ingredientes", {}).items() if c > 0}
    if not ingredientes:
        raise ValueError("La fórmula necesita al menos un ingrediente.")
    if nombre in ingredientes:
        raise ValueError("Una elaboración base no puede llevarse a sí misma.")
    formula["ingredientes"] = ingredientes


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
    Registro de UNA limpieza o despiece: qué producto en bruto se limpió
    (y de qué lote), cuánto pesaba, cuánto producto limpio salió, qué
    derivados se aprovecharon y cuánta merma quedó.

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
        lote_origen: Optional[str] = None,
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
        self.lote_origen = lote_origen  # descripción del lote en bruto usado (None en limpiezas antiguas)

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
        lote = f" [{self.lote_origen}]" if self.lote_origen else ""
        return (
            f"{self.fecha.strftime('%d/%m/%Y')} | {self.cantidad_origen} {self.unidad_origen} de {self.producto_origen}"
            f"{lote} ({round(self.peso_bruto_kg, 3)} kg bruto) -> {round(self.peso_limpio_kg, 3)} kg de "
            f"{self.producto_limpio} | Derivados: {derivados} | Merma: {self.merma_kg} kg | "
            f"Rendimiento: {self.rendimiento:.0%}"
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
            "lote_origen": self.lote_origen,
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
            lote_origen=datos.get("lote_origen"),
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
        # Recetas preparadas por adelantado (tandas con raciones y caducidad).
        self.elaboraciones = RegistroElaboraciones()

    def agregar_producto(self, producto: Producto) -> None:
        if producto.nombre in self.productos:
            print(f"⚠️  Ya existe '{producto.nombre}'. Registra una entrada para añadir un lote nuevo.")
            return
        self.productos[producto.nombre] = producto
        print(f"✅ Producto añadido: {producto.nombre}")

    def eliminar_producto(self, nombre: str) -> None:
        if nombre in self.productos:
            del self.productos[nombre]
            print(f"🗑️  Producto eliminado: {nombre}")
        else:
            print(f"❌ No existe el producto '{nombre}'.")

    def _registrar(
        self, producto: Producto, lote: Lote, tipo: str, cantidad: float, motivo: str,
        servicio_id: Optional[int] = None,
    ) -> None:
        # Se registra SIEMPRE, tanto entradas como salidas -- por eso el
        # historial nunca puede desincronizarse: es imposible cambiar el
        # stock sin dejar constancia de por qué (ni de qué lote).
        self.historial.append(MovimientoStock(
            producto_nombre=producto.nombre,
            categoria=producto.categoria,
            tipo=tipo,
            cantidad=cantidad,
            unidad=producto.unidad,
            precio_unitario=lote.precio_unitario,
            motivo=motivo,
            lote_id=lote.id,
            lote=lote.etiqueta(),
            tipo_producto=producto.tipo,
            servicio_id=servicio_id,
        ))

    # ---------- Entradas: cada una es un lote nuevo ----------

    def entrada_stock(
        self,
        nombre: str,
        cantidad: float,
        precio_unitario: Optional[float] = None,
        proveedor: Optional[str] = None,
        fecha_caducidad: Optional[date] = None,
        peso_unitario: Optional[float] = None,
        motivo: str = "compra",
    ) -> Optional[Lote]:
        """
        Registra una entrada de mercancía. CADA entrada crea un LOTE NUEVO
        (aunque venga del mismo proveedor o tenga la misma caducidad que
        otro): así se sabe siempre qué se compró, cuándo, a quién y a qué precio.

        - precio_unitario: lo que costó esta vez (por defecto, el de la última entrada).
        - proveedor: a quién se compró esta vez (por defecto, el habitual).
        - fecha_caducidad: la de este lote (None si no caduca).
        - peso_unitario: para productos por unidades, el peso en bruto (kg)
          de cada unidad de este lote.
        - motivo: "compra" (por defecto) o "limpieza". Solo las compras
          cuentan como dinero gastado en Métricas.

        Devuelve el lote creado, o None si se rechazó (el motivo se explica por consola).
        """
        producto = self.productos.get(nombre)
        if producto is None:
            print(f"❌ No existe el producto '{nombre}'.")
            return None
        if cantidad <= 0:
            print("❌ La cantidad debe ser mayor que 0.")
            return None
        if motivo not in MovimientoStock.MOTIVOS_ENTRADA:
            print(f"❌ Motivo de entrada no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_ENTRADA)}")
            return None
        precio = producto.precio_referencia if precio_unitario is None else precio_unitario
        if precio < 0:
            print("❌ El precio no puede ser negativo.")
            return None
        proveedor = (proveedor or "").strip() or producto.proveedor
        if _es_numero(proveedor):
            print("❌ El proveedor debe ser texto descriptivo.")
            return None
        if peso_unitario is not None and peso_unitario <= 0:
            print("❌ El peso por unidad debe ser mayor que 0.")
            return None

        lote = producto.nuevo_lote(cantidad, precio, proveedor, fecha_caducidad, peso_unitario, motivo)
        producto.precio_referencia = precio
        if lote.peso_unitario:
            producto.peso_unitario_referencia = lote.peso_unitario
        print(f"📦 Entrada: {cantidad} {producto.unidad} de {nombre} -> {lote.etiqueta()}")
        self._registrar(producto, lote, "entrada", cantidad, motivo)
        return lote

    # ---------- Salidas: siempre de un lote concreto ----------

    def salida_stock(
        self, nombre: str, cantidad: float, motivo: str, lote_id: int, servicio_id: Optional[int] = None,
    ) -> bool:
        """
        Saca `cantidad` del lote `lote_id` de un producto. Quien usa el
        programa decide de qué lote sale (puede querer gastar antes uno que
        caduca más tarde, por el motivo que sea).

        motivo: "consumo", "desperdicio" u "otro" ("limpieza" solo lo usa
        limpiar_producto()). Es lo que permite luego distinguir cuánto se ha
        consumido de verdad frente a cuánto se ha tirado.

        Devuelve True si se aplicó, False si se rechazó (producto o lote
        inexistente, motivo no válido o no hay tanto en ese lote).
        """
        return self.salida_repartida(nombre, [(lote_id, cantidad)], motivo, servicio_id)

    def salida_repartida(
        self, nombre: str, reparto: list[tuple[int, float]], motivo: str, servicio_id: Optional[int] = None,
    ) -> bool:
        """
        Saca stock de VARIOS lotes a la vez: `reparto` es una lista de
        (lote_id, cantidad). Se comprueba TODO antes de tocar nada: o se
        aplica entero o no se aplica nada. `servicio_id`: el servicio para
        el que sale (queda apuntado en el historial).
        """
        producto = self.productos.get(nombre)
        if producto is None:
            print(f"❌ No existe el producto '{nombre}'.")
            return False
        if motivo not in MovimientoStock.MOTIVOS_SALIDA_VALIDOS:
            print(f"❌ Motivo no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_SALIDA)}")
            return False
        reparto = [(lote_id, cantidad) for lote_id, cantidad in reparto if cantidad > 0]
        if not reparto:
            print("❌ La cantidad debe ser mayor que 0.")
            return False

        por_lote: dict[int, float] = {}
        for lote_id, cantidad in reparto:
            por_lote[lote_id] = por_lote.get(lote_id, 0) + cantidad
        for lote_id, cantidad in por_lote.items():
            lote = producto.buscar_lote(lote_id)
            if lote is None:
                print(f"❌ '{nombre}' no tiene el lote {lote_id}.")
                return False
            # Pequeño margen (1e-9) para que los decimales de coma flotante no
            # impidan sacar exactamente todo lo que hay (ej: 0.30000000000000004).
            if cantidad > lote.cantidad + 1e-9:
                print(
                    f"❌ En el lote {lote_id} de '{nombre}' solo hay {_numero(lote.cantidad)} {producto.unidad}, "
                    f"intentas sacar {_numero(cantidad)}. El stock nunca puede quedar en negativo."
                )
                return False

        for lote_id, cantidad in reparto:
            lote = producto.buscar_lote(lote_id)
            cantidad = min(cantidad, lote.cantidad)
            lote.cantidad = round(lote.cantidad - cantidad, 6)
            self._registrar(producto, lote, "salida", cantidad, motivo, servicio_id)
            print(f"📦 Salida ({motivo}): {_numero(cantidad)} {producto.unidad} de {nombre} [{lote.etiqueta()}]")
        producto.quitar_lotes_vacios()
        return True

    def compra_para_servicio(
        self,
        nombre: str,
        comprada: float,
        usada: float,
        importe_total: float,
        servicio_id: int,
        proveedor: Optional[str] = None,
        fecha_caducidad: Optional[date] = None,
    ) -> Lote:
        """
        Una compra NO PREVISTA hecha para un servicio (ej: 5 kg de tomate de
        urgencia, de los que se usan 3). En un solo paso:
        1. Entra la compra como un lote nuevo (cuenta como compra en Métricas),
           a precio = importe_total / comprada.
        2. Sale lo usado de ese lote como consumo DE ESE SERVICIO (cuenta en
           su coste real).
        3. Lo que sobra se queda en el inventario, en ese lote.
        Comprueba todo antes de tocar nada. Devuelve el lote creado.
        """
        producto = self.productos.get(nombre)
        if producto is None:
            raise ValueError(f"No existe el producto '{nombre}'.")
        if comprada <= 0:
            raise ValueError("La cantidad comprada debe ser mayor que 0.")
        if usada < 0 or usada > comprada + 1e-9:
            raise ValueError("Lo usado no puede ser negativo ni mayor que lo comprado.")
        if importe_total <= 0:
            raise ValueError("El importe debe ser mayor que 0.")
        if proveedor is not None and proveedor.strip() and _es_numero(proveedor.strip()):
            raise ValueError("El proveedor debe ser texto descriptivo.")

        lote = self.entrada_stock(
            nombre, comprada, precio_unitario=round(importe_total / comprada, 4),
            proveedor=proveedor, fecha_caducidad=fecha_caducidad,
        )
        if usada > 0:
            self.salida_stock(nombre, min(usada, lote.cantidad), "consumo", lote.id, servicio_id)
        return lote

    def desechar_lote(self, nombre: str, lote_id: int) -> bool:
        """Tira un lote ENTERO (normalmente uno caducado): sale todo como desperdicio."""
        producto = self.productos.get(nombre)
        lote = producto.buscar_lote(lote_id) if producto else None
        if lote is None:
            print(f"❌ No existe el lote {lote_id} de '{nombre}'.")
            return False
        return self.salida_stock(nombre, lote.cantidad, "desperdicio", lote_id)

    def repartir(self, nombre: str, cantidad: float, lotes_en_orden: list[int]) -> tuple[list[tuple[int, float]], float]:
        """
        Calcula (SIN tocar nada) cómo sacar `cantidad` usando los lotes en el
        orden indicado: primero todo lo posible del primero, luego del
        segundo... Devuelve (reparto, lo_que_falta_por_asignar).
        """
        producto = self.productos.get(nombre)
        reparto: list[tuple[int, float]] = []
        pendiente = cantidad
        for lote_id in lotes_en_orden:
            lote = producto.buscar_lote(lote_id) if producto else None
            if lote is None or pendiente <= 1e-9:
                continue
            sale = round(min(pendiente, lote.cantidad), 6)
            if sale > 0:
                reparto.append((lote_id, sale))
                pendiente -= sale
        return reparto, round(max(0.0, pendiente), 6)

    def actualizar_stock(
        self,
        nombre: str,
        cantidad: float,
        sumar: bool = True,
        nueva_fecha_caducidad: Optional[date] = None,
        motivo_salida: Optional[str] = None,
        motivo_entrada: str = "compra",
        peso_unitario_lote: Optional[float] = None,
        lote_id: Optional[int] = None,
    ) -> bool:
        """
        Atajo que se mantiene por compatibilidad con código antiguo (demos
        y pruebas). Las pantallas usan entrada_stock() y salida_stock().

        sumar=True  -> entrada_stock(): crea un lote nuevo.
        sumar=False -> salida del lote `lote_id`. Si no se indica lote, se
                       saca de los que caducan antes. (Las pantallas SIEMPRE
                       indican el lote: lo decide quien usa el programa.)
        """
        if sumar:
            return self.entrada_stock(
                nombre, cantidad, fecha_caducidad=nueva_fecha_caducidad,
                peso_unitario=peso_unitario_lote, motivo=motivo_entrada,
            ) is not None
        producto = self.productos.get(nombre)
        if producto is None:
            print(f"❌ No existe el producto '{nombre}'.")
            return False
        if lote_id is not None:
            return self.salida_stock(nombre, cantidad, motivo_salida, lote_id)
        if cantidad > producto.stock + 1e-9:
            print(
                f"❌ Stock insuficiente de '{nombre}': hay {producto.stock} {producto.unidad}, "
                f"intentas restar {cantidad}. El stock nunca puede quedar en negativo."
            )
            return False
        reparto, _ = self.repartir(nombre, cantidad, [l.id for l in producto.lotes_ordenados()])
        return self.salida_repartida(nombre, reparto, motivo_salida)

    # ---------- Corregir un lote ----------

    def editar_lote(
        self,
        nombre: str,
        lote_id: int,
        cantidad: Optional[float] = None,
        precio_unitario: Optional[float] = None,
        proveedor: Optional[str] = None,
        fecha_caducidad: Optional[date] = None,
        borrar_fecha_caducidad: bool = False,
        peso_unitario: Optional[float] = None,
    ) -> bool:
        """
        CORRIGE los datos de un lote (un error al apuntarlo, un recuento...).
        No es un movimiento de stock: no queda en el historial. Para registrar
        que algo se ha gastado o tirado, usa una salida.

        None = "no lo toques". borrar_fecha_caducidad=True deja el lote sin
        caducidad. Una cantidad de 0 elimina el lote.
        """
        producto = self.productos.get(nombre)
        lote = producto.buscar_lote(lote_id) if producto else None
        if lote is None:
            print(f"❌ No existe el lote {lote_id} de '{nombre}'.")
            return False
        if cantidad is not None and cantidad < 0:
            raise ValueError("La cantidad no puede ser negativa.")
        if precio_unitario is not None and precio_unitario < 0:
            raise ValueError("El precio no puede ser negativo.")
        if proveedor is not None and (not proveedor.strip() or _es_numero(proveedor)):
            raise ValueError("El proveedor debe ser texto descriptivo, no puede estar vacío ni ser un número")
        if peso_unitario is not None and peso_unitario <= 0:
            raise ValueError("El peso por unidad debe ser mayor que 0.")

        if cantidad is not None:
            lote.cantidad = cantidad
        if precio_unitario is not None:
            lote.precio_unitario = precio_unitario
        if proveedor is not None:
            lote.proveedor = proveedor.strip()
        if borrar_fecha_caducidad or producto.es_consumible():
            lote.fecha_caducidad = None
        elif fecha_caducidad is not None:
            lote.fecha_caducidad = fecha_caducidad
        if peso_unitario is not None and producto.unidad == "unidades":
            lote.peso_unitario = peso_unitario
        producto.quitar_lotes_vacios()
        print(f"✏️  Lote corregido: {nombre} -> {lote.descripcion(producto.unidad)}")
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
        lote_id: Optional[int] = None,
    ) -> Limpieza:
        """
        Limpia o despieza `cantidad` de UN LOTE de un producto con merma.

        - Sale del lote `lote_id` la `cantidad` en bruto (en su unidad: kg,
          g o unidades). Si el producto solo tiene un lote, no hace falta
          indicarlo.
        - Entra un lote nuevo del producto limpio, que carga con TODO el
          coste de lo que se ha limpiado.
        - Entra un lote de cada derivado aprovechado de `derivados`
          ({nombre: peso}) a coste 0.
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
        if lote_id is None:
            if len(origen.lotes) != 1:
                raise ValueError(f"Elige de qué lote de '{nombre_origen}' sale lo que vas a limpiar.")
            lote_id = origen.lotes[0].id
        lote = origen.buscar_lote(lote_id)
        if lote is None:
            raise ValueError(f"'{nombre_origen}' no tiene el lote {lote_id}.")
        if cantidad > lote.cantidad + 1e-9:
            raise ValueError(f"En el lote {lote_id} de '{nombre_origen}' solo hay {_numero(lote.cantidad)} {origen.unidad}.")

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

        peso_bruto_kg = origen.peso_kg(cantidad, lote)
        peso_limpio_kg = convertir(peso_limpio, unidad_peso, "kg")
        derivados_kg = {n: convertir(p, unidad_peso, "kg") for n, p in derivados_limpios.items()}
        total_kg = peso_limpio_kg + sum(derivados_kg.values())
        if total_kg > peso_bruto_kg + 1e-6:
            raise ValueError(
                f"El limpio más los derivados ({round(total_kg, 3)} kg) pesan más que el bruto "
                f"({round(peso_bruto_kg, 3)} kg). Revisa los pesos."
            )

        principal = self.productos.get(producto_limpio)
        for nombre in [producto_limpio, *derivados_kg]:
            existente = self.productos.get(nombre)
            if existente is not None and existente.es_consumible():
                raise ValueError(f"'{nombre}' es un consumible: no puede salir de una limpieza.")
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
        coste = round(cantidad * lote.precio_unitario, 2)
        etiqueta_origen = lote.etiqueta()

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

        self.salida_stock(nombre_origen, cantidad, "limpieza", lote_id)

        # El lote limpio carga con todo el coste de lo que se limpió.
        cantidad_limpio = round(convertir(peso_limpio_kg, "kg", principal.unidad), 6)
        self.entrada_stock(
            producto_limpio, cantidad_limpio, precio_unitario=round(coste / cantidad_limpio, 4),
            proveedor="Elaboración propia", fecha_caducidad=caducidades.get(producto_limpio), motivo="limpieza",
        )
        # Los derivados entran a coste 0.
        for nombre, kg in derivados_kg.items():
            derivado = self.productos[nombre]
            self.entrada_stock(
                nombre, round(convertir(kg, "kg", derivado.unidad), 6), precio_unitario=0,
                proveedor="Elaboración propia", fecha_caducidad=caducidades.get(nombre), motivo="limpieza",
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
            lote_origen=etiqueta_origen,
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
        proveedor: Optional[str] = None,
        stock_minimo: Optional[float] = None,
        tiene_merma: Optional[bool] = None,
        peso_unitario: Optional[float] = None,
        tipo: Optional[str] = None,
    ) -> bool:
        """
        Corrige los datos GENERALES de un producto ya existente: nombre,
        categoría, proveedor habitual, stock mínimo y merma. Lo que depende
        de cada compra (cantidad, precio, caducidad, peso por unidad de un
        lote concreto) se corrige en su lote, con editar_lote().

        Cualquier parámetro que dejes en None (el valor por defecto) NO
        se modifica -- así puedes cambiar solo el mínimo sin tener que
        repetir todos los demás datos.

        peso_unitario: peso por unidad de referencia (el que se propone al
        registrar compras nuevas de un producto con merma por unidades).

        tipo: "alimento" o "consumible" (por si se dio de alta en el tipo
        equivocado). Al pasar a consumible se quitan la merma y la caducidad
        de sus lotes.

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
        tipo_final = tipo if tipo is not None else producto.tipo
        if tipo_final not in Producto.TIPOS:
            raise ValueError(f"Tipo de producto no válido: '{tipo_final}'.")
        merma_final = tiene_merma if tiene_merma is not None else producto.tiene_merma
        if tipo_final == "consumible":
            if producto.origen or producto.es_subproducto:
                raise ValueError("Este producto sale de una limpieza: no puede ser un consumible.")
            merma_final = False
        if producto.es_base() and (tipo_final == "consumible" or merma_final):
            raise ValueError("Una elaboración base es un alimento sin merma.")
        if tipo_final == "consumible" and any(nombre_actual in b.formula["ingredientes"] for b in self.bases()):
            raise ValueError("Este producto es ingrediente de una elaboración base: no puede ser un consumible.")
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

        if tipo_final != producto.tipo:
            # Es una corrección (se dio de alta con el tipo equivocado): el
            # historial de este producto pasa a contar en su tipo correcto.
            for m in self.historial:
                if m.producto_nombre == producto.nombre:
                    m.tipo_producto = tipo_final
        producto.tipo = tipo_final
        if tipo_final == "consumible":
            for lote in producto.lotes:
                lote.fecha_caducidad = None
        producto.tiene_merma = merma_final
        if producto.unidad == "unidades" and peso_unitario is not None:
            producto.peso_unitario_referencia = peso_unitario
        producto.categoria = categoria_final
        producto.proveedor = proveedor_final
        if stock_minimo is not None:
            producto.stock_minimo = stock_minimo

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
        for p in self.productos.values():
            if p.es_base() and antiguo in p.formula["ingredientes"]:
                p.formula["ingredientes"] = {(nuevo if n == antiguo else n): c for n, c in p.formula["ingredientes"].items()}
        for prep in self.elaboraciones.preparaciones_base:
            if prep.producto == antiguo:
                prep.producto = nuevo

    # ---------- Elaboraciones base (sofritos, fondos, salsas...) ----------

    def bases(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.es_base()]

    def _lleva(self, nombre_base: str, buscado: str, vistos: Optional[set] = None) -> bool:
        """True si la fórmula de `nombre_base` lleva `buscado`, directamente o dentro de otra base."""
        vistos = vistos or set()
        producto = self.productos.get(nombre_base)
        if producto is None or not producto.es_base() or nombre_base in vistos:
            return False
        vistos.add(nombre_base)
        for ingrediente in producto.formula["ingredientes"]:
            if ingrediente == buscado or self._lleva(ingrediente, buscado, vistos):
                return True
        return False

    def _comprobar_formula(self, nombre: str, formula: dict) -> None:
        for ingrediente in formula["ingredientes"]:
            producto = self.productos.get(ingrediente)
            if producto is None:
                raise ValueError(f"'{ingrediente}' no existe en el inventario.")
            if producto.es_consumible():
                raise ValueError(f"'{ingrediente}' es un consumible: no puede ser ingrediente.")
            if ingrediente == nombre or self._lleva(ingrediente, nombre):
                raise ValueError(f"'{ingrediente}' ya lleva '{nombre}': las fórmulas no pueden ir en círculo.")

    def definir_base(
        self, nombre: str, categoria: str, unidad: str, cantidad: float, ingredientes: dict[str, float],
        vida_util_dias: Optional[int] = None, stock_minimo: float = 0,
    ) -> Producto:
        """
        Da de alta una elaboración base nueva (con stock 0): un producto que
        se prepara con una fórmula ("para `cantidad` hacen falta estos
        `ingredientes`"). Las recetas pueden usarla como cualquier ingrediente.
        """
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("Ponle un nombre a la elaboración base.")
        if nombre in self.productos:
            raise ValueError(f"Ya existe un producto llamado '{nombre}'.")
        formula = {"cantidad": cantidad, "ingredientes": dict(ingredientes)}
        producto = Producto(
            nombre, categoria, 0, unidad, 0, "Elaboración propia", stock_minimo,
            formula=formula, vida_util_dias=vida_util_dias,
        )
        self._comprobar_formula(nombre, producto.formula)
        self.agregar_producto(producto)
        return producto

    def editar_formula(
        self, nombre: str, cantidad: float, ingredientes: dict[str, float], vida_util_dias: Optional[int] = None,
    ) -> None:
        """Cambia la fórmula (y la vida útil) de una elaboración base."""
        producto = self.productos.get(nombre)
        if producto is None or not producto.es_base():
            raise ValueError(f"'{nombre}' no es una elaboración base.")
        formula = {"cantidad": cantidad, "ingredientes": dict(ingredientes)}
        _validar_formula(nombre, producto.unidad, formula)
        self._comprobar_formula(nombre, formula)
        if vida_util_dias is not None and vida_util_dias < 0:
            raise ValueError("La vida útil no puede ser negativa.")
        producto.formula = formula
        producto.vida_util_dias = vida_util_dias
        print(f"✏️  Fórmula de '{nombre}' actualizada.")

    def coste_estimado_base(self, nombre: str, cantidad: float = 1, vistos: Optional[set] = None) -> float:
        """
        Lo que costaría preparar `cantidad` de una elaboración base con los
        precios actuales. Si un ingrediente es otra base sin stock, se estima
        con SU fórmula.
        """
        vistos = vistos or set()
        producto = self.productos.get(nombre)
        if producto is None or not producto.es_base() or nombre in vistos:
            return 0.0
        total = 0.0
        for ingrediente, c in producto.ingredientes_para(cantidad).items():
            otro = self.productos.get(ingrediente)
            if otro is None:
                continue
            if otro.es_base() and otro.stock <= 0:
                total += self.coste_estimado_base(ingrediente, c, vistos | {nombre})
            else:
                total += c * otro.precio_unitario
        return round(total, 4)

    def buscar_producto(self, nombre: str) -> Optional[Producto]:
        return self.productos.get(nombre)

    def alimentos(self) -> list[Producto]:
        return [p for p in self.productos.values() if not p.es_consumible()]

    def consumibles(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.es_consumible()]

    def listar_por_categoria(self, categoria: str) -> list[Producto]:
        return [p for p in self.productos.values() if p.categoria == categoria]

    def productos_por_proveedor(self, proveedor: str) -> list[Producto]:
        """Todos los productos que vienen de un proveedor concreto (habitual o de alguno de sus lotes)."""
        return [
            p for p in self.productos.values()
            if p.proveedor == proveedor or any(l.proveedor == proveedor for l in p.lotes)
        ]

    def productos_bajo_minimo(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.esta_bajo_minimo()]

    def lotes_proximos_a_caducar(self, dias: int = 7) -> list[tuple[Producto, Lote]]:
        """Pares (producto, lote) de los lotes que caducan entre hoy y dentro de `dias` días, los más urgentes primero."""
        resultado = [
            (p, l) for p in self.productos.values() for l in p.lotes
            if l.dias_para_caducar() is not None and 0 <= l.dias_para_caducar() <= dias
        ]
        return sorted(resultado, key=lambda par: _clave_caducidad(par[1]))

    def lotes_caducados(self) -> list[tuple[Producto, Lote]]:
        """Pares (producto, lote) de los lotes cuya caducidad ya ha pasado (candidatos a desechar)."""
        resultado = [(p, l) for p in self.productos.values() for l in p.lotes if l.esta_caducado()]
        return sorted(resultado, key=lambda par: _clave_caducidad(par[1]))

    def productos_proximos_a_caducar(self, dias: int = 7) -> list[Producto]:
        """Productos con algún lote que caduca en los próximos `dias` días (sin repetir)."""
        vistos: list[Producto] = []
        for p, _ in self.lotes_proximos_a_caducar(dias):
            if p not in vistos:
                vistos.append(p)
        return vistos

    def valor_total_inventario(self) -> float:
        return round(sum(p.valor_total() for p in self.productos.values()), 2)

    def listar_todos(self) -> None:
        if not self.productos:
            print("El inventario está vacío.")
            return
        for producto in self.productos.values():
            print(producto)
            for lote in producto.lotes_ordenados():
                print(f"    · {lote.descripcion(producto.unidad)}")

    def to_dict(self) -> dict:
        """El inventario se convierte en una LISTA de productos y otra de movimientos, ya convertidos."""
        return {
            "productos": [p.to_dict() for p in self.productos.values()],
            "historial": [m.to_dict() for m in self.historial],
            "limpiezas": [l.to_dict() for l in self.limpiezas],
            "elaboraciones": self.elaboraciones.to_dict(),
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
        inventario.elaboraciones = RegistroElaboraciones.from_dict(datos.get("elaboraciones", {}))
        return inventario


if __name__ == "__main__":
    # --- DEMO: esto solo se ejecuta si corres ESTE archivo directamente ---
    from datetime import timedelta

    hoy = date.today()
    inventario = Inventario()
    inventario.agregar_producto(Producto(
        "Secreto ibérico", "Carnes", 1, "kg", 14, "Carnicería Pepe", stock_minimo=0.5,
        fecha_caducidad=hoy + timedelta(days=3),
    ))
    # Una compra nueva: otro lote, con otra caducidad, otro proveedor y otro precio.
    inventario.entrada_stock(
        "Secreto ibérico", 0.8, precio_unitario=15, proveedor="Ibéricos Sierra",
        fecha_caducidad=hoy + timedelta(days=8),
    )

    print("\n--- Inventario completo (con sus lotes) ---")
    inventario.listar_todos()

    secreto = inventario.buscar_producto("Secreto ibérico")
    print(f"\nStock total: {secreto.stock} kg | Precio medio: {secreto.precio_unitario} €/kg")
    print(f"Caducidad más próxima: {secreto.fecha_caducidad.strftime('%d/%m/%Y')}")

    # Quien usa el programa decide de qué lote sale: aquí, del que caduca MÁS TARDE.
    lote_tardio = secreto.lotes_ordenados()[-1]
    inventario.salida_stock("Secreto ibérico", 0.3, "consumo", lote_tardio.id)

    print("\n--- Lotes próximos a caducar (7 días) ---")
    for producto, lote in inventario.lotes_proximos_a_caducar():
        print(f"{producto.nombre}: {lote.descripcion(producto.unidad)}")

    print("\n--- Historial ---")
    for movimiento in inventario.historial:
        print(movimiento)
