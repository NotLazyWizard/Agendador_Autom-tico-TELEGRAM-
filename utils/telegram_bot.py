import json
import logging
import os
import re
from telegram import Bot, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

BOT_TOKEN = os.getenv("BOT_TOKEN")

nombre_usuario = os.getenv("NOMBRE_USUARIO")

#Mensaje para comprobar que el bot está activo

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hola, {nombre_usuario}! Todo listo y en marcha para trabajar hoy!\n"
        "Qué quieres hacer?\n"
        "/ayuda - Muestra la lista de comandos disponibles\n"
        "Si está todo en orden, manda un mensaje o nota de voz para agendar una cita!"
        )

async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Estos son los comandos disponibles:\n"
        "/estado - Muestra el estado actual del bot\n"
        "/citas_hoy - Muestra las citas programadas para el día de hoy\n"
        "/citas_mañana - Muestra las citas programadas para el día de mañana\n"
        "/citas_semana - Muestra las citas programadas para la semana actual\n"
    )

#El estado del bot depende si hay tokens suficientes para procesar solicitudes

async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("🔍 Verificando cuota de Groq...")

    try:
        client.chat.completions.create(
            model=os.getenv("GROQ_MODEL_INTERPRETE", "openai/gpt-oss-20b"),
            messages=[
                {"role": "user", "content": "¿Estás funcionando correctamente?"}]
            max_tokens=10,    
        )
        await update.message.reply_text("✅ El bot está funcionando correctamente y tiene tokens disponibles.")
    except Exception as e:
        error_texto = str(e)
        if "rate_limit_exceeded" in error_texto or "429" in error_texto:
            match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_texto)
            if match:
                minutos = int(match.group(1)) if match.group(1) else 0
                segundos = float(match.group(2))
                total_min = max(1, round((minutos * 60 + segundos) / 60))
                await update.message.reply_text(
                    f"⏳ No hay cuota disponible en este momento.\n"
                    f"Se restablecerá en aproximadamente {total_min} minuto{'s' if total_min != 1 else ''}."
                )
            else:
                await update.message.reply_text("⏳ No hay cuota disponible en este momento (límite alcanzado).")
        else:
            await update.message.reply_text(f"❌ Error al verificar: {error_texto[:200]}")


#citas programadas para hoy, mañana y semana actual

async def cmd_citas_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Mostrando las citas programadas para hoy...")
    # TO DO

async def cmd_citas_mañana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Mostrando las citas programadas para mañana...")
    # TO DO

async def cmd_citas_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Mostrando las citas programadas para la semana actual...")
    # TO DO

#Recibir audios en telegram

async def recibir_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.voice:
        file_id = update.message.voice.file_id
        new_file = await context.bot.get_file(file_id)
        file_path = f"audios/{file_id}.ogg"
        await new_file.download_to_drive(file_path)
        await update.message.reply_text("🎵 Audio recibido y guardado correctamente.")
    else:
        await update.message.reply_text("❌ No se recibió ningún audio.")