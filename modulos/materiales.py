"""
Módulo: materiales.py
----------------------
Gestiona el MATERIAL REUTILIZABLE: platos, vasos, cubertería, mantelería,
bandejas, chafings, neveras... Cosas que no se gastan: salen a un servicio
y vuelven. Lo que se pierde por el camino son roturas y pérdidas.

Por eso no usa lotes ni stock como los alimentos:
- cantidad_total: cuántos tienes (tuyos).
- en uso: cuántos han salido a servicios y todavía no han vuelto.
- disponibles: total - en uso. Lo que puedes llevarte a otro servicio.

Flujo de un servicio:
1. Salida: te llevas una "lista de carga" (el menú la propone según los
   comensales). Esos materiales pasan a "en uso".
2. Vuelta: apuntas cuántos han vuelto de cada uno. Lo que falta se
   registra como ROTURA o PÉRDIDA, con su coste de reposición, y deja de
   contar en el total (ya no lo tienes).
"""

import math
from datetime import date
from typing import Optional


def _es_numero(texto: str) -> bool:
    try:
        float(texto)
        return True
    except ValueError:
        return False


class Material:
    """UN tipo de material (ej: "Plato llano"), con cuántas unidades tienes en total."""

    def __init__(
        self,
        nombre: str,
        categoria: str,
        cantidad_total: int,
        precio_reposicion: float = 0.0,
        proveedor: str = "",
    ):
        """
        precio_reposicion: lo que cuesta reponer UNA unidad si se rompe o
        se pierde. Es lo que se apunta como coste de cada rotura.
        """
        if not nombre.strip():
            raise ValueError("Ponle un nombre al material.")
        if not categoria.strip() or _es_numero(categoria):
            raise ValueError("La categoría debe ser texto descriptivo, no puede estar vacía ni ser un número")
        if cantidad_total < 0 or int(cantidad_total) != cantidad_total:
            raise ValueError("La cantidad debe ser un número entero de unidades (0 o más).")
        if precio_reposicion < 0:
            raise ValueError("El precio no puede ser negativo.")
        self.nombre = nombre.strip()
        self.categoria = categoria.strip()
        self.cantidad_total = int(cantidad_total)
        self.precio_reposicion = precio_reposicion
        self.proveedor = proveedor.strip()

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre, "categoria": self.categoria, "cantidad_total": self.cantidad_total,
            "precio_reposicion": self.precio_reposicion, "proveedor": self.proveedor,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Material":
        return cls(
            datos["nombre"], datos["categoria"], datos["cantidad_total"],
            datos.get("precio_reposicion", 0.0), datos.get("proveedor", ""),
        )


