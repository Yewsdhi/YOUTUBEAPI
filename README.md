# Royal API + Telegram API-Key Bot

This project provides:
- FastAPI `/health`
- FastAPI `/download`
- Telegram `/start` and `/key`
- Unique `ROYAL_...` API keys
- 30-day expiry by default
- 3,000 requests/day by default
- Daily + all-time usage counters
- Renew / Revoke & Get New Key buttons
- PostgreSQL database
- yt-dlp + FFmpeg
- Optional server-side cookies

## Required environment variables

BOT_TOKEN=your Telegram BotFather token
DATABASE_URL=your PostgreSQL URL

Optional:
DAILY_LIMIT=3000
KEY_DAYS=30
MAX_FILE_MB=100
MAX_CONCURRENT=2
COOKIES_FILE=/app/cookies.txt

## API

GET /health

GET /download?url=YOUTUBE_URL&type=audio
Header:
X-API-Key: ROYAL_xxxxxxxxxxxxxxxx

`api_key` query parameter is also accepted for compatibility, but the header is safer.

## Heroku

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy?template=https://github.com/YOUR_USERNAME/YOUR_REPO)

The repository contains Procfile, runtime.txt and Aptfile.
Use a single web dyno/process because the Telegram bot uses polling.

Heroku's filesystem is ephemeral, so do not rely on local SQLite/files for permanent data.
Use PostgreSQL for keys and usage.

For cookies, keep the file private and only use cookies you are authorized to use.
Do not commit cookies.txt to GitHub.

## Deploy button

After putting the repository on GitHub, set the repository URL in the deploy button URL:
https://heroku.com/deploy?template=https://github.com/YOUR_USERNAME/YOUR_REPO
