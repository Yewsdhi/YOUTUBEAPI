import os
import re
import tempfile
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI(title="Royal Music API", version="1.0.0")

COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")

def ytdlp_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts

@app.get("/")
def root():
    return {
        "name": "Royal Music API",
        "status": "online",
        "docs": "/docs",
        "endpoints": ["/health", "/search", "/info", "/download"]
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)):
    try:
        opts = ytdlp_opts()
        opts.update({"extract_flat": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)

        results = []
        for item in data.get("entries", []):
            if not item:
                continue
            results.append({
                "title": item.get("title"),
                "url": item.get("webpage_url") or item.get("url"),
                "id": item.get("id"),
                "duration": item.get("duration"),
                "thumbnail": item.get("thumbnail"),
                "channel": item.get("channel") or item.get("uploader"),
            })
        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/info")
def info(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL(ytdlp_opts()) as ydl:
            data = ydl.extract_info(url, download=False)
        return {
            "title": data.get("title"),
            "url": data.get("webpage_url"),
            "duration": data.get("duration"),
            "thumbnail": data.get("thumbnail"),
            "channel": data.get("channel") or data.get("uploader"),
            "stream_url": data.get("url"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
def download(url: str = Query(...)):
    tempdir = tempfile.mkdtemp(prefix="music_")
    output = os.path.join(tempdir, "%(title).80s.%(ext)s")

    opts = ytdlp_opts()
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": output,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            requested = ydl.prepare_filename(info)
        mp3 = os.path.splitext(requested)[0] + ".mp3"

        if not os.path.exists(mp3):
            candidates = [os.path.join(tempdir, f) for f in os.listdir(tempdir)]
            mp3 = next((f for f in candidates if f.lower().endswith(".mp3")), None)

        if not mp3 or not os.path.exists(mp3):
            raise RuntimeError("Audio file was not created")

        safe_title = re.sub(r'[^a-zA-Z0-9._ -]', '', info.get("title") or "audio")[:80]
        return FileResponse(mp3, media_type="audio/mpeg", filename=f"{safe_title}.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
