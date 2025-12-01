import re
import asyncio
from textwrap import dedent
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.mcp import MultiMCPTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.models.openai import OpenAIChat
from icalendar import Calendar, Event
from datetime import datetime, timedelta
import streamlit as st
from datetime import date
import os


# -------------------- ICS GENERATION --------------------


def generate_ics_content(plan_text: str, start_date: datetime = None) -> bytes:
    """Generate an .ics calendar file from a travel itinerary text."""
    cal = Calendar()
    cal.add("prodid", "-//AI Travel Planner//github.com//")
    cal.add("version", "2.0")

    if start_date is None:
        start_date = datetime.today()

    # Split itinerary by days like "Day 1:", "Day 2:", etc.
    day_pattern = re.compile(r"Day (\d+)[:\s]+(.*?)(?=Day \d+|$)", re.DOTALL)
    days = day_pattern.findall(plan_text)

    if not days:
        # Fallback: single all-day event
        event = Event()
        event.add("summary", "Travel Itinerary")
        event.add("description", plan_text)
        event.add("dtstart", start_date.date())
        event.add("dtend", start_date.date())
        event.add("dtstamp", datetime.now())
        cal.add_component(event)
    else:
        for day_num, day_content in days:
            day_num = int(day_num)
            current_date = start_date + timedelta(days=day_num - 1)

            event = Event()
            event.add("summary", f"Day {day_num} Itinerary")
            event.add("description", day_content.strip())
            event.add("dtstart", current_date.date())
            event.add("dtend", current_date.date())
            event.add("dtstamp", datetime.now())
            cal.add_component(event)

    return cal.to_ical()


# -------------------- CORE AGENT LOGIC --------------------


async def run_mcp_travel_planner(
    destination: str,
    num_days: int,
    preferences: str,
    budget: int,
    currency: str,
    openai_key: str,
    google_maps_key: str,
):
    """Async MCP-based travel planner with strict Airbnb usage and budget filtering."""
    try:
        # Google Maps key for MCP
        os.environ["GOOGLE_MAPS_API_KEY"] = google_maps_key

        # MCP tools: Airbnb + custom travel planner (uses Google Maps, etc.)
        mcp_tools = MultiMCPTools(
            [
                "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
                "npx @gongrzhe/server-travelplanner-mcp",
            ],
            env={"GOOGLE_MAPS_API_KEY": google_maps_key},
            timeout_seconds=60,
        )

        # Connect to all MCP servers
        await mcp_tools.connect()

        travel_planner = Agent(
            name="Travel Planner",
            role="Creates travel itineraries using Airbnb, Google Maps, and Web Search",
            model=OpenAIChat(id="gpt-4o", api_key=openai_key),
            description=dedent(
                """\
                You are a professional travel consultant AI that creates highly detailed travel itineraries
                directly without asking the user any questions.
                """
            ),
            instructions=[
                # Core behavior
                "Never ask the user questions — always generate a complete itinerary from the given input.",
                "Use all available tools (Airbnb MCP, Google Maps MCP, web search) proactively.",

                # Airbnb rules
                "Airbnb MCP MUST be used for ALL accommodation recommendations.",
                "Do NOT invent hotels or generic stays from general knowledge.",
                "Filter Airbnb results STRICTLY based on the total trip budget and number of travelers.",
                "Estimate how much of the total budget can reasonably be allocated to accommodation.",
                "Only select Airbnb listings whose total cost (per-night price × nights × travelers or guests) fits within that allocation.",
                "If Airbnb MCP fails or returns no suitable listings within budget, you MUST clearly say so and stop, rather than inventing accommodation.",

                # Maps & logistics
                "Use Google Maps MCP for all distances, travel times, and navigation info wherever possible.",
                "Include exact addresses for attractions, restaurants, and accommodations.",

                # Output style
                "Provide extremely detailed, day-by-day itineraries with timings, costs, and buffer time.",
                "Include transportation details, dining suggestions, weather/packing tips, safety and cultural notes.",
            ],
            tools=[mcp_tools, DuckDuckGoTools()],
            add_datetime_to_context=True,
            markdown=True,
            debug_mode=False,
        )

        # Main planning prompt
        prompt = f"""
        IMMEDIATELY create a highly detailed travel itinerary with the following info:

        **Destination:** {destination}
        **Duration:** {num_days} days
        **Total Budget:** {budget} {currency}

        **Traveler Details & Preferences:**
        {preferences}

        **ACCOMMODATION RULES (VERY IMPORTANT):**
        - You MUST use Airbnb MCP for ALL accommodation suggestions.
        - Do NOT fabricate hotels or stays: only use real Airbnb listings from the MCP tools.
        - Divide the total budget sensibly between accommodation, food, transport, and activities.
        - When choosing Airbnbs, ensure the total stay cost (per-night price × nights × appropriate guest count)
          keeps the entire trip within the overall budget.
        - If NO Airbnb listings are returned within budget, you MUST say clearly:
          "Airbnb MCP could not find accommodations within the budget" and stop instead of inventing options.

        **CRITICAL REQUIREMENTS:**
        - Must use Airbnb MCP for all accommodation listings and keep them within budget.
        - Must use Google Maps MCP for ALL distance and travel time calculations.
        - Provide exact street addresses for attractions, restaurants, and Airbnbs.
        - Include timings, transportation details, and estimated costs for each major step.
        - Include buffer time between activities to account for delays.
        - Provide weather expectations and packing recommendations.
        - Provide safety tips, cultural norms, currency information, and practical local advice.

        Produce everything in a clean, well-structured markdown format that is easy to read by a human traveler.
        """

        response: RunOutput = await travel_planner.arun(prompt)
        return response.content

    finally:
        # Ensure MCP connections are closed
        await mcp_tools.close()


