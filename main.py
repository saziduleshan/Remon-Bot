import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import ApplicationBuilder

from bot import register
from config import config
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8080"))


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        pass


def _start_health_server():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=False)
    thread.start()
    logger.info("Health check server listening on port %d", HEALTH_PORT)


async def post_init(application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Existing webhook cleared (if any)")
    start_scheduler(application)
    logger.info("Bot started and scheduler initialized")


def main():
    config.load()
    config.validate()

    _start_health_server()

    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )
    register(application)
    application.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("Startup failed")
        sys.exit(1)
