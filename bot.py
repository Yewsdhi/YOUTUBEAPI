import os
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from main import create_key, DAILY_LIMIT


API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError(
        "Set API_ID, API_HASH and BOT_TOKEN in Heroku Config Vars"
    )


bot = Client(
    "ROYALKeyBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔑 View Your Key",
                    callback_data="key",
                )
            ],
            [
                InlineKeyboardButton(
                    "📚 API Docs",
                    callback_data="docs",
                )
            ],
        ]
    )


@bot.on_message(filters.command("start") & filters.private)
async def start(_, m):

    name = (
        m.from_user.mention
        if m.from_user
        else "User"
    )

    await m.reply_text(
        f"👋 **Welcome {name}!**\n\n"
        "**Main Menu**",
        reply_markup=menu(),
    )


@bot.on_callback_query()
async def callback(_, q):

    if q.data == "key":

        try:
            key, created, expires = await create_key(
                q.from_user.id
            )

            created_dt = datetime.fromisoformat(
                created
            )

            expires_dt = datetime.fromisoformat(
                expires
            )

            created_text = created_dt.strftime(
                "%d %b %Y, %I:%M %p"
            )

            expires_text = expires_dt.strftime(
                "%d %b %Y, %I:%M %p"
            )

            text = (
                "🔑 **Your API Key**\n\n"
                f"**API Key:**\n`{key}`\n\n"
                "**Status:** 🟢 Active\n"
                f"**Daily Limit:** {DAILY_LIMIT:,}\n\n"
                f"**Created:** {created_text}\n"
                f"**Expires:** {expires_text}"
            )

            await q.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔄 Refresh",
                                callback_data="key",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "⬅️ Back",
                                callback_data="menu",
                            )
                        ],
                    ]
                ),
            )

        except Exception as e:

            await q.message.edit_text(
                f"❌ **Error**\n\n`{e}`",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Back",
                                callback_data="menu",
                            )
                        ]
                    ]
                ),
            )

    elif q.data == "docs":

        text = (
            "📚 **API Docs**\n\n"
            "**Endpoint:**\n"
            "`GET /download`\n\n"
            "**Audio:**\n"
            "`type=audio`\n\n"
            "**Video:**\n"
            "`type=video`\n\n"
            "**Parameters:**\n"
            "`url` — YouTube URL\n"
            "`type` — audio/video\n"
            "`api_key` — Your API key"
        )

        await q.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Back",
                            callback_data="menu",
                        )
                    ]
                ]
            ),
        )

    elif q.data == "menu":

        await q.message.edit_text(
            "👋 **Main Menu**",
            reply_markup=menu(),
        )

    await q.answer()


if __name__ == "__main__":
    print("🤖 ROYAL Key Bot starting...")
    bot.run()
