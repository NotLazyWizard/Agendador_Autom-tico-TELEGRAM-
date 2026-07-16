# Automatizador de Notas de Voz

Asistente personal para capturar notas de voz en Telegram, transcribirlas con Groq Whisper, guardarlas en SQLite y consultar el historial mediante comandos. El proyecto está diseñado como un monolito modular con Clean Architecture, separación estricta de responsabilidades y despliegue mediante Docker Compose.

## Arquitectura

La base del sistema sigue estos principios:

- **Clean Architecture**: el dominio y los casos de uso no dependen de Telegram, SQLite ni de Groq.
- **Separación por capas**: cada módulo tiene una única responsabilidad.
- **Inversión de dependencias**: los servicios de infraestructura se inyectan en los handlers y comandos.
- **Monolito modular**: una sola aplicación, pero con límites claros para crecer sin acoplamiento.
- **Compatibilidad con Docker y Raspberry Pi 5**: la base de contenedores está preparada para Linux, Windows y ARM64.

### Flujo general

1. Telegram recibe una nota de voz.
2. El bot descarga el archivo `.ogg`.
3. El handler de voz guarda una copia temporal.
4. `SpeechService` transcribe el audio con Groq Whisper.
5. `NoteRepository` persiste la nota en SQLite.
6. El handler elimina el audio temporal y, si corresponde, el archivo origen.
7. El bot responde: `Nota guardada correctamente.`

### Servicios principales

- `SpeechService`: transcribe audios `.ogg` con Groq Whisper.
- `SummaryService`: resume listas de textos usando Groq Chat.
- `CleanupService`: elimina notas antiguas y sus audios asociados.
- `InternalScheduler`: ejecuta `CleanupService` cada 24 horas sin bloquear el bot.
- `TelegramBot`: conecta con Telegram y registra handlers y comandos.
- `TelegramCommands`: implementa los comandos de consulta y formatea respuestas.
- `VoiceNoteHandler`: procesa una nota de voz desde Telegram hasta su guardado.
- `SQLiteNoteRepository`: persiste, consulta, actualiza y elimina notas.
- `logger.py`: centraliza la configuración y los helpers de logging.

## Docker

El proyecto se ejecuta dentro de un contenedor Python basado en `python:3.12-slim-bookworm`.

El contenedor incluye:

- `ffmpeg` para tratamiento de audio.
- `tini` para un manejo correcto de señales y procesos hijos.
- Usuario no root para ejecución más segura.
- Creación de directorios persistentes para base de datos, logs y audios.

### Directorios persistentes

- `database/`: almacena `app.db` y posibles copias de seguridad.
- `logs/`: almacena los archivos de log diarios.
- `audios/`: almacena audios temporales o persistentes según la estrategia de ejecución.

## Docker Compose

La orquestación local se realiza con `docker-compose.yml`.

El servicio principal:

- construye la imagen desde `Dockerfile`.
- monta volúmenes persistentes para `database/`, `logs/` y `audios/`.
- carga variables desde `.env`.
- reinicia el contenedor con política `unless-stopped`.
- ejecuta la aplicación con `python -m app.main`.

### Ejecución con Compose

```bash
docker-compose up -d --build
```

Para ver logs:

```bash
docker-compose logs -f
```

Para detener el servicio:

```bash
docker-compose down
```

## Variables de entorno

Las variables de ejemplo están en [`.env.example`](.env.example).

### Variables generales

- `APP_NAME`: nombre lógico del proyecto.
- `APP_ENV`: entorno de ejecución, por ejemplo `development` o `production`.
- `DEBUG`: activa o desactiva comportamiento de depuración.
- `TIMEZONE`: zona horaria base.

### Docker

- `DOCKER_PROJECT_NAME`: nombre del proyecto Compose.
- `DOCKER_CONTAINER_NAME`: nombre del contenedor.
- `DOCKER_RESTART_POLICY`: política de reinicio.
- `DOCKER_WORKDIR`: directorio de trabajo dentro del contenedor.
- `DOCKER_APP_USER`: usuario de ejecución.
- `DOCKER_APP_GROUP`: grupo de ejecución.
- `DOCKER_USE_BIND_MOUNTS`: activa o desactiva montajes de host.

### Logging

