"""
pruebas/probar_logica.py
--------------------------
Prueba la LÓGICA del programa (sin interfaz): lotes (entradas, salidas de
un lote elegido, desechar caducados, limpiezas por lote, completar
servicios eligiendo lotes, guardar/cargar, sesiones antiguas) y
consumibles.

Es un script normal de Python (sin pytest). Se ejecuta en GitHub Actions
junto a las pruebas de la interfaz, y también a mano:
    python pruebas/probar_logica.py
"""

import io
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, time, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "modulos"))

from inventario import Inventario, Producto  # noqa: E402
from metricas import Metricas  # noqa: E402
from recetario import Menu, Receta, Recetario  # noqa: E402
from servicios import Servicio  # noqa: E402
from exportador import exportar_todo  # noqa: E402
from servicios import RegistroServicios  # noqa: E402
from compras import GestorCompras  # noqa: E402

HOY = date.today()
fallos: list[str] = []

# Las pruebas de costes de servicios (hasta la sección de IVA) cuentan lo
# PAGADO, con IVA: el modo "no recupero el IVA". La sección de IVA prueba el otro.
from inventario import AJUSTES  # noqa: E402
AJUSTES["iva_recuperable"] = False


def comprobar(condicion: bool, descripcion: str) -> None:
    print(("✅ " if condicion else "❌ ") + descripcion)
    if not condicion:
        fallos.append(descripcion)


def silencio(funcion, *args, **kwargs):
    """Ejecuta sin llenar la pantalla con los print() de los módulos."""
    with redirect_stdout(io.StringIO()):
        return funcion(*args, **kwargs)


def inventario_secreto() -> Inventario:
    """Tu ejemplo: 1 kg de secreto que caduca pronto + una compra nueva que caduca más tarde."""
    inv = Inventario()
    silencio(inv.agregar_producto, Producto(
        "Secreto", "Carnes", 1, "kg", 14, "Carnicería Pepe", stock_minimo=0.5,
        fecha_caducidad=HOY + timedelta(days=10),
    ))
    silencio(inv.entrada_stock, "Secreto", 0.8, precio_unitario=15, proveedor="Ibéricos Sierra",
             fecha_caducidad=HOY + timedelta(days=15))
    return inv


print("--- Entradas: cada compra es un lote ---")
inv = inventario_secreto()
secreto = inv.buscar_producto("Secreto")
comprobar(len(secreto.lotes) == 2, "Una compra nueva crea un segundo lote")
comprobar(secreto.stock == 1.8, "El stock total es la suma de los lotes (1,8 kg)")
comprobar(secreto.fecha_caducidad == HOY + timedelta(days=10), "La caducidad del producto es la del lote más próximo")
comprobar(abs(secreto.valor_total() - 26) < 1e-9, "El valor es cada lote a su precio (14 + 12 = 26 €)")
comprobar(secreto.lotes[1].proveedor == "Ibéricos Sierra", "Cada lote guarda su proveedor")
silencio(inv.entrada_stock, "Secreto", 0.5, fecha_caducidad=HOY + timedelta(days=15))
comprobar(len(secreto.lotes) == 3, "Aunque tenga la misma caducidad, cada compra es un lote aparte")
comprobar(secreto.lotes[2].proveedor == "Carnicería Pepe" and secreto.lotes[2].precio_unitario == 15,
          "Sin indicar proveedor ni precio se usan el habitual y el de la última compra")
silencio(inv.agregar_producto, Producto("Aceite", "Aceites", 5, "litros", 4, "Oleícola"))
silencio(inv.entrada_stock, "Aceite", 5, precio_unitario=4.5)
aceite = inv.buscar_producto("Aceite")
comprobar(len(aceite.lotes) == 2 and aceite.fecha_caducidad is None,
          "Los productos sin caducidad también tienen un lote por compra")

print("\n--- Salidas: del lote que elige el usuario ---")
inv = inventario_secreto()
secreto = inv.buscar_producto("Secreto")
comprobar(silencio(inv.salida_stock, "Secreto", 0.3, "consumo", 2), "Se puede sacar del lote que caduca MÁS TARDE")
comprobar(abs(secreto.buscar_lote(2).cantidad - 0.5) < 1e-9 and secreto.buscar_lote(1).cantidad == 1,
          "Solo baja el lote elegido")
comprobar(not silencio(inv.salida_stock, "Secreto", 0.6, "consumo", 2), "No se puede sacar de un lote más de lo que tiene")
comprobar(inv.historial[-1].lote_id == 2 and inv.historial[-1].precio_unitario == 15,
          "El historial apunta el lote y su precio real")
silencio(inv.salida_stock, "Secreto", 0.5, "consumo", 2)
comprobar(secreto.buscar_lote(2) is None and len(secreto.lotes) == 1, "Un lote que llega a 0 desaparece")
silencio(inv.entrada_stock, "Secreto", 1)
comprobar(secreto.lotes[-1].id == 3, "Los números de lote no se reutilizan")

print("\n--- Desechar un lote caducado ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta", fecha_caducidad=HOY - timedelta(days=1)))
silencio(inv.entrada_stock, "Tomate", 3, precio_unitario=2.5, fecha_caducidad=HOY + timedelta(days=5))
comprobar(len(inv.lotes_caducados()) == 1, "Se detecta el lote caducado")
comprobar(len(inv.lotes_proximos_a_caducar()) == 1, "Y el que caduca en los próximos días, aparte")
comprobar(silencio(inv.desechar_lote, "Tomate", 1), "Se desecha el lote caducado")
tomate = inv.buscar_producto("Tomate")
comprobar(tomate.stock == 3 and not inv.lotes_caducados(), "Solo queda el lote bueno")
desperdicio = Metricas(inv).cantidad_desperdiciada("Tomate", HOY, HOY)
comprobar(desperdicio == 2, "Queda registrado como desperdicio (2 kg)")
comprobar(Metricas(inv).gasto_por_categoria(HOY, HOY) == {"Verduras": 7.5},
          "El gasto cuenta la compra a su precio (3 kg x 2,5 €); el stock inicial no es una compra")

print("\n--- Limpieza de un lote concreto ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Pata", "Carnes", 2, "unidades", 45, "Carnicería Pepe",
                                        tiene_merma=True, peso_unitario=7))
silencio(inv.entrada_stock, "Pata", 1, precio_unitario=50, peso_unitario=8)
pata = inv.buscar_producto("Pata")
comprobar(pata.lotes[1].peso_unitario == 8, "Cada lote de patas guarda su propio peso por unidad")
try:
    silencio(inv.limpiar_producto, "Pata", 1, "Carne limpia", 5)
    comprobar(False, "Con varios lotes hay que elegir cuál se limpia")
except ValueError:
    comprobar(True, "Con varios lotes hay que elegir cuál se limpia")
limpieza = silencio(inv.limpiar_producto, "Pata", 1, "Carne limpia", 5, {"Hueso": 1.5}, lote_id=2)
comprobar(limpieza.peso_bruto_kg == 8 and limpieza.coste == 50, "Usa el peso y el precio de ESE lote (8 kg, 50 €)")
comprobar(limpieza.lote_origen and "Lote 2" in limpieza.lote_origen, "La limpieza recuerda de qué lote salió")
limpia = inv.buscar_producto("Carne limpia")
comprobar(limpia.lotes[0].precio_unitario == 10, "El lote limpio carga con todo el coste (50 € / 5 kg)")
comprobar(inv.buscar_producto("Hueso").lotes[0].precio_unitario == 0, "Los derivados entran a coste 0")
comprobar(pata.stock == 2 and pata.buscar_lote(2) is None, "Solo sale el lote limpiado")

print("\n--- Completar un servicio eligiendo lotes ---")
inv = inventario_secreto()
recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Secreto a la brasa", "Principal", {"Secreto": 0.2}))
silencio(recetario.agregar_menu, Menu("Menú brasa", [recetario.recetas["Secreto a la brasa"]]))
servicio = Servicio(HOY, time(21, 0), 5, "Menú brasa")  # 1 kg de secreto

fila = recetario.previsualizar_consumo(servicio, inv)[0]
comprobar(fila["lotes_elegidos"] == [1] and fila["sin_asignar"] == 0,
          "Por defecto propone el lote que caduca antes (y aquí llega)")
fila = recetario.previsualizar_consumo(servicio, inv, {"Secreto": [2]})[0]
comprobar(abs(fila["sin_asignar"] - 0.2) < 1e-9 and fila["lotes_restantes"] == [1],
          "Si el lote elegido no llega, dice cuánto falta y con qué lotes se puede completar")
try:
    silencio(recetario.completar_servicio, servicio, inv, {"Secreto": [2]})
    comprobar(False, "No deja completar sin elegir con qué lote se completa")
except ValueError:
    comprobar(True, "No deja completar sin elegir con qué lote se completa")
comprobar(inv.buscar_producto("Secreto").stock == 1.8 and servicio.estado == "pendiente", "...y no toca nada")
silencio(recetario.completar_servicio, servicio, inv, {"Secreto": [2, 1]})
secreto = inv.buscar_producto("Secreto")
comprobar(secreto.buscar_lote(2) is None and abs(secreto.buscar_lote(1).cantidad - 0.8) < 1e-9,
          "Saca 0,8 del lote 2 y los 0,2 que faltan del lote 1")
comprobar(servicio.estado == "completado", "El servicio queda completado")

inv = inventario_secreto()
grande = Servicio(HOY, time(21, 0), 20, "Menú brasa")  # 4 kg: no hay suficiente
fila = recetario.previsualizar_consumo(grande, inv, {"Secreto": [2]})[0]
comprobar(fila["sin_asignar"] == 0 and fila["faltante"] == 2.2, "Si no hay bastante en total, se usan todos los lotes")
silencio(recetario.completar_servicio, grande, inv, {"Secreto": [2]})
comprobar(inv.buscar_producto("Secreto").stock == 0, "...y se descuenta todo lo que había")

print("\n--- Guardar, cargar y sesiones antiguas ---")
inv = inventario_secreto()
silencio(inv.salida_stock, "Secreto", 0.3, "consumo", 1)
copia = Inventario.from_dict(inv.to_dict())
s2 = copia.buscar_producto("Secreto")
comprobar([(l.id, l.cantidad, l.proveedor) for l in s2.lotes] == [(1, 0.7, "Carnicería Pepe"), (2, 0.8, "Ibéricos Sierra")],
          "Los lotes se guardan y se cargan igual")
comprobar(copia.historial[-1].lote == inv.historial[-1].lote, "El historial conserva el lote de cada movimiento")
antiguo = {"productos": [{
    "nombre": "Harina", "categoria": "Panadería", "stock": 3, "unidad": "kg", "precio_unitario": 1.2,
    "proveedor": "Harinas del Sur", "stock_minimo": 2, "fecha_caducidad": (HOY + timedelta(days=30)).isoformat(),
}], "historial": [{"producto_nombre": "Harina", "categoria": "Panadería", "tipo": "entrada", "cantidad": 3,
                   "unidad": "kg", "precio_unitario": 1.2, "fecha": HOY.isoformat()}]}
viejo = Inventario.from_dict(antiguo)
harina = viejo.buscar_producto("Harina")
comprobar(len(harina.lotes) == 1 and harina.stock == 3 and harina.precio_unitario == 1.2
          and harina.fecha_caducidad == HOY + timedelta(days=30),
          "Una sesión de antes de los lotes se convierte en un lote con su stock, precio y caducidad")

print("\n--- Corregir lotes y productos ---")
inv = inventario_secreto()
silencio(inv.editar_lote, "Secreto", 2, cantidad=0.75, fecha_caducidad=HOY + timedelta(days=20), proveedor="Otro")
lote = inv.buscar_producto("Secreto").buscar_lote(2)
comprobar(lote.cantidad == 0.75 and lote.proveedor == "Otro" and lote.fecha_caducidad == HOY + timedelta(days=20),
          "Se puede corregir la cantidad, el proveedor y la caducidad de un lote")
silencio(inv.editar_lote, "Secreto", 2, borrar_fecha_caducidad=True)
comprobar(lote.fecha_caducidad is None, "Se puede quitar la caducidad de un lote")
silencio(inv.editar_producto, "Secreto", nuevo_nombre="Secreto ibérico", stock_minimo=1)
comprobar(inv.buscar_producto("Secreto ibérico").stock == 1.75, "Renombrar el producto conserva sus lotes")

print("\n--- Excel ---")
inv = inventario_secreto()
with tempfile.TemporaryDirectory() as carpeta:
    ruta = silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta)
    from openpyxl import load_workbook
    libro = load_workbook(ruta)
    comprobar("Lotes" in libro.sheetnames and libro["Lotes"].max_row == 4,
              "El Excel tiene una hoja 'Lotes' con un renglón por lote (+ cabecera y total)")

print("\n--- Consumibles ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Pan", "Panadería", 5, "unidades", 0.5, "Horno"))
silencio(inv.agregar_producto, Producto(
    "Servilletas", "Desechables", 100, "unidades", 0.02, "Hostelería", stock_minimo=50,
    fecha_caducidad=HOY + timedelta(days=3), tipo="consumible",
))
serv_prod = inv.buscar_producto("Servilletas")
comprobar(serv_prod.es_consumible() and serv_prod.fecha_caducidad is None, "Un consumible no guarda caducidad")
try:
    Producto("Film", "Desechables", 1, "kg", 5, "Hostelería", tiene_merma=True, tipo="consumible")
    comprobar(False, "Un consumible no puede tener merma")
except ValueError:
    comprobar(True, "Un consumible no puede tener merma")
silencio(inv.entrada_stock, "Servilletas", 200, precio_unitario=0.01, fecha_caducidad=HOY + timedelta(days=3))
comprobar(serv_prod.lotes[-1].fecha_caducidad is None, "Sus compras tampoco guardan caducidad")
comprobar([p.nombre for p in inv.alimentos()] == ["Pan"] and [p.nombre for p in inv.consumibles()] == ["Servilletas"],
          "Alimentos y consumibles se listan por separado")

recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Bocadillo", "Principal", {"Pan": 1}))
menu = Menu("Picnic", [recetario.recetas["Bocadillo"]], {"Servilletas": 2})
silencio(recetario.agregar_menu, menu)
comprobar(menu.ingredientes_por_comensal() == {"Pan": 1}, "A simple vista, el menú solo muestra sus ingredientes")
comprobar(menu.calcular_necesidades_totales(4) == {"Pan": 4, "Servilletas": 8}, "Las necesidades suman comida y consumibles")
comprobar(menu.costo_consumibles_por_comensal(inv) > 0 and menu.costo_por_comensal(inv) == 0.5,
          "El coste de la comida y el de los consumibles se calculan por separado")
servicio = Servicio(HOY, time(14, 0), 4, "Picnic")
silencio(recetario.completar_servicio, servicio, inv, {"Servilletas": [1]})
comprobar(serv_prod.stock == 292 and inv.buscar_producto("Pan").stock == 1,
          "Completar el servicio descuenta también los consumibles (8 servilletas)")
comprobar(inv.historial[-1].tipo_producto in ("alimento", "consumible")
          and any(m.tipo_producto == "consumible" and m.motivo == "consumo" for m in inv.historial),
          "El historial sabe qué movimientos son de consumibles")
gasto = Metricas(inv).gasto_por_tipo(HOY, HOY)
comprobar(gasto == {"alimento": 0, "consumible": 2.0, "mantenimiento": 0}, f"El gasto se separa en alimentos y consumibles ({gasto})")

gestor = GestorCompras()
grande = Servicio(HOY + timedelta(days=1), time(14, 0), 200, "Picnic")
silencio(gestor.generar_lista_desde_servicios, [grande], recetario, inv)
comprobar(any(i.ingrediente == "Servilletas" and i.cantidad == 108 for i in gestor.items),
          "La lista de la compra incluye los consumibles que faltan (400 - 292 = 108)")

