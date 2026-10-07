"""
Módulo: persistencia.py
--------------------------
Guarda y carga el estado completo de la aplicación (inventario,
servicios, recetario, compras, informes, gastos y material) en un único archivo
JSON, para que los datos no se pierdan al cerrar el programa.

Se apoya en los métodos to_dict()/from_dict() que hemos añadido a cada
clase en su propio módulo — este archivo solo los combina.

Conceptos de Python nuevos en este módulo:
- El módulo `json` de la librería estándar (json.dump / json.load)
- Trabajar con archivos usando `with open(...) as f:` (se cierran
  solos automáticamente, incluso si algo falla a mitad de la lectura)
"""

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from inventario import Inventario
from servicios import RegistroServicios
from recetario import Recetario
from compras import GestorCompras
from metricas import ArchivoInformes
from gastos import RegistroGastos
from materiales import RegistroMaterial


@dataclass
class Sesion:
    """
    Todo lo que se guarda en una sesión, junto. Un @dataclass es una clase
    "de datos": Python le escribe solo el __init__ a partir de los campos
    de abajo. Así, al añadir algo nuevo (como los gastos) basta con añadir
    un campo, en vez de cambiar el orden de una tupla en todos los sitios.
    """
    inventario: Inventario
    registro_servicios: RegistroServicios
    recetario: Recetario
    gestor_compras: GestorCompras
    archivo_informes: ArchivoInformes
    registro_gastos: RegistroGastos = field(default_factory=RegistroGastos)
    registro_material: RegistroMaterial = field(default_factory=RegistroMaterial)


# ---------- Dónde se guardan los datos ----------

NOMBRE_CARPETA_WINDOWS = "GestionRestaurante"
COPIAS_A_CONSERVAR = 30  # copias diarias (una por día con cambios)


def carpeta_datos(carpeta_programa: Path) -> Path:
    """
    La carpeta donde viven los datos (sesión, copias, excels).

    - Variable de entorno GESTION_RESTAURANTE_DATOS: esa carpeta (pruebas).
    - Programa empaquetado (.exe) en Windows: %LOCALAPPDATA%\\GestionRestaurante.
      NO junto al .exe: si el .exe se abre desde dentro del ZIP o se mueve
      de carpeta, los datos se quedarían atrás. Si ya había datos junto al
      .exe (versiones anteriores), se copian aquí la primera vez.
    - Resto (python / streamlit run): carpeta_programa/datos, como siempre.
    """
    forzada = os.environ.get("GESTION_RESTAURANTE_DATOS")
    if forzada:
        return Path(forzada)
    if getattr(sys, "frozen", False) and os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        destino = Path(os.environ["LOCALAPPDATA"]) / NOMBRE_CARPETA_WINDOWS
        antigua = carpeta_programa / "datos"
        if (antigua / "sesion.json").exists() and not (destino / "sesion.json").exists():
            destino.mkdir(parents=True, exist_ok=True)
            for archivo in antigua.iterdir():
                if archivo.is_file():
                    shutil.copy2(archivo, destino / archivo.name)
        return destino
    return carpeta_programa / "datos"


# ---------- Guardar ----------

def sesion_a_dict(
    inventario: Inventario,
    registro_servicios: RegistroServicios,
    recetario: Recetario,
    gestor_compras: GestorCompras,
    archivo_informes: ArchivoInformes,
    registro_gastos: Optional[RegistroGastos] = None,
    registro_material: Optional[RegistroMaterial] = None,
) -> dict:
    """Todo el estado de la aplicación, como diccionario listo para JSON."""
    return {
        "inventario": inventario.to_dict(),
        "servicios": registro_servicios.to_dict(),
        "recetario": recetario.to_dict(),
        "compras": gestor_compras.to_dict(),
        "informes": archivo_informes.to_dict(),
        "gastos": (registro_gastos or RegistroGastos()).to_dict(),
        "material": (registro_material or RegistroMaterial()).to_dict(),
    }


def texto_json(datos: dict) -> str:
    # indent=2 -> legible para humanos; ensure_ascii=False -> conserva tildes y eñes.
    return json.dumps(datos, indent=2, ensure_ascii=False)


