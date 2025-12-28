import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MultiMCPTools

# -------------------------------------------------
# ENV (Railway already injects these)
# -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# -------------------------------------------------
# MCP TOOLS (Airbnb + Google Maps)
# -------------------------------------------------
mcp_tools = MultiMCPTools(
    servers=[
        {
            "name": "airbnb",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-airbnb"],
        },
        {
            "name": "google-maps",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-google-maps"],
        },
    ]
)

# -------------------------------------------------
# AGENT (ASYNC — REQUIRED FOR MCP)
# -------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    tools=[mcp_tools],
    system_prompt="""
You are Yori Travel Agent.
You MUST:
- Use Airbnb MCP for real property suggestions
- Use Google Maps MCP for distance & routing
- Split stays across multiple locations if requested
- Respect budget using distance & stay pricing
- Return a detailed, realistic itinerary
"""
)

# -------------------------------------------------
# MAIN LOGIC (ASYNC ONLY)
# -------------------------------------------------
async def run_travel_planner(payload: dict) -> str:
    prompt = f"""
Create a detailed travel itinerary.

Destination: {payload['destination']}
Days: {payload['num_days']}
Budget: {payload['budget']} {payload['currency']}
Travelers: {payload['num_travelers']}
Trip Type: {payload['trip_type']}
Group Type: {payload['group_type']}
Preferences: {payload['preferences']}

Requirements:
- Use Airbnb listings (realistic prices)
- Calculate travel distance between locations
- Allocate budget day-wise
- If multiple stays requested, change location logically
- Provide property names, distances & activity flow
"""
    result = await agent.arun(prompt)
    return result.content
