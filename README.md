# Municipio Conecta – Trámites en línea de Chilca

Portal de la Municipalidad de Chilca con FastAPI, Jinja2 y JavaScript para trámites, solicitudes, notificaciones y pagos simulados.

## Puesta en marcha (un solo comando)

```bash
python run.py          # Windows: también puedes hacer doble clic en run.bat
```

Para la demo local, abre Docker Desktop (o inicia Docker Engine con Compose). El lanzador crea el entorno virtual, instala las dependencias y genera un `.env` con claves propias. Luego inicia PostgreSQL 16 en el puerto local 55432, espera a que acepte conexiones y abre el portal en http://127.0.0.1:8000. Los datos se conservan en un volumen entre arranques. Para detener la base de la demo, usa `docker compose -f compose.demo.yaml stop`.

Si ya tienes PostgreSQL, configura `DATABASE_URL` antes del primer arranque o en `.env` como se indica abajo. Con una conexión propia no necesitas Docker.

Opciones: `--puerto 8080`, `--dev` (recarga automática al editar código), `--no-navegador`, `--reinstalar`.

Usuarios de demostración (los crea `run.py`): ciudadano `12345678` / `ClaveCiudadano1`, administrador `87654321` / `ClaveAdmin1234` y funcionaria de Servicios Públicos `11223344` / `ClaveFuncionario1`.
**Cambia estas claves y pon `SEED_DEMO_DATA=false` en el `.env` antes de usarlo con personas reales.**

