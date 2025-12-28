# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import run_travel_planner

app = FastAPI(title="MCP AI Travel Planner")

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
    trip_type: str | None = None
    group_type: str | None = None
    preferences: str | None = None

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/plan-trip")
def plan_trip(data: TripRequest):
    itinerary = run_travel_planner(data.dict())
    return {
        "status": "success",
        "itinerary": itinerary
    }
