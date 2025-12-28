import os
import asyncio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MultiMCPTools

# Create MCP tools (Node-based MCP servers)
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

# Connect MCP tools ONCE at startup
asyncio.get_event_loop().run_until_complete(mcp_tools.connect())

agent = Agent(
    name="Yori MCP Travel Planner",
    model=OpenAIChat(),  # Uses OPENAI_API_KEY from Railway
    tools=[mcp_tools],
    instructions="""
You are a professional travel planner.

MANDATORY RULES:
- Use Airbnb MCP for ALL stays
- Use Google Maps MCP for distance & routing
- NEVER invent hotels or distances
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
