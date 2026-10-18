"""
Genera pruebas/datos_guardados/sesion_v2.json: unos datos guardados con la
versión 2 del formato (con sobrantes, antes del valor de los subproductos de
limpieza; commit 9a19e0b... 18/10/2026). Igual que sesion_v1 más sobrantes
apuntados (uno de ellos anulado).

Se ejecutó UNA VEZ con esa versión y el archivo resultante se guarda tal cual
en el repositorio. NO hay que volver a generarlo: su gracia es que sea una foto
de datos "antiguos". La prueba de compatibilidad (probar_logica.py) comprueba
que cada versión nueva del programa los sigue abriendo sin perder nada.

Usa casi todo lo que el programa sabía guardar: productos de los tres tipos,
lotes, compras, limpiezas, bases, tandas, recetas, menús, servicios (pendiente,
completado, cancelado), gastos, material, lista de la compra, informes y notas.
"""

import sys
from datetime import date, time, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "modulos"))

from inventario import Inventario, Producto  # noqa: E402
from servicios import RegistroServicios, Servicio  # noqa: E402
from recetario import Recetario, Receta, Menu  # noqa: E402
from compras import GestorCompras  # noqa: E402
from metricas import ArchivoInformes  # noqa: E402
from gastos import RegistroGastos, Gasto, NOTA_COSTE_AL_COMPLETAR  # noqa: E402
from materiales import RegistroMaterial, Material  # noqa: E402
from persistencia import sesion_a_dict, texto_json  # noqa: E402

HOY = date.today()
inv = Inventario()
serv = RegistroServicios()
rec = Recetario()
comp = GestorCompras()
informes = ArchivoInformes()
gastos = RegistroGastos()
mat = RegistroMaterial()

# --- Productos y compras ---
inv.agregar_producto(Producto("Harina de trigo", "Panadería", 10, "kg", 1.2, "Harinas del Sur", stock_minimo=2, iva=4))
inv.agregar_producto(Producto("Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5, iva=10))
inv.agregar_producto(Producto("Tomate", "Verduras", 6, "kg", 2.1, "Huerta Local", stock_minimo=2,
                              fecha_caducidad=HOY + timedelta(days=6), iva=4))
inv.entrada_stock("Tomate", 4, precio_unitario=2.3, proveedor="Frutas Paco", fecha_caducidad=HOY + timedelta(days=9))
inv.agregar_producto(Producto("Salmón", "Pescados", 5, "kg", 18, "Pescados Mar", stock_minimo=1,
                              fecha_caducidad=HOY + timedelta(days=3), iva=10))
inv.agregar_producto(Producto("Pata de cerdo", "Carnes", 2, "unidades", 45, "Carnicería Pepe", tiene_merma=True,
                              peso_unitario=7))
inv.limpiar_producto("Pata de cerdo", 1, "Carne de pata limpia", 4.5, {"Hueso de pata": 1.5})
inv.agregar_producto(Producto("Servilletas de papel", "Desechables", 500, "unidades", 0.02, "Hostelería Total",
                              stock_minimo=200, tipo="consumible"))
inv.agregar_producto(Producto("Lejía", "Limpieza", 4, "litros", 1.1, "Droguería Central", stock_minimo=2,
                              tipo="mantenimiento"))
inv.agregar_producto(Producto("Cebolla dulce", "Verduras", 5, "kg", 1.3, "Huerta Local",
                              fecha_caducidad=HOY + timedelta(days=12)))
inv.definir_base("Sofrito", "Elaboraciones", "kg", 1, {"Cebolla dulce": 1.5, "Tomate": 0.5}, vida_util_dias=4,
                 notas="Pochar a fuego lento.")
rec.preparar_base("Sofrito", 1, 0.9, inv)
# Un lote caducado desechado (desperdicio) y una salida a mano de lejía.
inv.agregar_producto(Producto("Nata", "Lácteos", 1, "litros", 3, "Lácteos Norte", fecha_caducidad=HOY - timedelta(days=2)))
inv.desechar_lote("Nata", 1)
inv.salida_stock("Lejía", 0.5, "consumo", 1)

# --- Recetas, menús y tandas ---
pan = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005}, vida_util_dias=3)
salmon = Receta("Salmón al horno", "Principal", {"Salmón": 0.2, "Sofrito": 0.03}, vida_util_dias=1)
for r in (pan, ensalada, salmon):
    rec.agregar_receta(r)