<details><summary>Instalación manual</summary>

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env  (completa SECRET_KEY y DATABASE_URL)
python main.py
```
</details>

### Base de datos y despliegue en un VPS

El portal usa PostgreSQL con SQLAlchemy y el controlador asyncpg. Crea la base y el usuario en tu servidor, copia `.env.example` a `.env` y configura `DATABASE_URL`:

```dotenv
DATABASE_URL=postgresql+asyncpg://USUARIO:CLAVE@HOST:5432/municipio_conecta
```

Codifica los caracteres reservados del usuario o la contraseña en la URL. El primer arranque crea las tablas en PostgreSQL. Si conservas datos de una instalación con otro motor, expórtalos y migra una copia antes de cambiar la conexión.

En el VPS, instala las dependencias, define una `SECRET_KEY` propia, `SEED_DEMO_DATA=false` y `PUBLIC_BASE_URL` con la URL HTTPS del dominio .pe asignado. Configura el emisor con `MUNI_NOMBRE`, `MUNI_RUC`, `MUNI_DIRECCION` y `MUNI_TELEFONO`. Ejecuta `python -m uvicorn main:app --host 127.0.0.1 --port 8000` desde la carpeta del proyecto detrás del proxy HTTPS. Usa una ruta persistente para `UPLOADS_DIR`. La pasarela de Etapa 3 es simulada; mantén `MODO_DEMO=true` para que las boletas lo indiquen.

### Datos de demostración
Con `SEED_DEMO_DATA=true` y la base vacía se crean un ciudadano (DNI 12345678) y un admin (DNI 87654321)
con tres deudas. Las contraseñas salen de `DEMO_CITIZEN_PASSWORD` / `DEMO_ADMIN_PASSWORD` o se generan al azar
y **se imprimen una sola vez** en la consola. Nunca actives esto en producción.

Para recrear la base desde cero: `python seed.py --reset` (borra todo).

En instalaciones existentes, conserva una copia de la base antes de actualizar. La inicialización agrega las columnas opcionales que falten; no convierte formatos históricos ni traslada datos entre motores.

## Tests

```bash
pip install -r requirements-dev.txt
```

Antes de ejecutar `pytest`, configura `MUNICIPIO_TEST_DATABASE_URL` en el entorno con la URL de una base PostgreSQL vacía y exclusiva para esa ejecución. La suite comprueba que esté vacía antes de escribir y deja los datos para su inspección. Por ejemplo, en PowerShell:

```powershell
$env:MUNICIPIO_TEST_DATABASE_URL = "postgresql+asyncpg://USUARIO:CLAVE@localhost:5432/municipio_pruebas"
python -m pytest
```

## Pagos y boleta (simulado)

La pasarela es **simulada** pero se comporta como una real: reserva atómica de la deuda, rechazos persistidos, bloqueo tras 5 pagos fallidos en 10 min, y nunca se guarda el número completo ni el CVV.
Tarjetas de prueba: `4111 1111 1111 1111` (aprobada), `4000 0000 0000 0002` (fondos insuficientes), `4000 0000 0000 0127` (transacción no permitida), `4000 0000 0000 0069` (tarjeta vencida/bloqueada), `5555 5555 5555 4444` (Mastercard OK).
Yape/Plin: celular de 9 dígitos que empiece con 9 y código de 6 dígitos (`000000` se rechaza).
Cada pago genera una **boleta PDF** (serie `COMPROBANTE_SERIE`, monto en letras, QR firmado con HMAC) verificable en `/verificar/...` sin iniciar sesión (nombre enmascarado). Con `MODO_DEMO=true` el PDF lleva marca "DEMOSTRACIÓN".
El admin tiene la pestaña **Recaudación** (filtros por fecha/medio/estado y exportación CSV). Variables nuevas: ver `.env.example`.
Las instalaciones PostgreSQL existentes incorporan las nuevas columnas opcionales al iniciar.

## Quejas, reclamos y peticiones
El ciudadano registra una **queja**, un **reclamo** o una **petición** (incluye acceso a la información pública y solicitudes de servicio), con adjuntos opcionales, y recibe un **código de seguimiento** (`QJ-`, `RC-`, `PT-` + año + correlativo) y una **fecha límite** calculada en días hábiles (configurable: `PLAZO_QUEJA_DIAS`, `PLAZO_RECLAMO_DIAS`, `PLAZO_PETICION_DIAS`, `PLAZO_INFORMACION_DIAS`; no considera feriados).
Puede seguir el caso en una línea de tiempo y agregar comentarios o adjuntos mientras esté abierto. El administrador/funcionario tiene una **bandeja** con resumen, filtros, búsqueda y casos con plazo vencido; atiende el caso (en atención → atendida / improcedente), redacta la **respuesta oficial** (obligatoria para cerrar; un caso cerrado no se reabre) y puede dejar **notas internas** que el ciudadano no ve.

## Catálogo de trámites
`GET /api/v1/tramites/catalogo` lista los trámites con requisitos, costo, plazo y campos propios. Nuevos: constancia de no adeudo (solo si no hay deudas pendientes), certificado de domicilio, licencia para evento y copia certificada. Para agregar uno: enum y costo en `models.py` y su ficha en `catalogo.py`.

## Notificaciones y seguimiento
La campana del encabezado avisa de pagos, cambios de estado de trámites y respuestas a quejas/peticiones (el funcionario recibe avisos de casos nuevos y comentarios). Cada trámite muestra su línea de tiempo: registro, pago y cambios de estado.

## Roles, áreas y derivación
Hay tres roles: **ciudadano**, **funcionario** (pertenece a un área) y **administrador**. Áreas: Mesa de Partes, Rentas y Tributos, Servicios Públicos, Obras y Desarrollo Urbano, Registro Civil y Atención al Ciudadano.
Cada queja/reclamo/petición y cada trámite se asigna al área que le corresponde (ver `catalogo.py`). El funcionario **solo ve y gestiona los casos de su área**; puede **derivar** una solicitud a otra área indicando el motivo (el ciudadano ve que fue derivada, pero no el motivo interno). El administrador ve todo, además de usuarios, recaudación, reportes y auditoría.
Crea funcionarios desde *Gestión de Usuarios* (rol "Funcionario de un área"). Con los datos de demostración existe la funcionaria `11223344` / `ClaveFuncionario1` (Servicios Públicos). Si ya tenías una base de datos de una versión anterior, esa funcionaria se agrega sola al iniciar (en modo demostración); no hace falta borrar nada.

## Cuenta propia y recuperación de contraseña
El ciudadano puede **crear su cuenta** desde la pantalla de ingreso (DNI, nombre, correo y contraseña; si RENIEC reconoce el DNI se usa su nombre oficial; hoy RENIEC es simulado) y **recuperar su contraseña** con un código de 6 dígitos enviado a su correo (vale 15 minutos, 5 intentos, un solo uso). Sin correo configurado y con `MODO_DEMO=true`, el código se muestra en la consola del servidor.

## Consulta pública de seguimiento
`/seguimiento`: cualquier persona consulta el estado de una queja/reclamo/petición (`RC-2026-00001`) o de un trámite (`2026-00001-LFU`) con el código y el DNI del titular, sin iniciar sesión. Solo se muestran estado e hitos, nunca textos, respuestas ni nombres; si algo no coincide, el mensaje es siempre el mismo.

## Avisos por correo y WhatsApp (opcional)
Completa en el `.env` y reinicia; luego prueba con `python probar_avisos.py tu_correo@ejemplo.com`.
- **Correo (SMTP):** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`. Gmail: `smtp.gmail.com`, puerto 587, y una *contraseña de aplicación* (requiere verificación en dos pasos). Microsoft 365 / correo institucional: `smtp.office365.com`, puerto 587; **muchas instituciones tienen el SMTP desactivado**: si `probar_avisos.py` dice "usuario o contraseña rechazados", pide que lo habiliten o usa otra cuenta (Gmail/Outlook personal). El ciudadano recibe un correo por cada aviso de su campana (trámite, pago, queja, petición).
- **WhatsApp (CallMeBot):** `CALLMEBOT_PHONE` (con código de país, p. ej. `+51987654321`) y `CALLMEBOT_APIKEY`. Para obtener la clave: guarda el contacto de CallMeBot, envíale por WhatsApp el mensaje que indica https://www.callmebot.com/blog/free-api-whatsapp-messages/ y te responderá con tu apikey. **CallMeBot solo escribe al número que lo activó**, por eso se usa como **aviso al personal** (casos nuevos, comentarios y derivaciones), no para cada ciudadano.
- Los avisos salen **solo si la operación se guardó**, van en segundo plano y un fallo de envío nunca afecta al trámite (queda en el log). No pongas contraseñas en el código ni las subas a git: viven solo en el `.env`.

