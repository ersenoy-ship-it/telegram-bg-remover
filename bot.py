import os
import io
import logging
import requests
import threading
from PIL import Image
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# --- КОНФИГУРАЦИЯ ---
TOKEN = "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН" # Вставь свой токен!
OCR_API_KEY = "K89996852888957"

# Состояния (States)
QR_GENERATING, IMG_CONVERTING, WAITING_FOR_OCR, WAITING_FOR_OCR_ARABIC = range(1, 5)

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK ДЛЯ RENDER ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Статус: Бот активен 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

# --- КЛАВИАТУРА ---
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🏁 Создать QR"), KeyboardButton("🖼 Конвертер")],
        [KeyboardButton("📝 Текст (RU/EN)"), KeyboardButton("☪️ Текст (Arabic)")],
        [KeyboardButton("ℹ️ Инфо"), KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

# --- БАЗОВЫЕ КОМАНДЫ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот готов к работе! Выберите нужную функцию:",
        reply_markup=main_menu_keyboard()
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- ЛОГИКА QR (🏁) ---
async def qr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправьте текст или ссылку для генерации QR-кода:")
    return QR_GENERATING

async def qr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={text}"
    await update.message.reply_photo(qr_url, caption=f"Ваш QR-код готов ✅\nДанные: {text}")
    return ConversationHandler.END

# --- ЛОГИКА КОНВЕРТЕРА (🖼) ---
async def img_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Пришлите фото для конвертации в PNG:")
    return IMG_CONVERTING

async def img_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    img_bytes = await photo_file.download_as_bytearray()
    
    img = Image.open(io.BytesIO(img_bytes))
    out_io = io.BytesIO()
    img.save(out_io, format="PNG")
    out_io.seek(0)
    
    await update.message.reply_document(document=out_io, filename="converted_image.png")
    return ConversationHandler.END

# --- ЛОГИКА OCR (ОБЩЕЕ ЯДРО) ---
async def ocr_process_logic(update: Update, lang_settings):
    status_msg = await update.message.reply_text("🔍 Обрабатываю изображение...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        
        # Сжатие фото (чтобы API не «вылетало» по таймауту или размеру)
        img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        compressed_bio = io.BytesIO()
        img.save(compressed_bio, format="JPEG", quality=85)
        compressed_bio.seek(0)

        payload = {
            'apikey': OCR_API_KEY,
            'scale': True,
            **lang_settings
        }
        
        files = {'file': ('img.jpg', compressed_bio, 'image/jpeg')}
        response = requests.post('https://api.ocr.space/parse/image', files=files, data=payload, timeout=60)
        res = response.json()

        if res.get("OCRExitCode") == 1:
            text = res["ParsedResults"][0].get("ParsedText", "").strip()
            if text:
                await status_msg.edit_text(f"📖 **Распознанный текст:**\n\n`{text}`", parse_mode="Markdown")
            else:
                await status_msg.edit_text("❌ Текст на изображении не найден.")
        else:
            err = res.get("ErrorMessage", ["Неизвестная ошибка API"])[0]
            await status_msg.edit_text(f"❌ Ошибка API: {err}")
    except Exception as e:
        logger.error(f"OCR Critical Error: {e}")
        await status_msg.edit_text("❌ Ошибка связи с сервером. Попробуйте позже.")

# Хендлеры для разных языков
async def ocr_standard_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Пришлите фото для распознавания (RU/EN):")
    return WAITING_FOR_OCR

async def ocr_arabic_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("☪️ Пришлите фото с арабским текстом:")
    return WAITING_FOR_OCR_ARABIC

async def ocr_process_standard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ocr_process_logic(update, {'language': 'rus,eng', 'OCREngine': 2})
    return ConversationHandler.END

async def ocr_process_arabic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ocr_process_logic(update, {'language': 'ara', 'OCREngine': 1})
    return ConversationHandler.END

# --- ЗАПУСК ---
if __name__ == "__main__":
    # Запуск Flask в фоне
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Сборка бота
    application = Application.builder().token(TOKEN).build()
    
    # Настройка диалогов
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text("🏁 Создать QR"), qr_request),
            MessageHandler(filters.Text("🖼 Конвертер"), img_request),
            MessageHandler(filters.Text("📝 Текст (RU/EN)"), ocr_standard_request),
            MessageHandler(filters.Text("☪️ Текст (Arabic)"), ocr_arabic_request),
        ],
        states={
            QR_GENERATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, qr_process)],
            IMG_CONVERTING: [MessageHandler(filters.PHOTO, img_process)],
            WAITING_FOR_OCR: [MessageHandler(filters.PHOTO, ocr_process_standard)],
            WAITING_FOR_OCR_ARABIC: [MessageHandler(filters.PHOTO, ocr_process_arabic)],
        },
        fallbacks=[MessageHandler(filters.Text(["❌ Отмена", "Отмена"]), cancel)]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    
    print("--- БОТ ЗАПУЩЕН И ГОТОВ К ТЕСТАМ ---")
    application.run_polling(drop_pending_updates=True)