actualizados = recetario.renombrar_producto("Servilletas", "Servilletas blancas")
comprobar("Servilletas blancas" in menu.consumibles_por_comensal and actualizados == ["menú Picnic"],
          "Renombrar un consumible lo actualiza en los menús")

copia = Recetario.from_dict(recetario.to_dict())
comprobar(copia.menus["Picnic"].consumibles_por_comensal == {"Servilletas blancas": 2},
          "Los consumibles del menú se guardan y se cargan")
comprobar(Inventario.from_dict(inv.to_dict()).buscar_producto("Servilletas").tipo == "consumible",
          "El tipo del producto se guarda y se carga")

silencio(inv.agregar_producto, Producto("Guantes", "Limpieza", 10, "unidades", 0.1, "Hostelería",
                                        fecha_caducidad=HOY + timedelta(days=90)))
silencio(inv.salida_stock, "Guantes", 2, "consumo", 1)
silencio(inv.editar_producto, "Guantes", tipo="consumible")
guantes = inv.buscar_producto("Guantes")
comprobar(guantes.es_consumible() and guantes.fecha_caducidad is None
          and all(m.tipo_producto == "consumible" for m in inv.historial if m.producto_nombre == "Guantes"),
          "Corregir el tipo a consumible quita la caducidad y pasa su historial a consumibles")

print("\n--- Gastos, precio de cobro y margen ---")
from gastos import Gasto, RegistroGastos, resumen_servicio  # noqa: E402
from persistencia import guardar_sesion, cargar_sesion  # noqa: E402
from metricas import ArchivoInformes  # noqa: E402

for mal, motivo in (
    (lambda: Gasto("Gasolina", "Transporte", 0), "importe 0"),
    (lambda: Gasto("Gasolina", "Gasolinera", 30), "categoría inventada"),
    (lambda: Gasto("  ", "Transporte", 30), "concepto vacío"),
):
    try:
        mal()
        comprobar(False, f"Un gasto con {motivo} se rechaza")
    except ValueError:
        comprobar(True, f"Un gasto con {motivo} se rechaza")

inv = inventario_secreto()
recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Secreto a la brasa", "Principal", {"Secreto": 0.2}))
silencio(recetario.agregar_menu, Menu("Menú brasa", [recetario.recetas["Secreto a la brasa"]]))
registro = RegistroServicios()
con_precio = Servicio(HOY, time(21, 0), 4, "Menú brasa", precio_cobrado=100)
sin_precio = Servicio(HOY, time(14, 0), 2, "Menú brasa")
silencio(registro.agregar_servicio, con_precio)
silencio(registro.agregar_servicio, sin_precio)
gastos = RegistroGastos()
silencio(gastos.agregar_gasto, Gasto("Gasolina", "Transporte", 20, servicio_id=con_precio.id))
silencio(gastos.agregar_gasto, Gasto("Seguro furgoneta", "Seguros e impuestos", 60))

r = resumen_servicio(con_precio, inv, recetario, gastos)
comprobar(r["estimado"] and abs(r["comida"] - 0.8 * inv.buscar_producto("Secreto").precio_unitario) < 0.02
          and r["gastos"] == 20,
          "Servicio pendiente: coste estimado de la comida + sus gastos (no los generales)")
comprobar(r["margen"] == round(100 - r["coste_total"], 2), "Margen = cobro - coste")
r2 = resumen_servicio(sin_precio, inv, recetario, gastos)
comprobar(r2["cobrado"] is None and r2["margen"] is None, "Sin precio de cobro no hay margen (y no falla nada)")

silencio(recetario.completar_servicio, con_precio, inv, {"Secreto": [2]})
r = resumen_servicio(con_precio, inv, recetario, gastos)
comprobar(not r["estimado"] and abs(r["comida"] - (0.8 * 15)) < 1e-9,
          "Servicio completado: coste REAL de lo que salió (0,8 kg del lote a 15 €/kg = 12 €)")
comprobar(all(m.servicio_id == con_precio.id for m in inv.historial if m.motivo == "consumo"),
          "Las salidas de un servicio quedan apuntadas con su número")

with tempfile.TemporaryDirectory() as carpeta:
    ruta = str(Path(carpeta) / "sesion.json")
    silencio(guardar_sesion, inv, registro, recetario, GestorCompras(), ArchivoInformes(), ruta, gastos)
    sesion = silencio(cargar_sesion, ruta)
    comprobar(len(sesion.registro_gastos.gastos) == 2 and sesion.registro_servicios.servicios[0].precio_cobrado == 100
              and sesion.registro_servicios.servicios[1].precio_cobrado is None,
              "Los gastos y los precios de cobro se guardan y se cargan")
    comprobar(resumen_servicio(sesion.registro_servicios.servicios[0], sesion.inventario, sesion.recetario,
                               sesion.registro_gastos)["comida"] == r["comida"],
              "Tras guardar y cargar, el coste real del servicio sigue igual")
    import json
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    del datos["gastos"]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    comprobar(silencio(cargar_sesion, ruta).registro_gastos.gastos == [],
              "Una sesión de antes de los gastos se carga sin gastos")
    ruta_excel = silencio(exportar_todo, inv, registro, GestorCompras(), carpeta, gastos, recetario)
    libro = load_workbook(ruta_excel)
    comprobar("Gastos" in libro.sheetnames and "Rentabilidad" in libro.sheetnames,
              "El Excel tiene las hojas 'Gastos' y 'Rentabilidad'")

print("\n--- Compra no prevista de un producto para un servicio ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 0, "kg", 2, "Huerta"))
servicio = Servicio(HOY, time(14, 0), 10, "Menú")
servicio.id = 99
try:
    inv.compra_para_servicio("Tomate", 5, 6, 10, servicio.id)
    comprobar(False, "No se puede usar más de lo que se compró")
except ValueError:
    comprobar(inv.buscar_producto("Tomate").stock == 0, "No se puede usar más de lo que se compró (y no toca nada)")
lote = silencio(inv.compra_para_servicio, "Tomate", 5, 3, 12.5, servicio.id, "Mercado central",
                HOY + timedelta(days=4))
tomate = inv.buscar_producto("Tomate")
comprobar(tomate.stock == 2 and lote.precio_unitario == 2.5 and lote.proveedor == "Mercado central"
          and lote.fecha_caducidad == HOY + timedelta(days=4),
          "Entra como lote (a 12,5 € / 5 kg = 2,5 €/kg) y sobran 2 kg en el inventario")
servicio.estado = "completado"
r = resumen_servicio(servicio, inv, Recetario(), RegistroGastos())
comprobar(r["comida"] == 7.5, "El servicio carga solo lo usado (3 kg x 2,5 € = 7,5 €)")
comprobar(Metricas(inv).gasto_por_categoria(HOY, HOY) == {"Verduras": 12.5},
          "En Métricas cuenta como compra (12,5 €), una sola vez")

print("\n--- Lista de la compra al día ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Arroz", "Despensa", 1, "kg", 1.5, "Mayorista"))
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 0, "litros", 4, "Mayorista"))
recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Paella", "Principal", {"Arroz": 0.1, "Aceite": 0.01}))
silencio(recetario.agregar_menu, Menu("Menú paella", [recetario.recetas["Paella"]]))
paella = Servicio(HOY + timedelta(days=2), time(14, 0), 50, "Menú paella")  # 5 kg de arroz, 0,5 l de aceite
gestor = GestorCompras()
silencio(gestor.generar_lista_desde_servicios, [paella], recetario, inv)
comprobar(gestor.pendiente_de("Arroz").cantidad == 4 and gestor.pendiente_de("Aceite") is not None,
          "La lista pide arroz (faltan 4 kg) y aceite")
silencio(inv.entrada_stock, "Arroz", 5, precio_unitario=1.4)  # comprado desde el inventario, sin pasar por la lista
avisos = silencio(gestor.generar_lista_desde_servicios, [paella], recetario, inv)
comprobar(gestor.pendiente_de("Arroz") is None and gestor.pendiente_de("Aceite") is not None,
          "Al regenerar la lista, se quita lo que ya no hace falta (el arroz) y se mantiene lo demás")
comprobar(any("Arroz" in a and "ya no hace falta" in a for a in avisos), "...y se avisa de ello")

print("\n--- Material reutilizable ---")
from materiales import Material, RegistroMaterial, lista_de_carga  # noqa: E402

try:
    Material("Plato", "Vajilla", 2.5)
    comprobar(False, "El material se cuenta en unidades enteras")
except ValueError:
    comprobar(True, "El material se cuenta en unidades enteras")

reg = RegistroMaterial()
silencio(reg.agregar_material, Material("Plato llano", "Vajilla", 50, 3.5))
silencio(reg.agregar_material, Material("Copa", "Cristalería", 30, 2.0))
comprobar(lista_de_carga({"Plato llano": 2, "Copa": 0.5}, 15) == {"Plato llano": 30, "Copa": 8},
          "La lista de carga se calcula por comensal y redondea hacia arriba (7,5 copas -> 8)")
silencio(reg.registrar_salida, 1, {"Plato llano": 30, "Copa": 8})
comprobar(reg.en_uso("Plato llano") == 30 and reg.disponibles("Plato llano") == 20
          and reg.buscar("Plato llano").cantidad_total == 50,
          "El material fuera sigue existiendo (50) pero no está disponible (20)")
try:
    reg.registrar_salida(2, {"Plato llano": 25})
    comprobar(False, "No se puede sacar más material del disponible")
except ValueError:
    comprobar(reg.en_uso("Plato llano") == 30, "No se puede sacar más material del disponible")
try:
    reg.editar_material("Plato llano", cantidad_total=10)
    comprobar(False, "El total no puede bajar de lo que está en uso")
except ValueError:
    comprobar(True, "El total no puede bajar de lo que está en uso")

incidencias = silencio(reg.registrar_vuelta, 1, {"Plato llano": 27, "Copa": 8}, {"Plato llano": 2})
comprobar(reg.en_uso("Plato llano") == 0 and reg.buscar("Plato llano").cantidad_total == 47,
          "Al volver: deja de estar en uso y lo que falta (3) deja de contar en el total")
comprobar(sorted((i.tipo, i.cantidad) for i in incidencias) == [("pérdida", 1), ("rotura", 2)],
          "De lo que falta: 2 roturas y 1 pérdida")
comprobar(reg.coste_incidencias_servicio(1) == 10.5, "Coste de roturas y pérdidas del servicio: 3 x 3,5 € = 10,5 €")

silencio(reg.reponer, "Plato llano", 3)
silencio(reg.dar_de_baja, "Copa", 1, "rotura")
comprobar(reg.buscar("Plato llano").cantidad_total == 50 and reg.buscar("Copa").cantidad_total == 29
          and reg.incidencias[-1].servicio_id is None,
          "Reponer suma unidades; una rotura en el almacén resta y no es de ningún servicio")

inv = inventario_secreto()
recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Secreto a la brasa", "Principal", {"Secreto": 0.2}))
silencio(recetario.agregar_menu, Menu("Menú brasa", [recetario.recetas["Secreto a la brasa"]], {}, {"Plato llano": 2}))
servicio = Servicio(HOY, time(21, 0), 4, "Menú brasa", precio_cobrado=100)
servicio.id = 1
r = resumen_servicio(servicio, inv, recetario, RegistroGastos(), reg)
comprobar(r["material"] == 10.5 and r["coste_total"] == round(r["comida"] + 10.5, 2),
          "El coste del servicio incluye el material roto o perdido")

silencio(reg.editar_material, "Plato llano", nuevo_nombre="Plato blanco")
recetario.renombrar_material("Plato llano", "Plato blanco")
comprobar("Plato blanco" in reg.materiales and reg.salidas[0].cantidades.get("Plato blanco") == 30
          and reg.incidencias[0].material == "Plato blanco"
          and recetario.menus["Menú brasa"].materiales_por_comensal == {"Plato blanco": 2},
          "Renombrar un material lo actualiza en salidas, roturas y menús")

with tempfile.TemporaryDirectory() as carpeta:
    ruta = str(Path(carpeta) / "sesion.json")
    silencio(guardar_sesion, inv, RegistroServicios(), recetario, GestorCompras(), ArchivoInformes(), ruta,
             RegistroGastos(), reg)
    sesion = silencio(cargar_sesion, ruta)
    comprobar(sesion.registro_material.buscar("Plato blanco").cantidad_total == 50
              and len(sesion.registro_material.incidencias) == 3
              and sesion.recetario.menus["Menú brasa"].materiales_por_comensal == {"Plato blanco": 2},
              "El material, sus roturas y el material de los menús se guardan y se cargan")
    ruta_excel = silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta, RegistroGastos(),
                          recetario, reg)
    comprobar("Material" in load_workbook(ruta_excel).sheetnames, "El Excel tiene la hoja 'Material'")

print("\n--- Historial de servicios ---")
import historial  # noqa: E402

inv = inventario_secreto()
recetario = Recetario()
silencio(recetario.agregar_receta, Receta("Secreto a la brasa", "Principal", {"Secreto": 0.2}))
silencio(recetario.agregar_menu, Menu("Menú brasa", [recetario.recetas["Secreto a la brasa"]]))
registro = RegistroServicios()
garcia = Servicio(HOY, time(21, 0), 4, "Menú brasa", precio_cobrado=100, cliente="Familia García", lugar="Finca Los Olivos")
lopez = Servicio(HOY, time(14, 0), 15, "Menú brasa", cliente="López")  # pide 3 kg y solo hay 1,8
cancelado = Servicio(HOY, time(13, 0), 2, "Menú brasa", cliente="Ruiz")
for s_ in (garcia, lopez, cancelado):
    silencio(registro.agregar_servicio, s_)
cancelado.cancelar()
silencio(recetario.completar_servicio, garcia, inv, {"Secreto": [1]})
garcia.valoracion = "Sobró pan; llevar más hielo"
silencio(recetario.completar_servicio, lopez, inv)

comprobar(garcia.fecha_completado == HOY and garcia.menu_completado["recetas"][0]["nombre"] == "Secreto a la brasa",
          "Al completar se guardan la fecha y una copia del menú")
recetario.recetas["Secreto a la brasa"].ingredientes_por_comensal["Secreto"] = 0.5
comprobar(historial.previsto(garcia) == {"Secreto": 0.8},
          "Si después se cambia la receta, el historial sigue mostrando lo que se hizo (0,2 x 4 = 0,8 kg)")
filas = historial.previsto_frente_a_real(lopez, inv)
comprobar(filas[0]["previsto"] == 3 and abs(filas[0]["real"] - 1.0) < 1e-9 and abs(filas[0]["diferencia"] + 2) < 1e-9,
          "Previsto frente a real: el menú pedía 3 kg y solo salió 1 kg (lo que quedaba)")
comprobar([s_.id for s_ in historial.filtrar_servicios(registro, date(2000, 1, 1), date.max)] == [garcia.id, lopez.id],
          "El historial solo lista los completados, los más recientes primero")
comprobar(len(historial.filtrar_servicios(registro, date(2000, 1, 1), date.max, incluir_cancelados=True)) == 3,
          "Opcionalmente, también los cancelados")
comprobar([s_.id for s_ in historial.filtrar_servicios(registro, date(2000, 1, 1), date.max, cliente="Familia García")] == [garcia.id],
          "Filtrar por cliente")
comprobar([s_.id for s_ in historial.filtrar_servicios(registro, date(2000, 1, 1), date.max, texto="hielo")] == [garcia.id],
          "Buscar texto (también en la valoración)")
