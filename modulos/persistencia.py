"""
Módulo: persistencia.py
--------------------------
Guarda y carga el estado completo de la aplicación (inventario,
servicios, recetario y compras) en un único archivo JSON, para que
los datos no se pierdan al cerrar el programa.

Se apoya en los métodos to_dict()/from_dict() que hemos añadido a cada
clase en su propio módulo — este archivo solo los combina.

Conceptos de Python nuevos en este módulo:
- El módulo `json` de la librería estándar (json.dump / json.load)
- Trabajar con archivos usando `with open(...) as f:` (se cierran
  solos automáticamente, incluso si algo falla a mitad de la lectura)
"""

import json
from pathlib import Path
from typing import Optional

from inventario import Inventario
from servicios import RegistroServicios
from recetario import Recetario
from compras import GestorCompras
from metricas import ArchivoInformes


def guardar_sesion(
    inventario: Inventario,
    registro_servicios: RegistroServicios,
    recetario: Recetario,
    gestor_compras: GestorCompras,
    archivo_informes: ArchivoInformes,
    ruta: str,
) -> None:
    """Guarda el estado completo de los 5 módulos en un archivo JSON."""
    datos = {
        "inventario": inventario.to_dict(),
        "servicios": registro_servicios.to_dict(),
        "recetario": recetario.to_dict(),
        "compras": gestor_compras.to_dict(),
        "informes": archivo_informes.to_dict(),
    }

    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        # indent=2 -> el JSON queda legible para humanos, no en una sola línea
        # ensure_ascii=False -> conserva tildes y eñes tal cual, en vez de \u00e9...
        json.dump(datos, f, indent=2, ensure_ascii=False)

    print(f"💾 Sesión guardada en {ruta}")


def cargar_sesion(
    ruta: str,
) -> Optional[tuple[Inventario, RegistroServicios, Recetario, GestorCompras, ArchivoInformes]]:
    """
    Carga una sesión guardada previamente. Devuelve None si el archivo
    no existe todavía (por ejemplo, la primera vez que se usa la app).
    """
    if not Path(ruta).exists():
        print("No hay ninguna sesión guardada todavía.")
        return None

    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)

    inventario = Inventario.from_dict(datos["inventario"])
    registro_servicios = RegistroServicios.from_dict(datos["servicios"])
    recetario = Recetario.from_dict(datos["recetario"])
    gestor_compras = GestorCompras.from_dict(datos["compras"])
    # .get(..., {"informes": []}): compatibilidad con sesiones guardadas
    # ANTES de que existieran los informes mensuales.
    archivo_informes = ArchivoInformes.from_dict(datos.get("informes", {"informes": []}))

    print(f"📂 Sesión cargada desde {ruta}")
    return inventario, registro_servicios, recetario, gestor_compras, archivo_informes


if __name__ == "__main__":
    from datetime import date, time
    from inventario import Producto
    from servicios import Servicio
    from recetario import Receta, Menu
    from compras import ItemCompra

    # --- Construimos un estado de ejemplo con datos en los 4 módulos ---
    inventario = Inventario()
    inventario.agregar_producto(Producto(
        "Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2
    ))
    inventario.agregar_producto(Producto(
        "Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2,
        fecha_caducidad=date(2026, 9, 1),
    ))

    registro = RegistroServicios()
    registro.agregar_servicio(Servicio(date(2026, 9, 2), time(21, 0), 8, "Menú del día"))

    pan_casero = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15})
    recetario = Recetario()
    recetario.agregar_receta(pan_casero)
    recetario.agregar_menu(Menu("Menú del día", [pan_casero]))

    gestor = GestorCompras()
    item = ItemCompra("Harina de trigo", 1.4, "kg", "Harinas del Sur", 1.2)
    item.marcar_comprado()  # probamos que este estado también sobrevive al guardado
    gestor.agregar_item(item)

    archivo_informes = ArchivoInformes()
    archivo_informes.generar_informe(inventario, 2026, 8)

    ruta_prueba = "sesion_prueba.json"

    print("\n--- Guardando sesión de ejemplo ---")
    guardar_sesion(inventario, registro, recetario, gestor, archivo_informes, ruta_prueba)

    print("\n--- Cargando esa misma sesión en objetos NUEVOS ---")
    resultado = cargar_sesion(ruta_prueba)
    inventario2, registro2, recetario2, gestor2, archivo_informes2 = resultado

    print("\n--- Comprobación: ¿coincide todo con el original? ---")
    print("Inventario cargado:")
    inventario2.listar_todos()
    print(f"¿Tomate próximo a caducar detectado? {len(inventario2.productos_proximos_a_caducar()) == 1}")

    print("\nServicios cargados:")
    registro2.listar_todos()
    print(f"¿El próximo servicio creado tendría id 2 (no repetiría el 1)? {Servicio._siguiente_id == 2}")

    print("\nRecetario cargado:")
    for m in recetario2.menus.values():
        print(m)
        for r in m.recetas:
            print(f"  -> {r}")

    print("\nCompras cargadas:")
    for i in gestor2.items:
        print(i)
    print(f"¿Se conservó que ya estaba comprado? {gestor2.items[0].comprado is True}")

    print("\nInformes mensuales cargados:")
    for informe in archivo_informes2.listar_informes():
        print(informe)
