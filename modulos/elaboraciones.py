"""
Módulo: elaboraciones.py
-------------------------
Las ELABORACIONES son tandas de una receta preparadas por adelantado (por
ejemplo, 20 raciones de ensalada hechas el día 1 para un servicio del día
3). Funcionan como los lotes de un producto:

- Cada tanda tiene sus raciones, su fecha de preparación, su caducidad y su
  coste real por ración (lo que costaron los ingredientes, a precio de
  cada lote).
- Al completar un servicio se pueden usar raciones de una o varias tandas
  en vez de gastar los ingredientes en crudo.
- Las tandas que caducan se pueden desechar (cuenta como desperdicio).

Este módulo solo GUARDA las tandas y lo que se hace con ellas. Prepararlas
(descontar los ingredientes) lo hace Recetario.preparar_elaboracion(),
porque necesita las recetas.
"""

from datetime import date
from typing import Optional


class Tanda:
    """UNA tanda de una receta preparada: ej. 'Ensalada de tomate, 20 raciones, caduca el 04/10'."""

    def __init__(
        self,
        id: int,
        receta: str,
        raciones: float,
        coste_por_racion: float,
        fecha_preparacion: Optional[date] = None,
        fecha_caducidad: Optional[date] = None,
        raciones_iniciales: Optional[float] = None,
        coste_por_racion_sin_iva: Optional[float] = None,
    ):
        if raciones < 0:
            raise ValueError("Las raciones no pueden ser negativas.")
        self.id = id
        self.receta = receta
        self.raciones = raciones  # las que QUEDAN
        self.raciones_iniciales = raciones if raciones_iniciales is None else raciones_iniciales
        self.coste_por_racion = coste_por_racion  # lo pagado (con IVA)
        # El mismo coste sin el IVA de los ingredientes (para la rentabilidad
        # si el negocio recupera el IVA). Las tandas antiguas no lo tienen.
        self.coste_por_racion_sin_iva = coste_por_racion if coste_por_racion_sin_iva is None else coste_por_racion_sin_iva
        self.fecha_preparacion = fecha_preparacion or date.today()
        self.fecha_caducidad = fecha_caducidad

    def dias_para_caducar(self) -> Optional[int]:
        if self.fecha_caducidad is None:
            return None
        return (self.fecha_caducidad - date.today()).days

    def esta_caducada(self, en_fecha: Optional[date] = None) -> bool:
        """True si ya ha caducado (o si habrá caducado en `en_fecha`, si se indica)."""
        if self.fecha_caducidad is None:
            return False
        return self.fecha_caducidad < (en_fecha or date.today())

    def valor(self) -> float:
        return round(self.raciones * self.coste_por_racion, 2)

    def etiqueta(self) -> str:
        """'Tanda 2 · preparada 01/10 · cad. 04/10/2026'."""
        caducidad = f"cad. {self.fecha_caducidad.strftime('%d/%m/%Y')}" if self.fecha_caducidad else "sin caducidad"
        return f"Tanda {self.id} · preparada {self.fecha_preparacion.strftime('%d/%m')} · {caducidad}"

    def descripcion(self) -> str:
        return f"{self.etiqueta()} · {round(self.raciones, 3):g} raciones · {self.coste_por_racion:.2f} €/ración"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "receta": self.receta, "raciones": self.raciones,
            "raciones_iniciales": self.raciones_iniciales, "coste_por_racion": self.coste_por_racion,
            "coste_por_racion_sin_iva": self.coste_por_racion_sin_iva,
            "fecha_preparacion": self.fecha_preparacion.isoformat(),
            "fecha_caducidad": self.fecha_caducidad.isoformat() if self.fecha_caducidad else None,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Tanda":
        return cls(
            datos["id"], datos["receta"], datos["raciones"], datos["coste_por_racion"],
            date.fromisoformat(datos["fecha_preparacion"]),
            date.fromisoformat(datos["fecha_caducidad"]) if datos.get("fecha_caducidad") else None,
            datos.get("raciones_iniciales"), datos.get("coste_por_racion_sin_iva"),
        )


