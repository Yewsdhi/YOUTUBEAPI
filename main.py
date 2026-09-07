import os, asyncio, secrets
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import aiosqlite, yt_dlp

app = FastAPI(title="ROYAL YouTube API")
DB_PATH = os.getenv("DB_PATH", "/tmp/royal_api.db")
DOWNLOAD_DIR = Path("/tmp/royal_downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "3000"))
KEY_DAYS = int(os.getenv("KEY_DAYS", "30"))

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS keys (
            user_id INTEGER PRIMARY KEY, api_key TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            requests INTEGER DEFAULT 0, audio INTEGER DEFAULT 0, video INTEGER DEFAULT 0)""")
        await db.commit()

@app.on_event("startup")
async def startup():
    await init_db()

def valid_youtube(url):
    try:
        return (urlparse(url).hostname or "").lower() in {
            "youtube.com","www.youtube.com","m.youtube.com","youtu.be","www.youtube-nocookie.com"}
    except Exception:
        return False

async def verify_key(key):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, expires_at, requests FROM keys WHERE api_key=?", (key,))
        row = await cur.fetchone()
    if not row:
        return False, "Invalid API Key"
    if datetime.fromisoformat(row[1]) <= datetime.utcnow():
        return False, "API Key Expired"
    if row[2] >= DAILY_LIMIT:
        return False, "Daily limit reached"
    return True, row[0]

@app.get("/")
async def root():
    return {"status":"running","name":"ROYAL YouTube API","docs":"/docs","health":"/health"}

@app.get("/health")
async def health():
    await init_db()
    return {"status":"healthy","yt_dlp":yt_dlp.version.__version__}

@app.get("/download")
async def download(url: str, type: str, api_key: str, background_tasks: BackgroundTasks):
    ok, result = await verify_key(api_key)
    if not ok:
        raise HTTPException(403, result)
    if type not in {"audio","video"}:
        raise HTTPException(400, "type must be audio or video")
    if not valid_youtube(url):
        raise HTTPException(400, "Please provide a valid YouTube URL")

    job = secrets.token_hex(12)
    base = DOWNLOAD_DIR / job
    opts = {"quiet":True,"no_warnings":True,"noplaylist":True,
            "outtmpl":str(base)+".%(ext)s","retries":2,
            "fragment_retries":2,"socket_timeout":30}
    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE","")
    if cookie_file and Path(cookie_file).is_file():
        opts["cookiefile"] = cookie_file

    if type == "audio":
        opts.update({"format":"bestaudio/best",
            "postprocessors":[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]})
    else:
        opts.update({"format":"bestvideo*+bestaudio/best","merge_output_format":"mp4"})

    try:
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(opts).download([url]))
        candidates = sorted(DOWNLOAD_DIR.glob(job+".*"), key=lambda p:p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("Output file was not found")
        path = candidates[0]
        col = "audio" if type == "audio" else "video"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"UPDATE keys SET requests=requests+1,{col}={col}+1 WHERE api_key=?", (api_key,))
            await db.commit()
        background_tasks.add_task(lambda: path.unlink(missing_ok=True))
        return FileResponse(path, filename=("audio.mp3" if type=="audio" else "video.mp4"))
    except Exception as e:
        raise HTTPException(500, f"Download error: {e}")

async def create_key(user_id):
    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT api_key, created_at, expires_at FROM keys WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        now = datetime.utcnow()
        if row and datetime.fromisoformat(row[2]) > now:
            return row
        key = "ROYAL_" + secrets.token_hex(8)
        created = now.isoformat()
        expires = (now + timedelta(days=KEY_DAYS)).isoformat()
        await db.execute("""INSERT OR REPLACE INTO keys
            (user_id,api_key,created_at,expires_at,requests,audio,video)
            VALUES (?,?,?,?,0,0,0)""", (user_id,key,created,expires))
        await db.commit()
        return key, created, expires
