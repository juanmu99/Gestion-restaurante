"""
iniciar_app.py
----------------
Punto de entrada SOLO para la versión empaquetada (.exe) de la app.

No lo uses en desarrollo -- para eso sigues usando `streamlit run app.py`
a mano, como siempre. Este archivo es lo que PyInstaller convierte en el
ejecutable: arranca el servidor de Streamlit por dentro y abre el
navegador solo, para que quien lo use no tenga que saber qué es una
terminal ni escribir ningún comando.

Cómo funciona (para que lo entiendas si algo falla):
1. Streamlit necesita el archivo .py DE VERDAD para ejecutarlo -- no
   basta con que esté "empaquetado" dentro del .exe como código. Por
   eso, en el build (ver .github/workflows/build-windows.yml) se
   incluye app.py como un archivo de datos suelto, no solo como código.
2. Cuando el .exe arranca, PyInstaller lo descomprime todo (incluido
   ese app.py suelto) en una carpeta temporal. sys._MEIPASS apunta a
   esa carpeta -- ahí es donde buscamos app.py en tiempo de ejecución.
3. Streamlit arranca en segundo plano en un hilo aparte, mientras el
   hilo principal espera un par de segundos y abre el navegador.
"""

import sys
import threading
import time
import webbrowser
from pathlib import Path


def _ruta_app_py() -> str:
    """Encuentra la copia de app.py que el build incluyó como archivo de datos."""
    if getattr(sys, "frozen", False):
        # sys._MEIPASS: carpeta temporal donde PyInstaller descomprime
        # los archivos de datos del bundle en cada arranque.
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return str(base / "app.py")


def _abrir_navegador(url: str) -> None:
    # Pequeña espera para dar tiempo a que el servidor de Streamlit
    # esté escuchando antes de intentar abrir la página.
    time.sleep(2)
    webbrowser.open(url)


def _salida_en_utf8() -> None:
    """
    Los módulos imprimen emojis (✅, ❌...). En Windows, si la salida del
    programa no va a una ventana de consola (por ejemplo, si se guarda en
    un archivo de registro), Python usa una codificación antigua que no
    los conoce y el print() fallaría con UnicodeEncodeError. Con esto se
    escriben en UTF-8 y, si algún carácter no se puede, se sustituye en
    vez de romper el programa.
    """
    for flujo in (sys.stdout, sys.stderr):
        if flujo is not None and hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _salida_en_utf8()

    from streamlit.web import cli as stcli

    puerto = "8501"
    url = f"http://localhost:{puerto}"

    threading.Thread(target=_abrir_navegador, args=(url,), daemon=True).start()

    sys.argv = [
        "streamlit", "run", _ruta_app_py(),
        "--server.port", puerto,
        "--server.headless", "true",
        "--global.developmentMode", "false",
        "--browser.gatherUsageStats", "false",
    ]
    sys.exit(stcli.main())
