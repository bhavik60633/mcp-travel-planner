"""TP-05 A1–A8: every visit is checked against the place's opening hours for that day (Google and the AI simulated)."""

from __future__ import annotations

from helpers import FakeGooglePlaces, jaipur_places_with_hours

MONDAY = "2026-10-19"
JAIPUR_TRIP = {
    "destination": "Jaipur",
    "num_days": 2,
    "budget": 45000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Forts, museums and food.",
}


def plan(client, monkeypatch, itinerary, start_date=MONDAY, replacement=None):
    import main

    monkeypatch.setattr(main, "run_travel_planner", lambda data: itinerary)
    if replacement is not None:
        monkeypatch.setattr(main, "suggest_replacement", replacement)
    trip = dict(JAIPUR_TRIP)
    if start_date:
        trip["start_date"] = start_date
    r = client.post("/plan-trip", json=trip)
    assert r.status_code == 200, r.text
    return r.json()


def timing(body):
    return [(v["start"], v["end"], v["place"], v["status"], v["hours"], v["label"]) for v in body["visits"]]


def google():
    return FakeGooglePlaces(places=jaipur_places_with_hours())


# --------------------------------------------------------------------------- A1


def test_A1_the_ai_is_told_to_write_every_visit_as_a_time_range_with_the_place_in_bold():
    import main

    assert "09:00–11:00: **Hawa Mahal**" in str(main.agent.instructions)


def test_A1_each_days_visits_are_read_as_day_start_end_and_place():
    from places.schedule import read_visits

    itinerary = (
        "A 2-day plan.\n\n"
        "## Day 1: Pink City\n"
        "- 09:00–11:00: **Hawa Mahal** — see the windows.\n"
        "* 11:30 - 12:30: **Tapri Central**\n"
        "12:45–13:15 **Lassiwala** for a lassi\n"
        "- **Evening:** free time\n"
        "- Lunch at **Rawat Mishthan Bhandar**\n\n"
        "### Day 2 – Forts\n"
        "- 9:00 AM–10:30 AM: **Amber Fort**\n"
        "- 1:15 pm – 2:00 pm: **Panna Meena ka Kund**\n"
    )

    assert [(v.day, v.start, v.end, v.place) for v in read_visits(itinerary)] == [
        (1, "09:00", "11:00", "Hawa Mahal"),
        (1, "11:30", "12:30", "Tapri Central"),
        (1, "12:45", "13:15", "Lassiwala"),
        (2, "09:00", "10:30", "Amber Fort"),
        (2, "13:15", "14:00", "Panna Meena ka Kund"),
    ]


def test_A1_visits_with_a_few_words_before_the_place_are_read_too():
    # Found in a real itinerary on 14 Sep 2026: gpt-4o-mini wrote "12:30–13:30: Lunch at **LMB (Laxmi Misthan Bhandar)**".
    from places.schedule import read_visits

    itinerary = (
        "## Day 1: Pink City\n"
        "12:30–13:30: Lunch at **LMB (Laxmi Misthan Bhandar)** — dal baati churma.\n"
        "16:00–17:00: Coffee break at **Tapri Central** — rooftop chai.\n"
    )

    assert [(v.start, v.end, v.place) for v in read_visits(itinerary)] == [
        ("12:30", "13:30", "LMB (Laxmi Misthan Bhandar)"),
        ("16:00", "17:00", "Tapri Central"),
    ]


def test_A1_a_named_place_made_of_common_words_still_counts():
    # Found in the same itinerary: "11:00–12:30: **City Palace**" was skipped, because "city" and "palace" are common words.
    from places.extract import named_places
    from places.schedule import read_visits

    itinerary = "## Day 1: Pink City\n11:00–12:30: **City Palace** — the royal museum.\n- Rest at the **hotel**.\n- Walk through the **Old City**.\n"

    assert named_places(itinerary) == ["City Palace", "Old City"]
    assert [v.place for v in read_visits(itinerary)] == ["City Palace"]


# --------------------------------------------------------------------------- A2


def test_A2_place_checks_ask_google_for_opening_hours(review_client, monkeypatch):
    places = google()
    client = review_client(places)

    plan(client, monkeypatch, "## Day 1\n- 10:00–11:00: **Hawa Mahal**\n")

    fields = set(places.requests[0].headers["X-Goog-FieldMask"].split(","))
    assert {"places.regularOpeningHours", "places.currentOpeningHours", "places.utcOffsetMinutes"} <= fields


