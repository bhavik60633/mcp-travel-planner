from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import run_travel_planner

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