ensalada.poner_nota("Aliñar justo antes de servir.")
for nombre, cat, uds, precio in (("Plato llano", "Vajilla", 60, 3.5), ("Copa de vino", "Cristalería", 48, 2.8)):
    mat.agregar_material(Material(nombre, cat, uds, precio, "Hostelería Total"))
rec.agregar_menu(Menu("Menú boda", [pan, ensalada, salmon], {"Servilletas de papel": 2},
                      {"Plato llano": 2, "Copa de vino": 1}))
rec.agregar_menu(Menu("Menú del día", [pan, ensalada], {"Servilletas de papel": 1}))
rec.preparar_elaboracion("Ensalada de tomate", 10, inv, fecha_caducidad=HOY + timedelta(days=2))
rec.preparar_elaboracion("Pan casero", 4, inv)

# --- Servicios ---
boda = Servicio(HOY, time(14, 0), 12, "Menú boda", precio_cobrado=900, cliente="Familia García", lugar="Finca El Olivo")
dia = Servicio(HOY + timedelta(days=5), time(21, 0), 8, "Menú del día", precio_cobrado=240)
anulado = Servicio(HOY + timedelta(days=7), time(13, 0), 20, "Menú boda")
for s in (boda, dia, anulado):
    serv.agregar_servicio(s)
anulado.cancelar()
mat.registrar_salida(boda.id, {"Plato llano": 24, "Copa de vino": 12})
plan = rec.plan_elaboraciones(boda, inv)
rec.completar_servicio(boda, inv, plan_elaboraciones={r: [t for t, _ in p["reparto"]] for r, p in plan.items()})
mat.registrar_vuelta(boda.id, {"Plato llano": 22}, {"Plato llano": 2})
boda.valoracion = "Todo bien; sobró bastante salmón."
inv.salida_stock("Lejía", 0.3, "consumo", 1, servicio_id=boda.id)
inv.compra_para_servicio("Tomate", 2, 1, 5, boda.id, proveedor="Súper de guardia")
gastos.agregar_gasto(Gasto("Gasolina", "Transporte", 30, servicio_id=boda.id, iva=21))
gastos.agregar_gasto(Gasto("Camarero extra", "Personal extra", 120, servicio_id=boda.id, iva=0,
                           notas=NOTA_COSTE_AL_COMPLETAR))
gastos.agregar_gasto(Gasto("Seguro furgoneta", "Seguros e impuestos", 60))

# Una tanda que se queda con raciones.
rec.preparar_elaboracion("Ensalada de tomate", 5, inv, fecha_caducidad=HOY + timedelta(days=2))

# --- Lista de la compra e informes ---
comp.generar_lista_desde_servicios(serv.servicios_proximos(10), rec, inv)
comp.agregar_a_mano("Papel de horno", 2, "unidades", "Hostelería Total", 1.5)
if comp.items:
    comp.items[0].marcar_comprado()
informes.generar_informe(inv, HOY.year, HOY.month)

# --- Sobrantes (formato 2) ---
import sobrantes  # noqa: E402
sobrantes.registrar(boda, inv, {"Salmón": 1}, {"Ensalada de tomate": 2})
sobrantes.registrar(boda, inv, {"Servilletas de papel": 5})
sobrantes.anular(inv, sobrantes.salidas_sobrante(inv, boda.id)[-1])

datos = sesion_a_dict(inv, serv, rec, comp, informes, gastos, mat)
assert datos["version_datos"] == 2
destino = Path(__file__).with_name("sesion_v2.json")
destino.write_text(texto_json(datos), encoding="utf-8")
print(f"Guardado {destino}")
