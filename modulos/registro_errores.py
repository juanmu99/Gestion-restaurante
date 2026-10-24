"""
Módulo: registro_errores.py
--------------------------
El ARCHIVO DE REGISTRO DE ERRORES (registro_errores.log), en la carpeta de
datos. Si algo falla, queda apuntado aquí con la fecha, la pantalla, el
ordenador y el detalle técnico, para que el cliente pueda enviárselo al
desarrollador (Exportar / Backup › Registro de errores).

- Nunca hace fallar al programa: si no se puede escribir, se ignora.
- Nunca crece sin control: al pasar de TAMANO_MAXIMO, el registro se aparta
  como registro_errores.log.1 (solo se guarda uno anterior) y se empieza otro.
- No guarda los datos del negocio; solo el error (a veces su texto menciona
  un nombre, por ejemplo de un producto).
"""

import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

NOMBRE_ARCHIVO = "registro_errores.log"
TAMANO_MAXIMO = 1_000_000  # bytes (~1 MB)
CABECERA = "===== "

_carpeta: Optional[Path] = None
_programa = ""
# Para no llenar el registro con el mismo error repetido en cada clic (por
# ejemplo, si el disco está lleno): el mismo error solo se apunta una vez
# cada REPETIR_TRAS minutos.
REPETIR_TRAS = 10
_ultimos: dict[tuple, datetime] = {}


def configurar(carpeta: Path, programa: str = "") -> None:
    """Dónde se guarda el registro (la carpeta de datos) y qué versión del programa es."""
    global _carpeta, _programa
    _carpeta = Path(carpeta)
    _programa = programa


def ruta(carpeta: Optional[Path] = None) -> Optional[Path]:
    carpeta = Path(carpeta) if carpeta is not None else _carpeta
    return carpeta / NOMBRE_ARCHIVO if carpeta is not None else None


def _sistema() -> str:
    try:
        return f"{platform.platform()} · Python {platform.python_version()}"
    except Exception:  # noqa: BLE001
        return sys.platform


def apuntar(que: str, pantalla: str = "", excepcion: Optional[BaseException] = None, detalle: str = "") -> bool:
    """
    Apunta un error en el registro. `que`: qué ha pasado, en pocas palabras.
    `excepcion`: el error de Python (se guarda su detalle técnico completo).
    Devuelve True si se ha podido apuntar. Nunca lanza excepciones.
    """
    archivo = ruta()
    if archivo is None:
        return False
    try:
        clave = (que, pantalla, detalle, repr(excepcion))
        ahora = datetime.now()
        if clave in _ultimos and (ahora - _ultimos[clave]).total_seconds() < REPETIR_TRAS * 60:
            return False
        _ultimos[clave] = ahora
        lineas = [f"{CABECERA}{datetime.now():%d/%m/%Y %H:%M:%S} {CABECERA.strip()}", f"Qué: {que}"]
        if pantalla:
            lineas.append(f"Pantalla: {pantalla}")
        lineas.append(f"Programa: {_programa or '—'}")
        lineas.append(f"Ordenador: {_sistema()}")
        if detalle:
            lineas.append(f"Detalle: {detalle}")
        if excepcion is not None:
            lineas.append("Detalle técnico:")
            lineas.append("".join(traceback.format_exception(type(excepcion), excepcion, excepcion.__traceback__)).rstrip())
        texto = "\n".join(lineas) + "\n\n"
        archivo.parent.mkdir(parents=True, exist_ok=True)
        if archivo.exists() and archivo.stat().st_size + len(texto.encode("utf-8")) > TAMANO_MAXIMO:
            archivo.replace(archivo.with_name(NOMBRE_ARCHIVO + ".1"))  # se aparta el antiguo (solo uno)
        with open(archivo, "a", encoding="utf-8") as f:
            f.write(texto)
        return True
    except Exception:  # noqa: BLE001 -- el registro nunca debe hacer fallar al programa
        return False


def resumen(carpeta: Optional[Path] = None) -> dict:
    """{"errores": cuántos hay apuntados (con el registro anterior), "ultimo": fecha del último o None, "ruta"}."""
    archivo = ruta(carpeta)
    errores, ultimo = 0, None
    for f in (archivo.with_name(NOMBRE_ARCHIVO + ".1"), archivo) if archivo else ():
        try:
            for linea in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if linea.startswith(CABECERA):
                    errores += 1
                    try:
                        ultimo = datetime.strptime(linea[len(CABECERA):len(CABECERA) + 19], "%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        pass
        except OSError:
            continue
    return {"errores": errores, "ultimo": ultimo, "ruta": archivo}


def contenido(carpeta: Optional[Path] = None) -> bytes:
    """El registro para descargarlo y enviarlo: el anterior (si lo hay) y el actual, juntos."""
    archivo = ruta(carpeta)
    partes = []
    for f in (archivo.with_name(NOMBRE_ARCHIVO + ".1"), archivo) if archivo else ():
        try:
            partes.append(f.read_bytes())
        except OSError:
            continue
    return b"".join(partes)
