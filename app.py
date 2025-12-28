# app.py
import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(),  # uses OPENAI_API_KEY automatically
    instructions="""
You are an elite AI travel planner.

You MUST:
- Use MCP servers for Airbnb and Google Maps
- Calculate distance-based costs
- Suggest stays, routes, and daily plans
- Return a unique itinerary every time
- Never return templates or generic plans

If MCP data is available, ALWAYS use it.
"""
)

def run_travel_planner(payload: dict) -> str:
    prompt = f"""
Plan a detailed trip.

Destination: {payload['destination']}
Days: {payload['num_days']}
Budget: {payload['budget']} {payload['currency']}
Travelers: {payload['num_travelers']}
Preferences: {payload.get('preferences', 'None')}
"""

    result = agent.run(prompt)
    return result.content

