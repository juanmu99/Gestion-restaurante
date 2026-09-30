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

PAGINAS = ["Dashboard", "Inventario", "Servicios", "Recetario", "Compras", "Métricas", "Exportar / Backup"]
PESTANAS_INVENTARIO = ["✏️ Editar producto", "📦 Actualizar stock", "🏷️ Lotes", "🔪 Limpiar producto", "📜 Limpiezas"]


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
                    page.get_by_text("🍅 Alimentos", exact=True).first.click()
                    esperar(page)
                except Exception as e:  # noqa: BLE001
                    errores.append(f"Inventario > Consumibles: {e}")
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

        navegador.close()

    for error in errores:
        print(f"❌ No se pudo capturar {error}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
