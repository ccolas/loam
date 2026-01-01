from abc import abstractmethod


class BaseAgent:
    def __init__(self, user, params):
        self.user = user
        self.params = params
        self.verbose = params['verbose']


    @abstractmethod
    def interact(self, message):
        pass

    @property
    def user_id(self):
        return self.user.user_id

    def save(self):
        self.user.save()