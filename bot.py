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

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN")
# Укажи здесь свою ссылку (например, t.me/твой_ник)
DEV_URL = "https://t.me/your_username" 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния диалога для ConversationHandler
QR_GENERATING = 1
IMG_CONVERTING = 2
WAITING_FOR_OCR = 3

# Дизайн кнопок (Стиль Apple - минимализм и эмодзи)
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔳 Создать QR"), KeyboardButton("🖼 Конвертер")],
        [KeyboardButton("📝 Текст с фото"), KeyboardButton("ℹ️ Инфо")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def generate_qr(text):
    """Генерация QR-кода в памяти"""
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ================= ОБРАБОТЧИКИ (ХЕНДЛЕРЫ) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start и приветствие"""
    user = update.effective_user.first_name
    welcome_text = (
        f"Привет, {user}! 👋\n\n"
        "Я — **iAssistant**. Твой минималистичный помощник для быстрых задач.\n"
        "Выберите действие в меню ниже:"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END

async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Кавычки должны быть и в начале, и в конце ссылки!
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💻 Связаться с разработчиком", url="https://t.me/ZYB_19")]
    ])
    info_text = (
        " **iAssistant Support**\n\n"
        "**Версия:** 2.1 (Stable)\n"
        "**Статус:** Все системы работают ✅\n\n"
        "**Инструкция:**\n"
        "1. Выберите инструмент в меню.\n"
        "2. Следуйте коротким указаниям.\n"
        "3. Кнопка «Отмена» прерывает текущую задачу.\n\n"
        "Бот оптимизирован для работы на Render Free Tier."
    )
    await update.message.reply_text(info_text, reply_markup=keyboard, parse_mode="Markdown")

# --- Логика QR-генератора ---
async def qr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔗 Отправьте ссылку или текст для создания QR-кода:", reply_markup=main_menu_keyboard())
    return QR_GENERATING

async def qr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    qr_img = generate_qr(text)
    await update.message.reply_photo(photo=qr_img, caption="✨ Ваш QR-код готов", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- Логика Конвертера (PNG) ---
async def img_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Пришлите фото, которое нужно сконвертировать в PNG:")
    return IMG_CONVERTING

async def img_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Обработка изображения...")
    photo = await update.message.photo[-1].get_file()
    img_bytes = await photo.download_as_bytearray()
    
    img = Image.open(io.BytesIO(img_bytes))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    
    await update.message.reply_document(document=out, filename="result.png", caption="✅ Сжато и конвертировано", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- Логика OCR (Текст с фото) ---
async def ocr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Пришлите четкое фото с текстом для распознавания:")
    return WAITING_FOR_OCR

async def ocr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 Анализирую текст...")
    try:
        photo = await update.message.photo[-1].get_file()
        img_url = photo.file_path
        # Используем внешний API, чтобы не нагружать RAM сервера
        api_url = f"https://api.ocr.space/parse/imageurl?apikey=K89996852888957&url={img_url}&language=rus"
        
        response = requests.get(api_url).json()
        
        if response.get("ParsedResults"):
            text = response["ParsedResults"][0]["ParsedText"]
            if text.strip():
                await update.message.reply_text(f"📖 **Распознанный текст:**\n\n`{text}`", 
                                               parse_mode="Markdown", reply_markup=main_menu_keyboard())
            else:
                await update.message.reply_text("Текст на фото не найден.", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("Ошибка сервиса OCR. Попробуйте позже.", reply_markup=main_menu_keyboard())
            
    except Exception as e:
        logger.error(f"OCR Error: {e}")
        await update.message.reply_text("Не удалось распознать текст.")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    await update.message.reply_text("Действие отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ================= ИНИЦИАЛИЗАЦИЯ И ЗАПУСК =================

# Создаем приложение
application = Application.builder().token(TOKEN).build()

# 1. Сначала регистрируем обычные команды
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Regex("ℹ️ Инфо"), info_handler))

# 2. Регистрируем диалоговый обработчик
conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("🔳 Создать QR"), qr_request),
        MessageHandler(filters.Regex("🖼 Конвертер"), img_request),
        MessageHandler(filters.Regex("📝 Текст с фото"), ocr_request),
    ],
    states={
        QR_GENERATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, qr_process)],
        IMG_CONVERTING: [MessageHandler(filters.PHOTO, img_process)],
        WAITING_FOR_OCR: [MessageHandler(filters.PHOTO, ocr_process)],
    },
    fallbacks=[
        MessageHandler(filters.Regex("❌ Отмена"), cancel),
        CommandHandler("start", start)
    ],
)

application.add_handler(conv_handler)

# --- Настройка Flask (для Render) ---
server = Flask(__name__)

@server.route("/")
def health_check():
    return "iAssistant is Online", 200

def run_bot():
    print("🤖 Бот запускается...")
    # drop_pending_updates=True сбрасывает старые сообщения
    application.run_polling(stop_signals=None, drop_pending_updates=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Запускаем бота в отдельном потоке
    threading.Thread(target=run_bot, daemon=True).start()
    # Запускаем веб-сервер
    print(f"🚀 Веб-сервер на порту {port}")
    server.run(host="0.0.0.0", port=port)