comprobar(historial.clientes(registro) == ["Familia García", "López", "Ruiz"], "Lista de clientes")
r = historial.resumen_periodo(historial.filtrar_servicios(registro, date(2000, 1, 1), date.max), inv, recetario,
                              RegistroGastos(), RegistroMaterial())
comprobar(r["servicios"] == 2 and r["comensales"] == 19 and r["facturado"] == 100 and r["servicios_sin_cobro"] == 1
          and r["menu_mas_repetido"] == "Menú brasa",
          "Resumen del periodo: 2 servicios, 19 comensales, 100 € facturados (1 sin precio)")
f = historial.ficha(garcia, inv, recetario, RegistroGastos(), RegistroMaterial())
comprobar(len(f["consumos"]) == 1 and f["consumos"][0]["lote"].startswith("Lote 1") and f["coste_por_comensal"] > 0,
          "La ficha recoge lo que salió de cada lote y el coste por comensal")
nuevo = silencio(historial.repetir_servicio, registro, garcia, HOY + timedelta(days=30), time(20, 0))
comprobar(nuevo.estado == "pendiente" and nuevo.menu == "Menú brasa" and nuevo.cliente == "Familia García"
          and nuevo.precio_cobrado == 100 and nuevo.comensales == 4 and nuevo.id != garcia.id,
          "Repetir un servicio crea uno nuevo igual en otra fecha")
copia = RegistroServicios.from_dict(registro.to_dict())
g2 = copia.buscar_por_id(garcia.id)
comprobar(g2.cliente == "Familia García" and g2.lugar == "Finca Los Olivos" and g2.valoracion == garcia.valoracion
          and g2.fecha_completado == HOY and g2.menu_completado == garcia.menu_completado,
          "Cliente, lugar, valoración y copia del menú se guardan y se cargan")
with tempfile.TemporaryDirectory() as carpeta:
    ruta_excel = silencio(exportar_todo, inv, registro, GestorCompras(), carpeta, RegistroGastos(), recetario, RegistroMaterial())
    hoja = load_workbook(ruta_excel)["Historial"]
    comprobar(hoja.max_row == 3 and hoja["D2"].value in ("Familia García", "López"),
              "El Excel tiene la hoja 'Historial' con una fila por servicio completado")

print("\n--- Elaboraciones (recetas preparadas por adelantado) ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta", fecha_caducidad=HOY + timedelta(days=5)))
silencio(inv.entrada_stock, "Tomate", 3, precio_unitario=3, fecha_caducidad=HOY + timedelta(days=9))
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 5, "litros", 4, "Mayorista"))
recetario = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1, "Aceite": 0.01}, vida_util_dias=3)
silencio(recetario.agregar_receta, ensalada)
silencio(recetario.agregar_menu, Menu("Menú ensalada", [ensalada]))
comprobar(ensalada.caducidad_propuesta(HOY) == HOY + timedelta(days=3), "La vida útil propone la caducidad (hoy + 3 días)")
comprobar(Recetario.from_dict(recetario.to_dict()).recetas["Ensalada"].vida_util_dias == 3, "La vida útil se guarda y se carga")

try:
    recetario.preparar_elaboracion("Ensalada", 100, inv)  # 10 kg de tomate: solo hay 5
    comprobar(False, "Sin ingredientes suficientes no se prepara")
except ValueError as e:
    comprobar("Tomate" in str(e) and inv.buscar_producto("Tomate").stock == 5 and not inv.elaboraciones.tandas,
              "Sin ingredientes suficientes no se prepara (y no toca nada)")
tanda = silencio(recetario.preparar_elaboracion, "Ensalada", 20, inv, {"Tomate": [2]}, ensalada.caducidad_propuesta(HOY))
tomate = inv.buscar_producto("Tomate")
comprobar(abs(tomate.buscar_lote(2).cantidad - 1) < 1e-9 and tomate.buscar_lote(1).cantidad == 2,
          "Preparar gasta los ingredientes del lote elegido (2 kg del lote 2)")
comprobar(inv.historial[-1].motivo == "elaboración", "Queda en el historial con el motivo 'elaboración'")
comprobar(abs(tanda.coste_por_racion - (2 * 3 + 0.2 * 4) / 20) < 1e-9 and tanda.raciones == 20
          and tanda.fecha_caducidad == HOY + timedelta(days=3),
          "La tanda tiene 20 raciones, su caducidad y su coste real por ración (0,34 €)")

servicio = Servicio(HOY + timedelta(days=1), time(14, 0), 30, "Menú ensalada")
servicio.id = 501
plan = recetario.plan_elaboraciones(servicio, inv)
comprobar(plan["Ensalada"]["raciones"] == 20 and plan["Ensalada"]["restantes"] == 10,
          "Por defecto se usan las raciones preparadas (20) y el resto (10) se hace con ingredientes")
filas = recetario.previsualizar_consumo(servicio, inv, {"Tomate": [1]})
comprobar(next(f for f in filas if f["ingrediente"] == "Tomate")["necesario"] == 1,
          "Solo se descuentan los ingredientes de las 10 raciones restantes (1 kg de tomate)")
sin_usar = recetario.previsualizar_consumo(servicio, inv, {"Tomate": [1]}, {"Ensalada": []})
comprobar(next(f for f in sin_usar if f["ingrediente"] == "Tomate")["necesario"] == 3,
          "Se puede elegir no usar las raciones preparadas (todo con ingredientes: 3 kg)")

gestor = GestorCompras()
avisos = silencio(gestor.generar_lista_desde_servicios,
                  [Servicio(HOY + timedelta(days=1), time(14, 0), 80, "Menú ensalada")], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 3 and any("raciones preparadas" in a for a in avisos),
          "La lista de la compra descuenta lo ya preparado (80 - 20 = 60 raciones: 6 kg, hay 3 -> faltan 3)")
avisos = silencio(gestor.generar_lista_desde_servicios,
                  [Servicio(HOY + timedelta(days=10), time(14, 0), 80, "Menú ensalada")], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 8,
          "...pero no cuenta una tanda que habrá caducado el día del servicio (ni el tomate caducado: 8 kg)")

silencio(recetario.completar_servicio, servicio, inv, {"Tomate": [1]})
comprobar(not inv.elaboraciones.tandas and inv.elaboraciones.coste_servicio(501) == round(20 * tanda.coste_por_racion, 2),
          "Al completar, la tanda se gasta y su coste queda apuntado en el servicio")
r = resumen_servicio(servicio, inv, recetario, RegistroGastos())
comprobar(abs(r["comida"] - (20 * tanda.coste_por_racion + 1 * 2 + 0.1 * 4)) < 0.02,
          "El coste del servicio = raciones preparadas + ingredientes del resto")
f = historial.ficha(servicio, inv, recetario, RegistroGastos(), RegistroMaterial())
comprobar(any(c["producto"] == "Ensalada (preparada)" and c["cantidad"] == 20 for c in f["consumos"])
          and any(p["producto"] == "Tomate" and p["previsto"] == 1 and abs(p["diferencia"]) < 1e-9
                  for p in f["previsto_frente_a_real"]),
          "El historial muestra las raciones preparadas usadas y el previsto ya las descuenta")

vieja = silencio(recetario.preparar_elaboracion, "Ensalada", 5, inv, None, HOY - timedelta(days=1), HOY - timedelta(days=3))  # preparada hace 3 días
comprobar(inv.elaboraciones.caducadas() == [vieja], "Se detectan las tandas caducadas")
silencio(inv.elaboraciones.desechar, vieja.id)
comprobar(not inv.elaboraciones.tandas and Metricas(inv).valor_desperdiciado_total(HOY, HOY) == round(5 * vieja.coste_por_racion, 2),
          "Desechar una tanda cuenta como desperdicio, con su coste")
comprobar(Metricas(inv).cantidad_consumida("Tomate", HOY, HOY) > 0, "Lo gastado al preparar cuenta como consumo en Métricas")
silencio(recetario.preparar_elaboracion, "Ensalada", 4, inv, None, HOY + timedelta(days=2))
copia = Inventario.from_dict(inv.to_dict())
comprobar(len(copia.elaboraciones.tandas) == 1 and copia.elaboraciones.tandas[0].raciones == 4
          and len(copia.elaboraciones.usos) == len(inv.elaboraciones.usos),
          "Las tandas y sus usos se guardan y se cargan")

print("\n--- Elaboraciones base (sofritos, fondos, salsas...) ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 4, "kg", 1.5, "Huerta", fecha_caducidad=HOY + timedelta(days=10)))
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 5, "litros", 4, "Mayorista"))
silencio(inv.agregar_producto, Producto("Huesos", "Carnes", 3, "kg", 2, "Carnicería", fecha_caducidad=HOY + timedelta(days=4)))
silencio(inv.agregar_producto, Producto("Servilletas", "Mesa", 100, "unidades", 0.05, "Mayorista", tipo="consumible"))
sofrito = silencio(inv.definir_base, "Sofrito", "Elaboraciones", "kg", 1, {"Cebolla": 1.5, "Aceite": 0.1}, vida_util_dias=4)
comprobar(sofrito.es_base() and sofrito.stock == 0 and sofrito.tipo_descripcion() == "Elaboración base"
          and sofrito in inv.alimentos(), "Una elaboración base es un alimento más, con su fórmula y stock 0")
comprobar(sofrito.ingredientes_para(2) == {"Cebolla": 3, "Aceite": 0.2}, "La fórmula se escala a la cantidad que se prepara")
for malos, motivo in (
    ({"Patata": 1}, "un ingrediente que no existe"),
    ({"Servilletas": 1}, "un consumible"),
    ({"Sofrito": 1}, "a sí misma"),
):
    try:
        silencio(inv.editar_formula, "Sofrito", 1, malos)
        comprobar(False, f"La fórmula no admite {motivo}")
    except ValueError:
        comprobar(inv.buscar_producto("Sofrito").formula["ingredientes"] == {"Cebolla": 1.5, "Aceite": 0.1},
                  f"La fórmula no admite {motivo} (y no cambia nada)")
salsa = silencio(inv.definir_base, "Salsa", "Elaboraciones", "litros", 2, {"Sofrito": 0.5, "Huesos": 1})
try:
    silencio(inv.editar_formula, "Sofrito", 1, {"Cebolla": 1.5, "Salsa": 0.2})
    comprobar(False, "Las fórmulas no pueden ir en círculo")
except ValueError:
    comprobar(True, "Las fórmulas no pueden ir en círculo (Sofrito lleva Salsa, que lleva Sofrito)")

try:
    recetario = Recetario()
    recetario.preparar_base("Sofrito", 10, 9, inv)  # 15 kg de cebolla: solo hay 4
    comprobar(False, "Sin ingredientes suficientes no se prepara la base")
except ValueError as e:
    comprobar("Cebolla" in str(e) and sofrito.stock == 0, "Sin ingredientes suficientes no se prepara la base")
prep = silencio(recetario.preparar_base, "Sofrito", 2, 1.6, inv, {"Cebolla": [1], "Aceite": [1]})
comprobar(inv.buscar_producto("Cebolla").stock == 1 and abs(inv.buscar_producto("Aceite").stock - 4.8) < 1e-9,
          "Preparar 2 kg gasta lo que pide la fórmula (3 kg de cebolla, 0,2 l de aceite)")
comprobar(sofrito.stock == 1.6 and prep.prevista == 2 and prep.obtenida == 1.6 and prep.diferencia == -0.4,
          "Entra lo que salió DE VERDAD (1,6 kg) y queda apuntado: previsto 2, obtenido 1,6, diferencia -0,4")
lote = sofrito.lotes[0]
comprobar(lote.procedencia == "elaboración" and lote.fecha_caducidad == HOY + timedelta(days=4)
          and abs(lote.precio_unitario - (3 * 1.5 + 0.2 * 4) / 1.6) < 1e-3 and prep.coste == 5.3,
          "El lote del sofrito tiene su caducidad (vida útil 4 días) y su coste real (5,30 € / 1,6 kg)")
comprobar(Metricas(inv).gasto_por_categoria(HOY, HOY).get("Elaboraciones", 0) == 0,
          "Preparar una base no cuenta como compra (no es dinero gastado)")
silencio(inv.editar_producto, "Cebolla", "Cebolla blanca")
comprobar(sofrito.formula["ingredientes"] == {"Cebolla blanca": 1.5, "Aceite": 0.1},
          "Al renombrar un ingrediente, la fórmula de la base se actualiza")
copia = Inventario.from_dict(inv.to_dict())
comprobar(copia.buscar_producto("Sofrito").es_base() and copia.buscar_producto("Sofrito").vida_util_dias == 4
          and len(copia.elaboraciones.preparaciones_base) == 1
          and copia.elaboraciones.preparaciones_base[0].obtenida == 1.6,
          "Las bases, sus fórmulas y sus preparaciones se guardan y se cargan")

# Lista de la compra: un plato con salsa (que lleva sofrito, que lleva cebolla)
rec = Recetario()
guiso = Receta("Guiso", "Principales", {"Salsa": 0.1})
silencio(rec.agregar_receta, guiso)
silencio(rec.agregar_menu, Menu("Menú guiso", [guiso]))
serv = Servicio(HOY + timedelta(days=2), time(14, 0), 40, "Menú guiso")
compras = GestorCompras()
avisos = silencio(compras.generar_lista_desde_servicios, [serv], rec, inv)
pedidos = {i.ingrediente: i.cantidad for i in compras.items_pendientes()}
# 4 l de salsa -> 1 kg de sofrito (hay 1,6: no falta) + 2 kg de huesos (hay 3: no falta)
comprobar(pedidos == {} and any("Salsa" in a for a in avisos),
          "Si falta una base, la lista pide sus ingredientes (aquí hay de todo: no se compra nada)")
serv.comensales = 200  # 20 l de salsa -> 5 kg de sofrito (faltan 3,4) y 10 kg de huesos
silencio(compras.generar_lista_desde_servicios, [serv], rec, inv)
pedidos = {i.ingrediente: i.cantidad for i in compras.items_pendientes()}
nombre_cebolla = "Cebolla blanca"
comprobar("Salsa" not in pedidos and "Sofrito" not in pedidos and pedidos.get("Huesos") == 7
          and abs(pedidos.get(nombre_cebolla, 0) - (3.4 * 1.5 - 1)) < 1e-6,
          "Bases dentro de bases: no se compran salsa ni sofrito, sino huesos (7 kg) y la cebolla que falta (4,1 kg)")

with tempfile.TemporaryDirectory() as carpeta:
    from openpyxl import load_workbook
    hoja = load_workbook(silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta))["Elaboraciones base"]
    valores = [c.value for fila in hoja.iter_rows() for c in fila]
    comprobar("Sofrito" in valores and "Salsa" in valores and 1.6 in valores and "Obtenida" in valores,
              "El Excel tiene la hoja 'Elaboraciones base' con fórmulas y preparaciones")

print("\n--- Anotaciones (bloc de notas) ---")
from recetario import Menu as _Menu  # noqa: E402
r = Receta("Croquetas", "Entrantes", {"Aceite": 0.01})
comprobar(r.notas == "" and r.notas_fecha is None, "Una receta nueva no tiene notas")
r.poner_nota("  Bechamel del día anterior.\nFreír a 180 grados.  ")
comprobar(r.notas == "Bechamel del día anterior.\nFreír a 180 grados." and r.notas_fecha == HOY,
          "Se guarda la nota (con sus saltos de línea) y la fecha en que se editó")
