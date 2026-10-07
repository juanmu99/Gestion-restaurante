"""
Módulo: gastos.py
------------------
Registra los GASTOS que no son stock (gasolina, peajes, personal extra,
alquileres, lavandería...) y calcula cuánto ha costado de verdad cada
servicio y, si se indicó lo que se cobró, su margen.

Un gasto puede ir asociado a un servicio concreto (la gasolina de ir a
una boda) o ser un gasto general del negocio (el seguro de la furgoneta).

Conecta con:
- servicios.py  -> el precio cobrado de cada servicio
- inventario.py -> lo que se gastó del inventario en cada servicio (sus
                   movimientos de salida llevan el número del servicio)
- recetario.py  -> el coste ESTIMADO de un servicio que aún no se ha hecho
"""

from datetime import date
from typing import Optional

from inventario import Inventario
from materiales import RegistroMaterial
from recetario import Recetario
from servicios import Servicio


# Nota con la que se apuntan los costes no previstos añadidos al completar un
# servicio: así, si se deshace el servicio, se sabe cuáles quitar.
NOTA_COSTE_AL_COMPLETAR = "Coste no previsto, añadido al completar el servicio"


class Gasto:
    """UN gasto: qué, cuánto, cuándo y, si es de un servicio, de cuál."""

    # IVA que se propone según la categoría: 21 % salvo lo que normalmente no
    # lleva (personal, seguros). Se puede cambiar en cada gasto.
    IVA_POR_CATEGORIA = {"Personal extra": 0.0, "Seguros e impuestos": 0.0}

    @classmethod
    def iva_propuesto(cls, categoria: str) -> float:
        return cls.IVA_POR_CATEGORIA.get(categoria, 21.0)

    # Categorías fijas, para poder agrupar y comparar (igual que las
    # unidades del inventario: nada de "Gasolina", "gasolina", "Gasoil"...).
    CATEGORIAS = (
        "Transporte", "Personal extra", "Alquiler de material", "Lavandería",
        "Mantenimiento", "Seguros e impuestos", "Otros",
    )

    _siguiente_id = 1  # contador compartido, como en Servicio

    def __init__(
        self,
        concepto: str,
        categoria: str,
        importe: float,
        fecha: Optional[date] = None,
        servicio_id: Optional[int] = None,
        notas: str = "",
        iva: Optional[float] = None,
    ):
        """
        `importe` es lo PAGADO (con IVA, lo del ticket). `iva` es su tipo de
        IVA en % (21, 10, 4, 0 = sin IVA, como una nómina). None = "IVA no
        desglosado": los gastos apuntados antes de existir este dato, que se
        cuentan tal cual (como si no llevaran IVA recuperable).
        """
        if not concepto.strip():
            raise ValueError("Indica el concepto del gasto (ej: 'Gasolina boda García').")
        if categoria not in self.CATEGORIAS:
            raise ValueError(f"Categoría no válida: '{categoria}'. Debe ser una de: {', '.join(self.CATEGORIAS)}")
        if importe <= 0:
            raise ValueError("El importe debe ser mayor que 0.")
        if iva is not None and iva < 0:
            raise ValueError("El IVA no puede ser negativo.")

        self.id = Gasto._siguiente_id
        Gasto._siguiente_id += 1
        self.concepto = concepto.strip()
        self.categoria = categoria
        self.importe = round(importe, 2)
        self.fecha = fecha or date.today()
        self.servicio_id = servicio_id  # None = gasto general del negocio
        self.notas = notas
        self.iva = iva

    @property
    def importe_sin_iva(self) -> float:
        """El importe sin su IVA (igual al importe si no lleva IVA o no está desglosado)."""
        return self.importe / (1 + self.iva / 100) if self.iva else self.importe

    @property
    def cuota_iva(self) -> float:
        """El IVA pagado en este gasto (0 si no lleva o no está desglosado)."""
        return round(self.importe - self.importe_sin_iva, 2)

    def coste(self, sin_iva: bool) -> float:
        """Lo que cuesta este gasto: sin su IVA si el negocio lo recupera (`sin_iva`), o lo pagado."""
        return round(self.importe_sin_iva if sin_iva else self.importe, 2)

    def __str__(self) -> str:
        servicio = f" | servicio #{self.servicio_id}" if self.servicio_id else " | general"
        return f"[#{self.id}] {self.fecha.strftime('%d/%m/%Y')} {self.concepto} ({self.categoria}): {self.importe}€{servicio}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "concepto": self.concepto,
            "categoria": self.categoria,
            "importe": self.importe,
            "fecha": self.fecha.isoformat(),
            "servicio_id": self.servicio_id,
            "notas": self.notas,
            "iva": self.iva,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Gasto":
        gasto = cls(
            datos["concepto"], datos["categoria"], datos["importe"],
            fecha=date.fromisoformat(datos["fecha"]), servicio_id=datos.get("servicio_id"), notas=datos.get("notas", ""),
            iva=datos.get("iva"),  # los gastos antiguos no lo tienen: "IVA no desglosado"
        )
        gasto.id = datos["id"]  # conserva su número original (ver Servicio.from_dict)
        return gasto


