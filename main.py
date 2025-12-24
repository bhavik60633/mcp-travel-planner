import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# --------------------
# CREATE AGENT
# --------------------
agent = Agent(
    model=OpenAIChat(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini"
    ),
    instructions="""
You are an expert travel planner.
Create a realistic, detailed, day-wise itinerary.
Use local places, food, timings, and travel tips.
Do NOT return generic templates.
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
