// Import hook registered by install-domain-handoff.mjs. The Airbnb MCP server loads with its photo field
// switched on (see airbnb-photos.mjs). Every other file loads untouched.
import { readFileSync } from "node:fs";
import { switchOnPhotos } from "./airbnb-photos.mjs";

const SERVER_FILE = "/@openbnb/mcp-server-airbnb/dist/index.js";

function text(source) {
  return typeof source === "string" ? source : new TextDecoder().decode(source);
}

export async function load(url, context, nextLoad) {
  const loaded = await nextLoad(url, context);
  if (!url.endsWith(SERVER_FILE)) return loaded;

  let version = "unknown";
  try {
    version = JSON.parse(readFileSync(new URL("../package.json", url), "utf8")).version;
  } catch {
    // an unreadable package.json counts as an unchecked version
  }
  const result = switchOnPhotos(text(loaded.source), version);
  if (!result.enabled) process.stderr.write(`[yori] Airbnb photos are off: ${result.reason}\n`);
  return { ...loaded, source: result.source };
}
