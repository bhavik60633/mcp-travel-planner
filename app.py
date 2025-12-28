# app.py
import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTool

# MCP Servers (Airbnb + Google Maps)
airbnb = MCPTool(
    name="airbnb",
    url="http://localhost:3333"  # or your MCP server URL
)

google_maps = MCPTool(
    name="google_maps",
    url="http://localhost:3334"
)

agent = Agent(
    model=OpenAIChat(),   # DO NOT pass model="gpt-4" etc
    tools=[airbnb, google_maps],
    instructions="""
    You are an elite AI travel planner.
    You MUST:
    - Use Airbnb MCP for stays
    - Use Google Maps MCP for distance & routing
    - Calculate cost using distance + nights
    - Return a detailed, unique itinerary
    """
)

def run_travel_planner(payload: dict) -> str:
    prompt = f"""
    Plan a trip with real calculations.

    Destination: {payload['destination']}
    Days: {payload['num_days']}
    Budget: {payload['budget']} {payload['currency']}
    Travelers: {payload['num_travelers']}
    Preferences: {payload.get('preferences')}
    """

    result = agent.run(prompt)
    return result.content
