from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="MCP AI Travel Planner API",
    description="Lovable-ready backend for MCP-powered travel planning",
    version="1.0.0",
)

# =========================
# CORS CONFIG (CRITICAL)
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for now (Lovable, browser, etc.)
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
    This endpoint is called by Lovable via POST.
    It returns a markdown itinerary string.
    """

    # Basic validation (extra safety)
    if not request.destination:
        raise HTTPException(status_code=400, detail="Destination is required")

    # 🔹 TEMP DEMO RESPONSE (replace with MCP agent call if needed)
    # Your real MCP logic can stay here – this is just a safe example
    itinerary = f"""
## ✈️ Trip to {request.destination}

**Duration:** {request.num_days} days  
**Budget:** {request.budget} {request.currency}  
**Travelers:** {request.num_travelers}  
**Trip Type:** {request.trip_type}  
**Group Type:** {request.group_type}

---

### 🗓 Day 1
- Arrival and hotel check-in
- Local sightseeing
- Dinner at a recommended restaurant

### 🗓 Day 2
- Cultural attractions
- Local food exploration
- Evening leisure time

### 🗓 Day 3
- Shopping and relaxation
- Departure

---

### 🎯 Preferences Considered
{request.preferences}

Enjoy your journey! 🌍
"""

    return {
        "status": "success",
        "itinerary": itinerary
    }
