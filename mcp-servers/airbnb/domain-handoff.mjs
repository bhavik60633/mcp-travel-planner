// Follows Airbnb's country redirect page (TP-03 E5).
//
// From outside the US, www.airbnb.com answers with a small page that sends the browser on to the
// country's Airbnb (www.airbnb.co.in from India) instead of the page asked for. The Airbnb MCP server
// can't follow it, so every search failed (openbnb-org/mcp-server-airbnb issue #60, seen 14 Sep 2026).
// This repeats the same request on the Airbnb domain that page names. Other sites pass through untouched.

const REDIRECT_FORM = /<form[^>]+action="https:\/\/(www\.airbnb\.[a-z]{2,3}(?:\.[a-z]{2})?)\/v2\/domain_switch\/handoff"/i;
const REDIRECT_PAGE_MAX_CHARS = 20000; // the redirect page is about 1 KB; real result pages are over 1 MB

export function followDomainHandoff(fetchImpl) {
  return async function fetchFollowingDomainHandoff(input, init) {
    const response = await fetchImpl(input, init);
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
    if (url.host !== "www.airbnb.com") return response;

    const body = await response.text();
    const target = body.length < REDIRECT_PAGE_MAX_CHARS ? REDIRECT_FORM.exec(body)?.[1] : undefined;
    if (!target || target === url.host) {
      return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
    }
    url.host = target;
    return fetchImpl(url.toString(), init);
  };
}