def test_A2_within_7_days_the_hours_for_that_exact_date_are_used_including_special_days(review_client, monkeypatch):
    # Hawa Mahal usually closes at 4:30 PM; on Wed 16 Sep 2026 (two days after "today") Google lists 1:00 PM.
    client = review_client(google())
    itinerary = "## Day 1: Pink City\n- 14:00–15:00: **Hawa Mahal**\n"

    soon = plan(client, monkeypatch, itinerary, start_date="2026-09-16")
    later = plan(client, monkeypatch, itinerary, start_date="2026-10-21")

    assert soon["visits"][0]["hours"] == "Open 9:00 AM – 1:00 PM"
    assert soon["visits"][0]["status"] == "time_changed"
    assert timing(later) == [("14:00", "15:00", "Hawa Mahal", "open", "Open 9:00 AM – 4:30 PM", "Open at this time")]


# --------------------------------------------------------------------------- A3


def test_A3_a_visit_inside_the_places_hours_is_open_at_this_time(review_client, monkeypatch):
    client = review_client(google())

    body = plan(client, monkeypatch, "## Day 1: Pink City\n- 09:00–11:00: **Hawa Mahal** — windows.\n- 11:30–12:30: **Tapri Central** — chai.\n")

    assert body["visits"] == [
        {"day": 1, "date": "2026-10-19", "start": "09:00", "end": "11:00", "planned_start": "09:00", "planned_end": "11:00",
         "place": "Hawa Mahal", "status": "open", "hours": "Open 9:00 AM – 4:30 PM", "label": "Open at this time"},
        {"day": 1, "date": "2026-10-19", "start": "11:30", "end": "12:30", "planned_start": "11:30", "planned_end": "12:30",
         "place": "Tapri Central", "status": "open", "hours": "Open 8:00 AM – 11:00 PM", "label": "Open at this time"},
    ]


# --------------------------------------------------------------------------- A4


def test_A4_a_visit_before_opening_moves_to_the_opening_time_keeping_its_length(review_client, monkeypatch):
    client = review_client(google())

    body = plan(client, monkeypatch, "## Day 1: Museums\n- 08:00–09:30: **Albert Hall Museum** — galleries.\n- 12:00–13:00: **Tapri Central** — lunch.\n")

    assert timing(body)[0] == ("10:00", "11:30", "Albert Hall Museum", "time_changed", "Open 10:00 AM – 5:00 PM", "Time changed: opens 10:00 AM")
    assert (body["visits"][0]["planned_start"], body["visits"][0]["planned_end"]) == ("08:00", "09:30")
    assert "- 10:00–11:30: **Albert Hall Museum** — galleries." in body["itinerary"]
    assert "08:00–09:30" not in body["itinerary"]


def test_A4_a_visit_after_closing_moves_earlier_to_end_at_closing_time(review_client, monkeypatch):
    client = review_client(google())

    body = plan(client, monkeypatch, "## Day 1: Museums\n- 16:30–18:00: **Albert Hall Museum** — galleries.\n")

    assert timing(body) == [("15:30", "17:00", "Albert Hall Museum", "time_changed", "Open 10:00 AM – 5:00 PM", "Time changed: closes 5:00 PM")]
    assert "- 15:30–17:00: **Albert Hall Museum**" in body["itinerary"]


def test_A4_a_visit_isnt_moved_onto_another_visit_and_is_labelled_closed_at_this_time(review_client, monkeypatch):
    client = review_client(google())
    itinerary = "## Day 1: Museums\n- 08:00–09:30: **Albert Hall Museum** — galleries.\n- 10:30–11:30: **Tapri Central** — chai.\n"

    body = plan(client, monkeypatch, itinerary)

    assert timing(body)[0] == ("08:00", "09:30", "Albert Hall Museum", "closed_at_time", "Open 10:00 AM – 5:00 PM", "Closed at this time · Open 10:00 AM – 5:00 PM")
    assert body["itinerary"] == itinerary


# --------------------------------------------------------------------------- A5


def test_A5_a_place_closed_all_that_day_is_replaced_once_with_one_open_at_that_time(review_client, monkeypatch):
    client = review_client(google())
    asked = []

    def replacement(name, reason):
        asked.append((name, reason))
        return "Albert Hall Museum"

    body = plan(client, monkeypatch, "## Day 1: Museums\n- 11:00–12:00: **Rajasthan Museum** — Rajput art.\n", replacement=replacement)

    assert asked == [("Rajasthan Museum", "closed on Monday")]
    assert timing(body) == [("11:00", "12:00", "Albert Hall Museum", "replaced", "Open 10:00 AM – 5:00 PM", "Suggested instead of a place that's closed on Monday")]
    assert "- 11:00–12:00: **Albert Hall Museum** — Rajput art." in body["itinerary"]
    assert "Rajasthan Museum" not in body["itinerary"]
    places = {place["query"]: place for place in body["places"]}
    assert (places["Albert Hall Museum"]["status"], places["Albert Hall Museum"]["replaces"], places["Albert Hall Museum"]["reason"]) == ("replaced", "Rajasthan Museum", "closed on Monday")
    assert "Rajasthan Museum" not in places


