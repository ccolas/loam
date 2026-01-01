import os
import asyncio
from functools import wraps

# api cost per million
api_costs = {"gpt-4o-mini-2024-07-18": dict(output_tokens=0.6,
                                            input_tokens=0.15)}


def get_repo_path():
    repo_path = '/'.join(os.path.dirname(os.path.realpath(__file__)).split('/')[:-1]) + '/'
    return repo_path


def load_api_keys(to_load='openai telegram'):
    to_load = to_load.split(' ')

    repo_path = get_repo_path()
    if 'openai' in to_load:
        if '.api_openai' in os.listdir(repo_path):
            with open(repo_path + '.api_openai', 'r') as f:
                os.environ['OPENAI_API_KEY'] = f.read()
        else:
            raise ValueError('Please add your openai api key in root/.api_openai')

    if 'telegram' in to_load:
        if '.api_telegram_bot' in os.listdir(repo_path):
            with open(repo_path + '.api_telegram_bot', 'r') as f:
                os.environ['TELEGRAM_BOT_KEY'] = f.read()
        else:
            raise ValueError('Please add the telegram bot api key in music_explorers/.api_telegram_bot')


class TokensUsage:
    def __init__(self):
        self.tokens_usage = None
        self.reset_usage()

    def reset_usage(self):
        self.tokens_usage = dict()

    def add(self, llm, token_usage):
        if llm not in self.tokens_usage.keys():
            assert llm in api_costs.keys(), f'please add token costs of {llm} to api_costs dict'
            self.tokens_usage[llm] = dict(output_tokens=0, input_tokens=0)

        for k in self.tokens_usage[llm].keys():
            self.tokens_usage[llm][k] += token_usage[k]

    def get(self):
        return self.tokens_usage


def compute_usage_cost(agent):
    tokens_usage = agent.user.data['tokens_usage'].get()
    cost = 0
    for llm, llm_usage in tokens_usage.items():
        cost += llm_usage['output_tokens'] / 1e6 * api_costs[llm]['output_tokens'] + \
                llm_usage['input_tokens'] / 1e6 * api_costs[llm]['input_tokens']
    return cost


def format_msg(msg, n_spaces):
    return msg.replace('\n', '\n' + ' ' * n_spaces)


MAX_USERS_MSG = ("Sorry we've reached the maximum number of users I can handle for now. "
                 "Please contact Cedric if you really want to chat with me!")
MAX_CREDITS_MSG = (f"Sorry you've used all you free credits ($AMOUNT). "
                   f"Please contact Cedric if you want to continue chatting with me!")
