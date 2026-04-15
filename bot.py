import os
import io
import logging
import threading
import qrcode
from flask import Flask
from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

# Состояния диалога
CHOOSING_TASK = 0
QR_GENERATING = 1
IMG_CONVERTING = 2

# Дизайн кнопок (Apple Style)
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🔳 Создать QR", "🖼 Конвертер"],
        ["📝 Текст с фото", "ℹ️ Инфо"]
    ], resize_keyboard=True)

# ================= ЛОГИКА ИНСТРУМЕНТОВ =================

def generate_qr(text):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

# ================= ХЕНДЛЕРЫ =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    welcome_text = (
        f"Привет, {user}! 👋\n\n"
        "Я — **iAssistant**. Твой минималистичный помощник для быстрых задач.\n"
        "Выберите действие в меню ниже:"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END

async def qr_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔗 Отправьте ссылку или текст для создания QR-кода:")
    return QR_GENERATING

async def qr_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    qr_img = generate_qr(text)
    await update.message.reply_photo(photo=qr_img, caption="✨ Ваш QR-код готов")
    return ConversationHandler.END

async def img_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Отправьте изображение (как фото), которое нужно сжать и перевести в PNG:")
    return IMG_CONVERTING

async def img_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = await update.message.photo[-1].get_file()
    img_bytes = await photo.download_as_bytearray()
    
    img = Image.open(io.BytesIO(img_bytes))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    
    await update.message.reply_document(document=out, filename="converted.png", caption="✅ Оптимизировано")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ================= ИНИЦИАЛИЗАЦИЯ =================

app = Application.builder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("🔳 Создать QR"), qr_request),
        MessageHandler(filters.Regex("🖼 Конвертер"), img_request),
    ],
    states={
        QR_GENERATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, qr_process)],
        IMG_CONVERTING: [MessageHandler(filters.PHOTO, img_process)],
    },
    fallbacks=[MessageHandler(filters.Regex("Отмена"), cancel)],
)

app.add_handler(CommandHandler("start", start))
app.add_handler(conv_handler)

# ================= WEB SERVER =================

server = Flask(__name__)

@server.route("/")
def health():
    return "iAssistant is Online", 200

def run_bot():
    print("🤖 iAssistant starting...")
    app.run_polling(stop_signals=None, drop_pending_updates=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=run_bot, daemon=True).start()
    server.run(host="0.0.0.0", port=port)
