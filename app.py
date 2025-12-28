from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MultiMCPTools

# MCP tools (auto-detected, no manual servers)
mcp_tools = MultiMCPTools()

agent = Agent(
    model=OpenAIChat(),
    tools=[mcp_tools],
    system_prompt="""
You are Yori Travel Agent.

Rules:
- Use MCP tools when available (Airbnb, Maps)
- Generate realistic itineraries
- Split stays if requested
- Respect distance and budget
"""
)

async def run_travel_planner(payload: dict) -> str:
    prompt = f"""
Destination: {payload['destination']}
Days: {payload['num_days']}
Budget: {payload['budget']} {payload['currency']}
Travelers: {payload['num_travelers']}
Trip Type: {payload['trip_type']}
Group Type: {payload['group_type']}
Preferences: {payload['preferences']}

Generate a detailed itinerary.
"""
    response = await agent.arun(prompt)
    return response.content
