import os
import re
import secrets
import asyncio
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
import yt_dlp


# =========================
# CONFIG
# =========================

APP_NAME = "ROYAL YouTube API"

DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "3000"))
KEY_DAYS = int(os.getenv("KEY_DAYS", "30"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "100"))

DATABASE_URL = os.getenv("DATABASE_URL", "")

DOWNLOAD_DIR = "/tmp/royal_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

db_pool = None


# =========================
# DATABASE
# =========================

def get_database_url():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    # Heroku can provide postgres://
    if DATABASE_URL.startswith("postgres://"):
        return DATABASE_URL.replace(
            "postgres://",
            "postgresql://",
            1
        )

    return DATABASE_URL


async def get_pool():
    global db_pool

    if db_pool is None:
        db_pool = await asyncpg.create_pool(
            dsn=get_database_url(),
            min_size=1,
            max_size=5,
            command_timeout=60,
        )

    return db_pool


async def init_db():
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                api_key TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                daily_limit INTEGER NOT NULL DEFAULT 3000,

                daily_count INTEGER NOT NULL DEFAULT 0,
                daily_date DATE NOT NULL,

                total_requests BIGINT NOT NULL DEFAULT 0,
                audio_requests BIGINT NOT NULL DEFAULT 0,
                video_requests BIGINT NOT NULL DEFAULT 0
            )
            """
        )

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_keys_api_key
            ON api_keys(api_key)
            """
        )

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_keys_user_id
            ON api_keys(user_id)
            """
        )


# =========================
# CREATE API KEY
# =========================

async def create_key(user_id: int):
    pool = await get_pool()

    now = datetime.now(timezone.utc)
    expires = now.replace(
        year=now.year + (now.month + KEY_DAYS // 365)
    ) if False else now

    # Correct day-based expiry
    from datetime import timedelta
    expires = now + timedelta(days=KEY_DAYS)

    api_key = "ROYAL_" + secrets.token_hex(8)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO api_keys (
                user_id,
                api_key,
                created_at,
                expires_at,
                daily_limit,
                daily_date
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_id,
            api_key,
            now,
            expires,
            DAILY_LIMIT,
            now.date(),
        )

    return (
        api_key,
        now.isoformat(),
        expires.isoformat(),
    )


# =========================
# API KEY VALIDATION
# =========================

async def validate_api_key(api_key: str, request_type: str):
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key is required"
        )

    pool = await get_pool()

    today = datetime.now(timezone.utc).date()

    async with pool.acquire() as conn:
        async with conn.transaction():

            row = await conn.fetchrow(
                """
                SELECT *
                FROM api_keys
                WHERE api_key = $1
                FOR UPDATE
                """,
                api_key,
            )

            if not row:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid API Key"
                )

            now = datetime.now(timezone.utc)

            if row["expires_at"] <= now:
                raise HTTPException(
                    status_code=401,
                    detail="API Key Expired"
                )

            daily_count = row["daily_count"]

            # New day = reset counter
            if row["daily_date"] != today:
                daily_count = 0

                await conn.execute(
                    """
                    UPDATE api_keys
                    SET daily_count = 0,
                        daily_date = $1
                    WHERE id = $2
                    """,
                    today,
                    row["id"],
                )

            if daily_count >= row["daily_limit"]:
                raise HTTPException(
                    status_code=429,
                    detail="Daily API limit reached"
                )

            await conn.execute(
                """
                UPDATE api_keys
                SET
                    daily_count = daily_count + 1,
                    total_requests = total_requests + 1,
                    audio_requests =
                        audio_requests +
                        CASE
                            WHEN $1 = 'audio' THEN 1
                            ELSE 0
                        END,
                    video_requests =
                        video_requests +
                        CASE
                            WHEN $1 = 'video' THEN 1
                            ELSE 0
                        END
                WHERE id = $2
                """,
                request_type,
                row["id"],
            )

            return row


# =========================
# FASTAPI
# =========================

app = FastAPI(
    title=APP_NAME,
    description="ROYAL YouTube Downloader API",
    version="1.0.0",
)


@app.on_event("startup")
async def startup():
    await init_db()


@app.on_event("shutdown")
async def shutdown():
    global db_pool

    if db_pool:
        await db_pool.close()
        db_pool = None


# =========================
# HOME
# =========================

@app.get("/")
async def home():
    return {
        "status": "running",
        "name": APP_NAME,
        "docs": "/docs",
        "health": "/health",
    }


# =========================
# HEALTH
# =========================

@app.get("/health")
async def health():
    try:
        pool = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")

        return {
            "status": "healthy",
            "database": "connected"
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e)
        }


# =========================
# YOUTUBE URL CHECK
# =========================

def normalize_youtube_url(url: str):
    url = url.strip()

    pattern = re.compile(
        r"^(https?://)?"
        r"(www\.)?"
        r"(youtube\.com|youtu\.be)"
        r"/"
    )

    if not pattern.search(url):
        raise HTTPException(
            status_code=400,
            detail="Only YouTube URLs are supported"
        )

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url


# =========================
# DOWNLOAD
# =========================

@app.get("/download")
async def download(
    url: str = Query(..., description="YouTube video URL"),
    type: str = Query(
        "audio",
        description="audio or video"
    ),
    api_key: str = Query(
        "",
        description="Your ROYAL API Key"
    ),
):
    type = type.lower().strip()

    if type not in ("audio", "video"):
        raise HTTPException(
            status_code=400,
            detail="type must be audio or video"
        )

    # Validate key BEFORE downloading
    await validate_api_key(api_key, type)

    url = normalize_youtube_url(url)

    unique_id = secrets.token_hex(8)

    if type == "audio":
        output_template = os.path.join(
            DOWNLOAD_DIR,
            f"{unique_id}.%(ext)s"
        )

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

    else:
        output_template = os.path.join(
            DOWNLOAD_DIR,
            f"{unique_id}.%(ext)s"
        )

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

    # Optional authorized cookies file
    cookies_file = "/app/cookies.txt"

    if os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    try:
        loop = asyncio.get_running_loop()

        def do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True
                )

                return info

        info = await loop.run_in_executor(
            None,
            do_download
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)}"
        )

    title = info.get("title", "download")
    title = re.sub(
        r'[\\/*?:"<>|]',
        "_",
        title
    )

    possible_files = []

    for filename in os.listdir(DOWNLOAD_DIR):
        if filename.startswith(unique_id):
            possible_files.append(
                os.path.join(DOWNLOAD_DIR, filename)
            )

    if not possible_files:
        raise HTTPException(
            status_code=500,
            detail="Downloaded file not found"
        )

    file_path = possible_files[0]

    file_size_mb = (
        os.path.getsize(file_path) /
        (1024 * 1024)
    )

    if file_size_mb > MAX_FILE_MB:
        try:
            os.remove(file_path)
        except Exception:
            pass

        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {MAX_FILE_MB} MB"
        )

    extension = os.path.splitext(file_path)[1]

    if type == "audio":
        media_type = "audio/mpeg"
        filename = f"{title}.mp3"
    else:
        media_type = "video/mp4"
        filename = f"{title}{extension}"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename,
        background=None,
    )
