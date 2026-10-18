"""
pruebas/capturas.py
---------------------
Abre la app (ya arrancada con `streamlit run app.py` en el puerto 8501) en
un navegador Chromium sin pantalla, recorre todas las páginas y las
pestañas del inventario, y guarda una captura de cada una en
resultados/capturas/.

Se ejecuta en GitHub Actions justo después de probar_interfaz.py, que deja
una sesión guardada con datos (productos, una limpieza, compras...), así
que las capturas muestran la app "en uso" y no vacía.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "resultados" / "capturas"

PAGINAS = ["Dashboard", "Inventario", "Servicios", "Historial", "Recetario", "Compras", "Gastos", "Métricas", "Exportar / Backup", "Ajustes"]
PESTANAS_INVENTARIO = ["✏️ Editar producto", "📦 Actualizar stock", "🏷️ Lotes", "📈 Historial de precios", "🔪 Limpiar producto", "📜 Limpiezas"]


def esperar(page) -> None:
    """Espera a que Streamlit termine de ejecutar el script tras un clic."""
    page.wait_for_timeout(800)
    try:
        # Mientras el script corre, Streamlit muestra un indicador "Running..."
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=15000)
    except Exception:  # noqa: BLE001 -- si no aparece, simplemente seguimos
        pass
    page.wait_for_timeout(700)


def nombre_archivo(numero: int, texto: str) -> str:
    limpio = "".join(c if c.isalnum() else "_" for c in texto).strip("_").lower()
    return f"{numero:02d}_{limpio}.png"


def main() -> int:
    CARPETA.mkdir(parents=True, exist_ok=True)
    numero = 1
    errores = []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # Ventana alta para que quepa casi toda la página en la captura
        page = navegador.new_page(viewport={"width": 1440, "height": 2000})
        # El servidor se arranca justo antes en segundo plano: hay que esperar
        # a que responda (si no, a veces falla con ERR_CONNECTION_REFUSED).
        import time
        import urllib.request
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=2) as r:
                    if r.read().decode().strip() == "ok":
                        break
            except OSError:
                time.sleep(1)
        page.goto(URL)
        page.wait_for_selector('[data-testid="stSidebar"]', timeout=90000)
        esperar(page)

        if not (RAIZ / "datos" / "sesion.json").exists():
            page.get_by_role("button", name="🧪 Cargar datos de ejemplo").click()
            esperar(page)

        sidebar = page.locator('[data-testid="stSidebar"]')
        for pagina in PAGINAS:
            try:
                sidebar.get_by_text(pagina, exact=True).click()
                esperar(page)
                page.screenshot(path=str(CARPETA / nombre_archivo(numero, pagina)), full_page=True)
                print(f"📸 {pagina}")
            except Exception as e:  # noqa: BLE001
                errores.append(f"{pagina}: {e}")
            numero += 1

            if pagina == "Inventario":
                for pestana in PESTANAS_INVENTARIO:
                    try:
                        page.get_by_role("tab", name=pestana).click()
                        esperar(page)
                        page.screenshot(
                            path=str(CARPETA / nombre_archivo(numero, f"inventario {pestana}")), full_page=True
                        )
                        print(f"📸 Inventario > {pestana}")
                    except Exception as e:  # noqa: BLE001
                        errores.append(f"Inventario > {pestana}: {e}")
                    numero += 1
                try:
                    page.get_by_text("🧻 Consumibles", exact=True).first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "inventario consumibles")), full_page=True)
                    print("📸 Inventario > Consumibles")
                    numero += 1
                    page.get_by_text("🥘 Elaboraciones", exact=True).first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "inventario elaboraciones")), full_page=True)
                    print("📸 Inventario > Elaboraciones")
                    numero += 1
                    page.get_by_text("Una elaboración base (kg / litros)", exact=True).first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "inventario preparar base")), full_page=True)
                    print("📸 Inventario > Elaboraciones > Preparar base")
                    numero += 1
                    page.get_by_role("tab", name="🧪 Preparaciones de bases").click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "inventario preparaciones bases")), full_page=True)
                    print("📸 Inventario > Preparaciones de bases")
                    numero += 1
                    page.get_by_text("🍽️ Material", exact=True).first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "inventario material")), full_page=True)
                    print("📸 Inventario > Material")
                    page.get_by_text("🍅 Alimentos", exact=True).first.click()
                    esperar(page)
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Inventario > Consumibles: {e}")
                numero += 1

            if pagina == "Servicios":
                for pestana in ("🚚 Material", "💶 Rentabilidad"):
                    try:
                        page.get_by_role("tab", name=pestana).click()
                        esperar(page)
                        page.screenshot(path=str(CARPETA / nombre_archivo(numero, f"servicios {pestana}")), full_page=True)
                        print(f"📸 Servicios > {pestana}")
                    except Exception as e:  # noqa: BLE001
                        errores.append(f"Servicios > {pestana}: {e}")
                    numero += 1

            if pagina == "Servicios":
                # Completar un servicio, hasta el paso 3 (Sobrantes). Solo se mira: no se completa.
                try:
                    import re
                    page.get_by_role("tab", name="✅ Completar servicio").click()
                    esperar(page)
                    page.locator('[data-testid="stSelectbox"]').filter(has_text="Servicio a completar").click()
                    page.get_by_role("option", name=re.compile("Menú del día")).first.click()
                    esperar(page)
                    for _ in range(2):
                        page.get_by_role("button", name="Siguiente →").click()
                        esperar(page)
                    campos = page.get_by_label(re.compile(r"Se tira \("))
                    if campos.count():
                        campos.first.fill("1")
                        campos.first.press("Enter")
                        esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "servicios completar paso 3 sobrantes")),
                                    full_page=True)
                    print("📸 Servicios > Completar > paso 3 (Sobrantes)")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Servicios > Completar > Sobrantes: {e}")
                numero += 1

            if pagina == "Historial":
                try:
                    import re
                    page.locator('[data-testid="stSelectbox"]').filter(has_text="Servicio").last.click()
                    page.get_by_role("option", name=re.compile("Menú sobrantes")).first.click()
                    esperar(page)
                    page.get_by_role("tab", name="🗑️ Sobrantes").click()
                    esperar(page)
                    page.get_by_text("Cada sobrante apuntado").first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "historial sobrantes")), full_page=True)
                    print("📸 Historial > ficha > Sobrantes")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Historial > Sobrantes: {e}")
                numero += 1

            if pagina == "Métricas":
                try:
                    page.get_by_role("tab", name="🗑️ Sobrantes").click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "metricas sobrantes")), full_page=True)
                    print("📸 Métricas > Sobrantes")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Métricas > Sobrantes: {e}")
                numero += 1
                try:
                    page.get_by_role("tab", name="🧾 IVA").click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "metricas iva")), full_page=True)
                    print("📸 Métricas > IVA")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Métricas > IVA: {e}")
                numero += 1

            if pagina == "Recetario":
                try:
                    page.get_by_role("tab", name="Menús").click()
                    esperar(page)
                    page.get_by_text("🔎 Ver detalle del menú").first.click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "recetario detalle menu")), full_page=True)
                    print("📸 Recetario > Detalle de menú")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Recetario > Detalle de menú: {e}")
                numero += 1
                # Coste de cada plato al diseñar: Crear menú con dos recetas elegidas y Crear receta con un ingrediente.
                try:
                    import re
                    page.get_by_role("tab", name="➕ Crear menú").click()
                    esperar(page)
                    for receta in ("Pan casero", "Ensalada de tomate"):
                        page.locator('[data-testid="stMultiSelect"]').filter(has_text="Recetas a incluir").click()
                        page.get_by_role("option", name=receta, exact=True).click()
                        esperar(page)
                    page.get_by_label("Calcular para un número de comensales (opcional)").first.fill("25")
                    page.get_by_label("Calcular para un número de comensales (opcional)").first.press("Enter")
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "recetario crear menu coste")), full_page=True)
                    print("📸 Recetario > Crear menú (coste)")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Recetario > Crear menú: {e}")
                numero += 1
                try:
                    page.get_by_role("tab", name="➕ Crear receta").click()
                    esperar(page)
                    campo = page.get_by_label(re.compile(r"Cantidad por comensal")).first
                    campo.fill("0.2")
                    campo.press("Enter")
                    esperar(page)
                    page.get_by_role("button", name="➕ Añadir ingrediente a la receta").click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "recetario crear receta coste")), full_page=True)
                    print("📸 Recetario > Crear receta (coste)")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Recetario > Crear receta: {e}")
                numero += 1
                try:
                    page.get_by_role("tab", name="🧪 Elaboraciones base").click()
                    esperar(page)
                    page.screenshot(path=str(CARPETA / nombre_archivo(numero, "recetario bases")), full_page=True)
                    print("📸 Recetario > Elaboraciones base")
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Recetario > Elaboraciones base: {e}")
                numero += 1

        navegador.close()

    for error in errores:
        print(f"❌ No se pudo capturar {error}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
