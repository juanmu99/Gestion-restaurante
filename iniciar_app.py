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
3. Streamlit arranca, y un hilo aparte espera a que responda de verdad
   antes de abrir el navegador (en un PC lento puede tardar).
4. Si el programa YA estaba abierto (puerto ocupado), no se arranca otro:
   solo se abre el navegador en el que ya está funcionando.
5. Solo escucha en este ordenador (127.0.0.1): nadie de la misma red wifi
   puede abrirlo, y Windows no pide permiso al Firewall.
"""

import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PUERTO = 8501
DIRECCION = "127.0.0.1"


def _ruta_app_py() -> str:
    """Encuentra la copia de app.py que el build incluyó como archivo de datos."""
    if getattr(sys, "frozen", False):
        # sys._MEIPASS: carpeta temporal donde PyInstaller descomprime
        # los archivos de datos del bundle en cada arranque.
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return str(base / "app.py")


def _puerto_ocupado(puerto: int) -> bool:
    """True si ya hay algo escuchando en ese puerto."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((DIRECCION, puerto)) == 0


# Sin proxy: en ordenadores con un proxy configurado en Windows, las
# peticiones a 127.0.0.1 podrían ir al proxy y no llegar nunca.
_SIN_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _servidor_listo(url: str) -> bool:
    """True si en `url` responde un servidor de Streamlit (el de este programa)."""
    try:
        with _SIN_PROXY.open(f"{url}/_stcore/health", timeout=2) as respuesta:
            return respuesta.read().decode().strip() == "ok"
    except OSError:
        return False


def _abrir_navegador(url: str, espera_maxima: int = 120) -> None:
    """Abre el navegador cuando el servidor ya responde (o, como mucho, pasados `espera_maxima` segundos)."""
    limite = time.time() + espera_maxima
    while time.time() < limite and not _servidor_listo(url):
        time.sleep(0.5)
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

    puerto = PUERTO
    url = f"http://{DIRECCION}:{puerto}"
    if _puerto_ocupado(puerto):
        if _servidor_listo(url):
            # Ya está abierto (por ejemplo, se cerró la pestaña pero no el
            # programa): no se arranca otro, solo se vuelve a abrir la página.
            print("El programa ya estaba abierto: abriendo el navegador...")
            webbrowser.open(url)
            sys.exit(0)
        # El puerto lo usa OTRO programa: se busca uno libre.
        puerto = next((p for p in range(PUERTO + 1, PUERTO + 20) if not _puerto_ocupado(p)), PUERTO)
        url = f"http://{DIRECCION}:{puerto}"

    threading.Thread(target=_abrir_navegador, args=(url,), daemon=True).start()

    sys.argv = [
        "streamlit", "run", _ruta_app_py(),
        "--server.port", str(puerto),
        "--server.address", DIRECCION,
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--global.developmentMode", "false",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",
    ]
    sys.exit(stcli.main())
