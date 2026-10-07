"""
pruebas/probar_exe.py
-----------------------
Prueba el .exe YA CONSTRUIDO, tal y como lo usaría el cliente, en la
máquina Windows de GitHub Actions (ver .github/workflows/build-windows.yml).

Las otras pruebas (probar_interfaz.py, capturas.py) usan el código fuente
en Linux. Esta comprueba el archivo que de verdad se entrega: que
PyInstaller ha metido dentro todo lo necesario y que el programa funciona
empaquetado. En concreto:

  1. El .exe arranca y la app responde en el navegador.
  2. Todas las páginas se abren sin errores (con datos de ejemplo).
  3. Los cambios se guardan SOLOS en %LOCALAPPDATA%\\GestionRestaurante
     (no junto al .exe: así no se pierden si el .exe se abre desde el ZIP o
     se mueve). En la prueba, LOCALAPPDATA apunta a una carpeta temporal.
  4. "Generar Excel" crea el .xlsx en esa misma carpeta de datos.
  5. Las librerías de Google Drive están dentro del .exe: al pulsar
     "Subir a Google Drive" sin credentials.json debe pedir ese archivo
     (junto al .exe), y NO decir que faltan librerías.
  6. Si se vuelve a abrir el .exe con el programa ya abierto, no arranca otro:
     se cierra solo enseguida (solo abre el navegador).
  7. Al cerrar y volver a abrir el .exe, los datos guardados siguen ahí.

Uso:  python pruebas/probar_exe.py dist/GestionRestaurante.exe
Deja el informe en resultados/resultado_exe.txt y capturas en
resultados/capturas_exe/.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8501"
RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "resultados"
CAPTURAS = RESULTADOS / "capturas_exe"
PAGINAS = ["Dashboard", "Inventario", "Servicios", "Historial", "Recetario", "Compras", "Gastos", "Métricas", "Exportar / Backup", "Ajustes"]

lineas: list[str] = []
fallos = 0


def comprobar(condicion: bool, descripcion: str, detalle: str = "") -> bool:
    global fallos
    if condicion:
        lineas.append(f"✅ {descripcion}")
    else:
        fallos += 1
        lineas.append(f"❌ {descripcion}" + (f" -- {detalle}" if detalle else ""))
    print(lineas[-1], flush=True)
    return condicion


LOCALAPPDATA_PRUEBA = Path(tempfile.mkdtemp(prefix="localappdata_"))


def arrancar_exe(exe: Path, log: Path) -> subprocess.Popen:
    # Se ejecuta desde SU carpeta, como cuando el cliente hace doble clic.
    # LOCALAPPDATA apunta a una carpeta temporal: así la prueba no toca nada
    # del ordenador y se sabe exactamente dónde deben aparecer los datos.
    salida = open(log, "a", encoding="utf-8", errors="replace")
    entorno = {**os.environ, "LOCALAPPDATA": str(LOCALAPPDATA_PRUEBA)}
    return subprocess.Popen([str(exe)], cwd=exe.parent, stdout=salida, stderr=subprocess.STDOUT, env=entorno)


def esperar_servidor(proceso: subprocess.Popen, segundos: int = 180) -> bool:
    """El .exe de un solo archivo tarda en arrancar: primero se descomprime."""
    limite = time.time() + segundos
    while time.time() < limite:
        if proceso.poll() is not None:
            return False  # el programa se ha cerrado solo: ha fallado
        try:
            with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
                if r.read().decode().strip() == "ok":
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def cerrar_exe(proceso: subprocess.Popen) -> None:
    # /T cierra también el proceso "hijo" que crea el .exe de un solo archivo.
    subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"], capture_output=True)
    try:
        proceso.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(3)  # que Windows suelte el puerto y los archivos


def esperar(page) -> None:
    """Espera a que Streamlit termine de ejecutar el script tras un clic."""
    page.wait_for_timeout(800)
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=20000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(700)


def errores_en_pantalla(page) -> str:
    """Texto de los errores de Python que Streamlit muestra en rojo, si hay."""
    cajas = page.locator('[data-testid="stException"]')
    return " | ".join(cajas.nth(i).inner_text()[:300] for i in range(cajas.count()))


def abrir_app(navegador):
    page = navegador.new_page(viewport={"width": 1440, "height": 2000})
    page.goto(URL)
    page.wait_for_selector('[data-testid="stSidebar"]', timeout=90000)
    esperar(page)
    return page


def ir_a(page, pagina: str) -> None:
    page.locator('[data-testid="stSidebar"]').get_by_text(pagina, exact=True).click()
    esperar(page)


def captura(page, nombre: str) -> None:
    page.screenshot(path=str(CAPTURAS / f"{nombre}.png"), full_page=True)


def probar(exe_original: Path) -> None:
    # Copiamos el .exe a una carpeta vacía: así comprobamos que crea sus
    # propios archivos (datos/...) a su lado y no depende del repositorio.
    carpeta = Path(tempfile.mkdtemp(prefix="cliente_"))
    exe = carpeta / exe_original.name
    shutil.copy2(exe_original, exe)
    log = RESULTADOS / "exe_consola.log"
    datos = LOCALAPPDATA_PRUEBA / "GestionRestaurante"

    # --- Primer arranque ---
    proceso = arrancar_exe(exe, log)
    inicio = time.time()
    if not comprobar(esperar_servidor(proceso), "El .exe arranca y la app responde",
                     "revisa exe_consola.log"):
        cerrar_exe(proceso)
        return
    lineas.append(f"   (tardó {time.time() - inicio:.0f} s en arrancar)")

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            page = abrir_app(navegador)
            comprobar(not errores_en_pantalla(page), "La página inicial se abre sin errores",
                      errores_en_pantalla(page))

            page.get_by_role("button", name="🧪 Cargar datos de ejemplo").click()
            esperar(page)

            for numero, pagina in enumerate(PAGINAS, start=1):
                try:
                    ir_a(page, pagina)
                    captura(page, f"{numero:02d}_{pagina.split()[0].lower()}")
                    error = errores_en_pantalla(page)
                    comprobar(not error, f"Página '{pagina}' sin errores", error)
                except Exception as e:  # noqa: BLE001
                    comprobar(False, f"Página '{pagina}' se puede abrir", str(e)[:300])

            # Guardado automático -> sesion.json en %LOCALAPPDATA%\\GestionRestaurante
            comprobar((datos / "sesion.json").exists() and not (carpeta / "datos" / "sesion.json").exists(),
                      "Los cambios se guardan solos en %LOCALAPPDATA%\\GestionRestaurante (no junto al .exe)")
            comprobar(any((datos / "copias").glob("sesion_*.json")), "Se crea la copia de seguridad del día")

            # Volver a abrir el .exe con el programa abierto: la segunda copia se cierra sola
            segunda = arrancar_exe(exe, log)
            try:
                segunda.wait(timeout=90)
                comprobar(segunda.returncode == 0, "Abrirlo otra vez no arranca un segundo programa (se cierra solo)")
            except subprocess.TimeoutExpired:
                comprobar(False, "Abrirlo otra vez no arranca un segundo programa (se cierra solo)",
                          "la segunda copia sigue abierta")
                cerrar_exe(segunda)

            # Exportar a Excel -> .xlsx junto al .exe
            ir_a(page, "Exportar / Backup")
            page.get_by_role("button", name="Generar Excel").click()
            esperar(page)
            excels = list(datos.glob("*.xlsx")) if datos.exists() else []
            comprobar(bool(excels), "'Generar Excel' crea el .xlsx en la carpeta de datos")

            # Google Drive sin credentials.json: debe pedir el archivo
            page.get_by_role("button", name="Subir a Google Drive").click()
            esperar(page)
            captura(page, "08_drive_sin_credenciales")
            avisos = " ".join(page.locator('[data-testid="stAlert"]').all_inner_texts())
            comprobar("Faltan librerías" not in avisos,
                      "Las librerías de Google Drive están dentro del .exe", avisos[:300])
            comprobar("credentials.json" in avisos and carpeta.name in avisos,
                      "Sin credenciales, pide credentials.json en la carpeta del .exe", avisos[:300])

            navegador.close()
    finally:
        cerrar_exe(proceso)

    # --- Segundo arranque: ¿siguen ahí los datos? ---
    proceso = arrancar_exe(exe, log)
    try:
        if not comprobar(esperar_servidor(proceso), "El .exe vuelve a arrancar tras cerrarlo"):
            return
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            page = abrir_app(navegador)
            ir_a(page, "Inventario")
            captura(page, "09_inventario_tras_reabrir")
            # La tabla se dibuja como imagen (su texto no se puede leer), así
            # que miramos el aviso de "Bajo mínimo", que sí es texto y solo
            # aparece si se han cargado los productos guardados.
            avisos = " ".join(page.locator('[data-testid="stAlert"]').all_inner_texts())
            comprobar("Harina de trigo" in avisos,
                      "Al reabrir, los datos guardados siguen ahí", avisos[:300])
            navegador.close()
    finally:
        cerrar_exe(proceso)
        shutil.rmtree(carpeta, ignore_errors=True)
        shutil.rmtree(LOCALAPPDATA_PRUEBA, ignore_errors=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python pruebas/probar_exe.py ruta\\al\\GestionRestaurante.exe")
        return 2
    exe = Path(sys.argv[1]).resolve()
    CAPTURAS.mkdir(parents=True, exist_ok=True)

    if comprobar(exe.exists(), f"Existe {exe.name}"):
        try:
            probar(exe)
        except Exception as e:  # noqa: BLE001
            comprobar(False, "La prueba del .exe terminó sin fallos inesperados", repr(e)[:500])

    lineas.append("")
    lineas.append("RESULTADO: " + ("TODO BIEN" if fallos == 0 else f"{fallos} FALLO(S)"))
    (RESULTADOS / "resultado_exe.txt").write_text("\n".join(lineas), encoding="utf-8")
    print(lineas[-1])
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