class RegistroGastos:
    """Todos los gastos del negocio."""

    def __init__(self):
        self.gastos: list[Gasto] = []

    def agregar_gasto(self, gasto: Gasto) -> None:
        usados = {g.id for g in self.gastos}  # el número no se puede repetir (ver RegistroServicios)
        if gasto.id in usados:
            gasto.id = max(usados) + 1
        Gasto._siguiente_id = max(Gasto._siguiente_id, gasto.id + 1)
        self.gastos.append(gasto)
        print(f"💶 Gasto registrado: {gasto}")

    def eliminar_gasto(self, id_gasto: int) -> bool:
        for gasto in self.gastos:
            if gasto.id == id_gasto:
                self.gastos.remove(gasto)
                print(f"🗑️  Gasto eliminado: {gasto}")
                return True
        print(f"❌ No existe el gasto #{id_gasto}")
        return False

    def quitar_costes_al_completar(self, servicio_id: int) -> list[Gasto]:
        """Quita los costes adicionales que se apuntaron AL COMPLETAR un servicio (al deshacerlo). Los devuelve."""
        quitados = [g for g in self.gastos if g.servicio_id == servicio_id and g.notas == NOTA_COSTE_AL_COMPLETAR]
        self.gastos = [g for g in self.gastos if g not in quitados]
        return quitados

    def buscar_por_id(self, id_gasto: int) -> Optional[Gasto]:
        return next((g for g in self.gastos if g.id == id_gasto), None)

    def gastos_de_servicio(self, servicio_id: int) -> list[Gasto]:
        return [g for g in self.gastos if g.servicio_id == servicio_id]

    def gastos_en_rango(self, desde: date, hasta: date) -> list[Gasto]:
        return sorted((g for g in self.gastos if desde <= g.fecha <= hasta), key=lambda g: g.fecha)

    def total_por_categoria(self, desde: date, hasta: date) -> dict[str, float]:
        totales: dict[str, float] = {}
        for g in self.gastos_en_rango(desde, hasta):
            totales[g.categoria] = round(totales.get(g.categoria, 0) + g.importe, 2)
        return totales

    def to_dict(self) -> dict:
        return {"gastos": [g.to_dict() for g in self.gastos]}

    @classmethod
    def from_dict(cls, datos: dict) -> "RegistroGastos":
        registro = cls()
        registro.gastos = [Gasto.from_dict(d) for d in datos.get("gastos", [])]
        if registro.gastos:
            Gasto._siguiente_id = max(g.id for g in registro.gastos) + 1
        return registro


