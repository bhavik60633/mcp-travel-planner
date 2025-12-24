from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio

# 🔹 IMPORT YOUR REAL AGENT FUNCTION
# This must already exist in your project (you showed it earlier)
from app import run_travel_planner  # ✅ DO NOT CHANGE if app.py contains the agent

# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="MCP AI Travel Planner API",
    description="Lovable-ready backend for MCP-powered travel planning",
    version="1.0.0",
)

# =========================
# CORS (REQUIRED FOR LOVABLE)
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for MVP
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# REQUEST MODEL
# =========================

class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str

# =========================
# HEALTH CHECK
# =========================

@app.get("/")
def health():
    return {"status": "ok"}

# =========================
# MAIN API ENDPOINT
# =========================

@app.post("/plan-trip")
async def plan_trip(request: TripRequest):
    """
    Generates a REAL itinerary using the MCP AI Travel Agent.
    """

    try:
        # 🔹 Call your real agent (blocking → async safe)
        itinerary = await asyncio.to_thread(
            run_travel_planner,
            destination=request.destination,
            num_days=request.num_days,
            preferences=request.preferences,
            budget=request.budget,
            currency=request.currency,
            openai_key=None,          # 🔑 agent already reads env var
            google_maps_key=None,     # 🔑 agent already reads env var
        )

        return {
            "status": "success",
            "itinerary": itinerary
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate itinerary: {str(e)}"
        )
