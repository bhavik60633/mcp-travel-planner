from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os

# ---------- OPENAI CLIENT ----------
client = OpenAI(api_key=os.getenv("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"))

# ---------- FASTAPI APP ----------
app = FastAPI(title="MCP AI Travel Planner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Lovable needs this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- REQUEST MODEL ----------
class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str

# ---------- HEALTH ----------
@app.get("/")
def health():
    return {"status": "ok"}

# ---------- MAIN AI ENDPOINT ----------
@app.post("/plan-trip")
def plan_trip(req: TripRequest):
    try:
        prompt = f"""
You are an expert human travel planner.

Create a REAL, detailed, non-repetitive itinerary.

Destination: {req.destination}
Days: {req.num_days}
Budget: {req.budget} {req.currency}
Travelers: {req.num_travelers}
Trip Type: {req.trip_type}
Group Type: {req.group_type}
Preferences: {req.preferences}

Rules:
- Every day MUST be different
- Use real locations
- Include food, timing, travel
- No generic templates
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.9
        )

        itinerary = response.choices[0].message.content

        return {
            "status": "success",
            "itinerary": itinerary
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
