# app.py
import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MultiMCPTools

# Define MCP tools (Node-based)
mcp_tools = MultiMCPTools(
    [
        "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
        "npx -y @gongrzhe/server-travelplanner-mcp"
    ],
    env={
        "GOOGLE_MAPS_API_KEY": os.getenv("GOOGLE_MAPS_API_KEY")
    },
    timeout_seconds=60
)

agent = Agent(
    name="Yori MCP Travel Planner",
    model=OpenAIChat(),  # Uses OPENAI_API_KEY from Railway
    tools=[mcp_tools],
    instructions="""
You are a professional travel planner.

MANDATORY:
- Use Airbnb MCP for accommodation
- Use Google Maps MCP for distance & routing
- Never invent hotels or distances
- If MCP fails, clearly say so
"""
)

def run_travel_planner(payload: dict) -> str:
    prompt = f"""
Create a detailed travel itinerary.

Destination: {payload['destination']}
Days: {payload['num_days']}
Budget: {payload['budget']} {payload['currency']}
Travelers: {payload['num_travelers']}
Preferences: {payload.get('preferences')}
"""
    result = agent.run(prompt)
    return result.content
