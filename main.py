import logging

from telegram.ext import ApplicationBuilder

from bot import register
from config import config
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    start_scheduler(application)
    logger.info("Bot started and scheduler initialized")


def main():
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )
    register(application)
    application.run_polling()


if __name__ == "__main__":
    main()
