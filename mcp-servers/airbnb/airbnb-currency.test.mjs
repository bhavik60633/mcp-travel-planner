// TP-05 D2: Airbnb is asked for prices in rupees, whatever country the server runs in.
// Found on Render (Singapore) on 15 Sep 2026: Airbnb answered in US dollars, so the rupee budget didn't apply.
// Run: node --test airbnb-currency.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { askForRupees } from "./airbnb-currency.mjs";

function fakeFetch() {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response("ok", { status: 200 });
  };
  return { fetch, calls };
}

test("Airbnb searches and listing pages ask for prices in rupees, keeping everything else", async () => {
  const { fetch, calls } = fakeFetch();
  const init = { headers: { "User-Agent": "test" } };

  await askForRupees(fetch)("https://www.airbnb.com/s/Goa--India/homes?checkin=2026-10-14&adults=2", init);
  await askForRupees(fetch)(new URL("https://www.airbnb.co.in/rooms/123?check_in=2026-10-14"), init);

  const urls = calls.map((call) => new URL(call.url));
  assert.deepEqual(urls.map((url) => url.searchParams.get("currency")), ["INR", "INR"]);
  assert.equal(urls[0].searchParams.get("checkin"), "2026-10-14");
  assert.equal(urls[0].searchParams.get("adults"), "2");
  assert.equal(urls[1].pathname, "/rooms/123");
  assert.equal(calls[0].init, init);
});

test("a currency already asked for is replaced by rupees", async () => {
  const { fetch, calls } = fakeFetch();

  await askForRupees(fetch)("https://www.airbnb.com.sg/s/Goa/homes?currency=SGD", {});

  assert.equal(new URL(calls[0].url).searchParams.getAll("currency").join(","), "INR");
});

test("requests to other sites are passed through untouched", async () => {
  const { fetch, calls } = fakeFetch();
  const photon = "https://photon.komoot.io/api/?q=Goa";

  await askForRupees(fetch)(photon, {});

  assert.equal(calls[0].url, photon);
});
