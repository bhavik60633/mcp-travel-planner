from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio

# 🔹 IMPORT YOUR MCP AGENT (logic only, NOT FastAPI)
from app import run_travel_planner  # app.py must NOT create FastAPI()

app = FastAPI(
    title="MCP AI Travel Planner API",
    version="1.0.0",
)

# ✅ CORS — THIS IS WHAT LOVABLE NEEDS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
async def plan_trip(req: TripRequest):
    try:
        itinerary = await asyncio.to_thread(
            run_travel_planner,
            destination=req.destination,
            num_days=req.num_days,
            preferences=req.preferences,
            budget=req.budget,
            currency=req.currency,
            openai_key=None,
            google_maps_key=None,
        )

        return {
            "status": "success",
            "itinerary": itinerary
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
