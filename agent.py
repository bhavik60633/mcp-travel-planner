import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Agent is created ONCE
agent = Agent(
    model=OpenAIChat(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    ),
    instructions="""
You are an expert travel planner.
Create a realistic, detailed, day-wise itinerary.
Use local places, food, timing, travel tips.
Do NOT repeat generic templates.
"""
)

def run_travel_planner(data: dict) -> str:
    prompt = f"""
Destination: {data['destination']}
Number of days: {data['num_days']}
Budget: {data['budget']} {data['currency']}
Number of travelers: {data['num_travelers']}
Trip type: {data['trip_type']}
Group type: {data['group_type']}
Preferences: {data['preferences']}
"""

    result = agent.run(prompt)

    return result.content
