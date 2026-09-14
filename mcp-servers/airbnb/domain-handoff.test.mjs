// TP-03 E5: from outside the US, www.airbnb.com answers with a small "Redirecting to www.airbnb.co.in"
// page instead of the search results (openbnb-org/mcp-server-airbnb issue #60, seen 14 Sep 2026).
// Yori repeats the request on the Airbnb domain that page names. Run: node --test domain-handoff.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { followDomainHandoff } from "./domain-handoff.mjs";

const SEARCH = "https://www.airbnb.com/s/Goa--India/homes?checkin=2026-10-14&checkout=2026-10-19&adults=2";
const PAGE = '<html><script id="data-deferred-state-0" type="application/json">{"ok":true}</script></html>';

// The page Airbnb sent from India on 14 Sep 2026, with its signed payload shortened.
const redirectPage = (host) => `<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Redirecting to ${host}</title></head>
<body onload="document.forms[0].submit()">
<form method="POST" action="https://${host}/v2/domain_switch/handoff">
<input type="hidden" name="version" value="1">
<input type="hidden" name="payload" value="eyJob3N0IjoiYWlyYm5iLmNvLmluIn0.signature">
<noscript><button type="submit">Redirecting to ${host}</button></noscript>
</form>
</body>
</html>`;

function fakeFetch(pages) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    const body = pages[new URL(url).host];
    return new Response(body ?? "not found", { status: body ? 200 : 404, headers: { "content-type": "text/html" } });
  };
  return { fetch, calls };
}

test("a country redirect page from airbnb.com is followed to that country's Airbnb", async () => {
  const { fetch, calls } = fakeFetch({ "www.airbnb.com": redirectPage("www.airbnb.co.in"), "www.airbnb.co.in": PAGE });
  const init = { headers: { "User-Agent": "test" } };

  const response = await followDomainHandoff(fetch)(SEARCH, init);

  assert.equal(response.status, 200);
  assert.equal(await response.text(), PAGE);
  assert.deepEqual(calls.map((call) => call.url), [SEARCH, SEARCH.replace("www.airbnb.com", "www.airbnb.co.in")]);
  assert.equal(calls[1].init, init);
});

test("a normal airbnb.com page comes back unchanged, from one request", async () => {
  const { fetch, calls } = fakeFetch({ "www.airbnb.com": PAGE });

  const response = await followDomainHandoff(fetch)(SEARCH, {});

  assert.equal(await response.text(), PAGE);
  assert.equal(calls.length, 1);
});

test("requests to other sites are passed through untouched", async () => {
  const { fetch, calls } = fakeFetch({ "photon.komoot.io": redirectPage("www.airbnb.co.in") });

  const response = await followDomainHandoff(fetch)("https://photon.komoot.io/api/?q=Goa", {});

  assert.match(await response.text(), /Redirecting to www\.airbnb\.co\.in/);
  assert.equal(calls.length, 1);
});

test("a redirect page naming a site that isn't Airbnb is not followed", async () => {
  const { fetch, calls } = fakeFetch({ "www.airbnb.com": redirectPage("www.example.com"), "www.example.com": PAGE });

  const response = await followDomainHandoff(fetch)(SEARCH, {});

  assert.match(await response.text(), /Redirecting to www\.example\.com/);
  assert.equal(calls.length, 1);
});

test("the Airbnb server's own fetch, imported from node-fetch, follows the redirect once the fix is loaded", () => {
  // Found on 14 Sep 2026: the server imports fetch from node-fetch instead of using Node's built-in fetch,
  // so replacing the built-in fetch changed nothing.
  const install = new URL("./install-domain-handoff.mjs", import.meta.url).href;
  const script = 'import fetch from "node-fetch"; console.log(fetch.name);';

  const result = spawnSync(process.execPath, ["--import", install, "--input-type=module", "-e", script], {
    cwd: fileURLToPath(new URL(".", import.meta.url)),
    encoding: "utf8",
  });

  assert.equal(result.stdout.trim(), "fetchFollowingDomainHandoff", result.stderr);
});
