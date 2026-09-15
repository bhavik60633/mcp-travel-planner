// Import hook registered by install-domain-handoff.mjs. The Airbnb MCP server imports fetch from node-fetch,
// so wherever node-fetch is imported, this hands out Yori's wrapper instead. The wrapper itself still gets
// the real node-fetch.
const WRAPPER = new URL("./node-fetch-with-handoff.mjs", import.meta.url).href;

export async function resolve(specifier, context, nextResolve) {
  if (specifier === "node-fetch" && context.parentURL !== WRAPPER) {
    return { url: WRAPPER, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
