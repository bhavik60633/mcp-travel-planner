// node-fetch with Yori's fix for Airbnb's country redirect page (see domain-handoff.mjs).
import nodeFetch from "node-fetch";
import { followDomainHandoff } from "./domain-handoff.mjs";

export * from "node-fetch";
export default followDomainHandoff(nodeFetch);
