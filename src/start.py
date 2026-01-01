import argparse
import asyncio

from src.async_bot import TelegramBot
from src.utils import api_costs


default_params = dict(verbose=True,
                      bot_name='Ada',
                      agent_id='simple_llm_agent',  # id of the agent to use, define it in src/agents and register it in src/agents/get_agent.py
                      llm_model='gpt-4o-mini-2024-07-18',
                      llm_timeout=10.0,  # timeout parameter for the llm
                      max_answer_tokens=1000,
                      max_tokens=4090,
                      max_users=2,  # maximum number of users for this project
                      max_credits=5,  # maximum USD to spend per user
                      )
# The admin has infinite budget
# Your project budget is max_users x max_credits (+ whatever you use with the admin telegram account)

assert default_params['llm_model'] in api_costs.keys(), f"please add the api costs of model {default_params['llm_model']}"

async def run_bot():
    while True:
        print('starting bot')
        bot = TelegramBot(default_params)
        try:
            await bot.start()
        except Exception as e:
            print(f'  > bot crashed with error: {e}')
            print(f'  > restarting bot')
            await asyncio.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run Telegram Bot")
    args = parser.parse_args()
    asyncio.run(run_bot())
