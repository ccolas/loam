from src.core.llm import LLM
from src.core.base_agent import BaseAgent
from src.utils import format_msg


class SimpleLLMAgent(BaseAgent):
    def __init__(self, user, params):
        super().__init__(user, params)
        self.llm = LLM(params)
        self.system_prompt = (f"You are a helpful assistant called {self.params['bot_name']}. "
                              f"You communicate through text, so keep your messages short and engaging. "
                              f"Don't use lists, just text normally.")

    def interact(self, message):
        if self.verbose:
            print(f'      > user: {format_msg(message, n_spaces=14)}')
        history = self.user.get_msgs() + [{'role': 'user', 'content': message}]
        llm_input = dict(system_prompt=self.system_prompt, messages_history=history)
        answer, tokens = self.llm.call(llm_input)
        self.user.data['tokens_usage'].add(self.llm.model, tokens)  # update token usage
        return [answer]

    def update_memory(self, user_msg, assistant_msgs):
        # update and save memory
        self.user.add_to_mem({'role': 'user', 'content': user_msg})
        self.user.add_to_mem({'role': 'assistant', 'content': assistant_msgs[0]})
