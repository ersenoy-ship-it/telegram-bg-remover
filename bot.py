import os
import io
import logging
import asyncio
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

from rembg import remove, new_session
from PIL import Image

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_FOR_OBJECT = 1
WAITING_FOR_BACKGROUND = 2

# ⚡ ГЛОБАЛЬНАЯ МОДЕЛЬ (ускорение x3–x5)
session = new_session("u2netp")

# 🧠 очередь (ограничение нагрузки)
semaphore = asyncio.Semaphore(2)

main_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🖼️ Удалить фон")],
        [KeyboardButton("🔄 Заменить фон")],
        [KeyboardButton("❌ Отмена")]
    ],
    resize_keyboard=True
)

# ================= ОБРАБОТКА =================

def process_remove_bg(image_bytes: bytes) -> bytes:
    input_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # 🪶 уменьшаем размер (ускорение + меньше RAM)
    input_image.thumbnail((1024, 1024))

    output_image = remove(input_image, session=session)

    output_bytes = io.BytesIO()
    output_image.save(output_bytes, format='PNG')
    return output_bytes.getvalue()


def combine_images(obj_bytes, bg_bytes):
    obj = Image.open(io.BytesIO(obj_bytes)).convert("RGBA")
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")

    bg = bg.resize(obj.size, Image.Resampling.LANCZOS)

    result = Image.alpha_composite(bg, obj)

    out = io.BytesIO()
    result.save(out, format='PNG')
    return out.getvalue()


# ================= ХЕНДЛЕРЫ =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Бот готов! Выберите действие:", reply_markup=main_keyboard)
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Удалить" in text:
        context.user_data['mode'] = 'remove'
        await update.message.reply_text("📸 Пришлите фото.")
        return WAITING_FOR_OBJECT

    elif "Заменить" in text:
        context.user_data['mode'] = 'replace'
        await update.message.reply_text("📸 Шаг 1: пришлите ОБЪЕКТ.")
        return WAITING_FOR_OBJECT

    return ConversationHandler.END


async def handle_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Обрабатываю...")

    async with semaphore:  # 🧠 ограничение нагрузки
        try:
            photo = await update.message.photo[-1].get_file()
            img_bytes = await photo.download_as_bytearray()

            res = process_remove_bg(img_bytes)

            context.user_data['obj'] = res

            if context.user_data.get('mode') == 'remove':
                await update.message.reply_document(
                    document=io.BytesIO(res),
                    filename="result.png"
                )
                return ConversationHandler.END

            await update.message.reply_text("✅ Теперь пришлите ФОН.")
            return WAITING_FOR_BACKGROUND

        except Exception as e:
            logger.error(e)
            await update.message.reply_text("Ошибка 😢")
            return ConversationHandler.END


async def handle_bg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with semaphore:
        try:
            photo = await update.message.photo[-1].get_file()
            bg_bytes = await photo.download_as_bytearray()

            final = combine_images(context.user_data['obj'], bg_bytes)

            await update.message.reply_photo(photo=io.BytesIO(final))

        except Exception as e:
            logger.error(e)
            await update.message.reply_text("Ошибка 😢")

    return ConversationHandler.END


# ================= TELEGRAM APP =================

app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^(🖼️ Удалить фон|🔄 Заменить фон)$"), button_handler)],
    states={
        WAITING_FOR_OBJECT: [MessageHandler(filters.PHOTO, handle_object)],
        WAITING_FOR_BACKGROUND: [MessageHandler(filters.PHOTO, handle_bg)],
    },
    fallbacks=[
        CommandHandler("start", start),
        MessageHandler(filters.Regex("Отмена"), start)
    ],
)

app.add_handler(CommandHandler("start", start))
app.add_handler(conv)


# ================= FLASK (WEBHOOK) =================

server = Flask(__name__)

@server.route("/")
def health():
    return "OK", 200


@server.route("/webhook", methods=["POST"])
async def webhook():
    data = request.get_json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return "ok"


# ================= ЗАПУСК =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server.run(host="0.0.0.0", port=port)
