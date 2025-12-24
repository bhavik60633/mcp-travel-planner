from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

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
def plan_trip(req: TripRequest):

    prompt = f"""
You are a professional travel planner.

Create a detailed, realistic, day-wise itinerary.

Destination: {req.destination}
Days: {req.num_days}
Budget: {req.budget} {req.currency}
Travelers: {req.num_travelers}
Trip type: {req.trip_type}
Group type: {req.group_type}
Preferences: {req.preferences}

Rules:
- Every day must be different
- Include real places
- Include food, transport, timing
- Avoid generic phrases
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )

    itinerary = response.choices[0].message.content

    return {
        "status": "success",
        "itinerary": itinerary
    }