class UsoTanda:
    """Lo que se hizo con raciones de una tanda: se sirvieron en un servicio o se tiraron."""

    MOTIVOS = ("consumo", "desperdicio")

    def __init__(
        self, tanda_id: int, receta: str, raciones: float, motivo: str, coste: float,
        servicio_id: Optional[int] = None, fecha: Optional[date] = None, coste_sin_iva: Optional[float] = None,
    ):
        if motivo not in self.MOTIVOS:
            raise ValueError(f"Motivo no válido: {motivo}")
        self.tanda_id = tanda_id
        self.receta = receta
        self.raciones = raciones
        self.motivo = motivo
        self.coste = round(coste, 2)  # con IVA
        self.coste_sin_iva = self.coste if coste_sin_iva is None else round(coste_sin_iva, 2)
        self.servicio_id = servicio_id
        self.fecha = fecha or date.today()

    def to_dict(self) -> dict:
        return {
            "tanda_id": self.tanda_id, "receta": self.receta, "raciones": self.raciones, "motivo": self.motivo,
            "coste": self.coste, "coste_sin_iva": self.coste_sin_iva, "servicio_id": self.servicio_id,
            "fecha": self.fecha.isoformat(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "UsoTanda":
        return cls(
            datos["tanda_id"], datos["receta"], datos["raciones"], datos["motivo"], datos["coste"],
            datos.get("servicio_id"), date.fromisoformat(datos["fecha"]), datos.get("coste_sin_iva"),
        )


class PreparacionBase:
    """
    Registro de UNA preparación de una elaboración base: cuánto se pensaba
    sacar con la fórmula, cuánto salió de verdad y cuánto costó.
    """

    def __init__(
        self, producto: str, unidad: str, prevista: float, obtenida: float, coste: float,
        lote_id: Optional[int] = None, fecha: Optional[date] = None,
    ):
        self.producto = producto
        self.unidad = unidad
        self.prevista = prevista
        self.obtenida = obtenida
        self.coste = round(coste, 2)
        self.lote_id = lote_id
        self.fecha = fecha or date.today()

    @property
    def diferencia(self) -> float:
        return round(self.obtenida - self.prevista, 3)

    @property
    def coste_por_unidad(self) -> float:
        return round(self.coste / self.obtenida, 4) if self.obtenida else 0.0

    def to_dict(self) -> dict:
        return {
            "producto": self.producto, "unidad": self.unidad, "prevista": self.prevista, "obtenida": self.obtenida,
            "coste": self.coste, "lote_id": self.lote_id, "fecha": self.fecha.isoformat(),
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "PreparacionBase":
        return cls(
            datos["producto"], datos["unidad"], datos["prevista"], datos["obtenida"], datos["coste"],
            datos.get("lote_id"), date.fromisoformat(datos["fecha"]),
        )


def _clave_caducidad(tanda: Tanda) -> tuple:
    """Lo que caduca antes, primero; sin caducidad, al final."""
    return (tanda.fecha_caducidad is None, tanda.fecha_caducidad or date.max, tanda.id)


class RegistroElaboraciones:
    """Todas las tandas preparadas y lo que se ha hecho con ellas."""

    def __init__(self):
        self.tandas: list[Tanda] = []  # solo las que tienen raciones
        self.usos: list[UsoTanda] = []
        self.siguiente_id = 1
        # Historial de preparaciones de elaboraciones BASE (previsto/obtenido).
        self.preparaciones_base: list[PreparacionBase] = []

    def nueva_tanda(
        self, receta: str, raciones: float, coste_por_racion: float,
        fecha_caducidad: Optional[date] = None, fecha_preparacion: Optional[date] = None,
        coste_por_racion_sin_iva: Optional[float] = None,
    ) -> Tanda:
        if raciones <= 0:
            raise ValueError("Las raciones deben ser más de 0.")
        tanda = Tanda(self.siguiente_id, receta, raciones, coste_por_racion, fecha_preparacion, fecha_caducidad,
                      coste_por_racion_sin_iva=coste_por_racion_sin_iva)
        self.siguiente_id += 1
        self.tandas.append(tanda)
        print(f"🥘 Elaboración preparada: {receta} -> {tanda.descripcion()}")
        return tanda

    def buscar(self, tanda_id: int) -> Optional[Tanda]:
        return next((t for t in self.tandas if t.id == tanda_id), None)

    def tandas_de(self, receta: str, para_fecha: Optional[date] = None) -> list[Tanda]:
        """
        Las tandas de una receta, primero las que caducan antes. Con
        `para_fecha`, solo las que no habrán caducado ese día.
        """
        tandas = [t for t in self.tandas if t.receta == receta and t.raciones > 1e-9]
        if para_fecha is not None:
            tandas = [t for t in tandas if not t.esta_caducada(para_fecha)]
        return sorted(tandas, key=_clave_caducidad)

    def raciones_disponibles(self, receta: str, para_fecha: Optional[date] = None) -> float:
        return round(sum(t.raciones for t in self.tandas_de(receta, para_fecha)), 3)

    def repartir(self, receta: str, raciones: float, tandas_en_orden: list[int]) -> tuple[list[tuple[int, float]], float]:
        """Como Inventario.repartir(): cómo sacar `raciones` de las tandas indicadas, en orden. (reparto, lo_que_falta)."""
        reparto: list[tuple[int, float]] = []
        pendiente = raciones
        for tanda_id in tandas_en_orden:
            tanda = self.buscar(tanda_id)
            if tanda is None or tanda.receta != receta or pendiente <= 1e-9:
                continue
            sale = round(min(pendiente, tanda.raciones), 6)
            if sale > 0:
                reparto.append((tanda_id, sale))
                pendiente -= sale
        return reparto, round(max(0.0, pendiente), 6)

    def _sacar(self, tanda: Tanda, raciones: float, motivo: str, servicio_id: Optional[int]) -> UsoTanda:
        raciones = min(raciones, tanda.raciones)
        tanda.raciones = round(tanda.raciones - raciones, 6)
        uso = UsoTanda(tanda.id, tanda.receta, raciones, motivo, raciones * tanda.coste_por_racion, servicio_id,
                       coste_sin_iva=raciones * tanda.coste_por_racion_sin_iva)
        self.usos.append(uso)
        self.tandas = [t for t in self.tandas if t.raciones > 1e-9]  # una tanda vacía desaparece
        return uso

    def usar(self, reparto: list[tuple[int, float]], servicio_id: Optional[int] = None) -> list[UsoTanda]:
        """Saca raciones de varias tandas (comprobando todo antes de tocar nada)."""
        for tanda_id, raciones in reparto:
            tanda = self.buscar(tanda_id)
            if tanda is None:
                raise ValueError(f"No existe la tanda {tanda_id}.")
            if raciones > tanda.raciones + 1e-9:
                raise ValueError(f"En la tanda {tanda_id} solo quedan {tanda.raciones:g} raciones.")
        return [self._sacar(self.buscar(t), r, "consumo", servicio_id) for t, r in reparto if r > 0]

    def desechar(self, tanda_id: int) -> UsoTanda:
        """Tira una tanda entera (normalmente caducada): cuenta como desperdicio, con su coste."""
        tanda = self.buscar(tanda_id)
        if tanda is None:
            raise ValueError(f"No existe la tanda {tanda_id}.")
        uso = self._sacar(tanda, tanda.raciones, "desperdicio", None)
        print(f"🗑️  Tanda desechada: {tanda.receta} ({uso.raciones:g} raciones, {uso.coste}€)")
        return uso

    def corregir(
        self, tanda_id: int, raciones: Optional[float] = None, fecha_caducidad: Optional[date] = None,
        borrar_caducidad: bool = False,
    ) -> None:
        """Corrige una tanda (un error al apuntarla). No es un uso: no cuenta como consumo ni desperdicio."""
        tanda = self.buscar(tanda_id)
        if tanda is None:
            raise ValueError(f"No existe la tanda {tanda_id}.")
        if raciones is not None:
            if raciones < 0:
                raise ValueError("Las raciones no pueden ser negativas.")
            tanda.raciones = raciones
        if borrar_caducidad:
            tanda.fecha_caducidad = None
        elif fecha_caducidad is not None:
            tanda.fecha_caducidad = fecha_caducidad
        self.tandas = [t for t in self.tandas if t.raciones > 1e-9]

    def caducadas(self) -> list[Tanda]:
        return sorted((t for t in self.tandas if t.esta_caducada()), key=_clave_caducidad)

    def proximas_a_caducar(self, dias: int = 7) -> list[Tanda]:
        return sorted(
            (t for t in self.tandas if t.dias_para_caducar() is not None and 0 <= t.dias_para_caducar() <= dias),
            key=_clave_caducidad,
        )

    def usos_de_servicio(self, servicio_id: int) -> list[UsoTanda]:
        return [u for u in self.usos if u.servicio_id == servicio_id and u.motivo == "consumo"]

    def coste_servicio(self, servicio_id: int, sin_iva: bool = False) -> float:
        """Lo que costaron las raciones preparadas usadas en un servicio (con IVA, o sin él si `sin_iva`)."""
        return round(sum(u.coste_sin_iva if sin_iva else u.coste for u in self.usos_de_servicio(servicio_id)), 2)

    def desperdicio_en_rango(self, desde: date, hasta: date) -> float:
        return round(sum(u.coste for u in self.usos if u.motivo == "desperdicio" and desde <= u.fecha <= hasta), 2)

    def renombrar_receta(self, antigua: str, nueva: str) -> None:
        for t in self.tandas:
            if t.receta == antigua:
                t.receta = nueva
        for u in self.usos:
            if u.receta == antigua:
                u.receta = nueva

    def to_dict(self) -> dict:
        return {
            "tandas": [t.to_dict() for t in self.tandas],
            "usos": [u.to_dict() for u in self.usos],
            "siguiente_id": self.siguiente_id,
            "preparaciones_base": [p.to_dict() for p in self.preparaciones_base],
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "RegistroElaboraciones":
        registro = cls()
        registro.tandas = [Tanda.from_dict(d) for d in datos.get("tandas", [])]
        registro.usos = [UsoTanda.from_dict(d) for d in datos.get("usos", [])]
        registro.siguiente_id = datos.get("siguiente_id", 1)
        registro.preparaciones_base = [PreparacionBase.from_dict(d) for d in datos.get("preparaciones_base", [])]
        return registro
