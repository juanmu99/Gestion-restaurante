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

from datetime import date, datetime, timedelta
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


# ---------- IVA ----------
# Cada precio se guarda SIN IVA (la "base") junto a su tipo de IVA. Lo que se
# VE en todo el programa es lo pagado de verdad: CON IVA (precio_unitario).
#
# El ajuste del negocio solo cambia la RENTABILIDAD de los servicios:
#   - iva_recuperable = True (régimen general): el IVA de las compras se
#     recupera en las declaraciones trimestrales de IVA (modelo 303), así que
#     el coste de un servicio para calcular su margen es SIN IVA.
#   - iva_recuperable = False (p. ej. recargo de equivalencia): ese IVA no se
#     recupera, así que el coste del servicio es CON IVA.
AJUSTES = {"iva_recuperable": True, "iva_cobro": 10.0}

# Tipos de IVA de España para comprar: general, reducido, superreducido y sin IVA.
TIPOS_IVA = {"21 % (general)": 21.0, "10 % (reducido)": 10.0, "4 % (superreducido)": 4.0, "Sin IVA": 0.0}
IVA_POR_DEFECTO = 21.0


def nombre_iva(iva: float) -> str:
    """'21 % (general)', 'Sin IVA'... (o '7 %' si es un tipo que no está en la lista)."""
    return next((nombre for nombre, valor in TIPOS_IVA.items() if abs(valor - iva) < 1e-9), f"{iva:g} %")


def precio_a_coste(precio: float, incluye_iva: bool, iva: float) -> float:
    """Un precio tal y como se apunta (con o sin IVA) -> lo pagado de verdad, CON IVA."""
    return precio if incluye_iva else precio * (1 + iva / 100)


class ConPrecio:
    """
    Precio guardado SIN IVA (`precio_base`) y su tipo de IVA (`iva`, en %).
    `precio_unitario` es lo pagado de verdad (CON IVA): es lo que se ve y se
    suma en todo el programa. Al asignarlo, se interpreta también con IVA.
    """

    iva: float = 0.0
    precio_base: float = 0.0

    @property
    def precio_unitario(self) -> float:
        # 10 decimales: solo quita el "ruido" de los cálculos con decimales
        # (14.000000000000002). Redondear a menos perdía dinero en productos
        # en gramos o mililitros (0,00062 €/g).
        return round(self.precio_base * (1 + self.iva / 100), 10)

    @precio_unitario.setter
    def precio_unitario(self, valor: float) -> None:
        self.precio_base = valor / (1 + self.iva / 100)

    @property
    def precio_con_iva(self) -> float:
        return self.precio_unitario


class MovimientoStock(ConPrecio):
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
        iva: float = 0.0,
        precio_base: Optional[float] = None,
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
        # El IVA de la compra de la que viene (0 si no aplica). Ver ConPrecio.
        self.iva = iva
        if precio_base is not None:
            self.precio_base = precio_base
        else:
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
        """Valor económico de este movimiento (cantidad x precio en ese momento, con IVA)."""
        return round(self.cantidad * self.precio_unitario, 2)

    def valor_sin_iva(self) -> float:
        return round(self.cantidad * self.precio_base, 2)

    def valor_iva(self) -> float:
        """El IVA de este movimiento (lo pagado de IVA, si es una compra)."""
        return round(self.cantidad * self.precio_base * self.iva / 100, 2)

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
            "precio_base": self.precio_base,
            "iva": self.iva,
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
            precio_unitario=0,
            # Sesiones de antes del IVA: su precio se toma tal cual, sin IVA aparte.
            precio_base=datos.get("precio_base", datos.get("precio_unitario", 0)),
            iva=datos.get("iva", 0.0),
            fecha=date.fromisoformat(datos["fecha"]),
            motivo=datos.get("motivo"),
            lote_id=datos.get("lote_id"),
            lote=datos.get("lote"),
            tipo_producto=datos.get("tipo_producto", "alimento"),
            servicio_id=datos.get("servicio_id"),
        )


class ConNotas:
    """
    Una ANOTACIÓN libre (un bloc de notas) para elaboraciones base, recetas y
    menús: lo que el usuario quiera explicar a sus compañeros ("pochar a
    fuego lento 40 min, sin dorar"). Una sola nota por elemento, que se
    reescribe; se guarda también la fecha en que se cambió por última vez.
    """

    notas: str = ""
    notas_fecha: Optional[date] = None

    def poner_nota(self, texto: str, fecha: Optional[date] = None) -> None:
        """Cambia la nota (texto vacío = borrarla)."""
        texto = (texto or "").strip()
        if texto == self.notas:
            return
        self.notas = texto
        self.notas_fecha = (fecha or date.today()) if texto else None

    def _notas_dict(self) -> dict:
        return {"notas": self.notas, "notas_fecha": self.notas_fecha.isoformat() if self.notas_fecha else None}

    def _cargar_notas(self, datos: dict) -> None:
        # .get(): las sesiones guardadas antes de las anotaciones no las tienen.
        self.notas = datos.get("notas", "") or ""
        fecha = datos.get("notas_fecha")
        self.notas_fecha = date.fromisoformat(fecha) if fecha else None


