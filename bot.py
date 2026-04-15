import asyncio
import os
import io
import logging
import threading
import qrcode
import requests
from flask import Flask
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
DEV_URL = "https://t.me/ZYB_19" 

# Состояния
QR_GENERATING, IMG_CONVERTING, WAITING_FOR_OCR = range(1, 4)

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔳 Создать QR"), KeyboardButton("🖼 Конвертер")],
        [KeyboardButton("📝 Текст с фото"), KeyboardButton("ℹ️ Инфо")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

# --- БАЗОВЫЕ КОМАНДЫ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Команда /start от {update.effective_user.id}")
    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! 👋\nЯ iAssistant. Выберите действие:",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено. Возврат в меню.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Разработчик", url=DEV_URL)]])
    await update.message.reply_text(" **iAssistant Support**\nВсе системы работают штатно ✅", reply_markup=kb, parse_mode="Markdown")

# --- 1. ЛОГИКА QR ---
async def qr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔗 Пришлите текст для создания QR-кода:")
    return QR_GENERATING

async def qr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(update.message.text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#ffffff")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        await update.message.reply_photo(photo=bio, caption="✨ Твой QR-код готов!", reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"QR Error: {e}")
        await update.message.reply_text("❌ Ошибка при создании QR.")
    return ConversationHandler.END

# --- 2. ЛОГИКА КОНВЕРТЕРА (PNG) ---
async def img_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Пришлите фото, которое нужно конвертировать в PNG:")
    return IMG_CONVERTING

async def img_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("⏳ Обработка изображения...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        
        img = Image.open(io.BytesIO(img_bytes))
        out = io.BytesIO()
        # Конвертируем и сохраняем
        img.save(out, format="PNG", optimize=True)
        out.seek(0)
        
        await update.message.reply_document(
            document=out, 
            filename="converted.png", 
            caption="✅ Готово! Файл конвертирован в PNG.",
            reply_markup=main_menu_keyboard()
        )
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Convert Error: {e}")
        await status_msg.edit_text("❌ Ошибка конвертации. Попробуйте другое фото.")
    return ConversationHandler.END

# --- 3. ЛОГИКА OCR (ТЕКСТ С ФОТО) ---
async def ocr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Пришлите фото для распознавания текста:")
    return WAITING_FOR_OCR

async def ocr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 Считываю текст (RU/EN/AR)...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        files = {'file': ('img.jpg', io.BytesIO(photo_bytes), 'image/jpeg')}
        
        # ОБНОВЛЕННЫЙ ПАРАМЕТР ЯЗЫКОВ
        payload = {
            'apikey': 'K89996852888957', 
            'language': 'rus,eng,ara', 
            'OCREngine': 1,
            'scale': True
        }
        
        res = requests.post('https://api.ocr.space/parse/image', files=files, data=payload, timeout=25).json()
        
    
        
        if res.get("ParsedResults"):
            text = res["ParsedResults"][0]["ParsedText"]
            if text.strip():
                await status_msg.edit_text(f"📖 **Распознанный текст:**\n\n`{text}`", parse_mode="Markdown")
            else:
                await status_msg.edit_text("❌ Текст не найден.")
        else:
            await status_msg.edit_text("❌ Ошибка сервиса распознавания.")
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await status_msg.edit_text("❌ Произошла ошибка. Проверьте интернет или размер фото.")
    return ConversationHandler.END

# ================= СЕРВЕР И ЗАПУСК =================

server = Flask(__name__)
@server.route("/")
def health(): return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    server.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Запуск веб-сервера для Render в отдельном потоке
    threading.Thread(target=run_flask, daemon=True).start()

    # Сборка приложения бота
    app = Application.builder().token(TOKEN).build()
    
    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Text(["ℹ️ Инфо", "Инфо"]), info_handler))

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text("🔳 Создать QR"), qr_request),
            MessageHandler(filters.Text("🖼 Конвертер"), img_request),
            MessageHandler(filters.Text("📝 Текст с фото"), ocr_request),
        ],
        states={
            QR_GENERATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, qr_process)],
            IMG_CONVERTING: [MessageHandler(filters.PHOTO, img_process)],
            WAITING_FOR_OCR: [MessageHandler(filters.PHOTO, ocr_process)],
        },
        fallbacks=[MessageHandler(filters.Text(["❌ Отмена", "Отмена"]), cancel)]
    )
    
    app.add_handler(conv)

    logger.info("--- БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ ---")
    app.run_polling(drop_pending_updates=True)