r.poner_nota("Bechamel del día anterior.\nFreír a 180 grados.", fecha=HOY + timedelta(days=3))
comprobar(r.notas_fecha == HOY, "Guardar la misma nota sin cambios no cambia la fecha")
m = _Menu("Menú croquetas", [r])
m.poner_nota("Para eventos de pie.")
sofrito = inv.buscar_producto("Sofrito")
sofrito.poner_nota("Pochar sin dorar.")
rec = Recetario()
silencio(rec.agregar_receta, r)
silencio(rec.agregar_menu, m)
copia_rec = Recetario.from_dict(rec.to_dict())
copia_inv = Inventario.from_dict(inv.to_dict())
comprobar(copia_rec.recetas["Croquetas"].notas == r.notas and copia_rec.recetas["Croquetas"].notas_fecha == HOY
          and copia_rec.menus["Menú croquetas"].notas == "Para eventos de pie."
          and copia_inv.buscar_producto("Sofrito").notas == "Pochar sin dorar.",
          "Las notas de recetas, menús y bases se guardan y se cargan")
foto = m.foto()
comprobar(foto["notas"] == "Para eventos de pie." and foto["recetas"][0]["notas"] == r.notas,
          "La copia del menú de un servicio completado guarda también sus notas")
datos_viejos = r.to_dict()
del datos_viejos["notas"], datos_viejos["notas_fecha"]
comprobar(Receta.from_dict(datos_viejos).notas == "", "Las sesiones de antes de las notas se cargan sin notas")
r.poner_nota("")
comprobar(r.notas == "" and r.notas_fecha is None, "Una nota vacía la borra")
r.poner_nota("Bechamel del día anterior.")
with tempfile.TemporaryDirectory() as carpeta:
    from openpyxl import load_workbook
    libro = load_workbook(silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta, None, rec))
    valores = [c.value for fila in libro["Recetario"].iter_rows() for c in fila]
    bases = [c.value for fila in libro["Elaboraciones base"].iter_rows() for c in fila]
    comprobar("Croquetas" in valores and "Bechamel del día anterior." in valores and "Para eventos de pie." in valores
              and "Pochar sin dorar." in bases,
              "El Excel tiene la hoja 'Recetario' con recetas, menús y notas, y las notas de las bases")

print("\n--- Limpieza y mantenimiento ---")
from gastos import RegistroGastos as _RG, resumen_servicio as _resumen  # noqa: E402
inv = Inventario()
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 5, "kg", 1, "Huerta"))
silencio(inv.agregar_producto, Producto("Lejía", "Limpieza", 4, "litros", 1.5, "Droguería", stock_minimo=2,
                                        tipo="mantenimiento", fecha_caducidad=HOY + timedelta(days=90)))
silencio(inv.agregar_producto, Producto("Bayetas", "Limpieza", 6, "unidades", 0.5, "Droguería", stock_minimo=10,
                                        tipo="mantenimiento"))
lejia = inv.buscar_producto("Lejía")
comprobar(inv.mantenimiento() == [lejia, inv.buscar_producto("Bayetas")] and lejia not in inv.alimentos()
          and lejia not in inv.consumibles() and lejia.fecha_caducidad == HOY + timedelta(days=90),
          "Los productos de limpieza y mantenimiento van en su propia lista y pueden tener caducidad")
try:
    Producto("Estropajo", "Limpieza", 1, "kg", 1, "Droguería", tipo="mantenimiento", tiene_merma=True)
    comprobar(False, "No pueden tener merma")
except ValueError:
    comprobar(True, "No pueden tener merma")
try:
    silencio(inv.definir_base, "Caldo raro", "Elaboraciones", "litros", 1, {"Lejía": 0.1})
    comprobar(False, "No pueden ser ingrediente")
except ValueError:
    comprobar("Caldo raro" not in inv.productos, "No pueden ser ingrediente de una elaboración base")

servicio = Servicio(HOY, time(20, 0), 10, "Menú inexistente")
servicio.id = 777
silencio(inv.salida_stock, "Lejía", 1, "consumo", 1, servicio_id=777)
silencio(inv.salida_stock, "Lejía", 0.5, "consumo", 1)
servicio.estado = "completado"
r = _resumen(servicio, inv, Recetario(), _RG())
comprobar(r["mantenimiento"] == 1.5 and r["comida"] == 0 and r["coste_total"] == 1.5,
          "Lo que sale para un servicio cuenta en su rentabilidad (1 l de lejía = 1,50 €); lo general no")
silencio(inv.entrada_stock, "Lejía", 2, precio_unitario=1.5, proveedor="Droguería")
silencio(inv.salida_stock, "Lejía", 2, "consumo", 2)  # se gasta lo comprado (para no cambiar el resto)
comprobar(Metricas(inv).gasto_por_tipo(HOY, HOY) == {"alimento": 0, "consumible": 0, "mantenimiento": 3.0},
          "Métricas separa el gasto en limpieza y mantenimiento (compra de 2 l de lejía = 3 €)")
compras = GestorCompras()
avisos = silencio(compras.generar_lista_desde_servicios, [], Recetario(), inv)
pedidos = {i.ingrediente: i.cantidad for i in compras.items_pendientes()}
comprobar(pedidos == {"Bayetas": 4} and any("Bayetas" in a and "mínimo" in a for a in avisos),
          "La lista de la compra repone hasta el mínimo lo que está por debajo (4 bayetas), aunque no haya servicios")
silencio(inv.salida_stock, "Lejía", 1, "consumo", 1)  # quedan 1,5 l de lejía (mínimo 2)
silencio(compras.generar_lista_desde_servicios, [], Recetario(), inv)
pedidos = {i.ingrediente: i.cantidad for i in compras.items_pendientes()}
comprobar(pedidos.get("Lejía") == 0.5 and pedidos.get("Bayetas") == 4,
          "Al volver a generarla no se borran: se mantienen y se añaden los nuevos (0,5 l de lejía)")
silencio(inv.editar_producto, "Bayetas", tipo="consumible")
comprobar(inv.buscar_producto("Bayetas").es_consumible() and inv.buscar_producto("Bayetas") in inv.consumibles(),
          "Se puede corregir el tipo si se dio de alta en la lista equivocada")
silencio(inv.editar_producto, "Bayetas", tipo="mantenimiento")
copia = Inventario.from_dict(inv.to_dict())
comprobar(copia.buscar_producto("Lejía").es_mantenimiento(), "Se guardan y se cargan")
with tempfile.TemporaryDirectory() as carpeta:
    from openpyxl import load_workbook
    hoja = load_workbook(silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta))["Inventario"]
    comprobar("Limpieza y mantenimiento" in [c.value for fila in hoja.iter_rows() for c in fila],
              "En el Excel aparecen con su clase")

print("\n--- Historial de precios ---")
from inventario import PrecioCompra  # noqa: E402
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 5, "kg", 1.6, "Huerta"))
silencio(inv.entrada_stock, "Tomate", 4, precio_unitario=1.8, proveedor="Frutas Paco")
silencio(inv.entrada_stock, "Tomate", 3, precio_unitario=1.7, proveedor="Huerta")
precios = inv.precios_de("Tomate")
comprobar([(p.proveedor, p.precio_unitario, p.origen) for p in precios]
          == [("Huerta", 1.6, "inicial"), ("Frutas Paco", 1.8, "compra"), ("Huerta", 1.7, "compra")],
          "Cada compra (y el stock inicial) queda en el historial de precios, con su proveedor")
resumen = inv.resumen_precios_por_proveedor("Tomate")
comprobar(resumen[0]["proveedor"] == "Huerta" and abs(resumen[0]["medio"] - (5 * 1.6 + 3 * 1.7) / 8) < 1e-6
          and resumen[0]["compras"] == 2 and resumen[1]["proveedor"] == "Frutas Paco",
          "El resumen por proveedor da el precio medio ponderado, del más barato al más caro")
silencio(inv.salida_stock, "Tomate", 5, "consumo", 1)
comprobar(len(inv.precios_de("Tomate")) == 3, "Aunque el lote se gaste entero, su precio sigue en el historial")
comprobar(inv.avisos_precios() == [], "Sin cambios grandes de precio no hay avisos")
silencio(inv.entrada_stock, "Tomate", 2, precio_unitario=2.3, proveedor="Frutas Paco")
avisos = inv.avisos_precios()
comprobar(len(avisos) == 1 and avisos[0]["producto"] == "Tomate" and avisos[0]["variacion"] > 0.3,
          "Una compra mucho más cara de lo habitual da un aviso")
silencio(inv.entrada_stock, "Tomate", 2, precio_unitario=1.2, proveedor="Huerta")
avisos = inv.avisos_precios()
comprobar(len(avisos) == 1 and avisos[0]["variacion"] < -0.2 and avisos[0]["precio"] == 1.2,
          "...y una mucho más barata, también (solo cuenta la última compra de cada producto)")
comprobar(inv.avisos_precios(hoy=HOY + timedelta(days=40)) == [], "Las compras de hace más de 30 días ya no avisan")
silencio(inv.agregar_producto, Producto("Carne limpia", "Carnes", 0, "kg", 0, "Propio"))
limpio_antes = len(inv.historial_precios)
silencio(inv.entrada_stock, "Carne limpia", 1, precio_unitario=9, motivo="limpieza")
comprobar(len(inv.historial_precios) == limpio_antes, "Lo que sale de una limpieza o elaboración no es una compra: no entra")
silencio(inv.editar_producto, "Tomate", "Tomate pera")
copia = Inventario.from_dict(inv.to_dict())
comprobar(len(copia.precios_de("Tomate pera")) == 5 and not copia.precios_de("Tomate"),
          "Se renombra con el producto y se guarda y se carga")
viejo = inv.to_dict()
del viejo["historial_precios"]
reconstruido = Inventario.from_dict(viejo)
comprobar([(p.proveedor, p.precio_unitario) for p in reconstruido.precios_de("Tomate pera")]
          == [("Frutas Paco", 1.8), ("Huerta", 1.7), ("Frutas Paco", 2.3), ("Huerta", 1.2)],
          "En sesiones antiguas se reconstruye con las compras del historial de movimientos")
with tempfile.TemporaryDirectory() as carpeta:
    from openpyxl import load_workbook
    hoja = load_workbook(silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta))["Historial de precios"]
    comprobar(hoja.max_row == 6 and hoja["C2"].value in ("Huerta", "Frutas Paco"),
              "El Excel tiene la hoja 'Historial de precios' (una fila por compra)")

print("\n--- Corregir un precio hacia atrás ---")
from gastos import RegistroGastos as _RG2, resumen_servicio as _res2  # noqa: E402
inv = Inventario()
silencio(inv.agregar_producto, Producto("Lomo", "Carnes", 0, "kg", 0, "Carnicería"))
lote = silencio(inv.entrada_stock, "Lomo", 5, precio_unitario=14, proveedor="Carnicería")  # error: eran 4 €/kg
silencio(inv.salida_stock, "Lomo", 2, "consumo", lote.id, servicio_id=900)
silencio(inv.salida_stock, "Lomo", 0.5, "desperdicio", lote.id)
silencio(inv.salida_stock, "Lomo", 1, "elaboración", lote.id)
usos = inv.usos_del_lote("Lomo", lote.id)
comprobar(usos["compra"] is not None and usos["servicios"] == {900: 28.0} and len(usos["salidas"]) == 3
          and len(usos["derivados"]) == 1,
          "Se sabe qué hay registrado con un lote: su compra, el servicio #900, un desperdicio y una elaboración")
silencio(inv.editar_lote, "Lomo", lote.id, precio_unitario=4)
comprobar(lote.precio_unitario == 4 and usos["compra"].precio_unitario == 14 and inv.precios_de("Lomo")[0].precio_unitario == 14,
          "Sin corregir lo registrado, solo cambia el lote (lo que salga a partir de ahora)")
silencio(inv.editar_lote, "Lomo", lote.id, precio_unitario=4, proveedor="Carnes Paco", corregir_registrado=True)
servicio = Servicio(HOY, time(14, 0), 10, "Menú inexistente")
servicio.id = 900
servicio.estado = "completado"
comprobar(_res2(servicio, inv, Recetario(), _RG2())["comida"] == 8.0
          and Metricas(inv).gasto_por_categoria(HOY, HOY) == {"Carnes": 20.0}
          and inv.precios_de("Lomo")[0].precio_unitario == 4 and inv.precios_de("Lomo")[0].proveedor == "Carnes Paco"
          and "Carnes Paco" in usos["compra"].lote,
          "Corrigiendo lo registrado: el servicio cuesta 8 €, la compra 20 € y el historial dice 4 € (y el proveedor nuevo)")
silencio(inv.salida_stock, "Lomo", 1.5, "consumo", lote.id, servicio_id=901)
comprobar(inv.buscar_producto("Lomo").buscar_lote(lote.id) is None, "(el lote ya se ha gastado entero)")
compra = inv.precios_de("Lomo")[0]
silencio(inv.corregir_compra, compra, 4.5)
comprobar(compra.precio_unitario == 4.5 and inv.usos_del_lote("Lomo", lote.id)["servicios"] == {900: 9.0, 901: 6.75},
          "Desde el historial de precios se corrige una compra aunque su lote ya no exista")
try:
    inv.corregir_compra(compra, -1)
    comprobar(False, "Un precio negativo no se acepta")
except ValueError:
    comprobar(compra.precio_unitario == 4.5, "Un precio negativo no se acepta")

print("\n--- IVA ---")
from inventario import precio_a_coste  # noqa: E402
inv = Inventario()
silencio(inv.agregar_producto, Producto("Leche", "Lácteos", 0, "litros", 0, "Lácteos SA", iva=4))
comprobar(Producto("Detergente", "Limpieza", 0, "litros", 0, "Droguería").iva == 21, "El IVA por defecto es el 21 %")
comprobar(precio_a_coste(1.0, False, 4) == 1.04 and precio_a_coste(1.04, True, 4) == 1.04,
          "Un precio escrito sin IVA se convierte en lo pagado (1 € + 4 % = 1,04 €)")
lote = silencio(inv.entrada_stock, "Leche", 10, precio_unitario=1.04, proveedor="Lácteos SA")
comprobar(abs(lote.precio_base - 1.0) < 1e-9 and lote.iva == 4 and lote.precio_unitario == 1.04,
          "Se ve lo pagado (1,04 €/l) y se guarda aparte sin IVA (1 €) y su tipo (4 %)")
silencio(inv.salida_stock, "Leche", 3, "consumo", lote.id, servicio_id=950)
comprobar(Metricas(inv).iva_soportado(HOY, HOY) == 0.4 and Metricas(inv).gasto_por_categoria(HOY, HOY) == {"Lácteos": 10.4},
          "Métricas: el gasto es lo pagado (10,40 €) y el IVA soportado se ve aparte (0,40 €)")
servicio = Servicio(HOY, time(14, 0), 10, "Menú inexistente")
servicio.id = 950
servicio.estado = "completado"
servicio.precio_cobrado = 100
inv.iva_recuperable = False
r = _res2(servicio, inv, Recetario(), _RG2())
comprobar(r["comida"] == 3.12 and r["iva_recuperable"] == 0, "Si NO se recupera el IVA, el servicio cuesta lo pagado (3,12 €)")
inv.iva_recuperable = True
r = _res2(servicio, inv, Recetario(), _RG2())
comprobar(r["comida"] == 3.0 and r["iva_recuperable"] == 0.12 and r["margen"] == 97.0 and lote.precio_unitario == 1.04,
          "Si se recupera, el margen se calcula sin IVA (3 €) y el IVA recuperable va aparte (0,12 €); el precio se sigue viendo con IVA")
copia = Inventario.from_dict(inv.to_dict())
comprobar(copia.iva_recuperable and copia.buscar_producto("Leche").lotes[0].precio_unitario == 1.04
          and copia.historial[-1].iva == 4, "El ajuste y los precios se guardan y se cargan")
