import os
import io
import logging
import threading
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from PIL import Image
from rembg import remove, new_session

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("BOT_TOKEN")
# Предзагрузка сессии с маленькой моделью для экономии RAM
session = new_session("u2netp")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_FOR_OBJECT = 1
WAITING_FOR_BACKGROUND = 2

main_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("🖼️ Удалить фон")], [KeyboardButton("🔄 Заменить фон")], [KeyboardButton("❌ Отмена")]],
    resize_keyboard=True
)

# ========== ФУНКЦИИ ОБРАБОТКИ ==========
def process_remove_bg(image_bytes: bytes) -> bytes:
    input_image = Image.open(io.BytesIO(image_bytes))
    # Используем заранее созданную сессию
    output_image = remove(input_image, session=session)
    output_bytes = io.BytesIO()
    output_image.save(output_bytes, format='PNG')
    return output_bytes.getvalue()

def replace_background(object_bytes: bytes, background_bytes: bytes) -> bytes:
    obj = Image.open(io.BytesIO(object_bytes)).convert("RGBA")
    bg = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
    bg = bg.resize(obj.size, Image.Resampling.LANCZOS)
    result = Image.alpha_composite(bg, obj) # Более корректное наложение
    output_bytes = io.BytesIO()
    result.save(output_bytes, format='PNG')
    return output_bytes.getvalue()

# ========== ХЕНДЛЕРЫ (сокращено для краткости, используйте свои) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Выберите действие:", reply_markup=main_keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🖼️ Удалить фон":
        context.user_data['mode'] = 'remove'
        await update.message.reply_text("📸 Отправьте фото.")
        return WAITING_FOR_OBJECT
    elif text == "🔄 Заменить фон":
        context.user_data['mode'] = 'replace'
        await update.message.reply_text("📸 ШАГ 1/2: Отправьте фото ОБЪЕКТА.")
        return WAITING_FOR_OBJECT
    return ConversationHandler.END

async def handle_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    msg = await update.message.reply_text("⏳ Обрабатываю (это может занять до 20 сек)...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        
        # Удаляем фон
        result_bytes = process_remove_bg(img_bytes)
        context.user_data['object_bytes'] = result_bytes
        
        if mode == 'remove':
            await update.message.reply_document(document=io.BytesIO(result_bytes), filename="no_bg.png", caption="✅ Готово!")
            return ConversationHandler.END
        else:
            await update.message.reply_text("✅ Объект готов! ШАГ 2/2: Отправьте ФОН.")
            return WAITING_FOR_BACKGROUND
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Ошибка обработки.")
        return ConversationHandler.END

async def handle_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo_file = await update.message.photo[-1].get_file()
        bg_bytes = await photo_file.download_as_bytearray()
        obj_bytes = context.user_data.get('object_bytes')
        
        final_img = replace_background(obj_bytes, bg_bytes)
        await update.message.reply_photo(photo=io.BytesIO(final_img), caption="✅ Фон заменен!")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Ошибка.")
    return ConversationHandler.END

# ========== СЕРВЕР И ЗАПУСК ==========
server = Flask(__name__)

@server.route('/')
def health(): return "OK", 200

def run_bot():
    # Используем переменную TOKEN, которая определена в начале файла
    application = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🖼️ Удалить фон|🔄 Заменить фон)$"), button_handler)],
        states={
            WAITING_FOR_OBJECT: [MessageHandler(filters.PHOTO, handle_object)],
            WAITING_FOR_BACKGROUND: [MessageHandler(filters.PHOTO, handle_background)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Отмена$"), start)],
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    
    # КРИТИЧЕСКИЙ МОМЕНТ: close_loop=False и stop_signals=False 
    # позволяют боту работать внутри threading
    application.run_polling(close_loop=False, stop_signals=False)

if __name__ == "__main__":
    # 1. Сначала запускаем бота в отдельном потоке
    threading.Thread(target=run_bot, daemon=True).start()
    
    # 2. Основной поток отдаем Flask, чтобы Render сразу увидел открытый порт
    port = int(os.environ.get('PORT', 10000))
    print(f"Запускаю Flask на порту {port}...")
    # debug=False обязателен для потоков!
    server.run(host='0.0.0.0', port=port, debug=False)
