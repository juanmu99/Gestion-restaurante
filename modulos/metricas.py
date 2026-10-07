"""
Módulo: metricas.py
---------------------
Calcula informes a partir del historial de movimientos de stock del
inventario: cuánto se ha consumido de un producto, cuánto se ha
desperdiciado, qué productos se usan más, y cuánto dinero se ha
gastado por categoría -- todo filtrable por un rango de fechas.

No almacena nada propio: solo LEE inventario.historial y lo resume de
distintas formas. Mismo patrón "fachada" que ya usamos en Dashboard
(Módulo 5): una clase que no tiene datos propios, solo consulta a otra.

Conceptos de Python nuevos en este módulo:
- timedelta para calcular "hace N días" a partir de hoy
- Comprehensions de diccionario con acumulación (parecido a lo que ya
  hiciste en compras.py y recetario.py)
"""

from datetime import date, timedelta
from typing import Optional
import calendar

from inventario import Inventario, MovimientoStock

PERIODOS_VALIDOS = ("semana", "mes", "trimestre", "año", "todo")

# Índice 0 sin usar a propósito, así NOMBRES_MESES[mes] funciona directo
# con los meses tal como los conocemos (1 = enero, ... 12 = diciembre).
NOMBRES_MESES = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_DIAS_POR_PERIODO = {
    "semana": 7,
    "mes": 30,
    "trimestre": 90,
    "año": 365,
}


def rango_desde_periodo(periodo: str) -> tuple[date, date]:
    """
    Traduce un periodo con nombre a un rango de fechas concreto, contando
    hacia atrás desde hoy. "todo" no pone límite inferior real (usa una
    fecha muy antigua) para incluir cualquier movimiento registrado.
    """
    hoy = date.today()

    if periodo == "todo":
        return date(1970, 1, 1), hoy
    if periodo not in _DIAS_POR_PERIODO:
        raise ValueError(f"Periodo no válido: '{periodo}'. Debe ser uno de: {', '.join(PERIODOS_VALIDOS)}")

    return hoy - timedelta(days=_DIAS_POR_PERIODO[periodo]), hoy


def rango_mes_calendario(año: int, mes: int) -> tuple[date, date]:
    """
    A diferencia de rango_desde_periodo("mes") (que cuenta 30 días hacia
    atrás desde HOY), esto devuelve el primer y último día de un mes de
    CALENDARIO concreto -- lo que hace falta para poder comparar "agosto"
    con "agosto del año pasado", no solo "los últimos 30 días".
    """
    primer_dia = date(año, mes, 1)
    ultimo_dia_numero = calendar.monthrange(año, mes)[1]  # [1] = nº de días que tiene ese mes
    ultimo_dia = date(año, mes, ultimo_dia_numero)
    return primer_dia, ultimo_dia