viejo = {"productos": [{"nombre": "Aceite", "categoria": "Despensa", "unidad": "litros", "proveedor": "X",
                        "stock_minimo": 0, "precio_referencia": 5, "lotes": [
                            {"id": 1, "cantidad": 2, "precio_unitario": 5, "proveedor": "X",
                             "fecha_entrada": HOY.isoformat(), "procedencia": "compra"}]}]}
antiguo = Inventario.from_dict(viejo)
comprobar(antiguo.buscar_producto("Aceite").precio_unitario == 5 and antiguo.buscar_producto("Aceite").lotes[0].iva == 0,
          "Las sesiones de antes del IVA se cargan con sus precios tal cual")

# Elaboraciones: conservan la parte de IVA de sus ingredientes
inv2 = Inventario()
silencio(inv2.agregar_producto, Producto("Cebolla", "Verduras", 3, "kg", 1.04, "Huerta", iva=4))
silencio(inv2.definir_base, "Sofrito", "Elaboraciones", "kg", 1, {"Cebolla": 1.5})
silencio(Recetario().preparar_base, "Sofrito", 1, 1, inv2)
sofrito = inv2.buscar_producto("Sofrito").lotes[0]
comprobar(abs(sofrito.precio_unitario - 1.56) < 1e-6 and abs(sofrito.precio_base - 1.5) < 1e-6,
          "Una elaboración base cuesta lo pagado (1,56 €) y guarda su parte sin IVA (1,50 €)")
rec2 = Recetario()
ensalada2 = Receta("Ensalada", "Entrantes", {"Cebolla": 0.1})
silencio(rec2.agregar_receta, ensalada2)
tanda = silencio(rec2.preparar_elaboracion, "Ensalada", 10, inv2)
comprobar(abs(tanda.coste_por_racion - 0.104) < 1e-6 and abs(tanda.coste_por_racion_sin_iva - 0.1) < 1e-6,
          "Una tanda guarda su coste con IVA y sin IVA")
silencio(inv2.editar_producto, "Cebolla", iva=10)
comprobar(inv2.buscar_producto("Cebolla").iva == 10 and inv2.buscar_producto("Cebolla").lotes[0].iva == 4,
          "Cambiar el IVA de un producto vale para las compras nuevas; las ya hechas conservan el suyo")

# IVA del trimestre (estimación)
from metricas import trimestre  # noqa: E402
registro = RegistroServicios()
servicio.fecha = HOY
silencio(registro.agregar_servicio, servicio)
desde, hasta = trimestre(HOY)
resumen = Metricas(inv).resumen_iva(desde, hasta, registro.servicios)
comprobar(resumen["soportado_por_tipo"] == {4.0: 0.4} and resumen["soportado"] == 0.4
          and resumen["repercutido"] == 10.0 and resumen["resultado"] == 9.6,
          "IVA del trimestre: 0,40 € pagado, 10 € cobrado (10 % de 100 €) -> 9,60 € a ingresar (estimación)")
with tempfile.TemporaryDirectory() as carpeta:
    from openpyxl import load_workbook
    libro = load_workbook(silencio(exportar_todo, inv, RegistroServicios(), GestorCompras(), carpeta))
    cabecera = [c.value for c in libro["Historial de precios"][1]]
    comprobar("IVA (%)" in cabecera and "Total con IVA (€)" in cabecera and libro["Historial de precios"]["G2"].value == 4,
              "El Excel separa precio sin IVA, IVA y precio con IVA")
AJUSTES["iva_recuperable"] = False

print("\n--- Fase 1: guardado seguro ---")
import json as _json  # noqa: E402
import os as _os  # noqa: E402
from persistencia import (  # noqa: E402
    guardar_sesion, cargar_sesion_segura, carpeta_datos, escribir_sesion, sesion_a_dict, firma,
)
from metricas import ArchivoInformes  # noqa: E402
with tempfile.TemporaryDirectory() as carpeta:
    ruta = Path(carpeta) / "sesion.json"
    inv = Inventario()
    silencio(inv.agregar_producto, Producto("Arroz", "Despensa", 5, "kg", 1.2, "Mayorista"))
    args = (inv, RegistroServicios(), Recetario(), GestorCompras(), ArchivoInformes())
    silencio(guardar_sesion, *args, str(ruta))
    silencio(inv.agregar_producto, Producto("Sal", "Despensa", 1, "kg", 0.5, "Mayorista"))
    silencio(guardar_sesion, *args, str(ruta))
    bak = ruta.with_name("sesion.json.bak")
    comprobar(ruta.exists() and bak.exists() and "Sal" not in bak.read_text(encoding="utf-8")
              and any((Path(carpeta) / "copias").glob("sesion_*.json")) and not ruta.with_name("sesion.json.tmp").exists(),
              "Guardar deja la versión anterior en .bak y una copia del día en copias/")
    ruta.write_text('{"inventario": {"productos": [', encoding="utf-8")  # archivo cortado a mitad
    sesion, aviso = silencio(cargar_sesion_segura, str(ruta))
    comprobar(sesion is not None and "Arroz" in sesion.inventario.productos and aviso and "recuperado" in aviso
              and any(Path(carpeta).glob("sesion_danada_*.json")),
              "Si sesion.json está dañado, se recupera de la copia y el dañado se aparta (no se borra)")
    for f in list(Path(carpeta).rglob("*.json*")):
        f.write_text("basura", encoding="utf-8")
    sesion, aviso = silencio(cargar_sesion_segura, str(ruta))
    comprobar(sesion is None and aviso and "vacío" in aviso, "Sin ninguna copia válida, se avisa y se empieza vacío")
    datos = sesion_a_dict(*args)
    ruta.write_text("\ufeff" + _json.dumps(datos), encoding="utf-8")  # con BOM (Bloc de notas)
    sesion, aviso = silencio(cargar_sesion_segura, str(ruta))
    comprobar(sesion is not None and aviso is None, "Un archivo guardado con BOM también se carga")
    comprobar(firma(datos) == firma(sesion_a_dict(*args)) and firma(datos) != firma({}),
              "La huella de los datos sirve para saber si hay cambios sin guardar")
from persistencia import SesionIlegible  # noqa: E402
from gastos import NOTA_COSTE_AL_COMPLETAR as NOTA_COSTE  # noqa: E402
import time as _time  # noqa: E402
with tempfile.TemporaryDirectory() as carpeta:
    ruta = Path(carpeta) / "sesion.json"
    inv = Inventario()
    args = (inv, RegistroServicios(), Recetario(), GestorCompras(), ArchivoInformes())
    silencio(inv.agregar_producto, Producto("Arroz", "Despensa", 5, "kg", 1.2, "Mayorista"))
    silencio(guardar_sesion, *args, str(ruta))
    _time.sleep(0.05)
    silencio(inv.agregar_producto, Producto("Sal", "Despensa", 1, "kg", 0.5, "Mayorista"))
    silencio(guardar_sesion, *args, str(ruta))  # .bak = solo arroz; copia de hoy = arroz + sal
    ruta.write_text("{roto", encoding="utf-8")
    sesion, aviso = silencio(cargar_sesion_segura, str(ruta))
    comprobar(sesion is not None and "Sal" in sesion.inventario.productos,
              "Al recuperar, se usa la copia MÁS RECIENTE (no se pierde lo último guardado)")
    datos = _json.loads(ruta.read_text(encoding="utf-8"))
    datos["inventario"]["productos"][0]["unidad"] = "cajas raras"  # JSON bueno, contenido que no se entiende
    ruta.write_text(_json.dumps(datos), encoding="utf-8")
    antes = ruta.read_text(encoding="utf-8")
    try:
        silencio(cargar_sesion_segura, str(ruta))
        comprobar(False, "Un contenido que no se entiende no se trata como archivo roto")
    except SesionIlegible:
        comprobar(ruta.read_text(encoding="utf-8") == antes,
                  "Si el archivo se lee pero no se entiende, se avisa y NO se aparta ni se sobrescribe")
with tempfile.TemporaryDirectory() as carpeta:
    ruta = Path(carpeta) / "sesion.json"
    (Path(carpeta) / "copias").write_text("no soy una carpeta", encoding="utf-8")  # las copias no se pueden hacer
    silencio(escribir_sesion, {"a": 1}, str(ruta))
    comprobar(_json.loads(ruta.read_text(encoding="utf-8")) == {"a": 1},
              "Si la copia del día falla, el guardado principal se hace igual")
a1, a2 = Inventario(), Inventario()
a1.iva_cobro = 21
comprobar(a2.iva_cobro == 10, "Los ajustes de IVA son de cada sesión (dos ventanas no se los pisan)")
_os.environ["GESTION_RESTAURANTE_DATOS"] = "/tmp/otra"
comprobar(carpeta_datos(Path("/x")) == Path("/tmp/otra"), "La carpeta de datos se puede fijar (pruebas)")
del _os.environ["GESTION_RESTAURANTE_DATOS"]
comprobar(carpeta_datos(Path("/x")) == Path("/x/datos"), "Fuera del .exe, los datos siguen en la carpeta 'datos'")

print("\n--- Fase 1: servicios, recetas y limpiezas ---")
registro = RegistroServicios()
s1 = Servicio(HOY, time(14, 0), 10, "Menú A")
s2 = Servicio(HOY, time(14, 0), 10, "Menú A")
s2.id = s1.id  # como si otra ventana hubiera dado el mismo número
silencio(registro.agregar_servicio, s1)
silencio(registro.agregar_servicio, s2)
comprobar(s1.id != s2.id, "Dos servicios nunca tienen el mismo número")
s1.completar()
try:
    registro.cancelar_servicio(s1.id)
    comprobar(False, "Un servicio completado no se puede cancelar")
except ValueError:
    comprobar(s1.estado == "completado", "Un servicio completado no se puede cancelar")
rec = Recetario()
silencio(rec.agregar_receta, Receta("Paella", "Arroces", {"Arroz": 0.1}))
for nombre in ("Paella", "paella ", " PAELLA"):
    try:
        rec.agregar_receta(Receta(nombre, "Arroces", {"Arroz": 0.2}))
        comprobar(False, f"No se puede crear otra receta '{nombre}'")
    except ValueError:
        pass
comprobar(rec.recetas["Paella"].ingredientes_por_comensal == {"Arroz": 0.1},
          "Una receta con un nombre que ya existe (aunque cambien mayúsculas o espacios) no sustituye a la otra")
silencio(rec.agregar_menu, Menu("Menú A", [rec.recetas["Paella"]]))
try:
    rec.agregar_menu(Menu("menú a", []))
    comprobar(False, "No se puede repetir un menú")
except ValueError:
    comprobar(True, "Un menú con un nombre que ya existe no sustituye al otro")
avisos = silencio(GestorCompras().generar_lista_desde_servicios,
                  [Servicio(HOY + timedelta(days=1), time(14, 0), 10, "Menu A")], rec, Inventario())
comprobar(any("no existe" in a for a in avisos), "La lista de la compra AVISA de un servicio cuyo menú no existe")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Pata", "Carnes", 2, "unidades", 40, "Carnicería", tiene_merma=True, peso_unitario=7))
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 5, "kg", 1, "Huerta"))
silencio(inv.definir_base, "Fondo", "Elaboraciones", "litros", 1, {"Cebolla": 1})
silencio(inv.definir_base, "Sofrito", "Elaboraciones", "kg", 1, {"Cebolla": 1})
try:
    silencio(inv.limpiar_producto, "Pata", 1, "Sofrito", 5, lote_id=1)
    comprobar(False, "Una limpieza no puede dar una elaboración base")
except ValueError:
    copia = Inventario.from_dict(inv.to_dict())
    comprobar(inv.buscar_producto("Pata").stock == 2 and copia.buscar_producto("Sofrito").es_base(),
              "Una limpieza no puede dar una elaboración base (antes dejaba la sesión imposible de abrir)")

print("\n--- Fase 2, bloque 1: precios exactos ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Harina", "Panadería", 0, "g", 0, "Harinas", iva=4))
lote = silencio(inv.entrada_stock, "Harina", 25000, precio_unitario=15.50 / 25000, proveedor="Harinas")
comprobar(abs(lote.valor() - 15.50) < 0.005 and abs(inv.buscar_producto("Harina").precio_unitario * 25000 - 15.50) < 1e-6,
          "25.000 g comprados por 15,50 € valen 15,50 € (antes, por el redondeo, 15,00 €)")
silencio(inv.agregar_producto, Producto("Pata", "Carnes", 1, "unidades", 40, "Carnicería", tiene_merma=True, peso_unitario=7))
silencio(inv.agregar_producto, Producto("Carne limpia", "Carnes", 0, "g", 0, "Propio"))
silencio(inv.limpiar_producto, "Pata", 1, "Carne limpia", 4321, unidad_peso="g", lote_id=1)
comprobar(abs(inv.buscar_producto("Carne limpia").lotes[0].valor() - 40) < 0.005,
          "Una limpieza en gramos conserva el coste exacto (40 €)")
lote2 = silencio(inv.compra_para_servicio, "Harina", 10000, 0, 6.30, 1)
comprobar(abs(lote2.valor() - 6.30) < 0.005, "Una compra de última hora en gramos también (10.000 g por 6,30 €)")

print("\n--- Fase 2, bloque 1: elaboraciones base sin preparar ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 10, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 5, "litros", 5, "Mayorista"))
silencio(inv.definir_base, "Sofrito", "Elaboraciones", "kg", 1, {"Cebolla": 2, "Aceite": 0.1})  # 4,50 €/kg
silencio(inv.definir_base, "Salsa", "Elaboraciones", "litros", 2, {"Sofrito": 1, "Aceite": 0.2})  # (4,5 + 1) / 2
rec = Recetario()
guiso = Receta("Guiso", "Principales", {"Sofrito": 0.05, "Salsa": 0.1})
silencio(rec.agregar_receta, guiso)
comprobar(abs(inv.precio_de("Sofrito") - 4.5) < 1e-9 and abs(inv.precio_de("Salsa") - 2.75) < 1e-9
          and guiso.costo_por_comensal(inv) == round(0.05 * 4.5 + 0.1 * 2.75, 2),
          "Una base sin preparar cuesta lo que su fórmula (sofrito 4,50 €/kg; salsa con sofrito 2,75 €/l), no 0 €")
silencio(rec.agregar_menu, Menu("Menú guiso", [guiso]))
servicio = Servicio(HOY + timedelta(days=3), time(14, 0), 200, "Menú guiso")
r = _res2(servicio, inv, rec, _RG2())
comprobar(abs(r["comida"] - 200 * (0.05 * 4.5 + 0.1 * 2.75)) < 0.01,
          "La rentabilidad estimada de un servicio cuenta las bases (200 comensales = 100 €, antes 0 €)")

print("\n--- Fase 2, bloque 1: 'la última compra fue a…' ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Gambas", "Pescado", 0, "kg", 0, "Lonja"))
lote = silencio(inv.entrada_stock, "Gambas", 2, precio_unitario=220, proveedor="Lonja")  # error: eran 22 €/kg
silencio(inv.salida_stock, "Gambas", 2, "consumo", lote.id)
silencio(inv.corregir_compra, inv.precios_de("Gambas")[-1], 22)
comprobar(abs(inv.buscar_producto("Gambas").precio_referencia - 22) < 1e-9,
          "Al corregir el precio de la última compra, se corrige también 'la última compra fue a…' (22 €, no 220 €)")
