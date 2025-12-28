from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import run_travel_planner

app = FastAPI(
    title="Yori MCP Travel Planner",
    version="1.0.0"
)

# -------------------------------------------------
# CORS (Lovable + Browser SAFE)
# -------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# REQUEST SCHEMA
# -------------------------------------------------
class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str

# -------------------------------------------------
# HEALTH
# -------------------------------------------------
@app.get("/")
async def health():
    return {"status": "ok"}

# -------------------------------------------------
# MAIN ENDPOINT (ASYNC — REQUIRED)
# -------------------------------------------------
@app.post("/plan-trip")
async def plan_trip(data: TripRequest):
    itinerary = await run_travel_planner(data.dict())
    return {
        "status": "success",
        "itinerary": itinerary
    }