- `LOG_LEVEL`: nivel de logging.
- `LOG_FORMAT`: formato del mensaje.
- `LOG_DATE_FORMAT`: formato de fecha del log.
- `LOG_FILE`: archivo de salida principal.
- `LOG_TO_CONSOLE`: activa logs por consola.
- `LOG_TO_FILE`: activa logs en archivo.
- `LOG_ROTATE_MAX_BYTES`: tamaño de rotación si se usa log por tamaño en módulos antiguos.
- `LOG_ROTATE_BACKUP_COUNT`: número de copias históricas.

### SQLite

- `DATABASE_PATH`: ruta del archivo SQLite.
- `SQLITE_TIMEOUT_SECONDS`: timeout de conexión.
- `SQLITE_JOURNAL_MODE`: modo de journal, normalmente `WAL`.
- `SQLITE_FOREIGN_KEYS`: activa claves foráneas.
- `SQLITE_BUSY_TIMEOUT_MS`: espera ante bloqueo.
- `SQLITE_BACKUP_ENABLED`: activa backup automático.
- `SQLITE_BACKUP_DIR`: directorio de copias.

### Groq

- `GROQ_API_KEY`: clave de API.
- `GROQ_MODEL`: modelo de Whisper o Chat.
- `GROQ_BASE_URL`: URL base de la API.
- `GROQ_TIMEOUT_SECONDS`: timeout de llamadas.
- `GROQ_MAX_RETRIES`: número máximo de reintentos.
- `GROQ_TEMPERATURE`: temperatura para Chat.
- `GROQ_LANGUAGE`: idioma esperado de salida.

### Telegram

- `BOT_TOKEN`: token del bot.
- `TELEGRAM_ALLOWED_USER_IDS`: lista opcional de usuarios permitidos.
- `TELEGRAM_POLLING_TIMEOUT_SECONDS`: timeout de polling.
- `TELEGRAM_WEBHOOK_ENABLED`: activa webhook si se usa.
- `TELEGRAM_WEBHOOK_PATH`: ruta del webhook.
- `TELEGRAM_WEBHOOK_SECRET_TOKEN`: secreto para webhook.
- `TELEGRAM_MAX_MESSAGE_LENGTH`: límite de caracteres en respuestas.

### Limpieza automática

- `CLEANUP_ENABLED`: activa el servicio de limpieza.
- `CLEANUP_INTERVAL_SECONDS`: intervalo entre ejecuciones.
- `CLEANUP_MAX_AUDIO_AGE_HOURS`: antigüedad máxima de audios.
- `CLEANUP_MAX_LOG_AGE_DAYS`: antigüedad máxima de logs.
- `CLEANUP_MAX_TEMP_AGE_HOURS`: antigüedad máxima de temporales.
- `CLEANUP_DRY_RUN`: simula la limpieza sin borrar.

## Instalación

### Opción recomendada: Docker

1. Copia el archivo `.env.example` a `.env`.
2. Completa `BOT_TOKEN` y `GROQ_API_KEY`.
3. Levanta el contenedor con Docker Compose.

```bash
docker-compose up -d --build
```

### Opción local

Si en el futuro deseas ejecutar fuera de Docker:

1. Crea un entorno virtual.
2. Instala las dependencias del proyecto.
3. Exporta o define las variables de entorno.
4. Ejecuta el módulo de arranque cuando exista.

## Despliegue en Raspberry Pi 5

El proyecto está preparado para Raspberry Pi 5 con arquitectura ARM64.

### Recomendación de despliegue

1. Instala Docker y Docker Compose en la Raspberry.
2. Clona el repositorio.
3. Configura el archivo `.env`.
4. Verifica que el sistema tenga acceso a Internet para Groq y Telegram.
5. Arranca el contenedor con `docker-compose up -d --build`.

### Consideraciones para ARM64

- La imagen base `python:3.12-slim-bookworm` es compatible con ARM64.
- `ffmpeg` está incluido para soportar tratamiento de audio.
- SQLite es ideal para un despliegue personal en Raspberry Pi por su bajo costo operativo.
- Los volúmenes persistentes evitan pérdida de datos al recrear contenedores.

## Actualización mediante Git

Flujo recomendado para actualizar el sistema:

```bash
git pull origin main
docker-compose up -d --build
```

Si cambió el esquema o los volúmenes, detén y recrea el contenedor:

```bash
docker-compose down
docker-compose up -d --build
```

## Backup de SQLite

La base de datos está en `database/app.db` cuando se usa el layout por defecto.