def firma(datos: dict) -> str:
    """Una "huella" corta del contenido: si no cambia, no hace falta volver a guardar."""
    return hashlib.sha256(texto_json(datos).encode("utf-8")).hexdigest()


def escribir_sesion(datos: dict, ruta: str) -> None:
    """
    Escribe la sesión de forma SEGURA:
    1. Se escribe primero en un archivo temporal y, solo cuando está
       completo, sustituye al bueno (os.replace es instantáneo). Si algo
       falla a mitad (corte de luz, disco lleno...), el archivo bueno sigue intacto.
    2. Antes, la versión anterior se guarda como sesion.json.bak.
    3. Una vez al día se deja una copia con fecha en copias/ (se conservan
       las COPIAS_A_CONSERVAR más recientes).
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        f.write(texto_json(datos))
        f.flush()
        os.fsync(f.fileno())
    if ruta.exists():
        try:
            shutil.copy2(ruta, ruta.with_name(ruta.name + ".bak"))
        except OSError as error:
            print(f"⚠️  No se ha podido hacer la copia .bak: {error}")
    os.replace(temporal, ruta)  # a partir de aquí, lo importante ya está guardado

    # Las copias son un extra: si fallan (archivo bloqueado...), el guardado sigue siendo bueno.
    try:
        copias = ruta.parent / "copias"
        copias.mkdir(exist_ok=True)
        copia_hoy = copias / f"sesion_{date.today().isoformat()}.json"
        shutil.copy2(ruta, copia_hoy)  # la de hoy se va actualizando: queda la última del día
        for vieja in sorted(copias.glob("sesion_*.json"))[:-COPIAS_A_CONSERVAR]:
            vieja.unlink(missing_ok=True)
    except OSError as error:
        print(f"⚠️  No se ha podido hacer la copia de seguridad del día: {error}")


def copia_antes_de_empezar_de_cero(datos: dict, ruta: str) -> Path:
    """
    Antes de borrar todos los datos ("Empezar de cero"), los guarda en
    copias/antes_de_empezar_de_cero_<fecha y hora>.json. Esta copia no entra
    en la rotación de las copias diarias: no se borra sola. Si no se puede
    escribir, lanza OSError (y entonces NO se debe borrar nada).
    """
    copias = Path(ruta).parent / "copias"
    copias.mkdir(parents=True, exist_ok=True)
    destino = copias / f"antes_de_empezar_de_cero_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto_json(datos))
        f.flush()
        os.fsync(f.fileno())
    return destino


def sesion_vacia(ajustes_de: Optional[Inventario] = None) -> Sesion:
    """Una sesión sin datos. Con `ajustes_de`, conserva los Ajustes (IVA) de ese inventario."""
    inventario = Inventario()
    if ajustes_de is not None:
        inventario.iva_recuperable = ajustes_de.iva_recuperable
        inventario.iva_cobro = ajustes_de.iva_cobro
    return Sesion(inventario, RegistroServicios(), Recetario(), GestorCompras(), ArchivoInformes())


def guardar_sesion(
    inventario: Inventario,
    registro_servicios: RegistroServicios,
    recetario: Recetario,
    gestor_compras: GestorCompras,
    archivo_informes: ArchivoInformes,
    ruta: str,
    registro_gastos: Optional[RegistroGastos] = None,
    registro_material: Optional[RegistroMaterial] = None,
) -> None:
    """Guarda el estado completo de todos los módulos en un archivo JSON (de forma segura)."""
    datos = sesion_a_dict(inventario, registro_servicios, recetario, gestor_compras, archivo_informes,
                          registro_gastos, registro_material)
    escribir_sesion(datos, ruta)
    print(f"💾 Sesión guardada en {ruta}")


# ---------- Cargar ----------

class SesionIlegible(Exception):
    """
    El archivo de datos se puede leer (no está roto), pero el programa no sabe
    interpretar su contenido (un dato que no pasa una comprobación, un fallo
    del programa...). En ese caso NO se aparta ni se sobrescribe nada: hay que
    revisarlo. El mensaje explica qué hacer.
    """


def _leer_json(ruta: Path) -> dict:
    # utf-8-sig: acepta también archivos guardados con BOM (Bloc de notas antiguo).
    with open(ruta, encoding="utf-8-sig") as f:
        return json.load(f)


def cargar_sesion_segura(ruta: str) -> tuple[Optional[Sesion], Optional[str]]:
    """
    Carga la sesión. Si el archivo está ROTO (no es un JSON completo: un
    corte a mitad, un disco dañado...), prueba con las copias de seguridad
    (sesion.json.bak y las diarias), de la más reciente a la más antigua, y
    aparta el roto (no lo borra). Devuelve (sesión o None, aviso o None).

    Si el archivo se lee bien pero su contenido no se puede interpretar,
    lanza SesionIlegible y NO toca nada (así el programa no arranca vacío
    encima de los datos buenos).
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return None, None
    try:
        _leer_json(ruta)
    except (ValueError, UnicodeDecodeError) as error:  # JSON roto
        print(f"❌ {ruta} está dañado: {error!r}")
    else:
        try:
            return cargar_sesion(str(ruta)), None
        except Exception as error:  # noqa: BLE001
            raise SesionIlegible(
                f"No se han podido abrir los datos guardados ({type(error).__name__}: {error}). No se ha tocado "
                f"nada: el archivo sigue en {ruta}. Cierra el programa y avisa a quien te lo instaló, con este "
                f"mensaje. Las copias de seguridad están en la carpeta «copias» de ese mismo sitio."
            ) from error
    apartado = ruta.with_name(f"sesion_danada_{datetime.now():%Y-%m-%d_%H%M%S}.json")
    shutil.move(str(ruta), apartado)
    candidatas = [ruta.with_name(ruta.name + ".bak"), *(ruta.parent / "copias").glob("sesion_*.json")]
    candidatas = sorted((c for c in candidatas if c.exists()), key=lambda c: c.stat().st_mtime, reverse=True)
    for copia in candidatas:
        try:
            sesion = cargar_sesion(str(copia))
        except Exception:  # noqa: BLE001
            continue
        shutil.copy2(copia, ruta)
        return sesion, (
            f"Los datos guardados estaban dañados y se han recuperado de la copia de seguridad «{copia.name}». "
            f"Revisa que esté todo: puede faltar lo último que hiciste. El archivo dañado se ha apartado como "
            f"«{apartado.name}»."
        )
    return None, (
        f"Los datos guardados estaban dañados y no había ninguna copia de seguridad válida. El programa empieza "
        f"vacío. El archivo dañado se ha apartado como «{apartado.name}» en {ruta.parent}: no lo borres."
    )


