from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import run_travel_planner

app = FastAPI(title="Yori MCP Travel Planner")

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
async def health():
    return {"status": "ok"}

@app.post("/plan-trip")
async def plan_trip(data: TripRequest):
    itinerary = await run_travel_planner(data.dict())
    return {
        "status": "success",
        "itinerary": itinerary
    }
