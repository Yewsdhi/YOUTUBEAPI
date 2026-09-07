import os, threading
import uvicorn
from bot import bot

def start_bot():
    bot.run()

if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT","8080")), workers=1)
