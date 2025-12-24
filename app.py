import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    ),
    instructions="Expert travel planner"
)

def run_travel_planner(data: dict) -> str:
    prompt = f"""
Destination: {data['destination']}
Days: {data['num_days']}
Budget: {data['budget']} {data['currency']}
Preferences: {data['preferences']}
"""
    return agent.run(prompt).content
