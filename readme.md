# LLM-powered Telegram chatbot

This repo contains the template of a telegram chatbot with a language model back-end.

It comes with a very simple LLM-based agent that connects the telegram bot to gpt-4o-mini from the OpenAI API.

To extend it, you can define a new `Agent` class in `src/agents/` and register it in `src/agents/get_agent.py`.
Each agent defines its own `interact(message)` function to react to a new user message.
Histories of user messages are stored locally and can be used by the agent (in `self.user.data['memory']`).

In the current state, this chatbot automatically authorized new users up to `max_users` and gives them a free API credit budget of `max_credit`.

Here are the steps to getting started.

**Step 1**: Install required libraries with `pip install -t requirements.txt`

**Step 2**: Setup the telegram chatbot.
* open Telegram and search for the "BotFather" bot
* send `/newbot` in the chat
* name it and choose its username
* save the chatbot token in `.api_telegram_bot`
* save your telegram ID in `.telegram_admin_user_id`

**Step 3**: Add API keys
* `.api_openai` (currently only OpenAI is supported) 

**Step 4**: Customize your bot
* set bot parameters in `chatbot/start.py`, eg `max_users`, `max_credits`, `bot_name`, and `agent_id`.
* code a custom Agent class or reuse `agent_id=simple_llm_agent`

**Step 5**: Run the bot
* `python chatbot/start.py (--sync)`