### Copia manual

```bash
cp database/app.db database/app.db.bak
```

En Windows PowerShell:

```powershell
Copy-Item .\database\app.db .\database\app.db.bak
```

### Copia consistente

Para evitar corrupciones, haz backup cuando el contenedor esté detenido o cuando SQLite no esté escribiendo intensamente.

### Buenas prácticas

- Conserva varias versiones de backup.
- Almacena una copia fuera del dispositivo principal si es posible.
- Verifica periódicamente que el archivo de backup se pueda abrir.

## Restauración

Para restaurar una copia de SQLite:

1. Detén el contenedor.
2. Sustituye `database/app.db` por la copia de respaldo.
3. Arranca de nuevo el servicio.

Ejemplo:

```bash
docker-compose down
cp database/app.db.bak database/app.db
docker-compose up -d
```

## Estructura del proyecto

```text
automatizador-de-citas/
├─ app/
│  ├─ __init__.py
│  └─ main.py
├─ cleanup_service.py
├─ config.py
├─ database.py
├─ docker-compose.yml
├─ Dockerfile
├─ logger.py
├─ scheduler_internal.py
├─ speech_service.py
├─ summary_service.py
├─ requirements.txt
├─ telegram_bot.py
├─ telegram_commands.py
├─ voice_note_handler.py
├─ .dockerignore
├─ .env.example
├─ .gitignore
├─ README.md
├─ audios/
├─ database/
└─ logs/
```

## Explicación de cada carpeta

### `audios/`

Carpeta para audios temporales o persistentes según la estrategia de ejecución. Se monta como volumen para no perder archivos al recrear contenedores.

### `database/`

Carpeta persistente para SQLite y sus respaldos. Contiene el archivo `app.db` y, opcionalmente, copias de seguridad.

### `logs/`

Carpeta persistente para los archivos de logging diarios y cualquier salida histórica del sistema.

### `app/`

Contiene el punto de entrada real de la aplicación en `app/main.py` y el paquete raíz de arranque.

## Explicación de cada servicio

### `config.py`

Carga las variables desde `.env`, valida obligatorias y centraliza la configuración general del sistema: Docker, logging, SQLite, Groq, Telegram y limpieza.

### `database.py`

Implementa el modelo `Note`, el `Repository Pattern`, la creación automática de SQLite, creación de tablas, CRUD completo, búsquedas por fecha y texto, últimas notas y estadísticas.

### `speech_service.py`

Recibe un `.ogg`, lo envía a Groq Whisper, obtiene la transcripción y devuelve solo el texto.

### `summary_service.py`

Recibe una lista de textos, construye el prompt y genera un resumen usando Groq Chat.

### `cleanup_service.py`

Elimina notas antiguas y, cuando corresponde, elimina el archivo de audio asociado. Devuelve estadísticas del ciclo de limpieza.

### `scheduler_internal.py`

Ejecuta `cleanup_service` cada 24 horas en modo asíncrono, sin detener el bot.

### `logger.py`

Centraliza el sistema de logging con rotación automática diaria, nivel configurable y helpers para errores, tiempos, consultas, llamadas a Groq y eventos de Telegram.

### `telegram_bot.py`

Conecta con Telegram, registra handlers, comandos y errores, pero no implementa lógica de negocio.

### `telegram_commands.py`

Implementa los comandos `/start`, `/help`, `/hoy`, `/ayer`, `/semana`, `/mes`, `/buscar`, `/ultimas` y `/estadisticas`, delegando el trabajo a los servicios y al repositorio.

### `voice_note_handler.py`

Procesa notas de voz: descarga, guarda temporalmente, transcribe con `SpeechService`, persiste con `NoteRepository` y elimina los archivos temporales.

## Notas de diseño

- No se mezcla SQL con los handlers de Telegram.
- No se usa LLM para procesar notas de voz.
- `SpeechService` y `SummaryService` están separados para evitar acoplamiento.
- El scheduler interno no bloquea el bot porque usa `asyncio`.
- El logging está centralizado para que todos los módulos compartan el mismo formato y destino.

## Próximos pasos recomendados

1. Crear el punto de entrada principal de la aplicación.
2. Definir el wiring final entre configuración, logging, repositorio, servicios y bot.
3. Añadir `requirements.txt` con las dependencias reales del proyecto.
4. Incorporar pruebas unitarias e integración.
