// node-fetch with Yori's fixes for the Airbnb server: follow Airbnb's country redirect page (domain-handoff.mjs)
// and ask for prices in rupees (airbnb-currency.mjs).
import nodeFetch from "node-fetch";
import { askForRupees } from "./airbnb-currency.mjs";
import { followDomainHandoff } from "./domain-handoff.mjs";

export * from "node-fetch";
export default followDomainHandoff(askForRupees(nodeFetch));
