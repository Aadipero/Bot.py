import os
import re
import sqlite3
import threading
import random
from urllib.parse import quote

from flask import Flask, redirect, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8521216823:AAFUg5Jg3uuaMuVREg076ZHCZhD_tAaGPGg").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "8423151783").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://bot1-py-9qyz.onrender.com").strip().rstrip("/")
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if not ADMIN_ID_RAW.isdigit():
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID.")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL is required, e.g. https://your-service.onrender.com")

ADMIN_ID = int(ADMIN_ID_RAW)

Path = __import__("pathlib").Path
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
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
        conn.execute("""
            INSERT INTO settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()

def normalize_number(raw):
    s = str(raw).strip()
    s = re.sub(r"[^\d+]", "", s)
    if not s:
        return None
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
    else:
        digits = s
        # 10-digit Indian number -> +91
        if len(digits) == 10 and digits.isdigit():
            s = "+91" + digits
            digits = digits
    if not digits.isdigit():
        return None
    if len(digits) < 8 or len(digits) > 15:
        return None
    return "+" + digits

def all_numbers():
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT number FROM numbers ORDER BY id")]

def add_numbers(text):
    # Parse numbers safely line-by-line so multiple pasted numbers
    # are not accidentally merged into one long candidate.
    cleaned = []
    seen = set()
    for line in (text or "").splitlines():
        # Allow comma/semicolon separated numbers on the same line.
        for item in re.split(r"[,;\s]+", line.strip()):
            n = normalize_number(item)
            if n and n not in seen:
                seen.add(n)
                cleaned.append(n)

    added = 0
    with db() as conn:
        for n in cleaned:
            cur = conn.execute("INSERT OR IGNORE INTO numbers(number) VALUES(?)", (n,))
            added += cur.rowcount
        conn.commit()
    return added, len(cleaned)

def is_admin(update):
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)

def wa_url(number):
    return "https://wa.me/" + number.lstrip("+").replace(" ", "")

def panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Numbers", callback_data="help_add"),
         InlineKeyboardButton("🎲 Random Page", callback_data="random")],
        [InlineKeyboardButton("🔗 Simple Page", callback_data="simple"),
         InlineKeyboardButton("📊 Number Count", callback_data="count")],
        [InlineKeyboardButton("🗑 Clear Numbers", callback_data="clear"),
         InlineKeyboardButton("⚙️ Set Link", callback_data="setlink")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Access denied.")
        return
    await update.message.reply_text(
        "👋 Admin Panel\n\n"
        "Numbers aur redirect pages yahin se manage karo.",
        reply_markup=panel()
    )

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    await update.message.reply_text(
        "📥 Numbers bhejo — ek line me ya bulk me.\n"
        "Example:\n+919876543210\n9876543211\n+919999999999\n\n"
        "10-digit Indian numbers me +91 automatically add hoga."
    )
    context.user_data["awaiting"] = "numbers"

async def setlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    await update.message.reply_text("🔗 Naya redirect link bhejo.\nExample: https://example.com")
    context.user_data["awaiting"] = "link"

async def random_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    nums = all_numbers()
    if not nums:
        await update.message.reply_text("⚠️ Pehle /add se numbers add karo.")
        return
    await update.message.reply_text(
        f"🎲 Random WhatsApp page ready:\n{PUBLIC_URL}/random",
        disable_web_page_preview=True
    )

async def simple_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    link = get_setting("simple_link")
    if not link:
        await update.message.reply_text("⚠️ Pehle /setlink se link set karo.")
        return
    await update.message.reply_text(
        f"🔗 Simple redirect page:\n{PUBLIC_URL}/simple",
        disable_web_page_preview=True
    )

async def numbers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    nums = all_numbers()
    if not nums:
        await update.message.reply_text("📭 No numbers saved.")
        return
    # Avoid an enormous Telegram message.
    if len(nums) <= 100:
        body = "\n".join(nums)
        await update.message.reply_text(f"📊 Total: {len(nums)}\n\n{body}")
    else:
        await update.message.reply_text(f"📊 Total saved numbers: {len(nums)}")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    with db() as conn:
        conn.execute("DELETE FROM numbers")
        conn.commit()
    await update.message.reply_text("🗑 All saved numbers cleared.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    mode = context.user_data.pop("awaiting", None)
    if mode == "numbers":
        added, parsed = add_numbers(update.message.text or "")
        await update.message.reply_text(
            f"✅ Done!\nParsed: {parsed}\nAdded: {added}\n"
            f"Total saved: {len(all_numbers())}",
            reply_markup=panel()
        )
    elif mode == "link":
        link = (update.message.text or "").strip()
        if not re.match(r"^https?://", link, re.I):
            await update.message.reply_text("❌ Link http:// ya https:// se start hona chahiye.")
            return
        set_setting("simple_link", link)
        await update.message.reply_text(
            f"✅ Link updated.\n\nSimple page:\n{PUBLIC_URL}/simple",
            reply_markup=panel(),
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text("Use /start to open the admin panel.")

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.edit_message_text("⛔ Access denied.")
        return

    data = q.data
    if data == "help_add":
        await q.message.reply_text(
            "📥 /add\n\nBulk numbers paste karo. One-per-line best rahega."
        )
    elif data == "random":
        nums = all_numbers()
        if not nums:
            await q.message.reply_text("⚠️ No numbers saved. /add use karo.")
        else:
            await q.message.reply_text(f"🎲 {PUBLIC_URL}/random", disable_web_page_preview=True)
    elif data == "simple":
        if not get_setting("simple_link"):
            await q.message.reply_text("⚠️ /setlink se link set karo.")
        else:
            await q.message.reply_text(f"🔗 {PUBLIC_URL}/simple", disable_web_page_preview=True)
    elif data == "count":
        await q.message.reply_text(f"📊 Saved numbers: {len(all_numbers())}")
    elif data == "clear":
        with db() as conn:
            conn.execute("DELETE FROM numbers")
            conn.commit()
        await q.message.reply_text("🗑 Numbers cleared.")
    elif data == "setlink":
        context.user_data["awaiting"] = "link"
        await q.message.reply_text("🔗 Ab naya redirect link bhejo.")

app_web = Flask(__name__)

@app_web.get("/")
def home():
    return "Bot is running."

@app_web.get("/random")
def random_page():
    nums = all_numbers()
    if not nums:
        return Response("No numbers available.", status=404, mimetype="text/plain")
    # Browser chooses a random saved number on each visit.
    js_nums = "[" + ",".join(repr(wa_url(n)) for n in nums) + "]"
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhatsApp Redirect</title>
<script>
const numbers = {js_nums};
const selected = numbers[Math.floor(Math.random() * numbers.length)];
window.location.replace(selected);
</script>
</head>
<body>Redirecting to WhatsApp…</body>
</html>"""
    return Response(html, mimetype="text/html")

@app_web.get("/simple")
def simple_page():
    link = get_setting("simple_link")
    if not link:
        return Response("Redirect link is not set.", status=404, mimetype="text/plain")
    # Server-side redirect, equivalent to a simple redirect page.
    return redirect(link, code=302)

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app_web.run(host="0.0.0.0", port=port, threaded=True)

def run_bot():
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("add", add_cmd))
    telegram_app.add_handler(CommandHandler("setlink", setlink_cmd))
    telegram_app.add_handler(CommandHandler("random", random_cmd))
    telegram_app.add_handler(CommandHandler("simple", simple_cmd))
    telegram_app.add_handler(CommandHandler("numbers", numbers_cmd))
    telegram_app.add_handler(CommandHandler("clear", clear_cmd))
    telegram_app.add_handler(CallbackQueryHandler(callbacks))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    telegram_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # IMPORTANT: python-telegram-bot polling must run in the MAIN thread.
    # Flask runs in the background so Render can health-check the service.
    db().close()
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    run_bot()
