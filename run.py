"""Arranque con un solo comando:  python run.py

Hace todo lo necesario la primera vez (entorno virtual, dependencias, archivo .env con
SECRET_KEY y datos de demostración) y después solo arranca el servidor.

Opciones:  --puerto 8080   --dev (recarga automática)   --no-navegador   --reinstalar
"""
import argparse
import hashlib
import os
import secrets
import subprocess
import sys
import threading
import time
import venv
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VENV = RAIZ / ".venv"
PY = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
MARCA = VENV / ".requirements.sha256"
ENV = RAIZ / ".env"
# La contraseña se define antes de DATABASE_URL en el .env generado y la expande python-dotenv.
URL_DEMO = "postgresql+asyncpg://municipio:${MUNICIPIO_DEMO_PG_PASSWORD}@127.0.0.1:55432/municipio_conecta"


def log(msg: str) -> None:
    print(f"[run] {msg}", flush=True)


def asegurar_venv() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Se necesita Python 3.10 o superior (https://www.python.org/downloads/).")
    if not PY.exists():
        log("Creando entorno virtual (.venv)...")
        venv.create(VENV, with_pip=True)


def asegurar_dependencias(forzar: bool) -> None:
    reqs = RAIZ / "requirements.txt"
    huella = hashlib.sha256(reqs.read_bytes()).hexdigest()
    if not forzar and MARCA.exists() and MARCA.read_text().strip() == huella:
        return
    log("Instalando dependencias (solo la primera vez, puede tardar 1-2 minutos)...")
    subprocess.check_call([str(PY), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(reqs)])
    MARCA.write_text(huella)


def asegurar_env() -> None:
    if ENV.exists():
        lineas = ENV.read_text(encoding="utf-8").splitlines()
        for pos in reversed(range(len(lineas))):
            nombre, sep, valor = lineas[pos].partition("=")
            if not sep or nombre.strip().removeprefix("export ").strip() != "SECRET_KEY":
                continue
            if len(valor.strip().strip("\"'")) >= 32:
                return
            lineas[pos] = f"SECRET_KEY={secrets.token_urlsafe(64)}"
            break
        else:
            lineas.append(f"SECRET_KEY={secrets.token_urlsafe(64)}")
        ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        log("SECRET_KEY generada en el .env existente.")
        return
    log("Creando .env con una SECRET_KEY propia...")
    base = (RAIZ / ".env.example").read_text(encoding="utf-8")
    cambios = {"SECRET_KEY": secrets.token_urlsafe(64)}
    if not os.getenv("DATABASE_URL"):
        log("Configurando la demo local con PostgreSQL.")
        cambios.update({
            "DATABASE_URL": URL_DEMO,
            "SEED_DEMO_DATA": "true",
            "DEMO_CITIZEN_PASSWORD": "ClaveCiudadano1",
            "DEMO_ADMIN_PASSWORD": "ClaveAdmin1234",
            "DEMO_STAFF_PASSWORD": "ClaveFuncionario1",
        })
    salida = []
    for linea in base.splitlines():
        clave = linea.split("=", 1)[0]
        if clave == "DATABASE_URL" and cambios.get(clave) == URL_DEMO:
            salida.append(f"MUNICIPIO_DEMO_PG_PASSWORD={secrets.token_hex(32)}")
        salida.append(f"{clave}={cambios[clave]}" if clave in cambios and "=" in linea and not linea.startswith("#") else linea)
    ENV.write_text("\n".join(salida) + "\n", encoding="utf-8")


def iniciar_postgres_demo() -> None:
    if os.getenv("DATABASE_URL"):
        return
    # Solo administrar la base asociada a la URL local que crea este lanzador.
    if f"DATABASE_URL={URL_DEMO}" not in ENV.read_text(encoding="utf-8").splitlines():
        return
    log("Iniciando PostgreSQL para la demo local...")
    try:
        subprocess.run(
            ["docker", "compose", "-f", "compose.demo.yaml", "up", "-d", "--wait", "--wait-timeout", "90", "postgres"],
            cwd=RAIZ, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("No se pudo iniciar PostgreSQL local. Comprueba Docker Compose y el puerto 55432, "
                 "o configura DATABASE_URL con tu servidor PostgreSQL.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--red", action="store_true", help="permite abrir la app desde otros dispositivos de tu red (p. ej. el celular)")
    ap.add_argument("--dev", action="store_true", help="recarga automática al editar código")
    ap.add_argument("--no-navegador", action="store_true")
    ap.add_argument("--reinstalar", action="store_true", help="reinstala las dependencias")
    args = ap.parse_args()

    asegurar_venv()
    asegurar_dependencias(args.reinstalar)
    asegurar_env()
    iniciar_postgres_demo()

    url = f"http://127.0.0.1:{args.puerto}"
    if not args.no_navegador:
        threading.Thread(target=lambda: (time.sleep(2.5), webbrowser.open(url)), daemon=True).start()
    print("=" * 60)
    print(f"  Portal listo en {url}   (Ctrl+C para detener)")
    if args.red:
        import socket
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); _s.connect(("8.8.8.8", 80)); ip = _s.getsockname()[0]; _s.close()
        except OSError:
            ip = "IP-de-tu-PC"
        print(f"  Desde tu celular (misma red Wi-Fi): http://{ip}:{args.puerto}")
    print("  Usuarios de la demo local: consulta la sección de demostración del README.")
    print("=" * 60, flush=True)
    cmd = [str(PY), "-m", "uvicorn", "main:app", "--host", "0.0.0.0" if args.red else "127.0.0.1", "--port", str(args.puerto)]
    if args.dev:
        cmd.append("--reload")
    try:
        raise SystemExit(subprocess.call(cmd, cwd=RAIZ))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
