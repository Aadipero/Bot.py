import os
import sqlite3
import random
import html
import re
from pathlib import Path
from urllib.parse import quote

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if not ADMIN_ID.isdigit():
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID.")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL must be your Render service URL, e.g. https://your-service.onrender.com")

ADMIN_ID = int(ADMIN_ID)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_setting(key, default=""):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

def set_setting(key, value):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        conn.commit()

def normalize_number(raw):
    s = raw.strip()
    if not s:
        return None
    # Keep + and digits only.
    s = re.sub(r"[^\d+]", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        # For India, allow 10-digit input and automatically add +91.
        digits = re.sub(r"\D", "", s)
        if len(digits) == 10:
            s = "+91" + digits
        else:
            s = "+" + digits
    digits = re.sub(r"\D", "", s)
    if len(digits) < 8 or len(digits) > 15:
        return None
    return "+" + digits

def add_numbers(text):
    # Accept one number per line, comma/space/semicolon separated too.
    raw_items = re.split(r"[\s,;]+", text.strip())
    added = 0
    invalid = 0
    with db() as conn:
        for raw in raw_items:
            n = normalize_number(raw)
            if not n:
                invalid += 1
                continue
            try:
                conn.execute("INSERT INTO numbers(number) VALUES(?)", (n,))
                added += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    return added, invalid

def get_numbers():
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT number FROM numbers ORDER BY id").fetchall()]

def clear_numbers():
    with db() as conn:
        conn.execute("DELETE FROM numbers")
        conn.commit()

def is_admin(update):
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)

async def deny(update):
    if update.effective_message:
        await update.effective_message.reply_text("⛔ Admin only.")

def panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Numbers", callback_data="help_add"),
         InlineKeyboardButton("📊 Count", callback_data="count")],
        [InlineKeyboardButton("🎲 Random Page", callback_data="random"),
         InlineKeyboardButton("🔗 Simple Page", callback_data="simple")],
        [InlineKeyboardButton("🔧 Set Link", callback_data="setlink"),
         InlineKeyboardButton("📋 Numbers", callback_data="numbers")],
        [InlineKeyboardButton("🗑 Clear Numbers", callback_data="clear")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await deny(update)
    await update.message.reply_text(
        "👋 Admin Panel\n\n"
        "Numbers aur redirect link yahin se manage karo.\n\n"
        "Commands:\n"
        "/add — bulk numbers add\n"
        "/numbers — saved numbers count\n"
        "/clear — delete all numbers\n"
        "/setlink LINK — simple redirect link set\n"
        "/random — random-number page\n"
        "/simple — simple redirect page\n"
        "/panel — buttons",
        reply_markup=panel()
    )

async def panel_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=panel())

async def add_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    context.user_data["waiting_for_numbers"] = True
    await update.message.reply_text(
        "📥 Ab numbers bhejo.\n"
        "Ek line me ek number ya space/comma separated bulk list.\n\n"
        "Example:\n+919876543210\n+919812345678\n\n"
        "India ke 10-digit numbers ko +91 automatically milega."
    )

async def text_handler(update, context):
    if not is_admin(update):
        return
    if not context.user_data.get("waiting_for_numbers"):
        return
    text = update.message.text or ""
    added, invalid = add_numbers(text)
    context.user_data["waiting_for_numbers"] = False
    total = len(get_numbers())
    await update.message.reply_text(
        f"✅ Added: {added}\n"
        f"⚠️ Invalid/skipped: {invalid}\n"
        f"📊 Total saved: {total}"
    )

async def numbers_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    nums = get_numbers()
    if not nums:
        return await update.message.reply_text("📭 No numbers saved.")
    # Avoid huge Telegram messages.
    preview = "\n".join(nums[:100])
    more = f"\n\n...and {len(nums)-100} more." if len(nums) > 100 else ""
    await update.message.reply_text(f"📊 Total: {len(nums)}\n\n{preview}{more}")

async def clear_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    clear_numbers()
    await update.message.reply_text("🗑 All saved numbers cleared.")

async def setlink_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    if not context.args:
        return await update.message.reply_text("Usage: /setlink https://example.com")
    link = context.args[0].strip()
    if not (link.startswith("https://") or link.startswith("http://")):
        return await update.message.reply_text("❌ Link must start with http:// or https://")
    set_setting("redirect_link", link)
    await update.message.reply_text(f"✅ Redirect link updated:\n{link}")

def page_url(mode):
    return f"{PUBLIC_URL}/page?mode={quote(mode)}"

