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
        precio_cobrado: Optional[float] = None,
        cliente: str = "",
        lugar: str = "",
    ):
        """
        precio_cobrado: lo que se cobra por el servicio ENTERO (opcional).
        Sirve para calcular el margen; si no se indica, el programa
        funciona igual, solo que sin margen.

        cliente y lugar: para quién y dónde es (opcionales). Sirven para
        buscar en el historial ("todo lo que hemos hecho para los García").
        """
        if comensales <= 0:
            raise ValueError("El número de comensales debe ser mayor que 0")
        if estado not in self.ESTADOS_VALIDOS:
            raise ValueError(f"Estado no válido: {estado}")
        if precio_cobrado is not None and precio_cobrado < 0:
            raise ValueError("El precio cobrado no puede ser negativo")

        # self.id es un atributo de INSTANCIA: cada Servicio tiene el suyo.
        self.id = Servicio._siguiente_id
        Servicio._siguiente_id += 1  # incrementamos el contador compartido

        self.fecha = fecha
        self.hora = hora
        self.comensales = comensales
        self.menu = menu
        self.notas = notas
        self.estado = estado
        self.precio_cobrado = precio_cobrado
        self.cliente = cliente.strip()
        self.lugar = lugar.strip()
        # Se rellenan al completar el servicio (ver Recetario.completar_servicio):
        self.fecha_completado: Optional[date] = None
        # Copia de cómo era el menú AL COMPLETARLO (recetas, cantidades,
        # consumibles y material): si después se cambia la receta, el
        # historial sigue mostrando lo que se hizo de verdad.
        self.menu_completado: Optional[dict] = None
        # "Cómo fue": incidencias, qué sobró o faltó, qué cambiar la próxima vez.
        self.valoracion = ""

    def fecha_hora(self) -> datetime:
        """Combina fecha y hora en un único objeto datetime."""
        return datetime.combine(self.fecha, self.hora)

    def confirmar(self) -> None:
        self.estado = "confirmado"

    def cancelar(self) -> None:
        # Un servicio ya hecho no se cancela: su stock ya salió y sus costes son reales.
        if self.estado == "completado":
            raise ValueError("Este servicio ya está completado: no se puede cancelar.")
        self.estado = "cancelado"

    def editar(
        self,
        fecha: Optional[date] = None,
        hora: Optional[time] = None,
        comensales: Optional[int] = None,
        menu: Optional[str] = None,
        notas: Optional[str] = None,
        cliente: Optional[str] = None,
        lugar: Optional[str] = None,
        precio_cobrado: Optional[float] = None,
        quitar_precio: bool = False,
        estado: Optional[str] = None,
    ) -> None:
        """
        Cambia los datos de un servicio que TODAVÍA NO SE HA HECHO (pendiente o
        confirmado). None = "no lo toques". `estado` solo puede ser
        "pendiente" o "confirmado" (para cancelar o completar están sus
        propias acciones). quitar_precio=True deja el servicio sin precio de cobro.
        Uno completado o cancelado no se edita: su stock y sus costes ya son reales.
        """
        if self.estado not in ("pendiente", "confirmado"):
            raise ValueError(f"El servicio #{self.id} está {self.estado}: ya no se puede editar.")
        if comensales is not None and comensales <= 0:
            raise ValueError("El número de comensales debe ser mayor que 0")
        if menu is not None and not menu.strip():
            raise ValueError("Elige el menú del servicio.")
        if precio_cobrado is not None and precio_cobrado < 0:
            raise ValueError("El precio cobrado no puede ser negativo")
        if estado is not None and estado not in ("pendiente", "confirmado"):
            raise ValueError("Aquí el estado solo puede ser 'pendiente' o 'confirmado'.")
        if fecha is not None:
            self.fecha = fecha
        if hora is not None:
            self.hora = hora
        if comensales is not None:
            self.comensales = int(comensales)
        if menu is not None:
            self.menu = menu.strip()
        if notas is not None:
            self.notas = notas
        if cliente is not None:
            self.cliente = cliente.strip()
        if lugar is not None:
            self.lugar = lugar.strip()
        if quitar_precio:
            self.precio_cobrado = None
        elif precio_cobrado is not None:
            self.precio_cobrado = precio_cobrado
        if estado is not None:
            self.estado = estado
        print(f"✏️  Servicio editado: {self}")

    def completar(self) -> None:
        self.estado = "completado"
        self.fecha_completado = date.today()

    def __str__(self) -> str:
        cobro = f" | Cobro: {self.precio_cobrado}€" if self.precio_cobrado is not None else ""
        cliente = f" | Cliente: {self.cliente}" if self.cliente else ""
        lugar = f" | Lugar: {self.lugar}" if self.lugar else ""
        return (
            f"[#{self.id}] {self.fecha.strftime('%d/%m/%Y')} {self.hora.strftime('%H:%M')} | "
            f"{self.comensales} comensales | Menú: {self.menu} | Estado: {self.estado}{cliente}{lugar}{cobro}"
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
            "precio_cobrado": self.precio_cobrado,
            "cliente": self.cliente,
            "lugar": self.lugar,
            "fecha_completado": self.fecha_completado.isoformat() if self.fecha_completado else None,
            "menu_completado": self.menu_completado,
            "valoracion": self.valoracion,
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
            precio_cobrado=datos.get("precio_cobrado"),  # no existe en sesiones antiguas
            cliente=datos.get("cliente", ""),
            lugar=datos.get("lugar", ""),
        )
        if datos.get("fecha_completado"):
            servicio.fecha_completado = date.fromisoformat(datos["fecha_completado"])
        servicio.menu_completado = datos.get("menu_completado")
        servicio.valoracion = datos.get("valoracion", "")
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
        # El número de servicio no se puede repetir (si el programa se abre en
        # dos ventanas, el contador compartido podría dar uno ya usado).
        usados = {s.id for s in self.servicios}
        if servicio.id in usados:
            servicio.id = max(usados) + 1
        Servicio._siguiente_id = max(Servicio._siguiente_id, servicio.id + 1)
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
        servicio.cancelar()  # lanza ValueError si ya está completado
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

    def servicios_de_hoy(self, hoy: Optional[date] = None) -> list[Servicio]:
        """Los servicios de hoy (sin los cancelados), por hora."""
        hoy = hoy or date.today()
        return sorted((s for s in self.servicios if s.fecha == hoy and s.estado != "cancelado"), key=lambda s: s.hora)

    def pasados_sin_completar(self, hoy: Optional[date] = None) -> list[Servicio]:
        """
        Servicios de días ANTERIORES a hoy que siguen pendientes o confirmados:
        seguramente se hicieron (o se anularon) y nadie lo apuntó. Mientras
        tanto, su stock no se descuenta y su coste real no cuenta.
        """
        hoy = hoy or date.today()
        return sorted((s for s in self.servicios if s.fecha < hoy and s.estado in ("pendiente", "confirmado")),
                      key=lambda s: (s.fecha, s.hora))

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