def trimestre(fecha: date) -> tuple[date, date]:
    """Primer y último día del trimestre natural de `fecha` (como el modelo 303)."""
    inicio_mes = 3 * ((fecha.month - 1) // 3) + 1
    desde = date(fecha.year, inicio_mes, 1)
    hasta = date(fecha.year + 1, 1, 1) - timedelta(days=1) if inicio_mes == 10 \
        else date(fecha.year, inicio_mes + 3, 1) - timedelta(days=1)
    return desde, hasta


class Metricas:
    """
    Consulta inventario.historial y lo resume de varias formas. No tiene
    datos propios -- si el historial cambia, las métricas cambian solas.
    """

    def __init__(self, inventario: Inventario):
        self.inventario = inventario

    def _en_rango(self, fecha_inicio: date, fecha_fin: date, tipo: Optional[str] = None) -> list[MovimientoStock]:
        """
        Movimientos entre dos fechas. `tipo` ("alimento" o "consumible")
        deja solo los de ese tipo de producto; None = todos.
        """
        return [
            m for m in self.inventario.historial
            if fecha_inicio <= m.fecha <= fecha_fin and (tipo is None or m.tipo_producto == tipo)
        ]

    def cantidad_consumida(self, producto_nombre: str, fecha_inicio: date, fecha_fin: date) -> float:
        """
        Cuánto se ha CONSUMIDO (no desperdiciado) de un producto en el rango
        dado. Cuenta también lo gastado al preparar elaboraciones.
        """
        return round(sum(
            m.cantidad for m in self._en_rango(fecha_inicio, fecha_fin)
            if m.producto_nombre == producto_nombre and m.tipo == "salida" and m.motivo in ("consumo", "elaboración")
        ), 3)

    def cantidad_desperdiciada(self, producto_nombre: str, fecha_inicio: date, fecha_fin: date) -> float:
        """Cuánto se ha tirado/desperdiciado de un producto en el rango dado."""
        return round(sum(
            m.cantidad for m in self._en_rango(fecha_inicio, fecha_fin)
            if m.producto_nombre == producto_nombre and m.tipo == "salida" and m.motivo == "desperdicio"
        ), 3)

    def productos_mas_consumidos(
        self, fecha_inicio: date, fecha_fin: date, top: int = 5, tipo: Optional[str] = None
    ) -> list[tuple[str, float]]:
        """Ranking de productos por cantidad CONSUMIDA (no desperdiciada), de mayor a menor."""
        acumulado: dict[str, float] = {}
        for m in self._en_rango(fecha_inicio, fecha_fin, tipo):
            if m.tipo == "salida" and m.motivo in ("consumo", "elaboración"):
                acumulado[m.producto_nombre] = round(acumulado.get(m.producto_nombre, 0) + m.cantidad, 3)
        return sorted(acumulado.items(), key=lambda par: par[1], reverse=True)[:top]

    def gasto_por_categoria(self, fecha_inicio: date, fecha_fin: date, tipo: Optional[str] = None) -> dict[str, float]:
        """
        Dinero gastado (COMPRAS) agrupado por categoría, en el rango dado.

        Solo cuentan las compras: la carne limpia que sale de una pata ya
        se pagó al comprar la pata, y contarla otra vez duplicaría el gasto.
        """
        gasto: dict[str, float] = {}
        for m in self._en_rango(fecha_inicio, fecha_fin, tipo):
            if m.es_compra():
                gasto[m.categoria] = round(gasto.get(m.categoria, 0) + m.valor(), 2)
        return gasto

    def resumen_limpiezas(self, fecha_inicio: date, fecha_fin: date) -> dict[str, dict]:
        """
        Por cada producto con merma limpiado en el rango: kg en bruto, kg
        limpios, kg aprovechados como derivados, kg de merma y rendimiento.
        La merma va aparte del desperdicio: es inevitable (el hueso existe),
        mientras que el desperdicio (algo que caducó) se puede evitar.
        """
        resumen: dict[str, dict] = {}
        for l in self.inventario.limpiezas:
            if not (fecha_inicio <= l.fecha <= fecha_fin):
                continue
            fila = resumen.setdefault(l.producto_origen, {
                "limpiezas": 0, "bruto_kg": 0.0, "limpio_kg": 0.0, "derivados_kg": 0.0, "merma_kg": 0.0,
            })
            fila["limpiezas"] += 1
            fila["bruto_kg"] += l.peso_bruto_kg
            fila["limpio_kg"] += l.peso_limpio_kg
            fila["derivados_kg"] += sum(l.derivados_kg.values())
            fila["merma_kg"] += l.merma_kg
        for fila in resumen.values():
            fila["rendimiento"] = fila["limpio_kg"] / fila["bruto_kg"] if fila["bruto_kg"] else 0.0
            for clave in ("bruto_kg", "limpio_kg", "derivados_kg", "merma_kg"):
                fila[clave] = round(fila[clave], 3)
        return resumen

    def merma_total_kg(self, fecha_inicio: date, fecha_fin: date) -> float:
        return round(sum(f["merma_kg"] for f in self.resumen_limpiezas(fecha_inicio, fecha_fin).values()), 3)

    def gasto_por_tipo(self, fecha_inicio: date, fecha_fin: date) -> dict[str, float]:
        """Dinero gastado en compras, separado en alimentos, consumibles y limpieza y mantenimiento."""
        return {
            tipo: round(sum(self.gasto_por_categoria(fecha_inicio, fecha_fin, tipo).values()), 2)
            for tipo in ("alimento", "consumible", "mantenimiento")
        }

    def iva_soportado(self, fecha_inicio: date, fecha_fin: date) -> float:
        """El IVA pagado en las compras del rango (lo que se puede deducir si el negocio lo deduce)."""
        return round(sum(
            m.cantidad * m.precio_base * m.iva / 100 for m in self._en_rango(fecha_inicio, fecha_fin) if m.es_compra()
        ), 2)

    def iva_soportado_por_tipo(self, fecha_inicio: date, fecha_fin: date) -> dict[float, float]:
        """El IVA pagado en las compras del rango, separado por tipo: {21.0: x, 10.0: y, 4.0: z}."""
        por_tipo: dict[float, float] = {}
        for m in self._en_rango(fecha_inicio, fecha_fin):
            if m.es_compra() and m.iva > 0:
                por_tipo[m.iva] = round(por_tipo.get(m.iva, 0) + m.cantidad * m.precio_base * m.iva / 100, 2)
        return dict(sorted(por_tipo.items(), reverse=True))

    def resumen_iva(self, fecha_inicio: date, fecha_fin: date, servicios: list) -> dict:
        """
        ESTIMACIÓN ORIENTATIVA del IVA de un periodo (normalmente un trimestre):
        - soportado: el IVA pagado en las compras registradas (por tipo).
        - repercutido: el IVA cobrado a los clientes, calculado sobre el
          precio de cobro (sin IVA) de los servicios completados en el
          periodo, con el IVA de cobro de los Ajustes (10 % en catering).
        - resultado: repercutido - soportado (> 0: a ingresar; < 0: a compensar).
        No incluye el IVA de los gastos (gasolina, personal...) ni de nada
        que no esté registrado aquí. No sustituye a un gestor o asesor fiscal.
        """
        por_tipo = self.iva_soportado_por_tipo(fecha_inicio, fecha_fin)
        soportado = round(sum(por_tipo.values()), 2)
        cobrados = [s for s in servicios if s.estado == "completado" and fecha_inicio <= s.fecha <= fecha_fin
                    and s.precio_cobrado is not None]
        base_cobrada = round(sum(s.precio_cobrado for s in cobrados), 2)
        repercutido = round(base_cobrada * self.inventario.iva_cobro / 100, 2)
        return {
            "soportado_por_tipo": por_tipo, "soportado": soportado,
            "base_cobrada": base_cobrada, "servicios_cobrados": len(cobrados),
            "servicios_sin_cobro": len([s for s in servicios if s.estado == "completado"
                                        and fecha_inicio <= s.fecha <= fecha_fin and s.precio_cobrado is None]),
            "repercutido": repercutido, "resultado": round(repercutido - soportado, 2),
        }

    def valor_desperdiciado_total(self, fecha_inicio: date, fecha_fin: date, tipo: Optional[str] = None) -> float:
        """
        Valor económico estimado de TODO lo desperdiciado en el rango dado:
        productos tirados y, en los alimentos, también las elaboraciones
        (tandas preparadas) desechadas.
        """
        productos = sum(
            m.valor() for m in self._en_rango(fecha_inicio, fecha_fin, tipo)
            if m.tipo == "salida" and m.motivo == "desperdicio"
        )
        tandas = self.inventario.elaboraciones.desperdicio_en_rango(fecha_inicio, fecha_fin) if tipo in (None, "alimento") else 0
        return round(productos + tandas, 2)

    def dias_estimados_para_agotarse(self, producto_nombre: str, dias_historial: int = 30) -> Optional[float]:
        """
        Proyección simple: al ritmo de consumo de los últimos
        `dias_historial` días, ¿en cuántos días se agotaría el stock
        ACTUAL de este producto? Devuelve None si no hay consumo
        reciente registrado (no se puede proyectar nada) o si el
        producto no existe.

        Es una proyección ingenua (asume que el ritmo se mantiene
        constante), no una predicción sofisticada -- pero para avisar
        con antelación razonable es más que suficiente.
        """
        producto = self.inventario.buscar_producto(producto_nombre)
        if producto is None:
            return None

        hoy = date.today()
        desde = hoy - timedelta(days=dias_historial)
        # Un producto en bruto no se "consume" en los servicios: se gasta al
        # limpiarlo. Por eso aquí cuentan las dos cosas.
        consumido = sum(
            m.cantidad for m in self._en_rango(desde, hoy)
            if m.producto_nombre == producto_nombre and m.tipo == "salida"
            and m.motivo in ("consumo", "limpieza", "elaboración")
        )

        if consumido <= 0:
            return None  # sin consumo reciente, no se puede proyectar nada

        ritmo_diario = consumido / dias_historial
        return round(producto.stock / ritmo_diario, 1)

    def productos_proximos_a_agotarse(self, dias_aviso: int = 7, dias_historial: int = 30) -> list[tuple[str, float]]:
        """
        Productos cuyo stock se agotaría dentro de `dias_aviso` días al
        ritmo de consumo actual, ordenados de más a menos urgente.
        """
        resultado = []
        for nombre, producto in self.inventario.productos.items():
            if producto.stock <= 0:
                continue  # ya está agotado: no "se agotará" (eso ya lo avisa "bajo mínimo")
            dias = self.dias_estimados_para_agotarse(nombre, dias_historial)
            if dias is not None and dias <= dias_aviso:
                resultado.append((nombre, dias))
        return sorted(resultado, key=lambda par: par[1])


class InformeMensual:
    """
    Una "foto" GUARDADA de las métricas de un mes de calendario concreto.
    A diferencia de Metricas (que recalcula todo al vuelo cada vez), esto
    se genera una vez y queda archivado -- así puedes comparar épocas del
    año entre sí sin volver a tocar el historial en crudo, e incluso
    seguiría existiendo si el historial detallado se archivara o borrara
    más adelante.
    """

    def __init__(
        self,
        año: int,
        mes: int,
        gasto_total: float,
        gasto_por_categoria: dict,
        consumo_por_producto: dict,
        desperdicio_por_producto: dict,
        valor_desperdiciado_total: float,
        fecha_generacion: Optional[date] = None,
    ):
        self.año = año
        self.mes = mes
        self.gasto_total = gasto_total
        self.gasto_por_categoria = gasto_por_categoria
        self.consumo_por_producto = consumo_por_producto
        self.desperdicio_por_producto = desperdicio_por_producto
        self.valor_desperdiciado_total = valor_desperdiciado_total
        self.fecha_generacion = fecha_generacion or date.today()

    @property
    def clave(self) -> str:
        """Identificador único tipo '2026-08', usado para guardar y buscar informes."""
        return f"{self.año}-{self.mes:02d}"

    def __str__(self) -> str:
        return (
            f"{NOMBRES_MESES[self.mes].capitalize()} {self.año}: "
            f"gasto {self.gasto_total}€, desperdicio {self.valor_desperdiciado_total}€"
        )

    def to_dict(self) -> dict:
        return {
            "año": self.año,
            "mes": self.mes,
            "gasto_total": self.gasto_total,
            "gasto_por_categoria": self.gasto_por_categoria,
            "consumo_por_producto": self.consumo_por_producto,
            "desperdicio_por_producto": self.desperdicio_por_producto,
            "valor_desperdiciado_total": self.valor_desperdiciado_total,
            "fecha_generacion": self.fecha_generacion.isoformat(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "InformeMensual":
        return cls(
            año=datos["año"],
            mes=datos["mes"],
            gasto_total=datos["gasto_total"],
            gasto_por_categoria=datos["gasto_por_categoria"],
            consumo_por_producto=datos["consumo_por_producto"],
            desperdicio_por_producto=datos["desperdicio_por_producto"],
            valor_desperdiciado_total=datos["valor_desperdiciado_total"],
            fecha_generacion=date.fromisoformat(datos["fecha_generacion"]),
        )


class ArchivoInformes:
    """Genera, guarda y compara informes mensuales ya archivados."""

    def __init__(self):
        self.informes: dict[str, InformeMensual] = {}  # clave "2026-08" -> InformeMensual

    def generar_informe(self, inventario: Inventario, año: int, mes: int) -> InformeMensual:
        """Calcula las métricas de ese mes de calendario y las GUARDA (sobrescribe si ya existía)."""
        metricas = Metricas(inventario)
        desde, hasta = rango_mes_calendario(año, mes)

        gasto_por_categoria = metricas.gasto_por_categoria(desde, hasta)
        gasto_total = round(sum(gasto_por_categoria.values()), 2)

        consumo_por_producto = {
            nombre: metricas.cantidad_consumida(nombre, desde, hasta) for nombre in inventario.productos
        }
        consumo_por_producto = {nombre: c for nombre, c in consumo_por_producto.items() if c > 0}

        desperdicio_por_producto = {
            nombre: metricas.cantidad_desperdiciada(nombre, desde, hasta) for nombre in inventario.productos
        }
        desperdicio_por_producto = {nombre: c for nombre, c in desperdicio_por_producto.items() if c > 0}

        valor_desperdiciado_total = metricas.valor_desperdiciado_total(desde, hasta)

        informe = InformeMensual(
            año=año, mes=mes, gasto_total=gasto_total, gasto_por_categoria=gasto_por_categoria,
            consumo_por_producto=consumo_por_producto, desperdicio_por_producto=desperdicio_por_producto,
            valor_desperdiciado_total=valor_desperdiciado_total,
        )
        self.informes[informe.clave] = informe
        print(f"📊 Informe generado y guardado: {informe}")
        return informe

    def buscar_informe(self, año: int, mes: int) -> Optional[InformeMensual]:
        return self.informes.get(f"{año}-{mes:02d}")

    def listar_informes(self) -> list[InformeMensual]:
        return sorted(self.informes.values(), key=lambda i: (i.año, i.mes))

    def comparar(self, año1: int, mes1: int, año2: int, mes2: int) -> dict:
        """
        Compara dos informes YA GUARDADOS (genera antes cada uno con
        generar_informe() si no existen todavía). Devuelve un diccionario
        con las diferencias clave entre ambos meses.
        """
        informe1 = self.buscar_informe(año1, mes1)
        informe2 = self.buscar_informe(año2, mes2)
        if informe1 is None or informe2 is None:
            faltante = f"{año1}-{mes1:02d}" if informe1 is None else f"{año2}-{mes2:02d}"
            print(f"❌ No hay informe guardado para {faltante}. Genéralo primero (opción 'Generar informe').")
            return {}

        categorias = set(informe1.gasto_por_categoria) | set(informe2.gasto_por_categoria)
        diferencia_por_categoria = {
            cat: round(informe2.gasto_por_categoria.get(cat, 0) - informe1.gasto_por_categoria.get(cat, 0), 2)
            for cat in categorias
        }

        return {
            "periodo_1": informe1.clave,
            "periodo_2": informe2.clave,
            "gasto_total_1": informe1.gasto_total,
            "gasto_total_2": informe2.gasto_total,
            "diferencia_gasto_total": round(informe2.gasto_total - informe1.gasto_total, 2),
            "diferencia_por_categoria": diferencia_por_categoria,
            "desperdicio_1": informe1.valor_desperdiciado_total,
            "desperdicio_2": informe2.valor_desperdiciado_total,
            "diferencia_desperdicio": round(informe2.valor_desperdiciado_total - informe1.valor_desperdiciado_total, 2),
        }

    def to_dict(self) -> dict:
        return {"informes": [i.to_dict() for i in self.informes.values()]}

    @classmethod
    def from_dict(cls, datos: dict) -> "ArchivoInformes":
        archivo = cls()
        for datos_informe in datos.get("informes", []):
            informe = InformeMensual.from_dict(datos_informe)
            archivo.informes[informe.clave] = informe
        return archivo


if __name__ == "__main__":
    from datetime import timedelta as td
    from inventario import Producto

    inv = Inventario()
    inv.agregar_producto(Producto("Tomate", "Verduras", 20, "kg", 2.1, "Huerta Local", stock_minimo=2))
    inv.agregar_producto(Producto("Harina de trigo", "Panadería", 20, "kg", 1.2, "Harinas del Sur", stock_minimo=2))

    # Simulamos varios movimientos: compras, consumo y desperdicio
    inv.actualizar_stock("Tomate", 15, sumar=True)
    inv.actualizar_stock("Harina de trigo", 10, sumar=True)
    inv.actualizar_stock("Tomate", 5, sumar=False, motivo_salida="consumo")
    inv.actualizar_stock("Tomate", 2, sumar=False, motivo_salida="desperdicio")
    inv.actualizar_stock("Harina de trigo", 3, sumar=False, motivo_salida="consumo")

    metricas = Metricas(inv)
    desde, hasta = rango_desde_periodo("mes")

    print(f"\n--- Métricas del último mes ({desde} a {hasta}) ---")
    print(f"Consumido de Tomate: {metricas.cantidad_consumida('Tomate', desde, hasta)} kg")
    print(f"Desperdiciado de Tomate: {metricas.cantidad_desperdiciada('Tomate', desde, hasta)} kg")
    print(f"Productos más consumidos: {metricas.productos_mas_consumidos(desde, hasta)}")
    print(f"Gasto por categoría: {metricas.gasto_por_categoria(desde, hasta)}")
    print(f"Valor total desperdiciado: {metricas.valor_desperdiciado_total(desde, hasta)} €")

    # --- Informes mensuales guardados ---
    print("\n--- Generando informes mensuales ---")
    archivo = ArchivoInformes()

    # Simulamos que estos movimientos ocurrieron en AGOSTO, y añadimos
    # unos cuantos más "en SEPTIEMBRE" manipulando la fecha directamente
    # (en la app real, la fecha la pone actualizar_stock() sola con la
    # fecha de hoy -- aquí lo forzamos solo para poder probar la
    # comparación entre dos meses distintos).
    for m in inv.historial:
        m.fecha = date(2026, 8, 15)

    inv.actualizar_stock("Tomate", 30, sumar=True)
    inv.actualizar_stock("Tomate", 10, sumar=False, motivo_salida="consumo")
    inv.historial[-1].fecha = date(2026, 9, 10)
    inv.historial[-2].fecha = date(2026, 9, 5)

    archivo.generar_informe(inv, 2026, 8)
    archivo.generar_informe(inv, 2026, 9)

    print("\n--- Informes guardados ---")
    for informe in archivo.listar_informes():
        print(informe)

    print("\n--- Comparación agosto vs septiembre ---")
    comparacion = archivo.comparar(2026, 8, 2026, 9)
    print(comparacion)