class Lote(ConPrecio):
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
        iva: float = 0.0,
        precio_base: Optional[float] = None,
    ):
        if cantidad < 0:
            raise ValueError("La cantidad de un lote no puede ser negativa.")
        if precio_unitario < 0:
            raise ValueError("El precio no puede ser negativo.")
        if procedencia not in self.PROCEDENCIAS:
            raise ValueError(f"Procedencia no válida: {procedencia}")
        self.id = id
        self.cantidad = cantidad
        # Precio sin IVA + tipo de IVA de esta compra (ver ConPrecio). Lo
        # que sale de una limpieza o una elaboración no lleva IVA propio (0).
        self.iva = iva
        if precio_base is not None:
            self.precio_base = precio_base
        else:
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

    def esta_caducado(self, en_fecha: Optional[date] = None) -> bool:
        """True si ya ha caducado (o si habrá caducado en `en_fecha`, si se indica)."""
        if self.fecha_caducidad is None:
            return False
        return self.fecha_caducidad < (en_fecha or date.today())

    def etiqueta(self) -> str:
        """Descripción corta para el historial y los desplegables: 'Lote 2 · cad. 15/10/2026 · Carnicería Pepe'."""
        caducidad = f"cad. {self.fecha_caducidad.strftime('%d/%m/%Y')}" if self.fecha_caducidad else "sin caducidad"
        return f"Lote {self.id} · {caducidad} · {self.proveedor}"

    def descripcion(self, unidad: str) -> str:
        """Descripción completa, con la cantidad que queda y el precio."""
        precio = self.precio_unitario
        precio_txt = f"{round(precio, 2):g}" if precio == 0 or precio >= 1 else f"{precio:.3g}"  # 0,0125 €/g, no 0,013
        texto = f"{self.etiqueta()} · {_numero(self.cantidad)} {unidad} · {precio_txt} €/{unidad}"
        if self.peso_unitario:
            texto += f" · {_numero(self.peso_unitario)} kg/unidad"
        return texto

    def __str__(self) -> str:
        return self.etiqueta()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cantidad": self.cantidad,
            "precio_base": self.precio_base,
            "iva": self.iva,
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
            precio_unitario=0,
            precio_base=datos.get("precio_base", datos.get("precio_unitario", 0)),
            iva=datos.get("iva", 0.0),
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


class Producto(ConNotas):
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
    # alimento: se cocina (ingredientes de recetas y elaboraciones).
    # consumible: se gasta por comensal en los menús (servilletas, vasos...).
    # mantenimiento: limpieza y mantenimiento (lejía, bayetas, gas...). No va
    #   en recetas ni en menús: se gasta a mano, para un servicio o en general.
    TIPOS = ("alimento", "consumible", "mantenimiento")
    NOMBRES_TIPOS = {"alimento": "Alimento", "consumible": "Consumible", "mantenimiento": "Limpieza y mantenimiento"}

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
        iva: float = IVA_POR_DEFECTO,
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

        tipo: "alimento" (por defecto), "consumible" o "mantenimiento". Solo
        los alimentos tienen merma. Un consumible no tiene caducidad (si se
        le pasa, se ignora); uno de mantenimiento puede tenerla o no.

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
        if tipo != "alimento" and (tiene_merma or origen or es_subproducto):
            raise ValueError("Solo los alimentos pueden tener merma o salir de una limpieza.")
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
        if iva < 0:
            raise ValueError("El IVA no puede ser negativo.")

        self.nombre = nombre
        # Tipo de IVA habitual de este producto (21, 10, 4 o 0 = sin IVA):
        # el que se aplica a sus compras. Cada lote guarda el suyo.
        self.iva = iva
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

    @property
    def precio_referencia(self) -> float:
        """Precio de la última compra, con IVA. Ver ConPrecio."""
        return round(self.precio_referencia_base * (1 + self.iva / 100), 10)

    @precio_referencia.setter
    def precio_referencia(self, valor: float) -> None:
        self.precio_referencia_base = valor / (1 + self.iva / 100)

    @property
    def precio_sin_iva(self) -> float:
        """Como precio_unitario, pero sin IVA (para la rentabilidad si el negocio recupera el IVA)."""
        stock = self.stock
        if stock <= 0:
            return self.precio_referencia_base
        return round(sum(l.cantidad * l.precio_base for l in self.lotes) / stock, 10)

    def es_consumible(self) -> bool:
        return self.tipo == "consumible"

    def es_alimento(self) -> bool:
        return self.tipo == "alimento"

    def es_mantenimiento(self) -> bool:
        return self.tipo == "mantenimiento"

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
        return round(sum(l.cantidad * l.precio_unitario for l in self.lotes) / stock, 10)

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

    def lotes_para_usar(self, en_fecha: Optional[date] = None) -> list[Lote]:
        """
        Sus lotes en el orden en que conviene gastarlos: primero los que
        siguen buenos (los que caducan antes, primero) y al final los ya
        caducados (en `en_fecha`, o hoy). Así nunca se propone un lote
        caducado mientras quede uno bueno.
        """
        return sorted(self.lotes, key=lambda l: (l.esta_caducado(en_fecha),) + _clave_caducidad(l))

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
        iva: Optional[float] = None,
    ) -> Lote:
        """
        Crea un lote nuevo con el siguiente número libre. No registra movimiento (eso lo hace Inventario).
        `iva`: el de este lote (por defecto, el del producto si es una compra; 0 si no).
        """
        lote = Lote(
            self.siguiente_lote, cantidad, precio_unitario, proveedor,
            fecha_caducidad=None if self.es_consumible() else fecha_caducidad,
            peso_unitario=(peso_unitario or self.peso_unitario_referencia) if self.unidad == "unidades" else None,
            procedencia=procedencia,
            # Solo lo comprado lleva IVA: lo que sale de limpiar o elaborar ya
            # tiene su coste calculado a partir de sus ingredientes.
            iva=iva if iva is not None else (self.iva if procedencia in ("compra", "inicial") else 0.0),
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
        if not self.es_alimento():
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

    @property
    def stock_bueno(self) -> float:
        """El stock que NO ha caducado (lo que de verdad se puede usar hoy)."""
        return round(sum(l.cantidad for l in self.lotes if not l.esta_caducado()), 6)

    def dias_para_caducar_bueno(self) -> Optional[int]:
        """Días hasta que caduque el primero de sus lotes BUENOS (None si ninguno bueno caduca)."""
        dias = [l.dias_para_caducar() for l in self.lotes
                if l.fecha_caducidad is not None and not l.esta_caducado() and l.cantidad > 0]
        return min(dias) if dias else None

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
            "precio_referencia_base": self.precio_referencia_base,
            "iva": self.iva,
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
            **self._notas_dict(),
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
            iva=datos.get("iva", IVA_POR_DEFECTO),
        )
        if "lotes" in datos:
            producto = cls(
                stock=0,
                precio_unitario=datos.get("precio_referencia", 0),
                lotes=[Lote.from_dict(d) for d in datos["lotes"]],
                siguiente_lote=datos.get("siguiente_lote", 1),
                **comun,
            )
        else:
            fecha = datos.get("fecha_caducidad")
            producto = cls(
                stock=datos["stock"],
                precio_unitario=datos["precio_unitario"],
                fecha_caducidad=date.fromisoformat(fecha) if fecha else None,
                **comun,
            )
        # Precio de referencia guardado sin IVA (las sesiones de antes del IVA lo tenían tal cual).
        producto.precio_referencia_base = datos.get(
            "precio_referencia_base", datos.get("precio_referencia", datos.get("precio_unitario", 0))
        )
        if "precio_referencia_base" not in datos:
            # Sesiones de antes del IVA: aquel precio era lo pagado; el producto
            # tiene ahora un tipo de IVA, así que se guarda la parte sin IVA
            # (si no, al mostrarlo con IVA subiría un 21 %).
            producto.precio_referencia_base = producto.precio_referencia_base / (1 + producto.iva / 100)
        if "lotes" not in datos:
            for lote in producto.lotes:  # sesiones muy antiguas: el precio, tal cual y sin IVA aparte
                lote.iva = 0.0
                lote.precio_base = datos["precio_unitario"]
        producto._cargar_notas(datos)
        return producto


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


