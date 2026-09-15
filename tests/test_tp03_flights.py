"""TP-03 A, B, C: flight prices match Google Flights.

Google is simulated with its own pages, saved on 14 Sep 2026 (tests/fixtures/google-*):
Delhi -> Mumbai on 14 Oct 2026 in INR and USD, the round-trip outbound list, and the
return lists Google shows after a non-stop and after a connecting outbound flight.
"""

from __future__ import annotations

import httpx
import pytest

from helpers import FakeGoogle, decode_b64, google_page_html, make_offer, priced_flights_leaving

INR_PAGE = ("google-ds1-DEL-BOM-2026-10-14-INR.js", "google-labels-DEL-BOM-2026-10-14-INR.txt")
USD_PAGE = ("google-ds1-DEL-BOM-2026-10-14-USD.js", "google-labels-DEL-BOM-2026-10-14-USD.txt")
DEL_LHR_USD_PAGE = ("google-ds1-DEL-LHR-2026-10-14-USD.js", "google-labels-DEL-LHR-2026-10-14-USD.txt")
ONE_WAY = {"from": "DEL", "to": "BOM", "depart": "2026-10-14"}
ROUND_TRIP = {"from": "DEL", "to": "BOM", "depart": "2026-10-14", "return": "2026-10-18", "currency": "INR"}


def google_source(*pages: str, pick=None):
    from flights.google_page import GooglePage
    from flights.sources import GfSearchSource

    google = FakeGoogle(*pages, pick=pick)
    return GfSearchSource(search_fn=GooglePage(http_get=google).search), google


def flight_numbers(journey: dict) -> list[str]:
    return [segment["flight_number"] for segment in journey["segments"]]


# --------------------------------------------------------------------------- A1


def test_A1_prices_come_back_in_the_chosen_currency(make_client):
    source, google = google_source(google_page_html(*USD_PAGE))
    client = make_client(sources=[source])

    r = client.get("/api/flights", params={**ONE_WAY, "currency": "USD", "sort": "cheapest"})

    assert r.status_code == 200, r.text
    request = google.requests[0]
    assert request["url"] == "https://www.google.com/travel/flights/search"
    assert (request["curr"], request["hl"], request["gl"]) == ("USD", "en", "IN")
    offers = r.json()["offers"]
    assert {offer["currency"] for offer in offers} == {"USD"}
    assert offers[0]["price"] == 63
    cheapest_nonstop = next(offer for offer in offers if offer["stops"] == 0)
    assert (cheapest_nonstop["price"], flight_numbers(cheapest_nonstop["outbound"])) == (66, ["AI 1745"])


@pytest.mark.parametrize("currency", ["INR", "EUR"])
def test_A1_a_page_in_another_currency_is_never_relabelled(make_client, currency):
    source, _ = google_source(google_page_html(*USD_PAGE))  # Google answered in US dollars
    client = make_client(sources=[source])

    r = client.get("/api/flights", params={**ONE_WAY, "currency": currency})

    assert r.status_code == 503
    assert r.json()["message"] == "Flight prices are temporarily unavailable. Try again in a few minutes."
    assert f"{currency} 63" not in r.text


def test_A1_fli_is_asked_in_english_for_india_in_the_chosen_currency(make_client):
    # Found by the live A2 check on 14 Sep 2026: without the country, fli got US-market fares in USD.
    from flights.models import DatesQuery
    from flights.sources import FliDateSource, FliSource

    from helpers import FakeFliClient

    flights_client = FakeFliClient(results=[])
    client = make_client(sources=[FliSource(client=flights_client)])
    client.get("/api/flights", params={"from": "DEL", "to": "LHR", "depart": "2026-10-14", "currency": "USD"})
    assert flights_client.searches[0] | {"filters": None} == {"filters": None, "currency": "USD", "language": "en", "country": "IN"}

    dates_client = FakeFliClient(results=[])
    query = DatesQuery(origin="DEL", destination="LHR", start=__import__("datetime").date(2026, 10, 1), end=__import__("datetime").date(2026, 10, 10),
                       trip_days=None, adults=1, cabin="economy", currency="GBP")
    FliDateSource(client=dates_client).search_dates(query)
    assert dates_client.searches[0] | {"filters": None} == {"filters": None, "currency": "GBP", "language": "en", "country": "IN"}


def test_A1_inr_page_gives_rupee_prices(make_client):
    source, google = google_source(google_page_html(*INR_PAGE))
    client = make_client(sources=[source])

    offers = client.get("/api/flights", params={**ONE_WAY, "currency": "INR", "sort": "cheapest"}).json()["offers"]

    assert google.requests[0]["curr"] == "INR"
    assert offers[0]["price"] == 5985
    assert next(o for o in offers if o["stops"] == 0)["price"] == 6314


# --------------------------------------------------------------------------- A3


