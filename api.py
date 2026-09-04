import os
import re
import tempfile
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI(title="Royal Music API", version="1.0.0")
COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")

def opts():
    x = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if os.path.exists(COOKIES_FILE):
        x["cookiefile"] = COOKIES_FILE
    return x

@app.get("/")
def home():
    return {"name":"Royal Music API","status":"online","docs":"/docs"}

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)):
    try:
        x=opts(); x["extract_flat"]=True
        with yt_dlp.YoutubeDL(x) as y:
            data=y.extract_info(f"ytsearch{limit}:{q}", download=False)
        return {"query":q,"results":[
            {"title":i.get("title"),"url":i.get("webpage_url") or i.get("url"),
             "id":i.get("id"),"duration":i.get("duration"),"thumbnail":i.get("thumbnail"),
             "channel":i.get("channel") or i.get("uploader")}
            for i in data.get("entries",[]) if i
        ]}
    except Exception as e:
        raise HTTPException(500,str(e))

@app.get("/info")
def info(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL(opts()) as y:
            d=y.extract_info(url, download=False)
        return {"title":d.get("title"),"url":d.get("webpage_url"),
                "duration":d.get("duration"),"thumbnail":d.get("thumbnail"),
                "channel":d.get("channel") or d.get("uploader"),"stream_url":d.get("url")}
    except Exception as e:
        raise HTTPException(500,str(e))

@app.get("/download")
def download(url: str = Query(...)):
    td=tempfile.mkdtemp(prefix="music_")
    out=os.path.join(td,"%(title).80s.%(ext)s")
    x=opts()
    x.update({"format":"bestaudio/best","outtmpl":out,
              "postprocessors":[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]})
    try:
        with yt_dlp.YoutubeDL(x) as y:
            d=y.extract_info(url,download=True)
            requested=y.prepare_filename(d)
        mp3=os.path.splitext(requested)[0]+".mp3"
        if not os.path.exists(mp3):
            mp3=next((os.path.join(td,f) for f in os.listdir(td) if f.endswith(".mp3")),None)
        if not mp3 or not os.path.exists(mp3):
            raise RuntimeError("Audio file was not created")
        title=re.sub(r"[^a-zA-Z0-9._ -]","",d.get("title") or "audio")[:80]
        return FileResponse(mp3,media_type="audio/mpeg",filename=f"{title}.mp3")
    except Exception as e:
        raise HTTPException(500,str(e))