lote = silencio(inv.entrada_stock, "Gambas", 1, precio_unitario=300, proveedor="Lonja")
silencio(inv.editar_lote, "Gambas", lote.id, precio_unitario=30)
comprobar(abs(inv.buscar_producto("Gambas").precio_referencia - 30) < 1e-9, "...también desde 'Editar producto'")
silencio(inv.agregar_producto, Producto("Pata", "Carnes", 1, "unidades", 40, "Carnicería", tiene_merma=True, peso_unitario=7))
silencio(inv.agregar_producto, Producto("Huesos", "Carnes", 0, "kg", 0, "Propio"))
silencio(inv.entrada_stock, "Huesos", 2, precio_unitario=1.5, proveedor="Carnicería")
silencio(inv.agregar_producto, Producto("Carne", "Carnes", 0, "kg", 0, "Propio"))
silencio(inv.limpiar_producto, "Pata", 1, "Carne", 4, derivados={"Huesos": 1}, lote_id=1)
comprobar(abs(inv.buscar_producto("Huesos").precio_referencia - 1.5) < 1e-9,
          "Un derivado a 0 € de una limpieza no cambia 'la última compra fue a…'")
viejo = {"productos": [{"nombre": "Harina", "categoria": "Panadería", "unidad": "kg", "proveedor": "X",
                        "stock_minimo": 0, "precio_referencia": 1.5, "lotes": []}]}
comprobar(abs(Inventario.from_dict(viejo).buscar_producto("Harina").precio_referencia - 1.5) < 1e-9,
          "En datos de antes del IVA, el precio de referencia no sube un 21 % (sigue en 1,50 €)")

print("\n--- Fase 2, bloque 2: caducidades en la lista de la compra ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta", fecha_caducidad=HOY + timedelta(days=3)))
silencio(inv.agregar_producto, Producto("Sal", "Despensa", 5, "kg", 1, "Mayorista"))
recetario = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1, "Sal": 0.01})
silencio(recetario.agregar_receta, ensalada)
silencio(recetario.agregar_menu, Menu("Menú ensalada", [ensalada]))
pronto = Servicio(HOY + timedelta(days=1), time(14, 0), 15, "Menú ensalada")
pronto.id = 701
tarde = Servicio(HOY + timedelta(days=5), time(14, 0), 15, "Menú ensalada")
tarde.id = 702
gestor = GestorCompras()
silencio(gestor.generar_lista_desde_servicios, [pronto], recetario, inv)
comprobar(gestor.pendiente_de("Tomate") is None, "Un lote que sigue bueno el día del servicio cuenta (1,5 kg de 2: no se compra)")
avisos = silencio(gestor.generar_lista_desde_servicios, [tarde], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 1.5,
          "Un lote que caduca ANTES del servicio no cuenta (se compran los 1,5 kg)")
comprobar(any("caducan el" in a and "#702" in a and "Tomate" in a for a in avisos),
          "...y se avisa de que ese lote caduca antes del servicio #702")
avisos = silencio(gestor.generar_lista_desde_servicios, [pronto, tarde], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 1.5,
          "Con dos servicios, el lote cubre el primero (antes de caducar) y para el segundo se compra")
comprobar(gestor.pendiente_de("Sal") is None, "Lo que no caduca cuenta siempre (sal)")

silencio(inv.entrada_stock, "Tomate", 1, precio_unitario=2, fecha_caducidad=HOY - timedelta(days=1))
avisos = silencio(gestor.generar_lista_desde_servicios, [pronto, tarde], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 1.5 and any("ya está caducado" in a for a in avisos),
          "Un lote YA caducado no cuenta, y se avisa de que se puede desechar")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta", fecha_caducidad=HOY + timedelta(days=10)))
silencio(inv.agregar_producto, Producto("Sal", "Despensa", 5, "kg", 1, "Mayorista"))
gestor = GestorCompras()
silencio(gestor.generar_lista_desde_servicios, [pronto, tarde], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 1,
          "El mismo lote no cubre dos servicios a la vez (3 kg necesarios, 2 en stock: falta 1)")

print("\n--- Fase 2, bloque 2: lotes caducados al preparar o completar ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 1, "kg", 2, "Huerta", fecha_caducidad=HOY - timedelta(days=2)))
silencio(inv.entrada_stock, "Tomate", 3, precio_unitario=2, fecha_caducidad=HOY + timedelta(days=4))
tomate = inv.buscar_producto("Tomate")
comprobar([l.id for l in tomate.lotes_para_usar()] == [2, 1],
          "Primero se propone el lote bueno; el caducado, al final (aunque caduque antes)")
filas = Recetario.filas_necesidades({"Tomate": 0.5}, inv)
comprobar(filas[0]["reparto"] == [(2, 0.5)] and filas[0]["caducados"] == [],
          "Por defecto se gasta del lote bueno, no del caducado")
filas = Recetario.filas_necesidades({"Tomate": 0.5}, inv, {"Tomate": [1]})
comprobar(filas[0]["caducados"] == [(1, 0.5, HOY - timedelta(days=2))],
          "Si se elige el lote caducado, la fila lo señala (para avisar)")
filas = Recetario.filas_necesidades({"Tomate": 5}, inv)
comprobar(filas[0]["reparto"] == [(2, 3), (1, 1)] and filas[0]["caducados"] == [(1, 1, HOY - timedelta(days=2))],
          "Si no llega con todo, lo caducado se gasta al final, y se señala")
inv2 = Inventario()
silencio(inv2.agregar_producto, Producto("Leche", "Lácteos", 2, "litros", 1, "Granja", fecha_caducidad=HOY - timedelta(days=1)))
filas = Recetario.filas_necesidades({"Leche": 1}, inv2)
comprobar(filas[0]["caducados"] == [(1, 1, HOY - timedelta(days=1))],
          "Con un único lote caducado también se señala (antes pasaba sin avisar)")

print("\n--- Fase 2, bloque 2: varias tandas y varios servicios ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 0, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Sal", "Despensa", 5, "kg", 1, "Mayorista"))
silencio(inv.elaboraciones.nueva_tanda, "Ensalada", 10, 0.5, HOY + timedelta(days=3))
silencio(inv.elaboraciones.nueva_tanda, "Ensalada", 10, 0.5, None)
s1 = Servicio(HOY + timedelta(days=1), time(14, 0), 10, "Menú ensalada")
s1.id = 711
s2 = Servicio(HOY + timedelta(days=6), time(14, 0), 10, "Menú ensalada")
s2.id = 712
gestor = GestorCompras()
silencio(gestor.generar_lista_desde_servicios, [s1, s2], recetario, inv)
comprobar(gestor.pendiente_de("Tomate") is None,
          "Cada servicio usa la tanda que caduca antes y sigue buena: no se compra de más (antes pedía 1 kg)")
s3 = Servicio(HOY + timedelta(days=7), time(14, 0), 10, "Menú ensalada")
s3.id = 713
silencio(gestor.generar_lista_desde_servicios, [s1, s2, s3], recetario, inv)
comprobar(gestor.pendiente_de("Tomate").cantidad == 1, "...y las raciones que ya no quedan sí se compran (1 kg)")

print("\n--- Fase 2, bloque 3: corregir la cantidad de una compra ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Arroz", "Despensa", 0, "kg", 0, "Mayorista", iva=10))
lote = silencio(inv.entrada_stock, "Arroz", 50, precio_unitario=1.1, proveedor="Mayorista")  # eran 5 kg
silencio(inv.salida_stock, "Arroz", 2, "consumo", lote.id)
met = Metricas(inv)
compra = inv.precios_de("Arroz")[-1]
silencio(inv.corregir_compra, compra, cantidad=5)
arroz = inv.buscar_producto("Arroz")
comprobar(abs(arroz.stock - 3) < 1e-9, "Compra de 50 kg corregida a 5 kg con 2 usados: quedan 3 kg en el lote")
comprobar(abs(met.gasto_por_tipo(HOY, HOY)["alimento"] - 5.5) < 1e-9 and inv.precios_de("Arroz")[-1].cantidad == 5,
          "El gasto en Métricas (5,50 €) y el historial de precios (5 kg) también se corrigen")
comprobar(abs(met.iva_soportado(HOY, HOY) - 0.5) < 1e-9, "...y el IVA soportado (0,50 €)")
try:
    inv.corregir_compra(compra, cantidad=1)
    comprobar(False, "No se puede corregir a menos de lo ya usado")
except ValueError as e:
    comprobar("ya se han usado 2" in str(e) and abs(arroz.stock - 3) < 1e-9,
              "No se puede corregir a menos de lo ya usado (2 kg), y no cambia nada")

print("\n--- Fase 2, bloque 3: anular una compra ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 0, "litros", 0, "Mayorista"))
silencio(inv.entrada_stock, "Aceite", 5, precio_unitario=6, proveedor="Mayorista")
duplicada = silencio(inv.entrada_stock, "Aceite", 5, precio_unitario=9, proveedor="Mayorista")
met = Metricas(inv)
compra = inv.precios_de("Aceite")[-1]
comprobar(inv.se_puede_anular(compra)[0], "Una compra de la que no ha salido nada se puede anular")
silencio(inv.anular_compra, compra)
aceite = inv.buscar_producto("Aceite")
comprobar(aceite.stock == 5 and aceite.buscar_lote(duplicada.id) is None and len(inv.precios_de("Aceite")) == 1
          and abs(met.gasto_por_tipo(HOY, HOY)["alimento"] - 30) < 1e-9,
          "Anular quita el lote, su gasto (queda 30 €) y su línea del historial de precios")
comprobar(abs(aceite.precio_referencia - 6) < 1e-9, "'La última compra fue a…' vuelve a la compra anterior (6 €)")
silencio(inv.salida_stock, "Aceite", 1, "consumo", aceite.lotes[0].id)
posible, motivo = inv.se_puede_anular(inv.precios_de("Aceite")[-1])
comprobar(not posible and "Corrígela" in motivo, "Una compra de la que ya se ha usado algo no se puede anular")
try:
    inv.anular_compra(inv.precios_de("Aceite")[-1])
    comprobar(False, "...ni forzándolo")
except ValueError:
    comprobar(aceite.stock == 4, "...ni forzándolo (no cambia nada)")

print("\n--- Fase 2, bloque 3: IVA de compras y productos ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Queso", "Lácteos", 0, "kg", 0, "Quesería"))  # 21 % por error
lote = silencio(inv.entrada_stock, "Queso", 2, precio_unitario=11, proveedor="Quesería")
silencio(inv.salida_stock, "Queso", 1, "consumo", lote.id)
met = Metricas(inv)
silencio(inv.corregir_compra, inv.precios_de("Queso")[-1], iva=10)
queso = inv.buscar_producto("Queso")
comprobar(abs(queso.lotes[0].precio_unitario - 11) < 1e-9 and abs(queso.lotes[0].precio_base - 10) < 1e-9
          and queso.lotes[0].iva == 10, "Corregir el IVA de una compra mantiene lo pagado (11 €) y la base pasa a 10 €")
comprobar(abs(met.iva_soportado(HOY, HOY) - 2) < 1e-9 and abs(met.gasto_por_tipo(HOY, HOY)["alimento"] - 22) < 1e-9,
          "El IVA soportado pasa a 2 € (10 % de 20) y el gasto sigue en 22 €")
salida = next(m for m in inv.historial if m.tipo == "salida")
comprobar(salida.iva == 10 and abs(salida.precio_unitario - 11) < 1e-9, "Lo que ya salió del lote también se corrige")
comprobar(queso.iva == 10 and abs(queso.precio_referencia - 11) < 1e-9,
          "El producto usa ese IVA en las próximas compras, y 'la última compra fue a…' sigue en 11 €")
silencio(inv.editar_producto, "Queso", iva=4)
comprobar(abs(queso.precio_referencia - 11) < 1e-9,
          "Cambiar el IVA del producto no cambia 'la última compra fue a…' (sigue en 11 €)")

silencio(inv.agregar_producto, Producto("Pata", "Carnes", 1, "unidades", 40, "Carnicería", tiene_merma=True,
                                        peso_unitario=7, iva=10))
silencio(inv.limpiar_producto, "Pata", 1, "Carne limpia", 4, derivados={"Huesos": 1}, lote_id=1)
comprobar(inv.buscar_producto("Carne limpia").iva == 10 and inv.buscar_producto("Huesos").iva == 10,
          "Los productos que nacen de una limpieza llevan el IVA del producto en bruto (10 %)")

print("\n--- Fase 2, bloque 4: IVA de los gastos ---")
inv = Inventario()
inv.iva_recuperable = True
gastos = RegistroGastos()
serv = Servicio(HOY, time(14, 0), 10, "Sin menú", precio_cobrado=500)
serv.id = 801
silencio(gastos.agregar_gasto, Gasto("Gasolina", "Transporte", 121, HOY, 801, iva=21))
silencio(gastos.agregar_gasto, Gasto("Camarero", "Personal extra", 100, HOY, 801, iva=0))
silencio(gastos.agregar_gasto, Gasto("Antiguo", "Otros", 50, HOY, 801))  # sin IVA desglosado
r = resumen_servicio(serv, inv, Recetario(), gastos)
comprobar(abs(r["gastos"] - 250) < 1e-9 and abs(r["iva_recuperable"] - 21) < 1e-9,
          "Si se recupera el IVA, los gastos cuentan sin IVA (100 + 100 + 50) y su IVA (21 €) va aparte")
inv.iva_recuperable = False
r = resumen_servicio(serv, inv, Recetario(), gastos)
comprobar(abs(r["gastos"] - 271) < 1e-9, "Si no se recupera, cuentan con IVA (271 €)")
comprobar(Gasto.iva_propuesto("Transporte") == 21 and Gasto.iva_propuesto("Personal extra") == 0,
          "Se propone 21 % (y 'Sin IVA' para personal y seguros)")
copia = RegistroGastos.from_dict(gastos.to_dict())
comprobar([g.iva for g in copia.gastos] == [21, 0, None], "El IVA de cada gasto se guarda y se carga (los antiguos: sin desglosar)")
inv.iva_recuperable = True
resumen = Metricas(inv).resumen_iva(HOY, HOY, [], gastos.gastos)
comprobar(abs(resumen["soportado"] - 21) < 1e-9 and resumen["gastos_sin_desglose"] == 1,
          "La estimación de IVA del trimestre suma el IVA de los gastos y avisa de los no desglosados")

print("\n--- Fase 2, bloque 4: completar un servicio no queda a medias ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Harina", "Despensa", 0.1234567, "kg", 1, "Mayorista"))
reparto, _ = inv.repartir("Harina", 0.1234567, [1])
comprobar(silencio(inv.salida_repartida, "Harina", reparto, "consumo") and inv.buscar_producto("Harina").stock == 0,
          "Un lote con más de 6 decimales se puede gastar entero (antes se rechazaba por redondeo)")
silencio(inv.agregar_producto, Producto("Sal", "Despensa", 1, "kg", 1, "Mayorista"))
rec = Recetario()
plato = Receta("Pan", "Panadería", {"Sal": 0.1})
silencio(rec.agregar_receta, plato)
silencio(rec.agregar_menu, Menu("Menú pan", [plato]))
serv = Servicio(HOY, time(14, 0), 5, "Menú pan")
serv.id = 802
filas = rec.previsualizar_consumo(serv, inv)
silencio(inv.salida_stock, "Sal", 0.9, "consumo", 1)  # el stock cambia entre la vista previa y completar
original = rec.previsualizar_consumo
rec.previsualizar_consumo = lambda *a, **k: filas  # simula que la pantalla tenía datos de antes
try:
    rec.completar_servicio(serv, inv)
    comprobar(False, "Si una salida no se puede hacer, no se completa")
except ValueError as e:
    comprobar(serv.estado != "completado" and abs(inv.buscar_producto("Sal").stock - 0.1) < 1e-9
              and "no se ha tocado nada" in str(e),
              "Si una salida no se puede hacer, el servicio NO se completa y no se toca nada")
rec.previsualizar_consumo = original