def run_travel_planner(
    destination: str,
    num_days: int,
    preferences: str,
    budget: int,
    currency: str,
    openai_key: str,
    google_maps_key: str,
):
    """Sync wrapper around the async planner."""
    return asyncio.run(
        run_mcp_travel_planner(
            destination,
            num_days,
            preferences,
            budget,
            currency,
            openai_key,
            google_maps_key,
        )
    )


# -------------------- STREAMLIT APP --------------------


st.set_page_config(page_title="MCP AI Travel Planner", page_icon="✈️", layout="wide")

# Session state
if "itinerary" not in st.session_state:
    st.session_state.itinerary = None

st.title("✈️ MCP AI Travel Planner")
st.caption("Plan your next adventure with real-time Airbnb + Google Maps MCP data.")

# Sidebar – API keys
with st.sidebar:
    st.header("🔑 API Keys Configuration")
    st.warning("⚠️ These services require API keys:")

    openai_api_key = st.text_input("OpenAI API Key", type="password")
    google_maps_key = st.text_input("Google Maps API Key", type="password")

    api_keys_provided = bool(openai_api_key and google_maps_key)

    if api_keys_provided:
        st.success("✅ All API keys configured!")
    else:
        st.warning("⚠️ Please enter BOTH keys to use the travel planner.")


if api_keys_provided:
    # ---------- Trip basics ----------
    st.header("🌍 Trip Details")

    col1, col2 = st.columns(2)

    with col1:
        destination = st.text_input("Destination", placeholder="e.g., Paris, Tokyo, New York")
        num_days = st.number_input("Number of Days", min_value=1, max_value=60, value=7)

    with col2:
        budget = st.number_input("Total Trip Budget", min_value=100, max_value=100000, step=100, value=2000)
        start_date = st.date_input("Start Date", min_value=date.today(), value=date.today())

    # ---------- New fields ----------
    num_travelers = st.number_input("Number of Travelers (Pax)", min_value=1, max_value=20, value=2)

    currency = st.selectbox(
        "Currency",
        ["USD", "EUR", "INR", "GBP", "AUD", "CAD", "JPY"],
        index=0,
    )

    trip_type = st.selectbox("Trip Type", ["Standard", "Budget", "Luxury"])
    group_type = st.selectbox("Group Type", ["Solo", "Couple", "Friends", "Family", "Business Group"])
    # -------------------------------

    # ---------- Preferences ----------
    st.subheader("🎯 Travel Preferences")

    preferences_input = st.text_area(
        "Describe your preferences",
        placeholder="e.g., culture, museums, local food, some nightlife, low walking, etc.",
        height=100,
    )

    quick_prefs = st.multiselect(
        "Quick Preferences (optional)",
        [
            "Adventure",
            "Relaxation",
            "Sightseeing",
            "Cultural Experiences",
            "Beach",
            "Mountain",
            "Luxury",
            "Budget-Friendly",
            "Food & Dining",
            "Shopping",
            "Nightlife",
            "Family-Friendly",
        ],
    )

    all_prefs = []
    if preferences_input:
        all_prefs.append(preferences_input)
    if quick_prefs:
        all_prefs.extend(quick_prefs)

    preferences_text = ", ".join(all_prefs) if all_prefs else "General sightseeing"

    # Bundle everything so the agent sees traveler info too
    enhanced_preferences = f"""
    {preferences_text}

    Number of Travelers: {num_travelers}
    Trip Type: {trip_type}
    Group Type: {group_type}
    Preferred Currency: {currency}
    """

    # ---------- Generate button & calendar ----------
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🎯 Generate Itinerary", type="primary"):
            if not destination:
                st.error("Please enter a destination.")
            else:
                with st.spinner("🧭 Connecting to Airbnb & Maps and planning your trip..."):
                    try:
                        response = run_travel_planner(
                            destination=destination,
                            num_days=num_days,
                            preferences=enhanced_preferences,
                            budget=budget,
                            currency=currency,
                            openai_key=openai_api_key,
                            google_maps_key=google_maps_key,
                        )

                        # Enforce Airbnb usage in the response
                        lower_resp = response.lower()
                        if "airbnb" in lower_resp and (
                            "listing" in lower_resp or "accommodation" in lower_resp or "stay" in lower_resp
                        ):
                            st.session_state.itinerary = response
                            st.success("🏨 Airbnb MCP successfully used for accommodation within your budget!")
                        else:
                            st.session_state.itinerary = None
                            st.error(
                                "❌ Airbnb MCP data does not appear in the response. "
                                "The app is configured to require real Airbnb listings that fit your budget."
                            )
                            st.info(
                                "Please check your internet connection and API keys, then try again. "
                                "If the issue persists, Airbnb MCP may be temporarily unavailable."
                            )
                            st.stop()

                    except Exception as e:
                        st.session_state.itinerary = None
                        st.error(f"Error while generating itinerary: {str(e)}")
                        st.info("Please verify your API keys and network connection, then try again.")

    with col2:
        if st.session_state.itinerary:
            ics_file = generate_ics_content(
                st.session_state.itinerary,
                datetime.combine(start_date, datetime.min.time()),
            )
            st.download_button(
                label="📅 Download as Calendar",
                data=ics_file,
                file_name="travel_itinerary.ics",
                mime="text/calendar",
            )

    # ---------- Show itinerary ----------
    if st.session_state.itinerary:
        st.header("📋 Your Travel Itinerary")
        st.markdown(st.session_state.itinerary)