def test_A5_if_the_replacement_is_closed_too_the_place_is_labelled_closed_on_that_day(review_client, monkeypatch):
    client = review_client(google())
    asked = []
    itinerary = "## Day 1: Museums\n- 11:00–12:00: **Rajasthan Museum** — Rajput art.\n"

    body = plan(client, monkeypatch, itinerary, replacement=lambda name, reason: asked.append(name) or "Anokhi Museum")

    assert asked == ["Rajasthan Museum"]
    assert timing(body) == [("11:00", "12:00", "Rajasthan Museum", "closed_all_day", None, "Closed on Monday")]
    assert body["itinerary"] == itinerary


# --------------------------------------------------------------------------- A6


def test_A6_open_24_hours_and_hours_not_listed_are_never_closed(review_client, monkeypatch):
    client = review_client(google())

    body = plan(client, monkeypatch, "## Day 1: Views\n- 06:00–07:00: **Jaipur Junction** — trains.\n- 17:30–18:30: **Nahargarh Viewpoint** — sunset.\n")

    assert timing(body) == [
        ("06:00", "07:00", "Jaipur Junction", "open_24_hours", "Open 24 hours", "Open at this time"),
        ("17:30", "18:30", "Nahargarh Viewpoint", "hours_not_listed", "Hours not listed", None),
    ]


# --------------------------------------------------------------------------- A7


def test_A7_without_a_start_date_every_day_of_the_week_is_checked(review_client, monkeypatch):
    client = review_client(google())
    itinerary = (
        "## Day 1: Museums\n"
        "- 09:00–10:00: **Hawa Mahal**\n"
        "- 11:00–12:00: **Rajasthan Museum**\n"
        "- 13:00–14:00: **Anokhi Museum**\n"
        "- 15:00–16:00: **Chokhi Dhani**\n"
    )

    body = plan(client, monkeypatch, itinerary, start_date=None)

    assert timing(body) == [
        ("09:00", "10:00", "Hawa Mahal", "open", "Open 9:00 AM – 4:30 PM", "Open at this time"),
        ("11:00", "12:00", "Rajasthan Museum", "closed_some_days", None, "Closed at this time on Monday"),
        ("13:00", "14:00", "Anokhi Museum", "closed_some_days", None, "Closed at this time on Monday and Tuesday"),
        ("15:00", "16:00", "Chokhi Dhani", "closed_at_time", "Open 5:00 PM – 11:00 PM", "Closed at this time · Open 5:00 PM – 11:00 PM"),
    ]
    assert [v["date"] for v in body["visits"]] == [None, None, None, None]
    assert body["itinerary"] == itinerary


# --------------------------------------------------------------------------- A8


def test_A8_changed_times_and_replacements_are_in_the_itinerary_text_and_in_places(review_client, monkeypatch):
    client = review_client(google())
    itinerary = (
        "A 2-day plan for Jaipur.\n\n"
        "## Day 1: Museums\n- 08:00–09:30: **Albert Hall Museum** — galleries.\n- 12:00–13:00: **Rajasthan Museum** — Rajput art.\n\n"
        "## Day 2: Old City\n- 09:00–11:00: **Hawa Mahal** — windows.\n"
    )

    body = plan(client, monkeypatch, itinerary, replacement=lambda name, reason: "Tapri Central")

    assert body["itinerary"] == (
        "A 2-day plan for Jaipur.\n\n"
        "## Day 1: Museums\n- 10:00–11:30: **Albert Hall Museum** — galleries.\n- 12:00–13:00: **Tapri Central** — Rajput art.\n\n"
        "## Day 2: Old City\n- 09:00–11:00: **Hawa Mahal** — windows.\n"
    )
    assert [(v["day"], v["date"], v["start"], v["end"], v["place"], v["status"]) for v in body["visits"]] == [
        (1, "2026-10-19", "10:00", "11:30", "Albert Hall Museum", "time_changed"),
        (1, "2026-10-19", "12:00", "13:00", "Tapri Central", "replaced"),
        (2, "2026-10-20", "09:00", "11:00", "Hawa Mahal", "open"),
    ]
    places = {place["query"]: place for place in body["places"]}
    assert set(places) == {"Albert Hall Museum", "Tapri Central", "Hawa Mahal"}
    assert (places["Tapri Central"]["status"], places["Tapri Central"]["replaces"]) == ("replaced", "Rajasthan Museum")
