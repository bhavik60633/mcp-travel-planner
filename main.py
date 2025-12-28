import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# --------------------
# CREATE AGENT (FIXED)
# --------------------
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-mini",  # ✅ MUST be `id`
        api_key=os.getenv("OPENAI_API_KEY")
    ),
    instructions="""
You are an expert travel planner.
Create a realistic, detailed, day-wise itinerary.
Use real places, food spots, timings, and travel tips.
Avoid generic templates and repetition.
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


# --------------------
# FASTAPI APP
# --------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/plan-trip")
def plan_trip(data: TripRequest):
    try:
        itinerary = run_travel_planner(data.dict())
        return {
            "status": "success",
            "itinerary": itinerary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
