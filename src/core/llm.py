import os
import time

import numpy as np
from openai import OpenAI
import tiktoken

from src.utils import load_api_keys


class LLM:
    def __init__(self, params):
        if 'OPENAI_API_KEY' not in os.environ.keys():
            load_api_keys('openai')
        self.openai_client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=params['llm_timeout'])
        # self.openai_client = instructor.patch(self.openai_client)
        self.model = params['llm_model']
        self.verbose = params['verbose']
        
        # handle context length
        self.id_oldest_msg_to_enter_context = 0
        if any([key in params['llm_model'] for key in ['gpt-3.5', 'gpt-4']]):
            encoding = 'cl100k_base'
        else:
            raise NotImplementedError

        self.max_answer_tokens = params['max_answer_tokens']
        self.max_tokens = params['max_tokens']
        self.max_context_tokens = self.max_tokens - self.max_answer_tokens
        self.encoding = tiktoken.get_encoding(encoding)

    def build_prompt(self, llm_input):
        system_prompt = llm_input['system_prompt']
        messages_history = llm_input['messages_history']

        # figure out the number of messages that can fit into the context
        all_str = system_prompt
        id_oldest_msg_to_enter_context = 0
        for i_m in range(len(messages_history) - 1, 0, -1):
            all_str += '\n' + messages_history[i_m]['content']
            if len(self.encoding.encode(all_str)) > self.max_context_tokens:
                id_oldest_msg_to_enter_context = i_m + 1
                break

        # make sure the first message is from the user
        if id_oldest_msg_to_enter_context % 2 == 1:
            id_oldest_msg_to_enter_context += 1

        messages = []
        messages.append(dict(role='system', content=system_prompt))
        for i_m, m in enumerate(messages_history[id_oldest_msg_to_enter_context:]):
            role = 'user' if i_m % 2 == 0 else "assistant"
            assert role == m['role']  # make sure the role of the message is the one we expect in turn-taking interaction
            messages.append(dict(role=m['role'], content=m['content']))
        return messages

    def call(self, llm_input, max_attempts=10):
        messages = self.build_prompt(llm_input)
        self.i_attempt = 0
        while self.i_attempt < max_attempts:
            try:
                answer = self.openai_client.chat.completions.create(model=self.model,
                                                                    messages=messages,
                                                                    max_tokens=self.max_answer_tokens)
                break
            except Exception as e:
                error = str(e)
                time.sleep(np.random.uniform(0.5, 3))
                answer = None
                self.i_attempt += 1
        if answer is not None:
            token_usage_openai = answer.usage.__dict__
            token_usage = dict(input_tokens=token_usage_openai['prompt_tokens'],
                               output_tokens=token_usage_openai['completion_tokens'])
            return answer.choices[0].message.content, token_usage
        else:
            if self.verbose:
                print(f'    > error: {error}')
            return "Error: the LM API is currently not working", None


    def call_llm(self, system_prompt, messages, response_model=None):

        while self.i_attempt < max_attempts:
            try:
                v = self.call_llm_func(system_prompt, messages, response_model)
                if self.verbose: print('    > llm call succeeded')
                break
            except Exception as e:
                if self.verbose:
                    print('    > llm call FAILED')
                    print(f'    > error: {repr(e)}')
                time.sleep(np.random.uniform(0.5, 3))
                answer_dict = None



    def call_llm_func(self, system_prompt, messages, response_model=None):
        self.i_attempt += 1
        if self.verbose: print(f'  > calling the llm (attempt {self.i_attempt} / {max_attempts})')
        input_llm = dict(messages_history=messages,
                         response_model=response_model,
                         system_prompt=system_prompt)
        answer = self.llm.call(input_llm)
        self.update_tokens_usage(answer)
        return answer