print("\n--- Fase 2, bloque 4: renombrar un producto ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 1, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 1, "kg", 1, "Huerta"))
for nombre in ("", "   "):
    try:
        inv.editar_producto("Tomate", nuevo_nombre=nombre)
        comprobar(False, "Un nombre vacío no se acepta")
    except ValueError:
        pass
comprobar("Tomate" in inv.productos, "Un nombre vacío o con solo espacios no se acepta")
comprobar(not silencio(inv.editar_producto, "Tomate", nuevo_nombre="cebolla") and "Tomate" in inv.productos,
          "Un nombre que ya existe con otras mayúsculas no se acepta")
comprobar(silencio(inv.editar_producto, "Tomate", nuevo_nombre="  Tomate pera ") and "Tomate pera" in inv.productos,
          "Los espacios de los lados se quitan ('Tomate pera')")
comprobar(silencio(inv.editar_producto, "Tomate pera", nuevo_nombre="tomate pera") and "tomate pera" in inv.productos,
          "Cambiar solo las mayúsculas del propio nombre sí se puede")
compras = GestorCompras()
from compras import ItemCompra  # noqa: E402
silencio(compras.agregar_item, ItemCompra("Cebolla", 2, "kg", "Huerta", 1))
compras.renombrar_producto("Cebolla", "Cebolla dulce")
comprobar(compras.pendiente_de("Cebolla dulce") is not None, "La lista de la compra pasa a usar el nombre nuevo")

print("\n--- Fase 3, bloque 1: editar servicios ---")
serv = Servicio(HOY, time(14, 0), 10, "Menú A", precio_cobrado=300)
silencio(serv.editar, fecha=HOY + timedelta(days=2), comensales=12, menu="Menú B", estado="confirmado", cliente=" Ruiz ")
comprobar(serv.fecha == HOY + timedelta(days=2) and serv.comensales == 12 and serv.menu == "Menú B"
          and serv.estado == "confirmado" and serv.cliente == "Ruiz" and serv.precio_cobrado == 300,
          "Un servicio pendiente se puede editar (fecha, comensales, menú, cliente) y marcar como confirmado")
silencio(serv.editar, quitar_precio=True)
comprobar(serv.precio_cobrado is None, "Se le puede quitar el precio de cobro")
for cambio, texto in (({"comensales": 0}, "comensales"), ({"estado": "completado"}, "estado")):
    try:
        serv.editar(**cambio)
        comprobar(False, f"Editar rechaza un valor no válido ({texto})")
    except ValueError:
        comprobar(serv.comensales == 12 and serv.estado == "confirmado", f"Editar rechaza un valor no válido ({texto})")
serv.completar()
try:
    serv.editar(comensales=5)
    comprobar(False, "Un servicio completado no se edita")
except ValueError:
    comprobar(serv.comensales == 12, "Un servicio completado no se edita")

print("\n--- Fase 3, bloque 1: editar y borrar recetas y menús ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 5, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Aceite", "Despensa", 5, "litros", 4, "Mayorista"))
rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1, "Aceite": 0.01})
gazpacho = Receta("Gazpacho", "Entrantes", {"Tomate": 0.2})
silencio(rec.agregar_receta, ensalada)
silencio(rec.agregar_receta, gazpacho)
silencio(rec.agregar_menu, Menu("Menú verano", [ensalada]))
silencio(rec.editar_receta, "Ensalada", ingredientes={"Tomate": 0.15, "Aceite": 0}, categoria="Primeros")
comprobar(ensalada.ingredientes_por_comensal == {"Tomate": 0.15} and ensalada.categoria == "Primeros"
          and rec.menus["Menú verano"].ingredientes_por_comensal() == {"Tomate": 0.15},
          "Editar una receta cambia cantidades, quita ingredientes (a 0) y el menú lo ve")
try:
    rec.editar_receta("Ensalada", ingredientes={"Tomate": 0})
    comprobar(False, "Una receta no se queda sin ingredientes")
except ValueError:
    comprobar(ensalada.ingredientes_por_comensal == {"Tomate": 0.15}, "Una receta no se queda sin ingredientes")
try:
    rec.eliminar_receta("Ensalada", inv)
    comprobar(False, "No se borra una receta que está en un menú")
except ValueError as e:
    comprobar("Menú verano" in str(e) and "Ensalada" in rec.recetas, "No se borra una receta que está en un menú (y dice cuál)")
silencio(inv.elaboraciones.nueva_tanda, "Gazpacho", 5, 1.0)
try:
    rec.eliminar_receta("Gazpacho", inv)
    comprobar(False, "No se borra una receta con raciones preparadas")
except ValueError:
    comprobar("Gazpacho" in rec.recetas, "No se borra una receta con raciones preparadas")
silencio(rec.editar_recetas_menu, "Menú verano", ["Ensalada", "Gazpacho"])
comprobar([r.nombre for r in rec.menus["Menú verano"].recetas] == ["Ensalada", "Gazpacho"], "Se pueden cambiar las recetas de un menú")
silencio(rec.editar_recetas_menu, "Menú verano", ["Gazpacho"])
silencio(rec.eliminar_receta, "Ensalada", inv)
comprobar("Ensalada" not in rec.recetas, "Quitada del menú, la receta ya se puede borrar")
pendiente = Servicio(HOY, time(14, 0), 10, "Menú verano")
hecho = Servicio(HOY, time(14, 0), 10, "Menú verano")
hecho.completar()
try:
    rec.eliminar_menu("Menú verano", [pendiente, hecho])
    comprobar(False, "No se borra un menú que usa un servicio pendiente")
except ValueError as e:
    comprobar(f"#{pendiente.id}" in str(e) and "Menú verano" in rec.menus,
              "No se borra un menú que usa un servicio pendiente (y dice cuál)")
silencio(rec.eliminar_menu, "Menú verano", [hecho])
comprobar("Menú verano" not in rec.menus, "Un menú que solo usan servicios ya hechos sí se puede borrar")

print("\n--- Fase 3, bloque 2: borrar productos y material ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Cebolla", "Verduras", 3, "kg", 1, "Huerta"))
silencio(inv.agregar_producto, Producto("Pimiento", "Verduras", 0, "kg", 0, "Huerta"))
silencio(inv.definir_base, "Sofrito", "Bases", "kg", 1, {"Cebolla": 1.5})
silencio(inv.salida_stock, "Tomate", 1, "consumo", 1)
rec = Recetario()
silencio(rec.agregar_receta, Receta("Ensalada", "Entrantes", {"Tomate": 0.1}))
try:
    inv.borrar_producto("Tomate", rec.donde_se_usa_producto("Tomate"))
    comprobar(False, "No se borra un producto que usa una receta")
except ValueError as e:
    comprobar("Ensalada" in str(e) and "Tomate" in inv.productos, "No se borra un producto que usa una receta (y dice cuál)")
try:
    inv.borrar_producto("Cebolla", rec.donde_se_usa_producto("Cebolla"))
    comprobar(False, "No se borra un ingrediente de una elaboración base")
except ValueError as e:
    comprobar("Sofrito" in str(e), "No se borra un ingrediente de una elaboración base (y dice cuál)")
silencio(rec.editar_receta, "Ensalada", ingredientes={"Pimiento": 0.1})
movimientos = len(inv.historial)
stock = silencio(inv.borrar_producto, "Tomate", rec.donde_se_usa_producto("Tomate"))
comprobar("Tomate" not in inv.productos and stock == 1 and len(inv.historial) == movimientos
          and len(inv.precios_de("Tomate")) == 1,
          "Un producto que ya no se usa se borra; su stock (1 kg) no cuenta como desperdicio y su historial se conserva")
compras = GestorCompras()
silencio(compras.agregar_item, ItemCompra("Tomate", 2, "kg", "Huerta", 2))
compras.quitar_producto("Tomate")
comprobar(compras.pendiente_de("Tomate") is None, "Lo pendiente de un producto borrado se quita de la lista de la compra")

reg = RegistroMaterial()
silencio(reg.agregar_material, Material("Copa", "Cristalería", 50, 2.0, "Bazar"))
silencio(reg.registrar_salida, 1, {"Copa": 10})
try:
    reg.borrar_material("Copa")
    comprobar(False, "No se borra material que está fuera")
except ValueError:
    comprobar("Copa" in reg.materiales, "No se borra un material con unidades fuera en un servicio")
silencio(reg.registrar_vuelta, 1, {"Copa": 9}, {"Copa": 1})
rec2 = Recetario()
silencio(rec2.agregar_receta, Receta("Pan", "Panadería", {"Harina": 0.1}))
silencio(rec2.agregar_menu, Menu("Menú copa", [rec2.recetas["Pan"]], materiales_por_comensal={"Copa": 2}))
silencio(reg.borrar_material, "Copa")
comprobar("Copa" not in reg.materiales and len(reg.incidencias) == 1 and rec2.quitar_material("Copa") == ["Menú copa"]
          and rec2.menus["Menú copa"].materiales_por_comensal == {},
          "Un material de vuelta se borra, se quita de los menús y sus roturas se conservan")

print("\n--- Fase 3, bloque 2: empezar de cero ---")
from persistencia import copia_antes_de_empezar_de_cero, sesion_vacia, sesion_a_dict as _sad  # noqa: E402
inv = Inventario()
inv.iva_recuperable = False
inv.iva_cobro = 7
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta"))
with tempfile.TemporaryDirectory() as carpeta:
    ruta = str(Path(carpeta) / "sesion.json")
    datos = _sad(inv, RegistroServicios(), Recetario(), GestorCompras(), ArchivoInformes(), RegistroGastos(), RegistroMaterial())
    copia = copia_antes_de_empezar_de_cero(datos, ruta)
    comprobar(copia.exists() and copia.parent.name == "copias" and copia.name.startswith("antes_de_empezar_de_cero_")
              and "Tomate" in copia.read_text(encoding="utf-8"),
              "Antes de empezar de cero se guarda una copia con todo (copias/antes_de_empezar_de_cero_...)")
vacia = sesion_vacia(inv)
comprobar(not vacia.inventario.productos and vacia.inventario.iva_recuperable is False and vacia.inventario.iva_cobro == 7,
          "La sesión nueva está vacía y conserva los ajustes del IVA")

print("\n--- Fase 3, bloque 3: deshacer un servicio completado ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 1, "kg", 2, "Huerta", fecha_caducidad=HOY + timedelta(days=4)))
silencio(inv.entrada_stock, "Tomate", 2, precio_unitario=3, proveedor="Mercado", fecha_caducidad=HOY + timedelta(days=8))
silencio(inv.agregar_producto, Producto("Servilleta", "Menaje", 100, "unidades", 0.05, "Bazar", tipo="consumible"))
silencio(inv.agregar_producto, Producto("Lejía", "Limpieza", 5, "litros", 1, "Droguería", tipo="mantenimiento"))
rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1})
silencio(rec.agregar_receta, ensalada)
silencio(rec.agregar_menu, Menu("Menú", [ensalada], {"Servilleta": 1}))
silencio(inv.elaboraciones.nueva_tanda, "Ensalada", 5, 0.3, HOY + timedelta(days=2))
gastos = RegistroGastos()
serv = Servicio(HOY, time(14, 0), 20, "Menú")  # 5 raciones preparadas + 15 con ingredientes (1,5 kg)
serv.id = 901
silencio(rec.completar_servicio, serv, inv, {"Tomate": [1, 2]})
silencio(inv.salida_stock, "Lejía", 1, "consumo", 1, servicio_id=901)  # mantenimiento apuntado a mano
silencio(gastos.agregar_gasto, Gasto("Taxi", "Transporte", 20, HOY, 901, NOTA_COSTE, iva=21))
silencio(gastos.agregar_gasto, Gasto("Camarero", "Personal extra", 80, HOY, 901, "", iva=0))
tomate = inv.buscar_producto("Tomate")
comprobar(tomate.buscar_lote(1) is None and abs(tomate.stock - 1.5) < 1e-9 and not inv.elaboraciones.tandas,
          "(Al completar se gasta el lote 1 entero, 0,5 kg del lote 2 y la tanda entera)")
r = silencio(rec.deshacer_completar, serv, inv, gastos)
lote1 = tomate.buscar_lote(1)
comprobar(serv.estado == "pendiente" and serv.fecha_completado is None and abs(tomate.stock - 3) < 1e-9
          and lote1 is not None and lote1.fecha_caducidad == HOY + timedelta(days=4) and abs(lote1.precio_unitario - 2) < 1e-9
          and lote1.proveedor == "Huerta" and abs(tomate.buscar_lote(2).cantidad - 2) < 1e-9,
          "Deshacer: vuelve a pendiente y lo usado vuelve a sus lotes (el lote 1 se recrea con su precio y caducidad)")
tanda = inv.elaboraciones.tandas_de("Ensalada")
comprobar(len(tanda) == 1 and tanda[0].raciones == 5 and tanda[0].fecha_caducidad == HOY + timedelta(days=2),
          "Las raciones preparadas vuelven a su tanda (con su caducidad)")
comprobar(inv.buscar_producto("Servilleta").stock == 100 and not inv.salidas_de_servicio(901)
          and not inv.elaboraciones.usos_de_servicio(901),
          "Los consumibles también vuelven, y su consumo desaparece del historial")
comprobar(inv.buscar_producto("Lejía").stock == 4, "La limpieza y mantenimiento apuntado a mano para el servicio no se toca")
comprobar([g.concepto for g in gastos.gastos] == ["Camarero"] and len(r["gastos"]) == 1,
          "Se quitan los costes añadidos al completar; los demás gastos del servicio se quedan")
silencio(rec.completar_servicio, serv, inv, {"Tomate": [1, 2]})
comprobar(serv.estado == "completado" and abs(tomate.stock - 1.5) < 1e-9, "Después se puede volver a completar")
try:
    rec.deshacer_completar(Servicio(HOY, time(14, 0), 2, "Menú"), inv)
    comprobar(False, "Solo se deshace un servicio completado")
except ValueError:
    comprobar(True, "Solo se deshace un servicio completado")
copia_elab = type(inv.elaboraciones).from_dict(inv.elaboraciones.to_dict())
comprobar(len(copia_elab.agotadas) == 1, "Las tandas gastadas enteras se guardan (para poder deshacer tras reabrir)")

print("\n--- Fase 3, bloque 3: copias de seguridad ---")
from persistencia import escribir_sesion, listar_copias  # noqa: E402
with tempfile.TemporaryDirectory() as carpeta:
    ruta = str(Path(carpeta) / "sesion.json")
    datos = _sad(inv, RegistroServicios(), rec, GestorCompras(), ArchivoInformes(), gastos, RegistroMaterial())
    escribir_sesion(datos, ruta)
    copia_antes_de_empezar_de_cero(datos, ruta, motivo="restaurar")
    (Path(carpeta) / "copias" / "sesion_2020-01-01.json").write_text("{roto", encoding="utf-8")
    copias = listar_copias(ruta)
    tipos = {c["tipo"] for c in copias}
    diaria = next(c for c in copias if c["nombre"] == f"sesion_{HOY.isoformat()}.json")
    rota = next(c for c in copias if c["nombre"] == "sesion_2020-01-01.json")
    comprobar(len(copias) == 3 and {"Copia del día", "Antes de restaurar otra copia"} <= tipos
              and diaria["resumen"] == {"productos": 3, "recetas": 1, "servicios": 0} and rota["resumen"] is None,
              "Se listan las copias con su tipo y lo que contienen (una dañada sale sin resumen)")

