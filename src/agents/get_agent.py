from src.agents.simple_llm_agent import SimpleLLMAgent

def get_agent(agent_id):
    if agent_id == 'simple_llm_agent':
        return SimpleLLMAgent
    else:
        raise NotImplementedError