import re
import os
import asyncio
from textwrap import dedent
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI
from pydantic import BaseModel

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.mcp import MultiMCPTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.models.openai import OpenAIChat

# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------

app = FastAPI(
    title="MCP AI Travel Planner API",
    description="Lovable-ready backend for MCP-powered travel planning",
    version="1.0.0",
)

# --------------------------------------------------
# INPUT SCHEMA (WHAT LOVABLE SENDS)
# --------------------------------------------------

class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str = "USD"
    num_travelers: int = 1
    trip_type: Optional[str] = "Standard"
    group_type: Optional[str] = "Solo"
    preferences: Optional[str] = "General sightseeing"

# --------------------------------------------------
# CORE AGENT LOGIC (UNCHANGED INTELLIGENCE)
# --------------------------------------------------

async def run_mcp_travel_planner(data: TripRequest) -> str:
    mcp_tools = None

    try:
        openai_key = os.environ.get("OPENAI_API_KEY")
        google_maps_key = os.environ.get("GOOGLE_MAPS_API_KEY")

        if not openai_key or not google_maps_key:
            raise ValueError("Missing OPENAI_API_KEY or GOOGLE_MAPS_API_KEY")

        os.environ["GOOGLE_MAPS_API_KEY"] = google_maps_key

        mcp_tools = MultiMCPTools(
            [
                "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
                "npx -y @gongrzhe/server-travelplanner-mcp",
            ],
            env={"GOOGLE_MAPS_API_KEY": google_maps_key},
            timeout_seconds=60,
        )

        await mcp_tools.connect()

        agent = Agent(
            name="Travel Planner",
            role="Creates detailed travel itineraries using Airbnb and Google Maps MCP",
            model=OpenAIChat(id="gpt-4o", api_key=openai_key),
            description=dedent(
                """
                You are a professional travel consultant AI.
                You must always generate a complete itinerary without asking questions.
                """
            ),
            instructions=[
                "Never ask the user questions.",
                "Always generate a full itinerary from provided data.",

                # Airbnb enforcement
                "You MUST use Airbnb MCP for all accommodation recommendations.",
                "Do NOT invent hotels or generic stays.",
                "Strictly respect the total trip budget.",
                "If Airbnb MCP finds no listings within budget, say so clearly and STOP.",

                # Maps enforcement
                "Use Google Maps MCP for distances and travel times.",
                "Provide exact addresses wherever possible.",

                # Output quality
                "Create extremely detailed, day-by-day plans.",
                "Include timings, costs, transport, food, safety, and packing tips.",
            ],
            tools=[mcp_tools, DuckDuckGoTools()],
            add_datetime_to_context=True,
            markdown=True,
            debug_mode=False,
        )

        enhanced_preferences = f"""
        {data.preferences}

        Number of Travelers: {data.num_travelers}
        Trip Type: {data.trip_type}
        Group Type: {data.group_type}
        Preferred Currency: {data.currency}
        """

        prompt = f"""
        IMMEDIATELY create a highly detailed travel itinerary.

        Destination: {data.destination}
        Duration: {data.num_days} days
        Total Budget: {data.budget} {data.currency}

        Traveler Preferences:
        {enhanced_preferences}

        ACCOMMODATION RULES:
        - Airbnb MCP MUST be used.
        - Total accommodation cost must fit within the overall budget.
        - If no Airbnb listings fit the budget, say so clearly and STOP.

        REQUIREMENTS:
        - Use Google Maps MCP for all distances and travel times.
        - Provide exact addresses.
        - Include buffer times.
        - Include food, transport, weather, safety, and cultural tips.

        Output in clean, readable Markdown.
        """

        response: RunOutput = await agent.arun(prompt)
        return response.content

    finally:
        if mcp_tools:
            await mcp_tools.close()

# --------------------------------------------------
# API ENDPOINT (WHAT LOVABLE CALLS)
# --------------------------------------------------

@app.post("/plan-trip")
async def plan_trip(request: TripRequest):
    itinerary = await run_mcp_travel_planner(request)
    return {
        "status": "success",
        "itinerary": itinerary,
    }

# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/")
def health():
    return {"status": "API is running"}
