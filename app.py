# bot.py
import os
import io
import logging
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from PIL import Image
from rembg import remove

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== СОСТОЯНИЯ ==========
WAITING_FOR_OBJECT = 1
WAITING_FOR_BACKGROUND = 2

# ========== КЛАВИАТУРА ==========
main_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🖼️ Удалить фон")],
        [KeyboardButton("🔄 Заменить фон")],
        [KeyboardButton("❌ Отмена")]
    ],
    resize_keyboard=True
)

# ========== ФУНКЦИИ ОБРАБОТКИ ==========
def remove_background(image_bytes: bytes) -> bytes:
    input_image = Image.open(io.BytesIO(image_bytes))
    output_image = remove(input_image)
    output_bytes = io.BytesIO()
    output_image.save(output_bytes, format='PNG')
    return output_bytes.getvalue()

def replace_background(object_bytes: bytes, background_bytes: bytes) -> bytes:
    obj = Image.open(io.BytesIO(object_bytes)).convert("RGBA")
    bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
    bg = bg.resize(obj.size, Image.Resampling.LANCZOS)
    result = bg.copy()
    result.paste(obj, (0, 0), obj)
    output_bytes = io.BytesIO()
    result.save(output_bytes, format='PNG')
    return output_bytes.getvalue()

# ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я умею удалять и заменять фон на фото.\n\nВыберите действие:",
        reply_markup=main_keyboard
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🖼️ Удалить фон":
        context.user_data['mode'] = 'remove'
        await update.message.reply_text("📸 Отправьте фото для удаления фона.")
        return WAITING_FOR_OBJECT
    elif text == "🔄 Заменить фон":
        context.user_data['mode'] = 'replace'
        await update.message.reply_text("📸 ШАГ 1/2: Отправьте фото ОБЪЕКТА.")
        return WAITING_FOR_OBJECT
    elif text == "❌ Отмена":
        await update.message.reply_text("❌ Отменено.", reply_markup=main_keyboard)
        return ConversationHandler.END
    return ConversationHandler.END

async def handle_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    await update.message.reply_text("⏳ Обрабатываю...")
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        img_bytes = await file.download_as_bytearray()
        result = remove_background(img_bytes)
        context.user_data['object_bytes'] = result
        
        if mode == 'remove':
            await update.message.reply_photo(result, caption="✅ Готово!", reply_markup=main_keyboard)
            return ConversationHandler.END
        else:
            await update.message.reply_text("✅ Объект готов!\n\n📸 ШАГ 2/2: Отправьте фото ФОНА.")
            return WAITING_FOR_BACKGROUND
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Ошибка. Попробуйте другое фото.")
        return ConversationHandler.END

async def handle_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎨 Накладываю на фон...")
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        bg_bytes = await file.download_as_bytearray()
        obj_bytes = context.user_data.get('object_bytes')
        if not obj_bytes:
            await update.message.reply_text("❌ Ошибка. Начните заново.")
            return ConversationHandler.END
        result = replace_background(obj_bytes, bg_bytes)
        await update.message.reply_photo(result, caption="✅ Готово!", reply_markup=main_keyboard)
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Ошибка. Попробуйте другие фото.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=main_keyboard)
    context.user_data.clear()
    return ConversationHandler.END

# ========== ВЕБ-СЕРВЕР ДЛЯ RENDER ==========
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!", 200

# ========== ЗАПУСК БОТА ==========
def run_bot():
    application = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🖼️ Удалить фон|🔄 Заменить фон)$"), button_handler)],
        states={
            WAITING_FOR_OBJECT: [MessageHandler(filters.PHOTO, handle_object)],
            WAITING_FOR_BACKGROUND: [MessageHandler(filters.PHOTO, handle_background)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), cancel)],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    application.run_polling()

if __name__ == "__main__":
    import threading
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
