// Asks Airbnb for prices in rupees (TP-05 D2).
//
// Airbnb picks the currency from where a request comes from. On Render's Singapore server it answered in US dollars,
// so the rupee budget couldn't apply (seen 15 Sep 2026). Yori's stay budgets are in rupees, so every request to an
// Airbnb site asks for INR. Requests to other sites pass through untouched.

const AIRBNB_HOST = /^www\.airbnb\.[a-z]{2,3}(?:\.[a-z]{2})?$/i;
export const STAY_CURRENCY = "INR";

export function askForRupees(fetchImpl) {
  return async function fetchInRupees(input, init) {
    const url = new URL(typeof input === "string" || input instanceof URL ? String(input) : input.url);
    if (!AIRBNB_HOST.test(url.host)) return fetchImpl(input, init);
    url.searchParams.set("currency", STAY_CURRENCY);
    return fetchImpl(url.toString(), init);
  };
}
