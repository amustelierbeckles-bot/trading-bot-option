"""
PocketOption Session Helper
============================
Script para extraer el SSID de sesión desde el navegador
y guardarlo en el .env automáticamente.

USO:
  1. Abre PocketOption en el navegador y loguéate
  2. Ejecuta este script: python po_session_helper.py
  3. Sigue las instrucciones en pantalla
"""

import os
import re
import sys


BANNER = """
╔══════════════════════════════════════════════════════╗
║      PocketOption Session Extractor v1.0             ║
║      Extrae tu SSID para el WebSocket                ║
╚══════════════════════════════════════════════════════╝

Cómo obtener tu SSID:

1. Abre PocketOption en Edge/Chrome y loguéate
2. Presiona F12 → Application (o Aplicación)
3. En el panel izquierdo: Storage → Cookies → https://pocketoption.com
4. Busca la cookie llamada: ci_session
5. Copia el valor completo (es una cadena larga)

O alternativamente:
1. F12 → Console (Consola)
2. Escribe: document.cookie
3. Presiona Enter
4. Busca "ci_session=XXXXXX" en el resultado
5. Copia el valor después del "="

"""

def extract_from_cookie_string(raw: str) -> str:
    """Extrae ci_session de una cadena de cookies completa."""
    match = re.search(r'ci_session=([^;]+)', raw)
    return match.group(1).strip() if match else raw.strip()


def update_env_file(ssid: str, env_path: str = ".env"):
    """Actualiza o agrega PO_SSID en el archivo .env"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), env_path)

    if not os.path.exists(env_path):
        print(f"⚠️  No se encontró {env_path}")
        env_path = input("Escribe la ruta completa al .env: ").strip()

    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'PO_SSID=' in content:
        # Actualiza valor existente
        content = re.sub(r'PO_SSID=.*', f'PO_SSID={ssid}', content)
        print("✅ PO_SSID actualizado en .env")
    else:
        # Agrega al final
        content += f'\n# PocketOption WebSocket Session\nPO_SSID={ssid}\n'
        print("✅ PO_SSID agregado al .env")

    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return env_path


def main():
    print(BANNER)

    ssid_raw = input("Pega aquí tu SSID (o la cadena completa de cookies): ").strip()

    if not ssid_raw:
        print("❌ No ingresaste nada. Saliendo.")
        sys.exit(1)

    # Extrae solo el valor si pegaron la cadena completa
    ssid = extract_from_cookie_string(ssid_raw)

    if len(ssid) < 20:
        print(f"⚠️  El SSID parece muy corto ({len(ssid)} chars). Verifica que copiaste bien.")
        confirm = input("¿Continuar igual? (s/n): ").strip().lower()
        if confirm != 's':
            sys.exit(1)

    print(f"\n📋 SSID capturado: {ssid[:20]}...{ssid[-10:]} ({len(ssid)} chars)")

    env_path = update_env_file(ssid)
    print(f"\n✅ Guardado en: {env_path}")
    print("\n🚀 Ahora reinicia el bot para activar el WebSocket de PO.")
    print("   El bot usará los precios REALES de PO en vez de Twelve Data.\n")


if __name__ == "__main__":
    main()
