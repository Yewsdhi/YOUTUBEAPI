# Royal Music API

FastAPI + yt-dlp backend for a Telegram music bot.

## Endpoints

- `GET /health`
- `GET /search?q=arijit`
- `GET /info?url=YOUTUBE_URL`
- `GET /download?url=YOUTUBE_URL`
- `GET /docs`

## Heroku

Create a Heroku app and deploy this repository. Heroku detects Python from the files and uses the `Procfile` web process.

If YouTube requires authentication, do not commit personal cookies to GitHub. Use a secure secret/file mechanism appropriate to your deployment.
