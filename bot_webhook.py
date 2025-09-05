# bot_webhook.py
# Python 3.10+, python-telegram-bot==21.4
import os
from telegram.ext import Application, AIORateLimiter

from bot import register_handlers

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "super-secret")

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
    register_handlers(app)
    return app

if __name__ == "__main__":
    app = build_app()
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        webhook_path=f"/{WEBHOOK_SECRET}",
        webhook_url=os.environ.get("PUBLIC_URL", "") + f"/{WEBHOOK_SECRET}",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