## Reportes y auditoría
El administrador ve *Reportes y Auditoría*: solicitudes por área/tipo/estado, % atendido dentro del plazo, tiempo promedio de respuesta, casos vencidos y trámites por área; y el registro de **quién hizo qué y cuándo** (cambios de estado, respuestas, derivaciones, altas de usuarios, restablecimiento de claves).

## Feriados
Los plazos en días hábiles saltan sábados, domingos y los feriados nacionales (`feriados.py`, incluye Jueves y Viernes Santo). Revisa la lista cada año y agrega feriados locales o días no laborables con `FERIADOS_EXTRA=2026-12-26,2027-01-02` en el `.env`.

## Estructura
- `main.py` – app, errores globales, cabeceras de seguridad
- `config.py` – variables de entorno (`.env`)
- `auth.py`, `security.py` – JWT (PyJWT) y bcrypt
- `models.py`, `schemas.py` – tablas y contratos (los enums están definidos una sola vez, en `models.py`)
- `feriados.py` – feriados nacionales para plazos; `probar_avisos.py` – prueba de correo y WhatsApp
- `catalogo.py` – áreas, fichas de trámites y categorías/plazos de quejas y peticiones
- `run.py` / `run.bat` / `run.sh` – arranque con un comando
- `controllers/` – endpoints; `services/` – lógica (intereses, uploads, IA, pasarela simulada)
- `static/`, `templates/` – interfaz web
- Los documentos subidos se guardan en `private_uploads/` (fuera de `static/`) y solo se descargan con sesión.

## Reglas importantes
- Todos los endpoints de trámites, deudas, pagos e IA exigen token; cada ciudadano solo ve lo suyo.
- El servidor calcula costos e intereses; el monto que envía el cliente solo se usa para confirmar.
- Una deuda o trámite solo se paga una vez; las deudas pagadas no generan intereses.
- Login: 5 intentos fallidos por DNI+IP cada 5 minutos → 429.

## Pendiente / para producción
- Pasarela de pago, RENIEC y SUNAT son **simulaciones** (`services/simulador_pago.py`, `services/integrations.py`).
- Pago de cuotas de un plan de fraccionamiento (hoy se genera el cronograma pero no se cobra cuota a cuota).
- El token JWT vive en `localStorage`; para mayor seguridad usar cookie `HttpOnly` + CSRF.
- Limitadores y métricas de IA están en memoria (una sola instancia); usar Redis/BD si hay varios workers.
- Migraciones con Alembic en lugar de `create_all`; HTTPS y `uvicorn` sin `reload` detrás de un proxy.
- Tailwind/FontAwesome/SweetAlert2 se cargan desde CDN; para producción conviene servirlos localmente.

## Uso en celular
La interfaz es responsiva: en pantallas pequeñas las pestañas pasan a una barra inferior tipo app, las ventanas se abren como hoja desde abajo y los campos evitan el zoom automático. Para probarla desde tu celular en la misma red Wi‑Fi: `python run.py --red` y abre `http://IP-de-tu-PC:8000`.
