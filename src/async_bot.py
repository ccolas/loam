import asyncio
import os
from collections import defaultdict

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

from src.utils import load_api_keys, get_repo_path, MAX_USERS_MSG, MAX_CREDITS_MSG, compute_usage_cost, format_msg
from src.core.manager import Manager


class TelegramBot:
    def __init__(self, params):
        if 'TELEGRAM_BOT_KEY' not in os.environ.keys():
            load_api_keys('telegram')
        self.params = params
        self.verbose = params['verbose']
        self.bot = Bot(token=os.environ['TELEGRAM_BOT_KEY'])
        self.dp = Dispatcher()
        self.manager = Manager(params)
        self.repo_path = get_repo_path()
        self.debug = True  # Set to True for debug prints

        self.user_tasks = defaultdict(lambda: None)
        self.user_messages = defaultdict(list)
        # self.new_user_messages = defaultdict(list)

        if '.telegram_admin_user_id' in os.listdir(self.repo_path):
            with open(self.repo_path + '.telegram_admin_user_id', 'r') as f:
                self.admin_user_id = int(f.read())
        else:
            raise ValueError('Please add your telegram user id in chatbot/.telegram_admin_user_id')

        self.setup_handlers()

    def setup_handlers(self):
        @self.dp.message(CommandStart())
        async def send_welcome(message: types.Message):
            valid_users = await self.get_valid_user_ids()
            if message.chat.id in valid_users:
                await message.reply("Hey, welcome back! What's up?")
            elif len(valid_users) < self.params['max_users']:
                await message.reply(f"Hey, I'm {self.params['bot_name']}! How are you doing?")
            else:
                await message.reply(MAX_USERS_MSG)

        @self.dp.message()
        async def chat(message: types.Message):
            valid_users = await self.get_valid_user_ids()
            if message.chat.id in valid_users:
                await self.process_message(message)
            elif len(valid_users) < self.params['max_users']:
                await self.add_user(message.chat.id)
                await self.process_message(message)
            else:
                await message.reply(MAX_USERS_MSG)

    async def process_message(self, message: types.Message):
        user_id = message.chat.id
        # self.new_user_messages[user_id].append(message.text)  # add new messages
        self.user_messages[user_id].append(message.text)  # add

        # Cancel any ongoing task for this user
        if self.user_tasks[user_id]:
            self.user_tasks[user_id].cancel()
            await asyncio.sleep(0)  # Yield control to allow cancellation to take effect
            print('      > cancel (new msg arrived)')

        # Start a new task to process messages
        self.user_tasks[user_id] = asyncio.create_task(self._process_user_messages(user_id))
        self.user_tasks[user_id].add_done_callback(lambda t: self.task_done_callback(user_id))

    def task_done_callback(self, user_id):
        self.user_tasks[user_id] = None

    async def _process_user_messages(self, user_id):
        agent = self.manager.get_agent(user_id)
        cost_so_far = compute_usage_cost(agent)

        if cost_so_far >= self.params['max_credits'] and user_id != self.admin_user_id:
            await self.bot.send_message(user_id, MAX_CREDITS_MSG.replace('AMOUNT', str(self.params['max_credits'])))
            return

        try:
            while True:
                messages_to_process = self.user_messages[user_id].copy()

                if not messages_to_process:
                    break

                concatenated_message = "\n".join(messages_to_process)

                # Process the message
                msgs = await self.async_interact(agent, concatenated_message)

                if msgs:
                    for msg in msgs:
                        await self.bot.send_message(user_id, msg, disable_web_page_preview=True)
                        if self.verbose:
                            print(f'      > assistant: {format_msg(msg, n_spaces=19)}')
                else:
                    print('      > processing error here')
                    msgs = "Sorry something went wrong I missed that message."

                # update memory if the messages were sent
                agent.update_memory(concatenated_message, msgs)
                self.user_messages[user_id].clear()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f'      > error in _process_user_messages for user {user_id}: {str(e)}')

    async def async_interact(self, agent, message):
        try:
            result = await asyncio.to_thread(agent.interact, message)
            return result
        except Exception as e:
            print(f'      > processing error in agent.interact: {str(e)}')
            return None


    async def get_valid_user_ids(self):
        if '.telegram_valid_user_ids' in os.listdir(self.repo_path):
            with open(self.repo_path + '.telegram_valid_user_ids', 'r') as f:
                user_ids = f.read()
        else:
            raise ValueError('Please add your telegram user id in chatbot/.telegram_valid_user_ids')
        return [] if len(user_ids) == 0 else [int(line) for line in user_ids.split('\n')]

    async def add_user(self, user_id):
        with open(self.repo_path + '.telegram_valid_user_ids', 'r') as f:
            user_ids = f.read()
        user_ids += f'\n{user_id}'
        with open(self.repo_path + '.telegram_valid_user_ids', 'w') as f:
            f.write(user_ids)

    async def start(self):
        await self.dp.start_polling(self.bot)

    def run(self):
        asyncio.run(self.start())
