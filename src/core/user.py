import os
import pickle
import json
import time
from collections import deque
from shutil import copy, rmtree

from src.utils import get_repo_path, TokensUsage

repo_path = get_repo_path()
users_data_path = repo_path + 'data/users/'


class User:
    def __init__(self, user_id, params):
        self.user_id = user_id
        self.params = params
        self.verbose = params['verbose']
        self.max_context_messages = params.get('max_context_messages', 50)  # Adjust as needed

        self.user_data_folder = users_data_path + f'{self.params["agent_id"]}/{user_id}/'
        self.data_path = self.user_data_folder + 'user_data.pkl'
        self.messages_path = self.user_data_folder + 'messages.jsonl'
        self.data = None
        self.recent_messages = deque(maxlen=self.max_context_messages)
        self.last_interaction = time.time()

        if os.path.exists(self.data_path) and os.path.exists(self.messages_path):
            self.load()
        else:
            self.create()

    def load(self):
        if self.verbose:
            print(f'    > loading user from memory: {self.user_id}')

        with open(self.data_path, 'rb') as f:
            self.data = pickle.load(f)

        # Load only the most recent messages
        if os.path.exists(self.messages_path):
            with open(self.messages_path, 'r') as f:
                messages = f.readlines()
                start_index = max(0, len(messages) - self.max_context_messages)
                for line in messages[start_index:]:
                    self.recent_messages.append(json.loads(line.strip()))

    def create(self):
        if self.verbose:
            print(f'    > creating new user: {self.user_id}')
        try:
            os.makedirs(self.user_data_folder, exist_ok=True)
            self.data = {
                'tokens_usage': TokensUsage(),
                'last_message_id': 0
            }
            self.save()
        except:
            if os.path.exists(self.user_data_folder):
                rmtree(self.user_data_folder)
            assert False, "error in user creation"

    def save(self):
        # Save user data
        if os.path.exists(self.data_path):
            copy(self.data_path, self.data_path + '.copy')
        with open(self.data_path, 'wb') as f:
            pickle.dump(self.data, f)
        if os.path.exists(self.data_path + '.copy'):
            os.remove(self.data_path + '.copy')

    def add_to_mem(self, msg):
        msg_id = self.data['last_message_id'] + 1
        msg_with_id = {'id': msg_id, **msg}
        self.recent_messages.append(msg_with_id)
        self.last_interaction = time.time()

        # Append the new message to the messages file
        with open(self.messages_path, 'a') as f:
            json.dump(msg_with_id, f)
            f.write('\n')

        # Update last_message_id after saving
        self.data['last_message_id'] = msg_id
        self.save()  # Save updated user data

    def get_msgs(self):
        return list(self.recent_messages)
