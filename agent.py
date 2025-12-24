def run_travel_planner(
    destination: str,
    num_days: int,
    preferences: str,
    budget: int,
    currency: str,
    openai_key=None,
    google_maps_key=None,
):
    itinerary = f"""
Trip to {destination}

Duration: {num_days} days
Budget: {budget} {currency}

Preferences considered:
{preferences}

Day-wise plan:
"""

    for day in range(1, num_days + 1):
        itinerary += f"""
Day {day}:
- Morning sightseeing
- Local food exploration
- Evening leisure time
"""

    itinerary += "\nEnjoy your journey! 🌍✈️"

    return itinerary