class PrecioCompra(ConPrecio):
    """
    UNA compra en el HISTORIAL DE PRECIOS: qué se compró, cuándo, a quién,
    cuánto y a qué precio por unidad (kg, litro, unidad...). Se apunta en
    cada compra y también con el stock inicial al dar de alta un producto.
    No se borra aunque el lote se gaste: sirve para ver cómo cambian los
    precios con la temporada y comparar proveedores.
    """

    def __init__(
        self, producto: str, fecha: date, proveedor: str, cantidad: float, unidad: str, precio_unitario: float,
        lote_id: Optional[int] = None, origen: str = "compra", iva: float = 0.0, precio_base: Optional[float] = None,
    ):
        self.producto = producto
        self.fecha = fecha
        self.proveedor = proveedor
        self.cantidad = cantidad
        self.unidad = unidad
        self.iva = iva
        if precio_base is not None:
            self.precio_base = precio_base
        else:
            self.precio_unitario = precio_unitario
        self.lote_id = lote_id
        self.origen = origen  # "compra" o "inicial" (stock con el que se dio de alta)

    @property
    def total(self) -> float:
        return round(self.cantidad * self.precio_unitario, 2)

    def to_dict(self) -> dict:
        return {
            "producto": self.producto, "fecha": self.fecha.isoformat(), "proveedor": self.proveedor,
            "cantidad": self.cantidad, "unidad": self.unidad, "precio_base": self.precio_base, "iva": self.iva,
            "lote_id": self.lote_id, "origen": self.origen,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "PrecioCompra":
        return cls(
            datos["producto"], date.fromisoformat(datos["fecha"]), datos["proveedor"], datos["cantidad"],
            datos["unidad"], 0, datos.get("lote_id"), datos.get("origen", "compra"), datos.get("iva", 0.0),
            precio_base=datos.get("precio_base", datos.get("precio_unitario", 0)),
        )


class Inventario:
    """Gestiona una colección de productos: altas, bajas, consultas..."""

    # Avisos de precio (Dashboard): una compra de los últimos DIAS_AVISO_PRECIO
    # días cuyo precio se separa más de UMBRAL_AVISO_PRECIO de la media de las
    # compras anteriores (de los últimos VENTANA_PRECIO_HABITUAL días).
    DIAS_AVISO_PRECIO = 30
    VENTANA_PRECIO_HABITUAL = 180
    UMBRAL_AVISO_PRECIO = 0.20

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
        # Historial de precios: una fila por compra (ver PrecioCompra).
        self.historial_precios: list[PrecioCompra] = []

    # Los ajustes de IVA son de CADA inventario (AJUSTES solo da el valor
    # inicial): si fueran globales, dos ventanas del programa se los pisarían.
    @property
    def iva_recuperable(self) -> bool:
        """Ajuste del negocio: ¿recupera el IVA de sus compras (régimen general)? Ver AJUSTES."""
        return self.__dict__.setdefault("_iva_recuperable", AJUSTES["iva_recuperable"])

    @iva_recuperable.setter
    def iva_recuperable(self, valor: bool) -> None:
        self._iva_recuperable = bool(valor)

    @property
    def iva_cobro(self) -> float:
        """IVA que se cobra a los clientes (10 % en catering), para estimar el IVA del trimestre."""
        return self.__dict__.setdefault("_iva_cobro", AJUSTES["iva_cobro"])

    @iva_cobro.setter
    def iva_cobro(self, valor: float) -> None:
        if valor < 0:
            raise ValueError("El IVA no puede ser negativo.")
        self._iva_cobro = float(valor)

    def agregar_producto(self, producto: Producto) -> None:
        if producto.nombre in self.productos:
            print(f"⚠️  Ya existe '{producto.nombre}'. Registra una entrada para añadir un lote nuevo.")
            return
        self.productos[producto.nombre] = producto
        # El stock con el que se da de alta también tiene un precio: entra en el historial de precios.
        for lote in producto.lotes:
            if lote.procedencia in ("inicial", "compra"):
                self._apuntar_precio(producto, lote, lote.cantidad, "inicial")
        print(f"✅ Producto añadido: {producto.nombre}")

    # ---------- Historial de precios ----------

    def _apuntar_precio(self, producto: Producto, lote: Lote, cantidad: float, origen: str = "compra") -> None:
        self.historial_precios.append(PrecioCompra(
            producto.nombre, lote.fecha_entrada, lote.proveedor, cantidad, producto.unidad, 0,
            lote.id, origen, lote.iva, precio_base=lote.precio_base,
        ))

    def precios_de(self, nombre: str) -> list[PrecioCompra]:
        """Todas las compras de un producto, de la más antigua a la más reciente."""
        return sorted((p for p in self.historial_precios if p.producto == nombre), key=lambda p: p.fecha)

    def resumen_precios_por_proveedor(self, nombre: str) -> list[dict]:
        """
        Por cada proveedor de un producto: nº de compras, precio medio
        (ponderado por la cantidad comprada), mínimo, máximo y el de la
        última compra. Ordenado del más barato (de media) al más caro.
        """
        grupos: dict[str, list[PrecioCompra]] = {}
        for p in self.precios_de(nombre):
            grupos.setdefault(p.proveedor, []).append(p)
        filas = []
        for proveedor, compras in grupos.items():
            cantidad = sum(c.cantidad for c in compras)
            media = sum(c.cantidad * c.precio_unitario for c in compras) / cantidad if cantidad else 0
            filas.append({
                "proveedor": proveedor, "compras": len(compras), "medio": round(media, 4),
                "minimo": min(c.precio_unitario for c in compras), "maximo": max(c.precio_unitario for c in compras),
                "ultimo": compras[-1].precio_unitario, "fecha_ultima": compras[-1].fecha,
            })
        return sorted(filas, key=lambda f: f["medio"])

    def avisos_precios(self, hoy: Optional[date] = None) -> list[dict]:
        """
        Compras RECIENTES (últimos DIAS_AVISO_PRECIO días) cuyo precio se
        separa más de un UMBRAL_AVISO_PRECIO de lo habitual: la media
        (ponderada) de las compras ANTERIORES de ese producto en los últimos
        VENTANA_PRECIO_HABITUAL días. Solo la última compra de cada producto.
        Devuelve dicts con: producto, unidad, fecha, proveedor, precio,
        habitual, variacion (+0,35 = un 35 % más caro) y compras_anteriores.
        """
        hoy = hoy or date.today()
        avisos = []
        for nombre in sorted({p.producto for p in self.historial_precios}):
            compras = self.precios_de(nombre)
            ultima = compras[-1]
            if (hoy - ultima.fecha).days > self.DIAS_AVISO_PRECIO:
                continue
            anteriores = [
                c for c in compras[:-1]
                if 0 <= (ultima.fecha - c.fecha).days <= self.VENTANA_PRECIO_HABITUAL
            ]
            cantidad = sum(c.cantidad for c in anteriores)
            if not anteriores or cantidad <= 0:
                continue
            habitual = sum(c.cantidad * c.precio_unitario for c in anteriores) / cantidad
            if habitual <= 0:
                continue
            variacion = ultima.precio_unitario / habitual - 1
            if abs(variacion) >= self.UMBRAL_AVISO_PRECIO - 1e-9:
                avisos.append({
                    "producto": nombre, "unidad": ultima.unidad, "fecha": ultima.fecha, "proveedor": ultima.proveedor,
                    "precio": ultima.precio_unitario, "habitual": round(habitual, 4), "variacion": round(variacion, 4),
                    "compras_anteriores": len(anteriores),
                })
        return sorted(avisos, key=lambda a: -abs(a["variacion"]))

    def eliminar_producto(self, nombre: str) -> None:
        if nombre in self.productos:
            del self.productos[nombre]
            print(f"🗑️  Producto eliminado: {nombre}")
        else:
            print(f"❌ No existe el producto '{nombre}'.")

    def donde_se_usa(self, nombre: str) -> list[str]:
        """
        Dónde se usa un producto DENTRO del inventario (lo que impide borrarlo):
        la fórmula de una elaboración base, o ser el producto en bruto del que
        sale un producto limpio. (Las recetas y los menús los mira el Recetario.)
        """
        usos = [f"la fórmula de la elaboración base '{b.nombre}'" for b in self.bases()
                if nombre in b.formula["ingredientes"]]
        usos += [f"el origen del producto limpio '{p.nombre}'" for p in self.productos.values() if p.origen == nombre]
        return usos

    def borrar_producto(self, nombre: str, otros_usos: Optional[list[str]] = None) -> float:
        """
        Borra un producto que ya no se usa. No se puede si se usa en algún
        sitio (`otros_usos`: recetas y menús, que mira quien llama; más
        donde_se_usa()). Si le queda stock, se quita SIN contar como
        desperdicio. Su historial (compras, consumos, precios) se conserva,
        para no descuadrar los meses pasados. Devuelve el stock que tenía.
        """
        producto = self.productos.get(nombre)
        if producto is None:
            raise ValueError(f"No existe el producto '{nombre}'.")
        usos = list(otros_usos or []) + self.donde_se_usa(nombre)
        if usos:
            raise ValueError(f"No se puede borrar '{nombre}': se usa en " + "; ".join(usos) + ".")
        stock = producto.stock
        del self.productos[nombre]
        print(f"🗑️  Producto borrado: {nombre}")
        return stock

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
            precio_unitario=0,
            precio_base=lote.precio_base,
            iva=lote.iva,
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
        iva: Optional[float] = None,
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

        lote = producto.nuevo_lote(cantidad, precio, proveedor, fecha_caducidad, peso_unitario, motivo, iva)
        if motivo == "compra":
            # "La última compra fue a…": solo las compras de verdad (no lo que
            # sale de una limpieza o una elaboración, ni un derivado a 0 €).
            producto.precio_referencia_base = lote.precio_base
        if lote.peso_unitario:
            producto.peso_unitario_referencia = lote.peso_unitario
        print(f"📦 Entrada: {cantidad} {producto.unidad} de {nombre} -> {lote.etiqueta()}")
        self._registrar(producto, lote, "entrada", cantidad, motivo)
        if motivo == "compra":
            self._apuntar_precio(producto, lote, cantidad)
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
        error = self.problema_salida(nombre, reparto, motivo)
        if error:
            print(f"❌ {error}")
            return False
        producto = self.productos[nombre]
        reparto = [(lote_id, cantidad) for lote_id, cantidad in reparto if cantidad > 0]
        for lote_id, cantidad in reparto:
            lote = producto.buscar_lote(lote_id)
            cantidad = min(cantidad, lote.cantidad)
            lote.cantidad = round(lote.cantidad - cantidad, 6)
            self._registrar(producto, lote, "salida", cantidad, motivo, servicio_id)
            print(f"📦 Salida ({motivo}): {_numero(cantidad)} {producto.unidad} de {nombre} [{lote.etiqueta()}]")
        producto.quitar_lotes_vacios()
        return True

    # ---------- Deshacer un servicio completado ----------

    def salidas_de_servicio(self, servicio_id: int) -> list[MovimientoStock]:
        """
        Lo que salió del inventario AL COMPLETAR un servicio: el consumo de
        alimentos y consumibles. (La limpieza y el mantenimiento que se
        apunta a mano para un servicio no se cuenta: no sale al completarlo.)
        """
        return [m for m in self.historial if m.servicio_id == servicio_id and m.tipo == "salida"
                and m.motivo == "consumo" and m.tipo_producto != "mantenimiento"]

    def devolver_salidas_servicio(self, servicio_id: int) -> list[MovimientoStock]:
        """
        Devuelve al inventario lo que salió al completar un servicio: cada
        cosa a su MISMO lote (si el lote ya se había gastado entero, se vuelve
        a crear con su número, precio, IVA, proveedor y caducidad). Esas
        salidas desaparecen del historial (y de Métricas). Comprueba todo
        antes de tocar nada. Devuelve las salidas devueltas.
        """
        salidas = self.salidas_de_servicio(servicio_id)
        faltan = sorted({m.producto_nombre for m in salidas if m.producto_nombre not in self.productos})
        if faltan:
            raise ValueError("Estos productos ya no existen en el inventario, así que no se les puede devolver lo "
                             "que se usó: " + ", ".join(faltan) + ".")
        for m in salidas:
            producto = self.productos[m.producto_nombre]
            lote = producto.buscar_lote(m.lote_id) if m.lote_id is not None else None
            if lote is None:
                lote = self._recrear_lote(producto, m)
            lote.cantidad = round(lote.cantidad + m.cantidad, 6)
        devueltas = {id(m) for m in salidas}
        self.historial = [m for m in self.historial if id(m) not in devueltas]
        print(f"↩️  Devuelto al inventario lo usado en el servicio #{servicio_id} ({len(salidas)} salida(s)).")
        return salidas

    def _recrear_lote(self, producto: Producto, salida: MovimientoStock) -> Lote:
        """Vuelve a crear (vacío) el lote del que salió `salida`, con los datos que guarda el historial."""
        proveedor, caducidad = producto.proveedor, None
        partes = (salida.lote or "").split(" · ", 2)
        if len(partes) == 3:
            proveedor = partes[2] or proveedor
            if partes[1].startswith("cad. "):
                try:
                    caducidad = datetime.strptime(partes[1][5:], "%d/%m/%Y").date()
                except ValueError:
                    caducidad = None
        entrada = next((m for m in self.historial if m.producto_nombre == producto.nombre and m.tipo == "entrada"
                        and m.lote_id == salida.lote_id), None)
        procedencia = {"compra": "compra", "limpieza": "limpieza", "elaboración": "elaboración"}.get(
            entrada.motivo if entrada else "", "compra")
        lote_id = salida.lote_id
        if lote_id is None:
            lote_id = producto.siguiente_lote
            producto.siguiente_lote += 1
        lote = Lote(
            lote_id, 0, 0, proveedor, fecha_entrada=entrada.fecha if entrada else salida.fecha,
            fecha_caducidad=caducidad,
            peso_unitario=producto.peso_unitario_referencia if producto.unidad == "unidades" else None,
            procedencia=procedencia, iva=salida.iva, precio_base=salida.precio_base,
        )
        producto.lotes.append(lote)
        return lote

    def problema_salida(self, nombre: str, reparto: list[tuple[int, float]], motivo: str = "consumo") -> Optional[str]:
        """
        Comprueba (SIN tocar nada) si se puede hacer una salida repartida.
        Devuelve el motivo por el que no se puede, o None si se puede.
        """
        producto = self.productos.get(nombre)
        if producto is None:
            return f"No existe el producto '{nombre}'."
        if motivo not in MovimientoStock.MOTIVOS_SALIDA_VALIDOS:
            return f"Motivo no válido. Debe ser uno de: {', '.join(MovimientoStock.MOTIVOS_SALIDA)}"
        reparto = [(lote_id, cantidad) for lote_id, cantidad in reparto if cantidad > 0]
        if not reparto:
            return "La cantidad debe ser mayor que 0."
        por_lote: dict[int, float] = {}
        for lote_id, cantidad in reparto:
            por_lote[lote_id] = por_lote.get(lote_id, 0) + cantidad
        for lote_id, cantidad in por_lote.items():
            lote = producto.buscar_lote(lote_id)
            if lote is None:
                return f"'{nombre}' no tiene el lote {lote_id}."
            # Pequeño margen para que los decimales de coma flotante no impidan
            # sacar exactamente todo lo que hay (ej: 0.30000000000000004).
            if cantidad > lote.cantidad + 1e-6:
                return (f"En el lote {lote_id} de '{nombre}' solo hay {_numero(lote.cantidad)} {producto.unidad}, "
                        f"intentas sacar {_numero(cantidad)}. El stock nunca puede quedar en negativo.")
        return None

    def compra_para_servicio(
        self,
        nombre: str,
        comprada: float,
        usada: float,
        importe_total: float,
        servicio_id: int,
        proveedor: Optional[str] = None,
        fecha_caducidad: Optional[date] = None,
        importe_incluye_iva: bool = True,
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

        precio = precio_a_coste(importe_total / comprada, importe_incluye_iva, producto.iva)
        lote = self.entrada_stock(
            nombre, comprada, precio_unitario=precio,
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
            # Redondeado, pero nunca por encima de lo que hay en el lote (un lote
            # con más de 6 decimales hacía que la salida se rechazara).
            sale = min(round(min(pendiente, lote.cantidad), 6), lote.cantidad)
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
        corregir_registrado: bool = False,
    ) -> bool:
        """
        CORRIGE los datos de un lote (un error al apuntarlo, un recuento...).
        No es un movimiento de stock: no queda en el historial. Para registrar
        que algo se ha gastado o tirado, usa una salida.

        None = "no lo toques". borrar_fecha_caducidad=True deja el lote sin
        caducidad. Una cantidad de 0 elimina el lote.

        corregir_registrado: si se cambia el precio (o el proveedor) y es
        True, se corrige también lo YA REGISTRADO con este lote: su compra
        (Métricas), el historial de precios y lo que ya salió de él (coste
        de servicios, desperdicio...). Ver usos_del_lote(). Si es False,
        solo cambia el lote: lo que salga a partir de ahora.
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

        if corregir_registrado:
            self._corregir_registrado(producto.nombre, lote.id, precio_unitario, proveedor)
        if cantidad is not None:
            lote.cantidad = cantidad
        if precio_unitario is not None:
            lote.precio_unitario = precio_unitario
            if self._es_ultima_compra(producto.nombre, lote.id):
                producto.precio_referencia_base = lote.precio_base
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

    def usos_del_lote(self, nombre: str, lote_id: int) -> dict:
        """
        Lo que ya se ha registrado con un lote y depende de su precio:
        - compra: su entrada (cuenta como dinero gastado en Métricas) o None.
        - salidas: lo que ya salió de él (consumo, desperdicio...), con su servicio si lo tiene.
        - servicios: {servicio_id: valor de lo que salió para ese servicio}.
        - derivados: salidas para elaborar o limpiar. Su coste ya pasó a
          otra cosa (una tanda, una elaboración base, un producto limpio), y
          eso NO se recalcula al corregir el precio.
        """
        movimientos = [m for m in self.historial if m.producto_nombre == nombre and m.lote_id == lote_id]
        compra = next((m for m in movimientos if m.es_compra()), None)
        salidas = [m for m in movimientos if m.tipo == "salida"]
        servicios: dict[int, float] = {}
        for m in salidas:
            if m.servicio_id is not None:
                servicios[m.servicio_id] = round(servicios.get(m.servicio_id, 0) + m.valor(), 2)
        return {
            "compra": compra,
            "salidas": salidas,
            "servicios": servicios,
            "derivados": [m for m in salidas if m.motivo in ("elaboración", "limpieza")],
        }

    def corregir_compra(
        self, compra: "PrecioCompra", precio_unitario: Optional[float] = None, proveedor: Optional[str] = None,
        cantidad: Optional[float] = None, iva: Optional[float] = None, iva_tambien_producto: bool = True,
    ) -> None:
        """
        Corrige una compra del HISTORIAL DE PRECIOS (un error al apuntarla),
        aunque su lote ya se haya gastado: se corrige todo lo registrado con
        ese lote (Métricas, IVA, historial de precios, coste de lo que ya
        salió) y el lote, si sigue. None = "no lo toques".

        - precio_unitario / proveedor: ver _corregir_registrado.
        - cantidad: lo que se compró de verdad. Lo que queda en el lote se
          ajusta en la diferencia (se compraron 5 kg, no 50, y se usaron 2:
          quedan 3). No puede ser menos de lo que ya se ha usado.
        - iva: el tipo de IVA correcto. Se mantiene lo que se pagó (con IVA)
          y se recalcula la parte sin IVA y el IVA soportado. Con
          iva_tambien_producto, el producto usa ese IVA en las próximas compras.

        Las compras sin número de lote (sesiones muy antiguas) solo se
        corrigen en el historial de precios.
        """
        if precio_unitario is not None and precio_unitario < 0:
            raise ValueError("El precio no puede ser negativo.")
        if proveedor is not None and (not proveedor.strip() or _es_numero(proveedor)):
            raise ValueError("El proveedor debe ser texto descriptivo, no puede estar vacío ni ser un número")
        if cantidad is not None and cantidad <= 0:
            raise ValueError("La cantidad comprada debe ser mayor que 0. Si la compra no existió, anúlala.")
        if iva is not None and iva < 0:
            raise ValueError("El IVA no puede ser negativo.")
        producto = self.productos.get(compra.producto)
        lote = producto.buscar_lote(compra.lote_id) if producto and compra.lote_id is not None else None

        if cantidad is not None and abs(cantidad - compra.cantidad) > 1e-9 and compra.lote_id is not None:
            diferencia = cantidad - compra.cantidad
            if lote is None:
                raise ValueError(
                    "Ese lote ya se ha gastado entero, así que su cantidad ya no se puede corregir aquí "
                    "(el precio y el IVA sí)."
                )
            if lote.cantidad + diferencia < -1e-9:
                usado = compra.cantidad - lote.cantidad
                raise ValueError(
                    f"De esta compra ya se han usado {_numero(usado)} {producto.unidad}: no puede ser de "
                    f"{_numero(cantidad)}. Revisa la cantidad."
                )

        # --- Validado: se aplica ---
        if compra.lote_id is None:
            if iva is not None:
                pagado = compra.precio_unitario
                compra.iva = iva
                compra.precio_unitario = pagado
            if precio_unitario is not None:
                compra.precio_unitario = precio_unitario
            if proveedor is not None:
                compra.proveedor = proveedor.strip()
            if cantidad is not None:
                compra.cantidad = cantidad
            return

        nombre = compra.producto
        if iva is not None:
            self._corregir_iva_registrado(nombre, compra.lote_id, iva)
            if producto is not None and iva_tambien_producto:
                pagado = producto.precio_referencia
                producto.iva = iva
                producto.precio_referencia = pagado
        if cantidad is not None and abs(cantidad - compra.cantidad) > 1e-9:
            diferencia = cantidad - compra.cantidad
            for m in self.historial:
                if m.producto_nombre == nombre and m.lote_id == compra.lote_id and m.es_compra():
                    m.cantidad = cantidad
            for p in self.historial_precios:
                if p.producto == nombre and p.lote_id == compra.lote_id:
                    p.cantidad = cantidad
            lote.cantidad = max(0.0, round(lote.cantidad + diferencia, 6))
        if lote is not None and (precio_unitario is not None or proveedor is not None):
            self.editar_lote(nombre, compra.lote_id, precio_unitario=precio_unitario, proveedor=proveedor,
                             corregir_registrado=True)
        elif precio_unitario is not None or proveedor is not None:
            self._corregir_registrado(nombre, compra.lote_id, precio_unitario, proveedor)
        if producto is not None and self._es_ultima_compra(nombre, compra.lote_id):
            producto.precio_referencia = compra.precio_unitario
        if producto is not None:
            producto.quitar_lotes_vacios()

    def _corregir_iva_registrado(self, nombre: str, lote_id: int, iva: float) -> None:
        """Cambia el IVA de un lote y de todo lo registrado con él, manteniendo lo pagado (con IVA)."""
        producto = self.productos.get(nombre)
        lote = producto.buscar_lote(lote_id) if producto else None
        registros = [m for m in self.historial if m.producto_nombre == nombre and m.lote_id == lote_id]
        registros += [p for p in self.historial_precios if p.producto == nombre and p.lote_id == lote_id]
        if lote is not None:
            registros.append(lote)
        for r in registros:
            pagado = r.precio_unitario
            r.iva = iva
            r.precio_unitario = pagado

    def se_puede_anular(self, compra: "PrecioCompra") -> tuple[bool, str]:
        """(True, "") si la compra se puede anular; si no, (False, por qué)."""
        if compra.lote_id is None:
            return False, "Es una compra muy antigua (sin número de lote): no se puede anular."
        producto = self.productos.get(compra.producto)
        lote = producto.buscar_lote(compra.lote_id) if producto else None
        usada = any(m.producto_nombre == compra.producto and m.lote_id == compra.lote_id and m.tipo == "salida"
                    for m in self.historial)
        if lote is None or usada or abs(lote.cantidad - compra.cantidad) > 1e-9:
            return False, ("De esta compra ya se ha usado algo: no se puede anular sin descuadrar lo ya "
                           "registrado. Corrígela (cantidad, precio o IVA) en su lugar.")
        return True, ""

    def anular_compra(self, compra: "PrecioCompra") -> None:
        """
        Borra una compra apuntada por error (o dos veces): su lote, su gasto
        (Métricas e IVA) y su línea del historial de precios. "La última
        compra fue a…" vuelve a la compra anterior. Solo si de ese lote no ha
        salido nada todavía (ver se_puede_anular).
        """
        posible, motivo = self.se_puede_anular(compra)
        if not posible:
            raise ValueError(motivo)
        nombre, lote_id = compra.producto, compra.lote_id
        producto = self.productos[nombre]
        era_la_ultima = self._es_ultima_compra(nombre, lote_id)
        producto.lotes = [l for l in producto.lotes if l.id != lote_id]
        self.historial = [m for m in self.historial if not (m.producto_nombre == nombre and m.lote_id == lote_id)]
        self.historial_precios = [p for p in self.historial_precios
                                  if not (p.producto == nombre and p.lote_id == lote_id)]
        anteriores = self.precios_de(nombre)
        if era_la_ultima and anteriores:
            producto.precio_referencia = anteriores[-1].precio_unitario
        print(f"🗑️  Compra anulada: lote {lote_id} de '{nombre}'.")

    def _es_ultima_compra(self, nombre: str, lote_id: Optional[int]) -> bool:
        """True si ese lote es la compra más reciente del producto (la de "la última compra fue a…")."""
        compras = self.precios_de(nombre)
        return lote_id is not None and bool(compras) and compras[-1].lote_id == lote_id

    def _corregir_registrado(
        self, nombre: str, lote_id: int, precio: Optional[float], proveedor: Optional[str],
    ) -> None:
        """Pone el precio (y el proveedor) corregidos en todo lo ya registrado con este lote."""
        for m in self.historial:
            if m.producto_nombre == nombre and m.lote_id == lote_id:
                if precio is not None:
                    m.precio_unitario = precio
                if proveedor is not None and m.lote:
                    partes = m.lote.split(" · ")
                    m.lote = " · ".join(partes[:-1] + [proveedor.strip()])
        for p in self.historial_precios:
            if p.producto == nombre and p.lote_id == lote_id:
                if precio is not None:
                    p.precio_unitario = precio
                if proveedor is not None:
                    p.proveedor = proveedor.strip()

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
            if existente is not None and not existente.es_alimento():
                raise ValueError(f"'{nombre}' no es un alimento: no puede salir de una limpieza.")
            if existente is not None and existente.es_base():
                raise ValueError(f"'{nombre}' es una elaboración base: no puede salir de una limpieza. "
                                 "Elige otro nombre.")
        if principal is not None:
            # Una elaboración base no sale de una limpieza: aceptarlo dejaba la
            # sesión imposible de volver a abrir.
            if principal.es_base():
                raise ValueError(f"'{producto_limpio}' es una elaboración base: no puede salir de una limpieza. "
                                 "Elige otro nombre para el producto limpio.")
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
            # Nace con el IVA del producto en bruto (pata al 10 % -> carne limpia al 10 %).
            principal = Producto(
                producto_limpio, origen.categoria, 0, unidad_nueva, 0, "Elaboración propia", origen=nombre_origen,
                iva=origen.iva,
            )
            self.agregar_producto(principal)
        elif principal.origen is None:
            # Ya existía (quizá se compraba limpio): desde ahora se sabe que también sale de aquí.
            principal.origen = nombre_origen
        for nombre in derivados_kg:
            if nombre not in self.productos:
                self.agregar_producto(Producto(
                    nombre, origen.categoria, 0, unidad_nueva, 0, "Elaboración propia", es_subproducto=True,
                    iva=origen.iva,
                ))

        self.salida_stock(nombre_origen, cantidad, "limpieza", lote_id)

        # El lote limpio carga con todo el coste de lo que se limpió.
        cantidad_limpio = round(convertir(peso_limpio_kg, "kg", principal.unidad), 6)
        self.entrada_stock(
            producto_limpio, cantidad_limpio, precio_unitario=coste / cantidad_limpio,
            proveedor="Elaboración propia", fecha_caducidad=caducidades.get(producto_limpio), motivo="limpieza",
            iva=lote.iva,  # su coste es el del bruto: lleva el mismo IVA (y se separa igual)
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
        iva: Optional[float] = None,
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

        tipo: "alimento", "consumible" o "mantenimiento" (por si se dio de alta
        en el tipo equivocado). Al dejar de ser alimento se quita la merma; al
        pasar a consumible, también la caducidad de sus lotes.

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
        if iva is not None and iva < 0:
            raise ValueError("El IVA no puede ser negativo.")
        tipo_final = tipo if tipo is not None else producto.tipo
        if tipo_final not in Producto.TIPOS:
            raise ValueError(f"Tipo de producto no válido: '{tipo_final}'.")
        merma_final = tiene_merma if tiene_merma is not None else producto.tiene_merma
        if tipo_final != "alimento":
            if producto.origen or producto.es_subproducto:
                raise ValueError("Este producto sale de una limpieza: tiene que ser un alimento.")
            merma_final = False
        if producto.es_base() and (tipo_final != "alimento" or merma_final):
            raise ValueError("Una elaboración base es un alimento sin merma.")
        if tipo_final != "alimento" and any(nombre_actual in b.formula["ingredientes"] for b in self.bases()):
            raise ValueError("Este producto es ingrediente de una elaboración base: tiene que ser un alimento.")
        peso_final = peso_unitario if peso_unitario is not None else producto.peso_unitario
        _validar_merma(producto.unidad, merma_final, peso_final)

        if nuevo_nombre is not None:
            nuevo_nombre = nuevo_nombre.strip()
            if not nuevo_nombre:
                raise ValueError("El nombre del producto no puede quedar vacío.")
        if nuevo_nombre is not None and nuevo_nombre != nombre_actual:
            # Tampoco con otras mayúsculas ("Tomate" y "tomate" serían el mismo producto).
            if any(n.lower() == nuevo_nombre.lower() and n != nombre_actual for n in self.productos):
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
        if iva is not None:
            # Solo para las compras de aquí en adelante: cada lote ya comprado
            # guarda su IVA. "La última compra fue a…" sigue siendo lo que se
            # pagó (con IVA): solo cambia cómo se reparte entre base e IVA.
            pagado = producto.precio_referencia
            producto.iva = iva
            producto.precio_referencia = pagado

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
        for precio in self.historial_precios:
            if precio.producto == antiguo:
                precio.producto = nuevo

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
            if not producto.es_alimento():
                raise ValueError(f"'{ingrediente}' no es un alimento: no puede ser ingrediente.")
            if ingrediente == nombre or self._lleva(ingrediente, nombre):
                raise ValueError(f"'{ingrediente}' ya lleva '{nombre}': las fórmulas no pueden ir en círculo.")

    def definir_base(
        self, nombre: str, categoria: str, unidad: str, cantidad: float, ingredientes: dict[str, float],
        vida_util_dias: Optional[int] = None, stock_minimo: float = 0, notas: str = "",
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
        producto.poner_nota(notas)
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

    def coste_estimado_base(
        self, nombre: str, cantidad: float = 1, vistos: Optional[set] = None, sin_iva: bool = False,
    ) -> float:
        """
        Lo que costaría preparar `cantidad` de una elaboración base con los
        precios actuales (con IVA, o sin él si `sin_iva`). Si un ingrediente es
        otra base sin stock, se estima con SU fórmula.
        """
        vistos = vistos or set()
        producto = self.productos.get(nombre)
        if producto is None or not producto.es_base() or nombre in vistos:
            return 0.0
        factor = cantidad / producto.formula["cantidad"]
        total = 0.0
        for ingrediente, c in producto.formula["ingredientes"].items():
            total += self.precio_de(ingrediente, sin_iva, vistos | {nombre}) * c * factor
        return round(total, 10)

    def precio_de(self, nombre: str, sin_iva: bool = False, vistos: Optional[set] = None) -> float:
        """
        Precio por unidad de un producto para ESTIMAR costes (recetas, menús,
        servicios pendientes): el medio de lo que hay en stock; sin stock, el de
        la última compra. Una elaboración base sin stock se calcula con su
        fórmula (antes contaba como 0 € si aún no se había preparado nunca).
        """
        producto = self.productos.get(nombre)
        if producto is None:
            return 0.0
        if producto.es_base() and producto.stock <= 0:
            return self.coste_estimado_base(nombre, 1, vistos, sin_iva)
        return producto.precio_sin_iva if sin_iva else producto.precio_unitario

    def buscar_producto(self, nombre: str) -> Optional[Producto]:
        return self.productos.get(nombre)

    def alimentos(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.es_alimento()]

    def consumibles(self) -> list[Producto]:
        return [p for p in self.productos.values() if p.es_consumible()]

    def mantenimiento(self) -> list[Producto]:
        """Productos de limpieza y mantenimiento (lejía, bayetas, gas...)."""
        return [p for p in self.productos.values() if p.es_mantenimiento()]

    def productos_de(self, tipo: str) -> list[Producto]:
        return [p for p in self.productos.values() if p.tipo == tipo]

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

    def valor_productos(self) -> float:
        """Lo que vale el stock de los productos (a precio de cada lote)."""
        return round(sum(p.valor_total() for p in self.productos.values()), 2)

    def valor_tandas(self) -> float:
        """Lo que valen las raciones ya preparadas (su coste por ración)."""
        return round(sum(t.valor() for t in self.elaboraciones.tandas), 2)

    def valor_total_inventario(self) -> float:
        """Productos + raciones preparadas (antes no contaba las tandas: lo preparado "desaparecía" del valor)."""
        return round(self.valor_productos() + self.valor_tandas(), 2)

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
            "historial_precios": [p.to_dict() for p in self.historial_precios],
            "iva_recuperable": self.iva_recuperable,
            "iva_cobro": self.iva_cobro,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Inventario":
        inventario = cls()
        # Ajustes de IVA (las sesiones de antes no los tienen: se deja el que haya).
        if "iva_recuperable" in datos:
            inventario.iva_recuperable = datos["iva_recuperable"]
        elif "costes_con_iva" in datos:
            inventario.iva_recuperable = not datos["costes_con_iva"]
        if "iva_cobro" in datos:
            inventario.iva_cobro = datos["iva_cobro"]
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
        if "historial_precios" in datos:
            inventario.historial_precios = [PrecioCompra.from_dict(d) for d in datos["historial_precios"]]
        else:
            # Sesiones de antes del historial de precios: se reconstruye con
            # las compras que ya estaban en el historial de movimientos.
            for m in inventario.historial:
                if m.es_compra():
                    proveedor = m.lote.split(" · ")[-1] if m.lote else ""
                    producto = inventario.productos.get(m.producto_nombre)
                    proveedor = proveedor or (producto.proveedor if producto else "")
                    inventario.historial_precios.append(PrecioCompra(
                        m.producto_nombre, m.fecha, proveedor, m.cantidad, m.unidad, 0, m.lote_id,
                        iva=m.iva, precio_base=m.precio_base,
                    ))
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
