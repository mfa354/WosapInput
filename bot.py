import logging
import os
import re
from typing import Optional

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========= Utils =========
def escape_markdown_v2(text: str) -> str:
    """Escape special characters for MarkdownV2"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))


def get_env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    """Read INT env var, sanitize common paste mistakes (spaces / leading '=')"""
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip()
    if val.startswith("="):
        val = val[1:].strip()
    if val == "":
        return default
    try:
        return int(val)
    except ValueError:
        # Tampilkan apa yang benar-benar terbaca agar mudah debug di Railway Logs
        raise ValueError(f"Environment variable {name} must be an integer (got {raw!r})")


# ========= Logging =========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ========= Config via ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

TARGET_USER_ID = get_env_int("TARGET_USER_ID", None)  # integer, required for sending
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")  # e.g. https://your-app.up.railway.app
PORT = int(os.getenv("PORT", "8080"))

# Auto-mode: webhook if WEBHOOK_BASE provided, else polling (override with MODE)
MODE = (os.getenv("MODE") or ("webhook" if WEBHOOK_BASE else "polling")).lower().strip()

# ========= Bot Logic =========
class PhoneBot:
    def __init__(self):
        self.waiting_for_number = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.waiting_for_number[user_id] = True

        await update.message.reply_text(
            "🤖 *Bot Pengirim Nomor Telepon*\n\n"
            "Silakan masukkan nomor telepon (contoh: 62858578089187)\n"
            "Bot akan mengirim nomor tanpa kode negara (62) ke akun tujuan.",
            parse_mode="Markdown",
        )

    def process_phone_number(self, phone_number: str) -> str:
        """Proses nomor telepon: hapus karakter non-digit dan kode negara 62"""
        clean_number = "".join(filter(str.isdigit, phone_number))
        if clean_number.startswith("62"):
            return clean_number[2:]
        return clean_number

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if not self.waiting_for_number.get(user_id, False):
            await update.message.reply_text("Gunakan /start untuk memulai proses input nomor telepon.")
            return

        text = (update.message.text or "").strip()
        digits_only = "".join(filter(str.isdigit, text))

        if not digits_only:
            await update.message.reply_text(
                "❌ *Input tidak valid!*\n\n"
                "Harap masukkan nomor telepon yang valid (minimal satu angka).\n"
                "Contoh: 62858578089187",
                parse_mode="Markdown",
            )
            return

        processed_number = self.process_phone_number(text)

        if TARGET_USER_ID is None:
            await update.message.reply_text(
                "⚠️ *TARGET_USER_ID belum dikonfigurasi di ENV!*\n\n"
                "Set variabel lingkungan `TARGET_USER_ID` (angka) di Railway.",
                parse_mode="Markdown",
            )
            return

        try:
            await context.bot.send_message(
                chat_id=TARGET_USER_ID,
                text=f"`{processed_number}`",
                parse_mode="Markdown",
            )
            await update.message.reply_text(
                "✅ *Berhasil terkirim!*\n\n"
                f"Nomor asli: `{text}`\n"
                f"Nomor terkirim: `{processed_number}`\n\n"
                "Masukkan nomor lagi atau gunakan /start untuk memulai ulang.",
                parse_mode="Markdown",
            )

        except Exception as e:
            error_msg = str(e).lower()
            logger.error("Error sending message: %s", e)

            if "chat not found" in error_msg:
                error_text = (
                    "❌ *Target chat tidak ditemukan!*\n\n"
                    "User tujuan belum pernah /start bot ini.\n"
                    "Minta user tujuan untuk:\n"
                    "1. Klik /start pada bot ini\n"
                    "2. Kirim pesan apa saja ke bot"
                )
            elif "blocked" in error_msg:
                error_text = (
                    "❌ *Bot diblokir oleh user tujuan!*\n\n"
                    "User tujuan telah memblokir bot ini.\n"
                    "Minta user untuk unblock bot terlebih dahulu."
                )
            elif "forbidden" in error_msg:
                error_text = (
                    "❌ *Tidak ada izin mengirim pesan!*\n\n"
                    "Pastikan user tujuan sudah /start bot ini."
                )
            else:
                error_text = (
                    "❌ *Gagal mengirim pesan!*\n\n"
                    f"Error: `{str(e)}`\n"
                    "Silakan coba lagi atau hubungi administrator."
                )

            await update.message.reply_text(error_text, parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "🤖 *Bot Pengirim Nomor Telepon*\n\n"
            "*Cara Penggunaan:*\n"
            "1. Ketik /start untuk memulai\n"
            "2. Masukkan nomor telepon (contoh: 62858578089187)\n"
            "3. Bot akan mengirim nomor tanpa kode '62' ke akun tujuan\n"
            "4. Ulangi langkah 2 untuk nomor berikutnya\n\n"
            "*Perintah yang tersedia:*\n"
            "/start - Mulai proses input nomor\n"
            "/help - Tampilkan bantuan ini\n"
            "/myid - Lihat Chat ID Anda\n"
            "/test - Test koneksi ke target user\n\n"
            "*Contoh:*\n"
            "Input: `62858578089187`\n"
            "Output: `858578089187`"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def get_my_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username or "Tidak ada username"
        first_name = update.effective_user.first_name or "Tidak ada nama"

        target_info = f"`{TARGET_USER_ID}`" if TARGET_USER_ID is not None else "_(belum diset)_"
        await update.message.reply_text(
            "👤 *Info Akun Anda:*\n\n"
            f"Chat ID: `{user_id}`\n"
            f"Username: @{username}\n"
            f"Nama: {first_name}\n\n"
            f"Target saat ini: {target_info}",
            parse_mode="Markdown",
        )

    async def test_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if TARGET_USER_ID is None:
            await update.message.reply_text(
                "⚠️ *TARGET_USER_ID belum dikonfigurasi di ENV!*\n"
                "Set `TARGET_USER_ID` di Railway, lalu coba lagi.",
                parse_mode="Markdown",
            )
            return

        try:
            await context.bot.send_message(
                chat_id=TARGET_USER_ID,
                text="🔄 Test koneksi dari bot"
            )
            await update.message.reply_text(
                "✅ *Test berhasil!*\n\nBot berhasil mengirim pesan ke target user.",
                parse_mode="Markdown",
            )
        except Exception as e:
            error_msg = str(e)
            logger.error("Test connection error: %s", error_msg)
            await update.message.reply_text(
                "❌ *Test gagal!*\n\n"
                f"Error: `{error_msg}`\n\n"
                "*Solusi:*\n"
                "1. Pastikan target user sudah /start bot ini\n"
                "2. Cek Chat ID target user dengan /myid\n"
                "3. Pastikan bot tidak diblokir target user",
                parse_mode="Markdown",
            )


def main():
    """Main function untuk menjalankan bot (polling lokal / webhook Railway)"""
    phone_bot = PhoneBot()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", phone_bot.start))
    application.add_handler(CommandHandler("help", phone_bot.help_command))
    application.add_handler(CommandHandler("myid", phone_bot.get_my_id))
    application.add_handler(CommandHandler("test", phone_bot.test_connection))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, phone_bot.handle_message))

    print(f"🤖 Mode: {MODE.upper()}")
    if MODE == "webhook":
        if not WEBHOOK_BASE:
            raise RuntimeError("WEBHOOK_BASE env var is required for webhook mode")
        url_path = BOT_TOKEN
        webhook_url = f"{WEBHOOK_BASE.rstrip('/')}/{url_path}"
        print(f"🌐 Setting webhook: {webhook_url}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        print("📡 Running with polling (lokal/dev).")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
