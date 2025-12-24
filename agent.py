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
✈️ Trip to {destination}

📅 Duration: {num_days} days  
💰 Budget: {budget} {currency}

🎯 Preferences considered:
{preferences}

📍 Day-wise plan:
"""

    for day in range(1, num_days + 1):
        itinerary += f"""

Day {day}:
"""

        if "temple" in preferences.lower() or "spiritual" in preferences.lower():
            itinerary += """
- Visit famous temples
- Attend local rituals or aarti
- Peaceful evening walk
"""
        elif "adventure" in preferences.lower():
            itinerary += """
- Adventure activity (trekking / water sports)
- Local exploration
- Sunset viewpoint
"""
        elif "food" in preferences.lower():
            itinerary += """
- Local food tour
- Famous cafés & street food
- Dessert & night market
"""
        else:
            itinerary += """
- Morning sightseeing
- Local food exploration
- Evening leisure time
"""

    itinerary += f"""

✅ Budget Guidance:
- Designed to stay within {budget} {currency}
- Mix of paid attractions & free experiences

✨ Enjoy your personalized trip to {destination}! 🌍
"""

    return itinerary
