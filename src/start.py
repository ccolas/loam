"""
Start script for Loam.
"""
import asyncio
import logging
import sys

from src.loam import Loam


def setup_logging():
    """Configure logging for the application."""
    loam_logger = logging.getLogger('loam')

    # Only add handler if not already configured
    if not loam_logger.handlers:
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%H:%M:%S'
        )

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)

        # Configure root loam logger
        loam_logger.setLevel(logging.DEBUG)
        loam_logger.addHandler(console_handler)

        # Prevent propagation to root logger (avoids duplicate output)
        loam_logger.propagate = False

    # Reduce noise from other libraries
    logging.getLogger('aiogram').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)


params = {
    'verbose': True,
    'bot_name': 'Obsidian',
}


async def run_bot():
    while True:
        print('Starting Loam...')
        bot = Loam(params)
        try:
            await bot.start()
        except Exception as e:
            print(f'  > bot crashed with error: {e}')
            print(f'  > restarting in 3 seconds...')
            await asyncio.sleep(3)


if __name__ == '__main__':
    setup_logging()
    logging.getLogger('loam').info('Loam bot starting up...')
    asyncio.run(run_bot())