import os
import asyncio
import threading
import uvicorn


def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    from bot import bot

    loop.run_until_complete(bot.start())
    loop.run_forever()


if __name__ == "__main__":
    bot_thread = threading.Thread(
        target=start_bot,
        name="start_bot",
        daemon=True
    )
    bot_thread.start()

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        workers=1
    )
