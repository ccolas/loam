import time

from src.core.user import User
from src.agents.get_agent import get_agent


class Manager:
    """
    The agent manager maintains the memories and prompts of all agents for all users.
    The memory is organized as follows:
      > each user has a folder {user_id}
      > each agent is a pickle file in that folder {user_id/agent_id.pkl}
      > user_data are stored in {user_id/user_data.pkl)
    """
    def __init__(self, params):
        self.agents = dict()
        self.verbose = params['verbose']
        self.params = params
        self.agent_class = get_agent(self.params['agent_id'])

    def get_agent(self, user_id):
        self.clear_inactive_users()
        if user_id not in self.agents.keys():
            user = User(user_id, self.params)
            self.agents[user_id] = self.agent_class(user, self.params)
        return self.agents[user_id]

    def clear_inactive_users(self, clear_after=10):
        # clear inactive user to maintain memory
        # clear_after number of seconds before flagging user as inactive (1200=20m)
        now = time.time()
        inactive_user_ids = []
        for user_id, agent in self.agents.items():
            if now - agent.user.last_interaction > clear_after:
                inactive_user_ids.append(user_id)

        for user_id in inactive_user_ids:
            del self.agents[user_id]



