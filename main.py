import asyncio
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import yt_dlp

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "3000"))
KEY_DAYS = int(os.getenv("KEY_DAYS", "30"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "100"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "2"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
COOKIES_FILE = Path(os.getenv("COOKIES_FILE", "/app/cookies.txt"))

app = FastAPI(title="Royal API", version="1.0.0")
download_slots = asyncio.Semaphore(MAX_CONCURRENT)
bot_app: Application | None = None

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be", "music.youtube.com"
}


def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def db_init():
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                user_id BIGINT PRIMARY KEY,
                api_key TEXT UNIQUE NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                daily_limit INTEGER NOT NULL,
                day_requests INTEGER NOT NULL DEFAULT 0,
                day_audio INTEGER NOT NULL DEFAULT 0,
                day_video INTEGER NOT NULL DEFAULT 0,
                total_requests BIGINT NOT NULL DEFAULT 0,
                total_audio BIGINT NOT NULL DEFAULT 0,
                total_video BIGINT NOT NULL DEFAULT 0,
                usage_day DATE NOT NULL
            )
            """)
            c.commit()


def now_utc():
    return datetime.now(timezone.utc)


def new_key():
    return "ROYAL_" + secrets.token_hex(8)


def get_record_by_user(user_id):
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM api_keys WHERE user_id=%s", (user_id,))
            return cur.fetchone()


def get_record_by_key(key):
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM api_keys WHERE api_key=%s", (key,))
            return cur.fetchone()


def reset_daily_if_needed(user_id):
    today = now_utc().date()
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE api_keys
                SET day_requests=0, day_audio=0, day_video=0, usage_day=%s
                WHERE user_id=%s AND usage_day <> %s
            """, (today, user_id, today))
            c.commit()


def create_or_get_key(user_id):
    reset_daily_if_needed(user_id)
    row = get_record_by_user(user_id)
    current = now_utc()
    if row and row[2] and row[4] > current:
        return row

    key = new_key()
    expires = current + timedelta(days=KEY_DAYS)
    today = current.date()

    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("""
                INSERT INTO api_keys
                (user_id, api_key, active, created_at, expires_at, daily_limit, usage_day)
                VALUES (%s,%s,TRUE,%s,%s,%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET
                  api_key=EXCLUDED.api_key,
                  active=TRUE,
                  created_at=EXCLUDED.created_at,
                  expires_at=EXCLUDED.expires_at,
                  daily_limit=EXCLUDED.daily_limit,
                  day_requests=0, day_audio=0, day_video=0,
                  usage_day=EXCLUDED.usage_day
            """, (user_id, key, current, expires, DAILY_LIMIT, today))
            c.commit()
    return get_record_by_user(user_id)


def renew_key(user_id):
    current = now_utc()
    expires = current + timedelta(days=KEY_DAYS)
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("""
                UPDATE api_keys
                SET active=TRUE, expires_at=%s
                WHERE user_id=%s
            """, (expires, user_id))
            c.commit()
    return get_record_by_user(user_id)


def revoke_and_new(user_id):
    with db_connect() as c:
        with c.cursor() as cur:
            cur.execute("UPDATE api_keys SET active=FALSE WHERE user_id=%s", (user_id,))
            c.commit()
    return create_or_get_key(user_id)


def format_key(row):
    # PostgreSQL row order matches CREATE TABLE order.
    if not row:
        return "No API key found. Use /start first."

    user_id, key, active, created, expires, limit_, day_req, day_audio, day_video, total_req, total_audio, total_video, usage_day = row
    current = now_utc()
    is_active = bool(active) and expires > current
    days_left = max(0, (expires.date() - current.date()).days)

    return (
        "🔑 <b>Your API Key</b>\n\n"
        f"<b>API Key:</b>\n<code>{key}</code>\n\n"
        f"<b>Status:</b> {'🟢 Active' if is_active else '🔴 Expired/Revoked'}\n"
        f"<b>Daily Limit:</b> {limit_:,}\n\n"
        "<b>Today's Usage:</b>\n"
        f"📊 Requests: {day_req:,}\n"
        f"🎵 Audio: {day_audio:,}\n"
        f"🎬 Video: {day_video:,}\n\n"
        "<b>All-Time Usage:</b>\n"
        f"📊 Total Requests: {total_req:,}\n"
        f"🎵 Total Audio: {total_audio:,}\n"
        f"🎬 Total Video: {total_video:,}\n\n"
        f"<b>Created:</b> {created.astimezone().strftime('%d %b %Y, %I:%M %p')}\n"
        f"<b>Expires:</b> {expires.astimezone().strftime('%d %b %Y, %I:%M %p')}\n"
        f"<b>Days Left:</b> {days_left} days"
    )