async def random_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    if not get_numbers():
        return await update.message.reply_text("❌ Pehle /add se numbers add karo.")
    await update.message.reply_text(
        "🎲 Random WhatsApp page ready:\n"
        f"{page_url('random')}"
    )

async def simple_cmd(update, context):
    if not is_admin(update):
        return await deny(update)
    link = get_setting("redirect_link")
    if not link:
        return await update.message.reply_text("❌ Pehle /setlink se link set karo.")
    await update.message.reply_text(
        "🔗 Simple redirect page ready:\n"
        f"{page_url('simple')}"
    )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return await q.edit_message_text("⛔ Admin only.")
    data = q.data
    if data == "help_add":
        context.user_data["waiting_for_numbers"] = True
        return await q.message.reply_text(
            "📥 Numbers bhejo — bulk me bhi bhej sakte ho.\n"
            "10-digit Indian numbers automatically +91 ho jayenge."
        )
    if data == "count":
        return await q.message.reply_text(f"📊 Saved numbers: {len(get_numbers())}")
    if data == "numbers":
        nums = get_numbers()
        if not nums:
            return await q.message.reply_text("📭 No numbers saved.")
        return await q.message.reply_text(f"📊 Total saved: {len(nums)}\n\n" + "\n".join(nums[:100]))
    if data == "random":
        if not get_numbers():
            return await q.message.reply_text("❌ Pehle numbers add karo.")
        return await q.message.reply_text(f"🎲 {page_url('random')}")
    if data == "simple":
        if not get_setting("redirect_link"):
            return await q.message.reply_text("❌ Pehle /setlink LINK use karo.")
        return await q.message.reply_text(f"🔗 {page_url('simple')}")
    if data == "setlink":
        context.user_data["waiting_for_link"] = True
        return await q.message.reply_text("🔗 Ab naya http/https link bhejo.")
    if data == "clear":
        clear_numbers()
        return await q.message.reply_text("🗑 All numbers cleared.")

async def link_text_handler(update, context):
    if not is_admin(update):
        return
    if not context.user_data.get("waiting_for_link"):
        return False
    link = update.message.text.strip()
    if not (link.startswith("https://") or link.startswith("http://")):
        await update.message.reply_text("❌ Valid http:// ya https:// link bhejo.")
        return True
    set_setting("redirect_link", link)
    context.user_data["waiting_for_link"] = False
    await update.message.reply_text(f"✅ Link changed:\n{link}")
    return True

async def smart_text(update, context):
    if await link_text_handler(update, context):
        return
    await text_handler(update, context)

def html_random():
    # Number is chosen when the public page is opened, matching the screenshot's behavior.
    nums = get_numbers()
    if not nums:
        return "<!doctype html><meta charset='utf-8'><title>Empty</title><h3>No numbers available.</h3>"
    js_numbers = "[" + ",".join(repr(n) for n in nums) + "]"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WhatsApp Redirect</title>
<script>
function redirectToWhatsApp() {{
    const numbers = {js_numbers};
    const selectedNumber = numbers[Math.floor(Math.random() * numbers.length)];
    const whatsappLink = "https://wa.me/" + selectedNumber.replace(/\\D/g, "");
    window.location.replace(whatsappLink);
}}
</script>
</head>
<body onload="redirectToWhatsApp()"></body>
</html>"""

def html_simple():
    link = get_setting("redirect_link")
    if not link:
        return "<!doctype html><h3>Redirect link not configured.</h3>"
    safe = html.escape(link, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="0;url={safe}">
<title>Redirecting...</title>
</head>
<body></body>
</html>"""

# Public web server: this bot uses Telegram's webhook mode, so Render only needs one web process.
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import urllib.parse

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/page":
            qs = urllib.parse.parse_qs(parsed.query)
            mode = qs.get("mode", ["random"])[0]
            body = (html_random() if mode == "random" else html_simple()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def start_public_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), WebHandler)
    server.serve_forever()

def main():
    threading.Thread(target=start_public_server, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("panel", panel_cmd))
    application.add_handler(CommandHandler("add", add_cmd))
    application.add_handler(CommandHandler("numbers", numbers_cmd))
    application.add_handler(CommandHandler("clear", clear_cmd))
    application.add_handler(CommandHandler("setlink", setlink_cmd))
    application.add_handler(CommandHandler("random", random_cmd))
    application.add_handler(CommandHandler("simple", simple_cmd))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_text))

    # Run polling. Render's web process stays alive because the public HTTP server is running.
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