def cargar_sesion(ruta: str) -> Optional[Sesion]:
    """
    Carga una sesión guardada previamente. Devuelve None si el archivo
    no existe todavía (por ejemplo, la primera vez que se usa la app).
    Si el archivo está dañado, lanza la excepción (ver cargar_sesion_segura).
    """
    if not Path(ruta).exists():
        print("No hay ninguna sesión guardada todavía.")
        return None

    datos = _leer_json(Path(ruta))

    inventario = Inventario.from_dict(datos["inventario"])
    registro_servicios = RegistroServicios.from_dict(datos["servicios"])
    recetario = Recetario.from_dict(datos["recetario"])
    gestor_compras = GestorCompras.from_dict(datos["compras"])
    # .get(..., {"informes": []}): compatibilidad con sesiones guardadas
    # ANTES de que existieran los informes mensuales.
    archivo_informes = ArchivoInformes.from_dict(datos.get("informes", {"informes": []}))

    # Las sesiones guardadas antes de existir los gastos no los tienen.
    registro_gastos = RegistroGastos.from_dict(datos.get("gastos", {"gastos": []}))
    registro_material = RegistroMaterial.from_dict(datos.get("material", {}))

    print(f"📂 Sesión cargada desde {ruta}")
    return Sesion(
        inventario, registro_servicios, recetario, gestor_compras, archivo_informes, registro_gastos, registro_material,
    )


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
    sesion = cargar_sesion(ruta_prueba)
    inventario2, registro2, recetario2 = sesion.inventario, sesion.registro_servicios, sesion.recetario
    gestor2, archivo_informes2 = sesion.gestor_compras, sesion.archivo_informes

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
