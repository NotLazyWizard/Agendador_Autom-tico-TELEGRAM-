import json
import logging
import os
import re
from telegram import Bot, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

BOT_TOKEN =