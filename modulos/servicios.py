"""
Módulo: servicios.py
---------------------
Gestiona el registro de servicios (eventos/comidas) del restaurante:
fecha, hora, número de comensales, menú elegido y estado del servicio.

Conceptos de Python nuevos en este módulo:
- Atributos de CLASE (compartidos por todos los objetos) vs atributos
  de INSTANCIA (propios de cada objeto) -> los usamos para generar
  un id automático y único para cada servicio.
- Combinar fecha y hora con `datetime.combine`
- `timedelta` para calcular rangos de fechas ("próximos N días")
- Ordenar listas de objetos con `sorted(..., key=...)`
"""

from datetime import date, time, datetime, timedelta
from typing import Optional


class Servicio:
    """
    Representa UN servicio: una comida/evento reservado en el restaurante.
    """

    # --- ATRIBUTO DE CLASE ---
    # Esta variable NO pertenece a un Servicio en concreto, pertenece a la
    # CLASE Servicio y la comparten TODOS los objetos que crees. La usamos
    # como contador para asignar un id único a cada servicio nuevo.
    _siguiente_id = 1

    ESTADOS_VALIDOS = ("pendiente", "confirmado", "cancelado", "completado")

    def __init__(
        self,
        fecha: date,
        hora: time,
        comensales: int,
        menu: str,
        notas: str = "",
        estado: str = "pendiente",
    ):
        if comensales <= 0:
            raise ValueError("El número de comensales debe ser mayor que 0")
        if estado not in self.ESTADOS_VALIDOS:
            raise ValueError(f"Estado no válido: {estado}")

        # self.id es un atributo de INSTANCIA: cada Servicio tiene el suyo.
        self.id = Servicio._siguiente_id
        Servicio._siguiente_id += 1  # incrementamos el contador compartido

        self.fecha = fecha
        self.hora = hora
        self.comensales = comensales
        self.menu = menu
        self.notas = notas
        self.estado = estado

    def fecha_hora(self) -> datetime:
        """Combina fecha y hora en un único objeto datetime."""
        return datetime.combine(self.fecha, self.hora)

    def confirmar(self) -> None:
        self.estado = "confirmado"

    def cancelar(self) -> None:
        self.estado = "cancelado"

    def completar(self) -> None:
        self.estado = "completado"

    def __str__(self) -> str:
        return (
            f"[#{self.id}] {self.fecha.strftime('%d/%m/%Y')} {self.hora.strftime('%H:%M')} | "
            f"{self.comensales} comensales | Menú: {self.menu} | Estado: {self.estado}"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fecha": self.fecha.isoformat(),
            "hora": self.hora.isoformat(),
            "comensales": self.comensales,
            "menu": self.menu,
            "notas": self.notas,
            "estado": self.estado,
        }

    @classmethod
    def from_dict(cls, datos: dict) -> "Servicio":
        servicio = cls(
            fecha=date.fromisoformat(datos["fecha"]),
            hora=time.fromisoformat(datos["hora"]),
            comensales=datos["comensales"],
            menu=datos["menu"],
            notas=datos["notas"],
            estado=datos["estado"],
        )
        # El constructor le asigna un id NUEVO automáticamente (usando el
        # contador de clase); lo sobrescribimos con el id ORIGINAL guardado,
        # para que este servicio siga siendo "el mismo" que antes de guardar.
        servicio.id = datos["id"]
        return servicio


class RegistroServicios:
    """Gestiona la colección de todos los servicios del restaurante."""

    def __init__(self):
        self.servicios: list[Servicio] = []

    def agregar_servicio(self, servicio: Servicio) -> None:
        self.servicios.append(servicio)
        print(f"✅ Servicio añadido: {servicio}")

    def buscar_por_id(self, id_servicio: int) -> Optional[Servicio]:
        for s in self.servicios:
            if s.id == id_servicio:
                return s
        return None

    def cancelar_servicio(self, id_servicio: int) -> None:
        servicio = self.buscar_por_id(id_servicio)
        if servicio is None:
            print(f"❌ No existe un servicio con id {id_servicio}")
            return
        servicio.cancelar()
        print(f"🚫 Servicio #{id_servicio} cancelado")

    def servicios_por_fecha(self, fecha: date) -> list[Servicio]:
        return [s for s in self.servicios if s.fecha == fecha]

    def servicios_proximos(self, dias: int = 7) -> list[Servicio]:
        """
        Servicios TODAVÍA POR HACER entre hoy y dentro de `dias` días.
        Se excluyen los cancelados y también los completados: un servicio
        ya hecho no es "próximo", y si contara en la lista de la compra
        pediría otra vez los ingredientes que ya se gastaron.
        """
        hoy = date.today()
        limite = hoy + timedelta(days=dias)
        return [
            s for s in self.servicios
            if hoy <= s.fecha <= limite and s.estado not in ("cancelado", "completado")
        ]

    def total_comensales_periodo(self, fecha_inicio: date, fecha_fin: date) -> int:
        return sum(
            s.comensales for s in self.servicios
            if fecha_inicio <= s.fecha <= fecha_fin and s.estado != "cancelado"
        )

    def listar_todos(self) -> None:
        if not self.servicios:
            print("No hay servicios registrados.")
            return
        # sorted() no modifica la lista original; devuelve una copia ordenada.
        # key=lambda s: (s.fecha, s.hora) -> ordena primero por fecha y,
        # si coinciden, por hora.
        for s in sorted(self.servicios, key=lambda s: (s.fecha, s.hora)):
            print(s)

    def to_dict(self) -> dict:
        return {"servicios": [s.to_dict() for s in self.servicios]}

    @classmethod
    def from_dict(cls, datos: dict) -> "RegistroServicios":
        registro = cls()
        for datos_servicio in datos["servicios"]:
            registro.servicios.append(Servicio.from_dict(datos_servicio))

        # Reajustamos el contador de ids: si no lo hiciéramos, el próximo
        # servicio que se cree podría reutilizar un id ya usado por uno
        # de los que acabamos de cargar.
        if registro.servicios:
            id_maximo = max(s.id for s in registro.servicios)
            Servicio._siguiente_id = id_maximo + 1

        return registro


if __name__ == "__main__":
    # --- DEMO ---
    registro = RegistroServicios()

    registro.agregar_servicio(Servicio(
        fecha=date(2026, 9, 5),
        hora=time(21, 0),
        comensales=12,
        menu="Menú degustación otoño",
        notas="Cumpleaños, tarta al final",
    ))

    registro.agregar_servicio(Servicio(
        fecha=date(2026, 9, 2),
        hora=time(14, 0),
        comensales=4,
        menu="Menú del día",
    ))

    registro.agregar_servicio(Servicio(
        fecha=date(2026, 9, 2),
        hora=time(21, 30),
        comensales=25,
        menu="Menú de bodas",
        estado="confirmado",
    ))

    print("\n--- Todos los servicios (ordenados por fecha/hora) ---")
    registro.listar_todos()

    print("\n--- Servicios en los próximos 7 días ---")
    for s in registro.servicios_proximos(7):
        print(s)

    print("\n--- Servicios del 2 de septiembre ---")
    for s in registro.servicios_por_fecha(date(2026, 9, 2)):
        print(s)

    total = registro.total_comensales_periodo(date(2026, 9, 1), date(2026, 9, 30))
    print(f"\n👥 Total comensales en septiembre: {total}")

    registro.cancelar_servicio(2)
    print("\n--- Tras cancelar el servicio #2 ---")
    registro.listar_todos()