print("\n--- Fase 3, bloque 4: Excel ---")
from openpyxl import load_workbook  # noqa: E402
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2.5, "Huerta"))
servicios = RegistroServicios()
silencio(servicios.agregar_servicio, Servicio(HOY, time(14, 0), 10, "Menú", precio_cobrado=300))
compras = GestorCompras()
silencio(compras.agregar_item, ItemCompra("Tomate", 2, "kg", "Huerta", 2.5))
silencio(compras.agregar_item, ItemCompra("Sal", 1, "kg", "Huerta", 1))
silencio(compras.marcar_comprado, "Sal")
gastos = RegistroGastos()
silencio(gastos.agregar_gasto, Gasto("Gasolina", "Transporte", 30, HOY, None, iva=21))
material = RegistroMaterial()
silencio(material.agregar_material, Material("Copa", "Cristalería", 10, 2.0, "Bazar"))
silencio(material.dar_de_baja, "Copa", 1)
with tempfile.TemporaryDirectory() as carpeta:
    ruta = silencio(exportar_todo, inv, servicios, compras, carpeta, gastos, Recetario(), material)
    wb = load_workbook(ruta)
    hoja = wb["Gastos"]
    comprobar(hoja.cell(row=2, column=2).is_date and hoja.cell(row=2, column=5).number_format.endswith('"€"'),
              "En el Excel, las fechas son fechas de verdad y los importes tienen formato de euros")
    hoja = wb["Material"]
    filas = [[c.value for c in f] for f in hoja.iter_rows()]
    comprobar(["Fecha", "Tipo", "Material", "Unidades", "Coste (€)", "Dónde"] in [f[:6] for f in filas],
              "La tabla de roturas y pérdidas tiene cabecera")
    hoja = wb["Lista de compra"]
    total = next(f for f in hoja.iter_rows() if f[4].value == "TOTAL pendiente")[5].value
    comprobar(total.startswith("=SUMIF(") and "Pendiente" in total, "El TOTAL de la lista de la compra es solo lo pendiente")
    comprobar(Path(ruta).name.startswith("gestion_catering_"), "El Excel se llama gestion_catering_<fecha>.xlsx")

print("\n--- Fase 3, bloque 5: cálculos y métricas menores ---")
from metricas import rango_desde_periodo  # noqa: E402
dia = date(2026, 8, 20)
comprobar(rango_desde_periodo("últimos 7 días", dia) == (date(2026, 8, 14), dia), "'Últimos 7 días' son 7 días justos (antes 8)")
comprobar(rango_desde_periodo("este mes", dia) == (date(2026, 8, 1), dia)
          and rango_desde_periodo("este trimestre", dia) == (date(2026, 7, 1), dia)
          and rango_desde_periodo("este año", dia) == (date(2026, 1, 1), dia),
          "'Este mes / trimestre / año' empiezan el día 1 (el trimestre, como en el IVA)")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 2, "kg", 2, "Huerta"))
silencio(inv.elaboraciones.nueva_tanda, "Ensalada", 10, 0.5, HOY + timedelta(days=2))
comprobar(abs(inv.valor_total_inventario() - 9) < 1e-9 and inv.valor_tandas() == 5,
          "El valor del inventario incluye las raciones preparadas (4 € de tomate + 5 € de tandas)")

rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1})
silencio(rec.agregar_receta, ensalada)
for preparacion, caducidad, texto in ((HOY, HOY - timedelta(days=1), "una caducidad anterior a la preparación"),
                                      (HOY + timedelta(days=1), None, "una preparación en el futuro")):
    try:
        rec.preparar_elaboracion("Ensalada", 1, inv, None, caducidad, preparacion)
        comprobar(False, f"No se acepta {texto}")
    except ValueError:
        comprobar(abs(inv.buscar_producto("Tomate").stock - 2) < 1e-9, f"No se acepta {texto} (y no se toca nada)")
tanda = inv.elaboraciones.tandas[0]
try:
    inv.elaboraciones.corregir(tanda.id, raciones=3, fecha_caducidad=tanda.fecha_preparacion - timedelta(days=1))
    comprobar(False, "Corregir una tanda no deja una caducidad anterior a la preparación")
except ValueError:
    comprobar(tanda.raciones == 10, "Corregir una tanda no deja una caducidad anterior a la preparación (ni cambia nada)")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 1, "kg", 2, "Huerta", stock_minimo=1,
                                        fecha_caducidad=HOY - timedelta(days=1)))
silencio(inv.entrada_stock, "Tomate", 2, precio_unitario=2, fecha_caducidad=HOY + timedelta(days=2))
rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1})
silencio(rec.agregar_receta, ensalada)
menu = Menu("Menú", [ensalada])
silencio(rec.agregar_menu, menu)
tomate = inv.buscar_producto("Tomate")
comprobar(tomate.stock_bueno == 2 and tomate.dias_para_caducar_bueno() == 2 and menu.ingredientes_en_riesgo(inv) == [tomate],
          "El Recomendador ve el lote bueno a punto de caducar aunque haya otro ya caducado")
comprobar(menu.se_puede_preparar(inv, 20) and not menu.se_puede_preparar(inv, 25),
          "...y no cuenta el stock caducado para decir si se puede preparar (2 kg buenos: 20 sí, 25 no)")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Huevo", "Huevos", 100, "unidades", 0.25, "Granja"))
silencio(inv.agregar_producto, Producto("Jamón", "Charcutería", 2, "kg", 40, "Ibéricos"))
silencio(inv.salida_stock, "Huevo", 24, "consumo", 1)
silencio(inv.salida_stock, "Jamón", 0.5, "consumo", 1)
ranking = Metricas(inv).productos_mas_consumidos(HOY, HOY)
comprobar([f["producto"] for f in ranking] == ["Jamón", "Huevo"] and ranking[0]["valor"] == 20 and ranking[1]["unidad"] == "unidades",
          "El ranking de más consumidos se ordena por valor (0,5 kg de jamón = 20 € antes que 24 huevos = 6 €)")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Azafrán", "Especias", 10, "g", 4.5, "Especias SL"))
compras = GestorCompras()
silencio(compras.agregar_item, ItemCompra("Azafrán", 5, "g", "Especias SL", 0.0125))
with tempfile.TemporaryDirectory() as carpeta:
    ruta = silencio(exportar_todo, inv, RegistroServicios(), compras, carpeta)
    celda = load_workbook(ruta)["Lista de compra"].cell(row=2, column=5)
    comprobar("0.00####" in celda.number_format,
              "En el Excel, un precio por gramo (0,0125 €/g) se ve con sus decimales, no como 0,00 €")

print("\n--- Fase 3, bloque 6: categorías, tipo de producto y consola ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 1, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Pepino", "  verduras ", 1, "kg", 1, "Huerta"))
comprobar(inv.buscar_producto("Pepino").categoria == "Verduras" and inv.categorias() == ["Verduras"],
          "Una categoría igual con otras mayúsculas o espacios se escribe como la que ya existe")
silencio(inv.agregar_producto, Producto("Cebolla", "Hortalizas", 1, "kg", 1, "Huerta"))
silencio(inv.editar_producto, "Cebolla", categoria="VERDURAS")
comprobar(inv.buscar_producto("Cebolla").categoria == "Verduras", "...también al editar un producto")
viejo = inv.to_dict()
viejo["productos"][1]["categoria"] = "verduras  "
comprobar(Inventario.from_dict(viejo).categorias() == ["Verduras"], "Los datos guardados con categorías repetidas se unifican al abrirlos")

rec = Recetario()
silencio(rec.agregar_receta, Receta("Ensalada", "Entrantes", {"Tomate": 0.1}))
silencio(rec.agregar_menu, Menu("Menú", [rec.recetas["Ensalada"]], {"Servilleta": 1}))
comprobar("Ensalada" in (rec.problema_cambio_tipo("Tomate", "consumible") or ""),
          "No se puede pasar a consumible un ingrediente de receta (y dice cuál)")
comprobar("Menú" in (rec.problema_cambio_tipo("Servilleta", "alimento") or ""),
          "No se puede pasar a alimento un consumible de menú (y dice cuál)")
comprobar(rec.problema_cambio_tipo("Pepino", "consumible") is None, "Un producto que no se usa sí puede cambiar de tipo")

sys.path.insert(0, str(RAIZ))
import main as consola  # noqa: E402
for texto in ("nan", "inf", "-inf", "NaN"):
    try:
        consola.a_numero(texto)
        comprobar(False, f"La consola rechaza '{texto}' como número")
    except ValueError:
        pass
comprobar(consola.a_numero("2,5") == 2.5, "La consola rechaza 'nan' e 'inf' como número, y acepta la coma decimal (2,5)")
_entradas = iter(["", "  ", "Tarta"])
consola.input = lambda mensaje="": next(_entradas)
comprobar(silencio(consola.pedir_nombre, "Nombre: ") == "Tarta", "La consola no acepta un nombre vacío (vuelve a preguntar)")
del consola.input

print("\n--- Mejora 1: Dashboard (hoy, pasados sin completar y dinero del mes) ---")
from gastos import resumen_periodo  # noqa: E402
registro = RegistroServicios()
ayer = Servicio(HOY - timedelta(days=1), time(14, 0), 10, "Menú")
hoy_tarde = Servicio(HOY, time(21, 0), 5, "Menú")
hoy_temprano = Servicio(HOY, time(13, 0), 8, "Menú")
cancelado_hoy = Servicio(HOY, time(15, 0), 8, "Menú")
for s_ in (ayer, hoy_tarde, hoy_temprano, cancelado_hoy):
    silencio(registro.agregar_servicio, s_)
silencio(registro.cancelar_servicio, cancelado_hoy.id)
comprobar([s_.id for s_ in registro.servicios_de_hoy()] == [hoy_temprano.id, hoy_tarde.id],
          "Los servicios de hoy, por hora (sin los cancelados)")
comprobar(registro.pasados_sin_completar() == [ayer], "Se detectan los servicios de días pasados sin completar")

inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 0, "kg", 0, "Huerta"))
silencio(inv.entrada_stock, "Tomate", 10, precio_unitario=2, proveedor="Huerta")
rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1})
silencio(rec.agregar_receta, ensalada)
silencio(rec.agregar_menu, Menu("Menú", [ensalada]))
inv.iva_recuperable = False
cobrado = Servicio(HOY, time(14, 0), 10, "Menú", precio_cobrado=100)
sin_cobro = Servicio(HOY, time(20, 0), 10, "Menú")
gastos = RegistroGastos()
for s_ in (cobrado, sin_cobro):
    s_.id = 950 + (s_ is sin_cobro)
    silencio(rec.completar_servicio, s_, inv)
silencio(gastos.agregar_gasto, Gasto("Gasolina", "Transporte", 30, HOY, 950, iva=21))
r = resumen_periodo([cobrado, sin_cobro], inv, rec, gastos, None, HOY.replace(day=1), HOY)
comprobar(r["facturado"] == 100 and r["margen"] == 68 and r["coste"] == 34 and r["servicios"] == 2 and r["sin_cobro"] == 1,
          "Dinero del mes: facturado 100 €, margen 68 € (100 - 2 € de tomate - 30 € de gasolina), 1 servicio sin cobro")
comprobar(r["compras"] == 20 and r["gastos"] == 30, "...y lo gastado en compras (20 €) y en gastos (30 €)")

print("\n--- Mejora 2: lista de la compra (a mano, para qué, bajo mínimo) ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Tomate", "Verduras", 0, "kg", 2, "Huerta"))
silencio(inv.agregar_producto, Producto("Harina", "Panadería", 1, "kg", 1, "Molino", stock_minimo=5))
silencio(inv.agregar_producto, Producto("Servilleta", "Menaje", 10, "unidades", 0.05, "Bazar", tipo="consumible",
                                        stock_minimo=100))
rec = Recetario()
ensalada = Receta("Ensalada", "Entrantes", {"Tomate": 0.1})
silencio(rec.agregar_receta, ensalada)
silencio(rec.agregar_menu, Menu("Menú", [ensalada]))
s1 = Servicio(HOY + timedelta(days=1), time(14, 0), 10, "Menú")
s1.id = 961
s2 = Servicio(HOY + timedelta(days=2), time(14, 0), 20, "Menú")
s2.id = 962
compras = GestorCompras()
avisos = silencio(compras.generar_lista_desde_servicios, [s1, s2], rec, inv)
tomate = compras.pendiente_de("Tomate")
comprobar(tomate.cantidad == 3 and tomate.para == [961, 962] and "#961" in tomate.motivo(),
          "Cada artículo dice para qué servicios es (tomate: #961 y #962)")
harina, servilleta = compras.pendiente_de("Harina"), compras.pendiente_de("Servilleta")
comprobar(harina is not None and harina.cantidad == 4 and harina.bajo_minimo and servilleta.cantidad == 90
          and "bajo mínimo" in servilleta.motivo() and any("Harina" in a and "mínimo" in a for a in avisos),
          "Se proponen también los alimentos y consumibles bajo mínimo (harina 4 kg, servilletas 90)")
silencio(compras.agregar_a_mano, "Papel de horno", 2, "unidades", "Bazar")
silencio(compras.agregar_a_mano, "Tomate", 1, "kg", "Huerta")
comprobar(compras.pendiente_de("Papel de horno").cantidad == 2 and compras.pendiente_de("Tomate").cantidad == 4,
          "Se puede añadir a mano algo nuevo o sumar a lo que ya está pendiente")
silencio(compras.generar_lista_desde_servicios, [s1], rec, inv)
comprobar(compras.pendiente_de("Tomate").cantidad == 2 and compras.pendiente_de("Papel de horno").cantidad == 2,
          "Al volver a generar la lista, lo añadido a mano se respeta (tomate 1 de #961 + 1 a mano; papel de horno)")
silencio(compras.generar_lista_desde_servicios, [], rec, inv)
comprobar(compras.pendiente_de("Tomate").cantidad == 1 and compras.pendiente_de("Tomate").para == [],
          "Si ya ningún servicio lo pide, se queda lo añadido a mano")
compras.cambiar_cantidad("Harina", 10)
compras.quitar_pendiente("Servilleta")
comprobar(compras.pendiente_de("Harina").cantidad == 10 and compras.pendiente_de("Servilleta") is None,
          "Se puede cambiar la cantidad de un artículo o quitarlo de la lista")
copia = GestorCompras.from_dict(compras.to_dict())
comprobar(copia.pendiente_de("Tomate").a_mano == 1 and copia.pendiente_de("Harina").bajo_minimo,
          "Para qué es cada cosa y lo añadido a mano se guardan y se cargan")

print("\n--- Mejora 3: caducidad al comprar y vida útil 'el mismo día' ---")
inv = Inventario()
silencio(inv.agregar_producto, Producto("Pescado", "Pescado", 0, "kg", 0, "Lonja"))
pescado = inv.buscar_producto("Pescado")
comprobar(pescado.caducidad_propuesta_compra(HOY) == HOY + timedelta(days=7),
          "Sin compras anteriores con caducidad, se proponen 7 días")
lote = silencio(inv.entrada_stock, "Pescado", 2, precio_unitario=10, fecha_caducidad=HOY + timedelta(days=3))
lote.fecha_entrada = HOY - timedelta(days=10)
lote.fecha_caducidad = HOY - timedelta(days=7)
comprobar(pescado.caducidad_propuesta_compra(HOY) == HOY + timedelta(days=3),
          "Si no, se propone lo que duró la última compra (3 días)")
mismo_dia = Receta("Tartar", "Entrantes", {"Pescado": 0.1}, vida_util_dias=0)
comprobar(mismo_dia.caducidad_propuesta(HOY) == HOY and Receta.from_dict(mismo_dia.to_dict()).vida_util_dias == 0,
          "Vida útil 0 = se toma el mismo día (y se guarda como 0, no como 'sin indicar')")

print()
if fallos:
    print(f"RESULTADO: {len(fallos)} FALLO(S)")
    sys.exit(1)
print("RESULTADO: TODO BIEN")
