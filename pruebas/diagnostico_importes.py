"""
Diagnóstico para la compilación (solo se usa en GitHub Actions): se empaqueta
con las mismas opciones que el programa y, al ejecutarlo, dice qué import
falla y por qué. Así se ve el error real que dentro del programa solo sale
como "Faltan librerías".
"""
import traceback

for modulo in ("cryptography", "cryptography.hazmat.bindings._rust", "requests", "google.auth.transport.requests",
               "google.oauth2.credentials", "google_auth_oauthlib.flow", "googleapiclient.discovery",
               "googleapiclient.http", "google_drive_backup"):
    try:
        __import__(modulo)
        print(f"OK  {modulo}")
    except Exception:  # noqa: BLE001
        print(f"MAL {modulo}")
        traceback.print_exc()
