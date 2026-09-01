"""
Módulo: google_drive_backup.py
--------------------------------
Sube un archivo (normalmente el Excel exportado) a una carpeta de
Google Drive, como copia de seguridad.

⚠️ IMPORTANTE — este módulo necesita configuración externa que no se
puede hacer desde aquí, y este entorno de pruebas no tiene acceso a
internet, así que este código NO ha podido ejecutarse ni probarse en
esta conversación (a diferencia de los demás módulos). Pruébalo tú en
tu propio ordenador siguiendo estos pasos:

1. Ve a https://console.cloud.google.com/ y crea un proyecto (o usa uno existente).
2. En "APIs y servicios" > "Biblioteca", busca y activa "Google Drive API".
3. En "APIs y servicios" > "Credenciales" > "Crear credenciales", elige
   "ID de cliente de OAuth", tipo de aplicación "App de escritorio".
4. Descarga el JSON de esa credencial y guárdalo exactamente como
   "credentials.json" dentro de la carpeta gestion_restaurante/
   (al mismo nivel que main.py).
5. En TU ordenador (no aquí), instala las librerías necesarias:
   pip install google-auth-oauthlib google-api-python-client

La PRIMERA vez que uses esto se abrirá una pestaña en tu navegador
pidiéndote iniciar sesión en Google y aceptar el acceso a Drive.
Tras aceptar, se guarda un "token.json" junto a main.py para no tener
que repetir el login cada vez (mientras el token siga siendo válido).
"""

from pathlib import Path
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# "drive.file": la app solo puede ver/editar los archivos que ELLA MISMA
# ha creado en tu Drive, no todo tu Drive. Es el permiso más prudente
# para este caso de uso.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# .parent.parent porque este archivo vive en modulos/, pero credentials.json
# debe guardarse junto a main.py, en la raíz del proyecto.
def _carpeta_base() -> Path:
    """
    Misma lógica que en app.py/main.py: si el programa está empaquetado
    con PyInstaller, las credenciales y el token deben vivir junto al
    propio .exe (persistente), NO en la carpeta temporal donde
    PyInstaller descomprime el programa en cada arranque (que es
    distinta cada vez y se borra sola -- ahí perderíamos el login de
    Google en cuanto se cerrara el programa).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent  # modulos/ -> raíz del proyecto


CARPETA_PROYECTO = _carpeta_base()
RUTA_CREDENCIALES = CARPETA_PROYECTO / "credentials.json"
RUTA_TOKEN = CARPETA_PROYECTO / "token.json"


def _obtener_credenciales() -> Credentials:
    """
    Gestiona el login con Google. Reutiliza el token guardado si existe
    y sigue siendo válido; si no, lo refresca o lanza el login en el
    navegador (solo la primera vez, o si el token deja de ser válido).
    """
    credenciales = None

    if RUTA_TOKEN.exists():
        credenciales = Credentials.from_authorized_user_file(str(RUTA_TOKEN), SCOPES)

    if not credenciales or not credenciales.valid:
        if credenciales and credenciales.expired and credenciales.refresh_token:
            credenciales.refresh(Request())
        else:
            if not RUTA_CREDENCIALES.exists():
                raise FileNotFoundError(
                    f"No se encontró {RUTA_CREDENCIALES}. Sigue los pasos del inicio "
                    f"de este archivo para descargar tus credenciales de Google Cloud."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(RUTA_CREDENCIALES), SCOPES)
            credenciales = flow.run_local_server(port=0)

        RUTA_TOKEN.write_text(credenciales.to_json())

    return credenciales


def _obtener_o_crear_carpeta(servicio, nombre_carpeta: str) -> str:
    """Busca una carpeta por nombre en Drive; si no existe, la crea. Devuelve su id."""
    query = (
        f"name='{nombre_carpeta}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    resultado = servicio.files().list(q=query, fields="files(id, name)").execute()
    carpetas = resultado.get("files", [])

    if carpetas:
        return carpetas[0]["id"]

    metadata = {"name": nombre_carpeta, "mimeType": "application/vnd.google-apps.folder"}
    carpeta = servicio.files().create(body=metadata, fields="id").execute()
    return carpeta["id"]


def subir_archivo(ruta_archivo: str, nombre_carpeta_drive: str = "Backups Restaurante") -> str:
    """
    Sube `ruta_archivo` a Google Drive, dentro de una carpeta llamada
    `nombre_carpeta_drive` (la crea si no existe todavía).
    Devuelve el id del archivo subido en Drive.
    """
    credenciales = _obtener_credenciales()
    servicio = build("drive", "v3", credentials=credenciales)

    carpeta_id = _obtener_o_crear_carpeta(servicio, nombre_carpeta_drive)

    metadata = {
        "name": Path(ruta_archivo).name,
        "parents": [carpeta_id],
    }
    media = MediaFileUpload(
        ruta_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    archivo_subido = servicio.files().create(body=metadata, media_body=media, fields="id").execute()

    print(f"☁️  Subido a Google Drive: {Path(ruta_archivo).name} (id: {archivo_subido['id']})")
    return archivo_subido["id"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python3 google_drive_backup.py ruta/al/archivo.xlsx")
    else:
        subir_archivo(sys.argv[1])
