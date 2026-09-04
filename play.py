import os
import requests

from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream


API_BASE_URL = os.getenv(
    "MUSIC_API_URL",
    "https://infinite-ridge-94088-e7cbd59f7c4c.herokuapp.com"
)

app = Client(
    "music_bot",
    api_id=int(os.getenv("API_ID")),
    api_hash=os.getenv("API_HASH"),
    bot_token=os.getenv("BOT_TOKEN")
)

call = PyTgCalls(app)


def search_song(query):
    response = requests.get(
        f"{API_BASE_URL}/search",
        params={"q": query, "limit": 5},
        timeout=60
    )

    response.raise_for_status()
    return response.json()


def get_audio_url(url):
    response = requests.get(
        f"{API_BASE_URL}/info",
        params={"url": url},
        timeout=120
    )

    response.raise_for_status()
    data = response.json()

    return data.get("stream_url"), data.get("title")


@app.on_message(filters.command("play") & filters.group)
async def play_handler(client: Client, message: Message):

    if len(message.command) < 2:
        await message.reply_text(
            "🎵 Usage:\n\n"
            "`/play song name`"
        )
        return

    query = message.text.split(None, 1)[1].strip()

    status = await message.reply_text(
        f"🔎 Searching:\n`{query}`"
    )

    try:
        data = search_song(query)
        results = data.get("results", [])

        if not results:
            await status.edit_text("❌ Song nahi mila.")
            return

        song = results[0]

        title = song.get("title") or query
        youtube_url = song.get("url")

        await status.edit_text(
            f"🎵 **Found:** `{title}`\n"
            f"⏳ Getting audio..."
        )

        stream_url, real_title = get_audio_url(youtube_url)

        if not stream_url:
            await status.edit_text(
                "❌ Audio stream nahi mila."
            )
            return

        await call.play(
            message.chat.id,
            MediaStream(stream_url)
        )

        await status.edit_text(
            f"▶️ **Now Playing**\n\n"
            f"🎵 `{real_title or title}`"
        )

    except requests.exceptions.Timeout:
        await status.edit_text(
            "❌ Music API timeout ho gayi.\n"
            "Thodi der baad try karo."
        )

    except Exception as e:
        print("PLAY ERROR:", repr(e))

        await status.edit_text(
            f"❌ Play failed:\n`{str(e)[:500]}`"
        )


app.run()
