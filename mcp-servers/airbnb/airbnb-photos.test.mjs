// TP-04 A2: the Airbnb server's photo field is switched on only for the pinned 0.3.0.
// Run: node --test airbnb-photos.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { PINNED_VERSION, switchOnPhotos } from "./airbnb-photos.mjs";
import { load } from "./airbnb-photos-hooks.mjs";

const SERVER = new URL("./node_modules/@openbnb/mcp-server-airbnb/dist/index.js", import.meta.url);
const serverSource = readFileSync(SERVER, "utf8");
const nextLoad = async (url) => ({ format: "module", source: readFileSync(new URL(url), "utf8"), shortCircuit: true });

function fakeServer(version, source) {
  const root = mkdtempSync(join(tmpdir(), "yori-airbnb-"));
  const dir = join(root, "node_modules", "@openbnb", "mcp-server-airbnb");
  mkdirSync(join(dir, "dist"), { recursive: true });
  writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "@openbnb/mcp-server-airbnb", version }));
  writeFileSync(join(dir, "dist", "index.js"), source);
  return pathToFileURL(join(dir, "dist", "index.js")).href;
}

async function withServerLog(run) {
  const written = [];
  const original = process.stderr.write;
  process.stderr.write = (chunk, ...rest) => {
    written.push(String(chunk));
    return true;
  };
  try {
    return { result: await run(), log: written.join("") };
  } finally {
    process.stderr.write = original;
  }
}

test("the pinned version is 0.3.0, the one installed", () => {
  const installed = JSON.parse(readFileSync(new URL("./node_modules/@openbnb/mcp-server-airbnb/package.json", import.meta.url), "utf8"));
  assert.equal(PINNED_VERSION, "0.3.0");
  assert.equal(installed.version, PINNED_VERSION);
});

test("the installed 0.3.0 server is loaded with its photo field switched on and nothing else changed", async () => {
  const loaded = await load(SERVER.href, {}, nextLoad);

  assert.match(String(loaded.source), /contextualPictures: \{ picture: true \}/);
  assert.doesNotMatch(String(loaded.source), /\/\/\s*contextualPictures/);
  const withoutField = (source) => source.replace(/\/\/\s*contextualPictures:\s*\{\s*\/\/\s*picture:\s*true\s*\/\/\s*\}|contextualPictures: \{ picture: true \}/, "");
  assert.equal(withoutField(String(loaded.source)), withoutField(serverSource));
});

test("another version is loaded unchanged, and the reason is written to the server log", async () => {
  const url = fakeServer("0.4.0", serverSource);

  const { result, log } = await withServerLog(() => load(url, {}, nextLoad));

  assert.equal(String(result.source), serverSource);
  assert.match(log, /Airbnb photos are off/);
  assert.match(log, /0\.4\.0/);
});

test("a 0.3.0 server without the photo field is loaded unchanged, with the reason", () => {
  const changed = serverSource.replace(/\/\/\s*contextualPictures:[\s\S]*?\/\/\s*\}/, "");

  const result = switchOnPhotos(changed, "0.3.0");

  assert.equal(result.enabled, false);
  assert.equal(result.source, changed);
  assert.match(result.reason, /photo field/);
});

test("other files are loaded untouched", async () => {
  const other = new URL("./domain-handoff.mjs", import.meta.url).href;

  const loaded = await load(other, {}, nextLoad);

  assert.equal(String(loaded.source), readFileSync(new URL(other), "utf8"));
});