def test_A3_every_priced_flight_on_the_page_is_in_the_results(make_client):
    from helpers import FIXTURES

    labels = [line for line in (FIXTURES / INR_PAGE[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
    source, _ = google_source(google_page_html(*INR_PAGE))
    client = make_client(sources=[source])

    body = client.get("/api/flights", params={**ONE_WAY, "currency": "INR"}).json()

    assert len(labels) == 66
    assert body["count"] == len(body["offers"]) == len(labels)


def test_A3_flights_left_out_of_one_read_of_googles_page_are_still_found(make_client):
    # Found by the live A2 check on 14 Sep 2026: one read of Google's page left out the cheapest
    # Delhi -> London flight, so Yori's cheapest was ₹23,305 instead of ₹22,434.
    from helpers import google_page_html_without

    partial = google_page_html_without(*INR_PAGE, drop_price=5985)
    full = google_page_html(*INR_PAGE)
    source, google = google_source(partial, full, full)
    client = make_client(sources=[source])

    body = client.get("/api/flights", params={**ONE_WAY, "currency": "INR", "sort": "cheapest"}).json()

    assert body["offers"][0]["price"] == 5985
    assert body["count"] == 66
    assert len(google.requests) == 3


def test_A3_googles_page_is_read_again_only_while_new_flights_appear(make_client):
    source, google = google_source(google_page_html(*INR_PAGE))
    client = make_client(sources=[source])

    body = client.get("/api/flights", params={**ONE_WAY, "currency": "INR"}).json()

    assert body["count"] == 66
    assert len(google.requests) == 2  # the second read added nothing new, so there was no third


def test_A3_flights_sharing_an_airline_and_departure_time_are_all_kept(make_client):
    # Found by the live A2 check on 14 Sep 2026: gf-search's page reader counts flights with the same airline
    # and departure time as one and keeps whichever Google lists first. On Delhi -> London that hid Finnair's
    # $235 and $238 connections behind its $245 one, so Yori's cheapest was $244 instead of $235.
    from helpers import FIXTURES

    labels = [line for line in (FIXTURES / DEL_LHR_USD_PAGE[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
    source, _ = google_source(google_page_html(*DEL_LHR_USD_PAGE))
    client = make_client(sources=[source])

    body = client.get("/api/flights", params={"from": "DEL", "to": "LHR", "depart": "2026-10-14", "currency": "USD", "sort": "cheapest"}).json()

    finnair = sorted((o["price"], flight_numbers(o["outbound"])) for o in body["offers"] if flight_numbers(o["outbound"])[0] == "AY 122")
    assert finnair == [(235, ["AY 122", "AY 1331"]), (238, ["AY 122", "AY 1339"]), (245, ["AY 122", "AY 1337"])]
    assert body["offers"][0]["price"] == 235
    assert body["count"] == len(labels) == 13


# --------------------------------------------------------------------------- A4


def test_A4_default_order_is_best_and_cheapest_is_still_available(make_client):
    nonstop = make_offer(origin="DEL", destination="BOM", depart="2026-10-14", price=6314, airline_code="AI",
                         airline="Air India", flight_number="AI 1745", dep_time="05:00", arr_time="07:10", duration=130)
    one_stop_data = make_offer(origin="DEL", destination="BOM", depart="2026-10-14", price=5985, flight_number="6E 6261",
                               dep_time="00:15", arr_time="07:15", duration=420).model_dump(by_alias=True)
    one_stop_data["stops"] = 1
    one_stop_data["outbound"]["stops"] = 1
    one_stop_data["outbound"]["layovers"] = [{"airport": "AMD", "duration_min": 190}]
    one_stop_data["outbound"]["segments"].append({**one_stop_data["outbound"]["segments"][0], "flight_number": "6E 6285", "from": "AMD"})
    one_stop_data["outbound"]["segments"][0]["to"] = "AMD"
    one_stop_data["id"] = "one-stop"
    from flights.models import Offer

    from helpers import FakeSource

    source = FakeSource("gf-search", offers=[Offer.model_validate(one_stop_data), nonstop])
    client = make_client(sources=[source])

    best = client.get("/api/flights", params={**ONE_WAY, "currency": "INR"}).json()
    assert best["sort"] == "best"
    assert [o["price"] for o in best["offers"]] == [6314, 5985]  # the 2 h 10 m non-stop first

    cheapest = client.get("/api/flights", params={**ONE_WAY, "currency": "INR", "sort": "cheapest"}).json()
    assert cheapest["sort"] == "cheapest"
    assert [o["price"] for o in cheapest["offers"]] == [5985, 6314]
    assert len(source.calls) == 1  # changing the order doesn't search again


def test_A4_best_order_on_a_real_google_page_puts_the_quick_non_stop_before_slow_connections(make_client):
    source, _ = google_source(google_page_html(*INR_PAGE))
    client = make_client(sources=[source])

    offers = client.get("/api/flights", params={**ONE_WAY, "currency": "INR"}).json()["offers"]

    air_india = next(i for i, o in enumerate(offers) if flight_numbers(o["outbound"]) == ["AI 1745"])
    slow_connection = next(i for i, o in enumerate(offers) if o["price"] == 5985 and o["stops"] == 1)
    assert air_india < slow_connection


def test_A4_unknown_sort_is_a_plain_400(make_client):
    from helpers import FakeSource

    client = make_client(sources=[FakeSource("gf-search")])

    r = client.get("/api/flights", params={**ONE_WAY, "sort": "random"})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": "Sort must be one of best, cheapest, fastest, earliest."}


# --------------------------------------------------------------------------- B1


def test_B1_nearby_day_prices_from_travelpayouts_mark_days_without_data(make_client):
    from flights.sources import TravelpayoutsDateSource

    def handler(request):
        assert request.url.path == "/aviasales/v3/grouped_prices"
        assert request.url.params["departure_at"] == "2026-10"
        return httpx.Response(200, json={
            "success": True,
            "currency": "inr",
            "data": {
                "2026-10-06": {"price": 16120, "departure_at": "2026-10-06T08:10:00+05:30"},
                "2026-10-08": {"price": 15890, "departure_at": "2026-10-08T15:05:00+05:30"},
                "2026-10-09": {"price": 0, "departure_at": "2026-10-09T06:05:00+05:30"},
                "2026-10-10": {"price": 17005.6, "departure_at": "2026-10-10T22:35:00+05:30"},
            },
        })

    source = TravelpayoutsDateSource(token="tp-test-token-5a4b3c2d1e", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client = make_client(date_sources=[source])

    body = client.get("/api/flights/dates", params={"from": "BOM", "to": "DXB", "start": "2026-10-06", "end": "2026-10-10", "currency": "INR"}).json()

    assert body["source"] == "travelpayouts"
    assert body["days"] == [
        {"date": "2026-10-06", "price": 16120},
        {"date": "2026-10-08", "price": 15890},
        {"date": "2026-10-10", "price": 17006},
    ]
    assert body["missing"] == ["2026-10-07", "2026-10-09"]


# --------------------------------------------------------------------------- C1


@pytest.mark.parametrize(
    "pick, returns_fixture",
    [
        (["6E 675"], "google-ds1-DEL-BOM-2026-10-18-rt-returns-after-nonstop-INR.js"),
        (["6E 6261", "6E 6285"], "google-ds1-DEL-BOM-2026-10-18-rt-returns-after-connecting-INR.js"),
    ],
)
def test_C1_choosing_an_outbound_flight_returns_googles_matching_returns(make_client, pick, returns_fixture):
    numbers = [number.split()[1].encode() for number in pick]

    def chosen_in(params: dict) -> bool:
        return all(number in decode_b64(params["tfs"]) for number in numbers)

    outbound_page = google_page_html("google-ds1-DEL-BOM-2026-10-14-rt-outbound-INR.js")
    source, google = google_source(outbound_page, google_page_html(returns_fixture), pick=lambda params: 1 if chosen_in(params) else 0)
    client = make_client(sources=[source])

    outbound = client.get("/api/flights", params=ROUND_TRIP).json()
    assert outbound["query"]["trip"] == "round_trip"
    assert all(offer["return"] is None for offer in outbound["offers"])
    chosen = next(offer for offer in outbound["offers"] if flight_numbers(offer["outbound"]) == pick)

    r = client.get("/api/flights/returns", params={**ROUND_TRIP, "outbound": chosen["id"]})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outbound"]["id"] == chosen["id"]
    assert body["count"] == len(body["offers"]) == priced_flights_leaving(returns_fixture, "BOM")
    for offer in body["offers"]:
        assert flight_numbers(offer["outbound"]) == pick
        back = offer["return"]
        assert (back["from"], back["to"]) == ("BOM", "DEL")
        assert back["departure"].startswith("2026-10-18")
        assert isinstance(offer["price"], int) and offer["price"] > 0 and offer["currency"] == "INR"
        assert offer["duration_min"] == offer["outbound"]["duration_min"] + back["duration_min"]
        assert (offer["return_match"], offer["booking_type"]) == ("exact", "exact")
        assert offer["booking_url"].startswith("https://www.google.com/travel/flights/booking?tfs=")

    outbound_reads = [request for request in google.requests if not chosen_in(request)]
    return_reads = [request for request in google.requests if chosen_in(request)]
    assert len(outbound_reads) == 2  # read until nothing new appeared, then served from the cache for the returns step
    assert 1 <= len(return_reads) <= 3
    selection = decode_b64(return_reads[0]["tfs"])
    for part in [b"2026-10-14", b"2026-10-18"] + [number.split()[1].encode() for number in pick]:
        assert part in selection, part


def test_C1_an_outbound_flight_that_is_no_longer_listed_is_a_plain_404(make_client):
    source, _ = google_source(google_page_html("google-ds1-DEL-BOM-2026-10-14-rt-outbound-INR.js"))
    client = make_client(sources=[source])

    r = client.get("/api/flights/returns", params={**ROUND_TRIP, "outbound": "gf-search:XX 1:2026-10-14T00:00"})

    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "message": "That outbound flight is no longer available. Search again."}


def test_C1_returns_need_a_return_date(make_client):
    source, _ = google_source(google_page_html(*INR_PAGE))
    client = make_client(sources=[source])

    r = client.get("/api/flights/returns", params={**ONE_WAY, "currency": "INR", "outbound": "any"})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": "Choose a return date to see return flights."}