def resumen_servicio(
    servicio: Servicio, inventario: Inventario, recetario: Recetario, registro_gastos: RegistroGastos,
    registro_material: Optional[RegistroMaterial] = None,
) -> dict:
    """
    Cuánto ha costado (o costará) un servicio y, si se sabe lo que se
    cobró, cuánto se ha ganado.

    - Servicio COMPLETADO: el coste de comida y consumibles es el REAL, el
      de lo que salió del inventario al completarlo, a precio de cada lote.
    - Servicio PENDIENTE: es una ESTIMACIÓN con los precios actuales y las
      cantidades del menú ("estimado" = True).
    - Si el negocio recupera el IVA (Inventario.iva_recuperable), los costes
      de lo comprado van SIN IVA, y "iva_recuperable" dice cuánto IVA era.

    Devuelve un diccionario con: comida, consumibles, mantenimiento (productos
    de limpieza y mantenimiento sacados para este servicio), gastos (total) y
    gastos_por_categoria (sin su IVA si se recupera), material (roturas y pérdidas), coste_total, cobrado (None si no se indicó),
    margen y margen_porcentaje (None si no hay cobro), y estimado.
    """
    estimado = servicio.estado != "completado"
    # Si el negocio recupera el IVA de sus compras, ese IVA no es un coste:
    # el margen se calcula sin él (y se muestra aparte como "IVA recuperable").
    sin_iva = inventario.iva_recuperable
    comida = consumibles = mantenimiento = 0.0
    comida_con = consumibles_con = mantenimiento_con = 0.0
    if estimado:
        menu = recetario.buscar_menu(servicio.menu)
        if menu is not None:
            comida = menu.costo_por_comensal(inventario, sin_iva, redondear=False) * servicio.comensales
            consumibles = menu.costo_consumibles_por_comensal(inventario, sin_iva, redondear=False) * servicio.comensales
            comida_con = menu.costo_por_comensal(inventario, redondear=False) * servicio.comensales
            consumibles_con = menu.costo_consumibles_por_comensal(inventario, redondear=False) * servicio.comensales
    else:
        for m in inventario.historial:
            if m.servicio_id == servicio.id and m.tipo == "salida":
                valor = m.valor_sin_iva() if sin_iva else m.valor()
                if m.tipo_producto == "consumible":
                    consumibles += valor
                    consumibles_con += m.valor()
                elif m.tipo_producto == "mantenimiento":
                    mantenimiento += valor  # limpieza y mantenimiento gastado en este servicio
                    mantenimiento_con += m.valor()
                else:
                    comida += valor
                    comida_con += m.valor()
        # raciones ya preparadas
        comida += inventario.elaboraciones.coste_servicio(servicio.id, sin_iva=sin_iva)
        comida_con += inventario.elaboraciones.coste_servicio(servicio.id)
    iva_recuperable = round((comida_con + consumibles_con + mantenimiento_con)
                            - (comida + consumibles + mantenimiento), 2) if sin_iva else 0.0

    # Los gastos (gasolina, personal...) siguen el mismo criterio: sin su IVA si se recupera.
    gastos_por_categoria: dict[str, float] = {}
    for g in registro_gastos.gastos_de_servicio(servicio.id):
        gastos_por_categoria[g.categoria] = round(gastos_por_categoria.get(g.categoria, 0) + g.coste(sin_iva), 2)
        if sin_iva:
            iva_recuperable = round(iva_recuperable + g.cuota_iva, 2)
    gastos = round(sum(gastos_por_categoria.values()), 2)

    material = registro_material.coste_incidencias_servicio(servicio.id) if registro_material else 0.0
    coste_total = round(comida + consumibles + mantenimiento + gastos + material, 2)
    cobrado = servicio.precio_cobrado
    margen = round(cobrado - coste_total, 2) if cobrado is not None else None
    return {
        "comida": round(comida, 2),
        "consumibles": round(consumibles, 2),
        "mantenimiento": round(mantenimiento, 2),
        "gastos": gastos,
        "gastos_por_categoria": gastos_por_categoria,
        "material": material,
        "coste_total": coste_total,
        "cobrado": cobrado,
        "margen": margen,
        "margen_porcentaje": (margen / cobrado if cobrado else None) if margen is not None else None,
        "estimado": estimado,
        # IVA de las compras usadas en el servicio que se recupera (0 si el negocio no lo recupera).
        "iva_recuperable": iva_recuperable,
        "sin_iva": sin_iva,
    }


if __name__ == "__main__":
    from datetime import time

    registro = RegistroGastos()
    registro.agregar_gasto(Gasto("Gasolina boda García", "Transporte", 45.3, servicio_id=1))
    registro.agregar_gasto(Gasto("Camarero extra", "Personal extra", 120, servicio_id=1))
    registro.agregar_gasto(Gasto("Seguro furgoneta", "Seguros e impuestos", 60))

    servicio = Servicio(date.today(), time(21, 0), 40, "Menú de bodas", precio_cobrado=2000)
    servicio.id = 1
    resumen = resumen_servicio(servicio, Inventario(), Recetario(), registro)
    print(f"\nServicio #1: coste {resumen['coste_total']}€, cobrado {resumen['cobrado']}€, margen {resumen['margen']}€")
    print(f"Gastos por categoría este mes: {registro.total_por_categoria(date.today().replace(day=1), date.today())}")
