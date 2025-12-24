import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 🔑 Ensure key exists (Railway injects it)
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY not found in environment")

# 👉 IMPORT YOUR AGENT FUNCTION
# ⚠️ app.py MUST exist and contain run_travel_planner()
from app import run_travel_planner

app = FastAPI(
    title="MCP AI Travel Planner API",
    version="1.0.0"
)

# 🌐 CORS (Lovable fix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- MODELS ----------

class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str


# ---------- ROUTES ----------

@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/plan-trip")
def plan_trip(req: TripRequest):
    try:
        # 🔥 THIS IS THE REAL AGENT CALL
        itinerary_text = run_travel_planner(
            destination=req.destination,
            num_days=req.num_days,
            budget=req.budget,
            currency=req.currency,
            num_travelers=req.num_travelers,
            trip_type=req.trip_type,
            group_type=req.group_type,
            preferences=req.preferences,
        )

        return {
            "status": "success",
            "itinerary": itinerary_text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