def key_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Renew", callback_data="renew")],
        [InlineKeyboardButton("🔄 Revoke & Get New Key", callback_data="newkey")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
    ])


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = create_or_get_key(update.effective_user.id)
    await update.message.reply_text(
        format_key(row),
        parse_mode="HTML",
        reply_markup=key_keyboard(),
    )


async def key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = create_or_get_key(update.effective_user.id)
    await update.message.reply_text(
        format_key(row),
        parse_mode="HTML",
        reply_markup=key_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if q.data == "renew":
        row = renew_key(user_id)
        await q.edit_message_text(
            format_key(row), parse_mode="HTML", reply_markup=key_keyboard()
        )
    elif q.data == "newkey":
        row = revoke_and_new(user_id)
        await q.edit_message_text(
            format_key(row), parse_mode="HTML", reply_markup=key_keyboard()
        )
    else:
        await q.edit_message_text(
            "🏠 <b>Royal API Key Bot</b>\n\nUse /key to view your API key.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 My API Key", callback_data="back")]
            ]),
        )


def check_api_key(supplied):
    if not supplied:
        raise HTTPException(401, "API key required.")
    row = get_record_by_key(supplied)
    if not row:
        raise HTTPException(401, "Invalid API key.")

    user_id, key, active, created, expires, limit_, day_req, day_audio, day_video, total_req, total_audio, total_video, usage_day = row
    current = now_utc()

    if not active or expires <= current:
        raise HTTPException(403, "API key expired or revoked.")

    reset_daily_if_needed(user_id)
    row = get_record_by_key(supplied)
    if row[6] >= row[5]:
        raise HTTPException(429, "Daily API limit reached.")

    return row


def increment_usage(user_id, media_type):
    reset_daily_if_needed(user_id)
    with db_connect() as c:
        with c.cursor() as cur:
            if media_type == "audio":
                cur.execute("""
                    UPDATE api_keys
                    SET day_requests=day_requests+1, day_audio=day_audio+1,
                        total_requests=total_requests+1, total_audio=total_audio+1
                    WHERE user_id=%s
                """, (user_id,))
            else:
                cur.execute("""
                    UPDATE api_keys
                    SET day_requests=day_requests+1, day_video=day_video+1,
                        total_requests=total_requests+1, total_video=total_video+1
                    WHERE user_id=%s
                """, (user_id,))
            c.commit()


def normalize_youtube_url(value: str):
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return f"https://www.youtube.com/watch?v={value}"
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only YouTube URLs are allowed.")
    if (parsed.hostname or "").lower() not in YOUTUBE_HOSTS:
        raise HTTPException(400, "Only YouTube URLs are supported.")
    return value


def cookie_path():
    return str(COOKIES_FILE) if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size else None


@app.get("/")
async def root():
    return {"status": "running", "service": "royal-api"}


@app.get("/health")
async def health():
    try:
        with db_connect() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "yt_dlp": yt_dlp.version.__version__,
        "cookies_configured": bool(cookie_path()),
    }


@app.get("/download")
async def download(
    url: str = Query(...),
    type: str = Query("audio", pattern="^(audio|video)$"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
):
    supplied = x_api_key or api_key
    row = check_api_key(supplied)
    user_id = row[0]
    target = normalize_youtube_url(url)

    workdir = Path(tempfile.mkdtemp(prefix="royal_"))
    template = str(workdir / "%(id)s.%(ext)s")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": template,
        "restrictfilenames": True,
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 30,
        "max_filesize": MAX_FILE_MB * 1024 * 1024,
        "format": "bestaudio/best" if type == "audio" else "best[ext=mp4]/best",
    }

    if type == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }]

    cp = cookie_path()
    if cp:
        opts["cookiefile"] = cp

    async with download_slots:
        try:
            def run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(target, download=True)
            info = await asyncio.to_thread(run)

            output = [p for p in workdir.iterdir() if p.is_file()]
            if not output:
                raise RuntimeError("No output file produced.")
            media = max(output, key=lambda p: p.stat().st_mtime)

            increment_usage(user_id, type)

            safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "", info.get("title") or "download")
            safe_title = safe_title.strip()[:80] or "download"

            def cleanup():
                shutil.rmtree(workdir, ignore_errors=True)

            return FileResponse(
                media,
                filename=safe_title + media.suffix,
                media_type="audio/mpeg" if media.suffix.lower() == ".mp3" else "application/octet-stream",
                background=BackgroundTask(cleanup),
            )
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except Exception as e:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(502, f"Download failed: {str(e)[:400]}")


@app.on_event("startup")
async def startup():
    global bot_app
    db_init()

    if not BOT_TOKEN:
        return

    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start_cmd))
    bot_app.add_handler(CommandHandler("key", key_cmd))
    bot_app.add_handler(CallbackQueryHandler(button_handler))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)


@app.on_event("shutdown")
async def shutdown():
    global bot_app
    if bot_app:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