class SalidaMaterial:
    """El material que se ha llevado a UN servicio, y (cuando vuelve) qué volvió."""

    def __init__(
        self,
        servicio_id: int,
        cantidades: dict[str, int],
        fecha_salida: Optional[date] = None,
        fecha_vuelta: Optional[date] = None,
        vuelto: Optional[dict[str, int]] = None,
    ):
        self.servicio_id = servicio_id
        self.cantidades = dict(cantidades)  # lo que salió: {material: unidades}
        self.fecha_salida = fecha_salida or date.today()
        self.fecha_vuelta = fecha_vuelta
        self.vuelto = dict(vuelto or {})  # lo que volvió (solo cuando ya ha vuelto)

    @property
    def ha_vuelto(self) -> bool:
        return self.fecha_vuelta is not None

    def to_dict(self) -> dict:
        return {
            "servicio_id": self.servicio_id, "cantidades": self.cantidades,
            "fecha_salida": self.fecha_salida.isoformat(),
            "fecha_vuelta": self.fecha_vuelta.isoformat() if self.fecha_vuelta else None,
            "vuelto": self.vuelto,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "SalidaMaterial":
        return cls(
            datos["servicio_id"], datos["cantidades"], date.fromisoformat(datos["fecha_salida"]),
            date.fromisoformat(datos["fecha_vuelta"]) if datos.get("fecha_vuelta") else None, datos.get("vuelto", {}),
        )


class Incidencia:
    """Una rotura o pérdida de material, con su coste de reposición."""

    TIPOS = ("rotura", "pérdida")

    def __init__(
        self, material: str, cantidad: int, tipo: str, coste: float,
        servicio_id: Optional[int] = None, fecha: Optional[date] = None,
    ):
        if tipo not in self.TIPOS:
            raise ValueError(f"Tipo de incidencia no válido: {tipo}")
        self.material = material
        self.cantidad = cantidad
        self.tipo = tipo
        self.coste = round(coste, 2)
        self.servicio_id = servicio_id  # None = fuera de un servicio (se rompió en el almacén)
        self.fecha = fecha or date.today()

    def __str__(self) -> str:
        servicio = f" (servicio #{self.servicio_id})" if self.servicio_id else ""
        return f"{self.fecha.strftime('%d/%m/%Y')} {self.tipo}: {self.cantidad} x {self.material} = {self.coste}€{servicio}"

    def to_dict(self) -> dict:
        return {
            "material": self.material, "cantidad": self.cantidad, "tipo": self.tipo, "coste": self.coste,
            "servicio_id": self.servicio_id, "fecha": self.fecha.isoformat(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Incidencia":
        return cls(
            datos["material"], datos["cantidad"], datos["tipo"], datos["coste"],
            datos.get("servicio_id"), date.fromisoformat(datos["fecha"]),
        )


class RegistroMaterial:
    """Todo el material reutilizable, sus salidas a servicios y sus roturas/pérdidas."""

    def __init__(self):
        self.materiales: dict[str, Material] = {}
        self.salidas: list[SalidaMaterial] = []
        self.incidencias: list[Incidencia] = []

    # ---------- Materiales ----------

    def agregar_material(self, material: Material) -> bool:
        if material.nombre in self.materiales:
            print(f"⚠️  Ya existe el material '{material.nombre}'.")
            return False
        self.materiales[material.nombre] = material
        print(f"✅ Material añadido: {material.nombre} ({material.cantidad_total} unidades)")
        return True

    def buscar(self, nombre: str) -> Optional[Material]:
        return self.materiales.get(nombre)

    def en_uso(self, nombre: str) -> int:
        """Unidades que han salido a servicios y todavía no han vuelto."""
        return sum(s.cantidades.get(nombre, 0) for s in self.salidas if not s.ha_vuelto)

    def disponibles(self, nombre: str) -> int:
        material = self.materiales.get(nombre)
        return material.cantidad_total - self.en_uso(nombre) if material else 0

    def editar_material(
        self, nombre_actual: str, nuevo_nombre: Optional[str] = None, categoria: Optional[str] = None,
        cantidad_total: Optional[int] = None, precio_reposicion: Optional[float] = None,
        proveedor: Optional[str] = None,
    ) -> bool:
        """
        Corrige los datos de un material (None = no cambiar). La cantidad
        total no puede quedar por debajo de lo que está ahora en uso.
        """
        material = self.materiales.get(nombre_actual)
        if material is None:
            print(f"❌ No existe el material '{nombre_actual}'.")
            return False
        # Se valida construyendo un Material con los datos finales (mismas reglas que al crear).
        final = Material(
            nuevo_nombre if nuevo_nombre is not None else material.nombre,
            categoria if categoria is not None else material.categoria,
            cantidad_total if cantidad_total is not None else material.cantidad_total,
            precio_reposicion if precio_reposicion is not None else material.precio_reposicion,
            proveedor if proveedor is not None else material.proveedor,
        )
        if final.cantidad_total < self.en_uso(nombre_actual):
            raise ValueError(
                f"Ahora mismo hay {self.en_uso(nombre_actual)} unidades de '{nombre_actual}' en uso: "
                "el total no puede ser menor."
            )
        if final.nombre != nombre_actual:
            if final.nombre in self.materiales:
                print(f"❌ Ya existe otro material llamado '{final.nombre}'.")
                return False
            del self.materiales[nombre_actual]
            self._renombrar_referencias(nombre_actual, final.nombre)
        material.nombre, material.categoria = final.nombre, final.categoria
        material.cantidad_total, material.precio_reposicion = final.cantidad_total, final.precio_reposicion
        material.proveedor = final.proveedor
        self.materiales[material.nombre] = material
        print(f"✏️  Material actualizado: {material.nombre}")
        return True

    def _renombrar_referencias(self, antiguo: str, nuevo: str) -> None:
        for s in self.salidas:
            if antiguo in s.cantidades:
                s.cantidades = {(nuevo if n == antiguo else n): c for n, c in s.cantidades.items()}
            if antiguo in s.vuelto:
                s.vuelto = {(nuevo if n == antiguo else n): c for n, c in s.vuelto.items()}
        for i in self.incidencias:
            if i.material == antiguo:
                i.material = nuevo

    def reponer(self, nombre: str, cantidad: int) -> bool:
        """Compras más unidades (o repones las rotas): aumenta el total."""
        material = self.materiales.get(nombre)
        if material is None or cantidad <= 0 or int(cantidad) != cantidad:
            print("❌ Indica un material existente y un número entero de unidades mayor que 0.")
            return False
        material.cantidad_total += int(cantidad)
        print(f"📦 {nombre}: +{int(cantidad)} unidades (total {material.cantidad_total})")
        return True

    def dar_de_baja(self, nombre: str, cantidad: int, tipo: str = "rotura") -> Optional[Incidencia]:
        """Una rotura o pérdida FUERA de un servicio (en el almacén, al fregar...)."""
        material = self.materiales.get(nombre)
        if material is None:
            raise ValueError(f"No existe el material '{nombre}'.")
        if cantidad <= 0 or int(cantidad) != cantidad:
            raise ValueError("Indica un número entero de unidades mayor que 0.")
        if cantidad > self.disponibles(nombre):
            raise ValueError(f"Solo hay {self.disponibles(nombre)} unidades de '{nombre}' disponibles (en el almacén).")
        return self._incidencia(material, int(cantidad), tipo, None)

    def _incidencia(self, material: Material, cantidad: int, tipo: str, servicio_id: Optional[int]) -> Incidencia:
        incidencia = Incidencia(material.nombre, cantidad, tipo, cantidad * material.precio_reposicion, servicio_id)
        material.cantidad_total -= cantidad
        self.incidencias.append(incidencia)
        print(f"💥 {incidencia}")
        return incidencia

    # ---------- Salidas a servicios ----------

    def salida_de(self, servicio_id: int) -> Optional[SalidaMaterial]:
        """La salida de material de un servicio que todavía no ha vuelto (si la hay)."""
        return next((s for s in self.salidas if s.servicio_id == servicio_id and not s.ha_vuelto), None)

    def salidas_de(self, servicio_id: int) -> list[SalidaMaterial]:
        return [s for s in self.salidas if s.servicio_id == servicio_id]

    def registrar_salida(self, servicio_id: int, cantidades: dict[str, int]) -> SalidaMaterial:
        """
        El material sale a un servicio: pasa a estar "en uso". Si ese
        servicio ya tenía material fuera, se suma a lo que ya salió.
        Comprueba todo antes de tocar nada.
        """
        cantidades = {n: int(c) for n, c in cantidades.items() if c and c > 0}
        if not cantidades:
            raise ValueError("La lista de carga está vacía.")
        for nombre, cantidad in cantidades.items():
            if nombre not in self.materiales:
                raise ValueError(f"No existe el material '{nombre}'.")
            if cantidad > self.disponibles(nombre):
                raise ValueError(
                    f"De '{nombre}' solo hay {self.disponibles(nombre)} disponibles "
                    f"({self.en_uso(nombre)} están en otros servicios)."
                )
        salida = self.salida_de(servicio_id)
        if salida is None:
            salida = SalidaMaterial(servicio_id, {})
            self.salidas.append(salida)
        for nombre, cantidad in cantidades.items():
            salida.cantidades[nombre] = salida.cantidades.get(nombre, 0) + cantidad
        print(f"🚚 Material fuera para el servicio #{servicio_id}: {salida.cantidades}")
        return salida

    def registrar_vuelta(
        self, servicio_id: int, vuelto: dict[str, int], rotos: Optional[dict[str, int]] = None,
    ) -> list[Incidencia]:
        """
        Vuelve el material de un servicio. `vuelto` = cuántos han vuelto de
        cada uno (lo que no se indica, se entiende que ha vuelto todo). De lo
        que falta, `rotos` dice cuántos se rompieron; el resto son pérdidas.
        Todo lo que falta deja de contar en el total y se apunta con su coste.
        """
        rotos = rotos or {}
        salida = self.salida_de(servicio_id)
        if salida is None:
            raise ValueError(f"El servicio #{servicio_id} no tiene material fuera.")
        faltan: dict[str, int] = {}
        for nombre, salio in salida.cantidades.items():
            volvio = int(vuelto.get(nombre, salio))
            if volvio < 0 or volvio > salio:
                raise ValueError(f"De '{nombre}' salieron {salio}: no pueden volver {volvio}.")
            roto = int(rotos.get(nombre, 0))
            if roto < 0 or roto > salio - volvio:
                raise ValueError(f"De '{nombre}' faltan {salio - volvio}: no pueden estar rotos {roto}.")
            faltan[nombre] = salio - volvio

        salida.vuelto = {n: salida.cantidades[n] - faltan[n] for n in salida.cantidades}
        salida.fecha_vuelta = date.today()
        incidencias = []
        for nombre, falta in faltan.items():
            material = self.materiales.get(nombre)
            if material is None or falta == 0:
                continue
            roto = int(rotos.get(nombre, 0))
            if roto:
                incidencias.append(self._incidencia(material, roto, "rotura", servicio_id))
            if falta - roto:
                incidencias.append(self._incidencia(material, falta - roto, "pérdida", servicio_id))
        print(f"✅ Material del servicio #{servicio_id} de vuelta.")
        return incidencias

    def coste_incidencias_servicio(self, servicio_id: int) -> float:
        return round(sum(i.coste for i in self.incidencias if i.servicio_id == servicio_id), 2)

    def incidencias_en_rango(self, desde: date, hasta: date) -> list[Incidencia]:
        return [i for i in self.incidencias if desde <= i.fecha <= hasta]

    def to_dict(self) -> dict:
        return {
            "materiales": [m.to_dict() for m in self.materiales.values()],
            "salidas": [s.to_dict() for s in self.salidas],
            "incidencias": [i.to_dict() for i in self.incidencias],
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "RegistroMaterial":
        registro = cls()
        for d in datos.get("materiales", []):
            material = Material.from_dict(d)
            registro.materiales[material.nombre] = material
        registro.salidas = [SalidaMaterial.from_dict(d) for d in datos.get("salidas", [])]
        registro.incidencias = [Incidencia.from_dict(d) for d in datos.get("incidencias", [])]
        return registro


def lista_de_carga(materiales_por_comensal: dict[str, float], comensales: int) -> dict[str, int]:
    """Cuántas unidades de cada material hacen falta (siempre enteras, redondeando hacia arriba)."""
    return {nombre: math.ceil(cantidad * comensales - 1e-9) for nombre, cantidad in materiales_por_comensal.items()}


if __name__ == "__main__":
    registro = RegistroMaterial()
    registro.agregar_material(Material("Plato llano", "Vajilla", 100, 3.5, "Hostelería Total"))
    registro.agregar_material(Material("Copa de vino", "Cristalería", 60, 2.8))

    carga = lista_de_carga({"Plato llano": 1, "Copa de vino": 1}, 40)
    registro.registrar_salida(7, carga)
    print(f"Platos: total 100, en uso {registro.en_uso('Plato llano')}, disponibles {registro.disponibles('Plato llano')}")

    # Vuelven 38 platos (2 rotos) y 37 copas (3 que no aparecen)
    registro.registrar_vuelta(7, {"Plato llano": 38, "Copa de vino": 37}, rotos={"Plato llano": 2})
    print(f"Platos ahora: {registro.buscar('Plato llano').cantidad_total} | "
          f"coste de roturas y pérdidas del servicio: {registro.coste_incidencias_servicio(7)}€")
