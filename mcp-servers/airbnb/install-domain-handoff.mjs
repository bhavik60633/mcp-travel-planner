// Loaded into the Airbnb MCP server with `node --import` before the server starts (see stays/airbnb.py).
// - The server imports fetch from node-fetch, so its node-fetch imports are pointed at Yori's wrapper, which
//   follows Airbnb's country redirect page (TP-03 E5).
// - The server loads with its listing photo field switched on (TP-04 A1).
import { register } from "node:module";

register("./node-fetch-hooks.mjs", import.meta.url);
register("./airbnb-photos-hooks.mjs", import.meta.url);
