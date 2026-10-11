// Freya Bank statement services, our mock for the final case.
// Stateless replay of data/test-customers.json (the pack's test-environment file): for a known customer / card /
// week it returns exactly the listed status and body, after `delaySeconds` when present.
//
// Wire contract: sources/documents/2026-10-01-service-contract.md (Mert Koç, 1 Oct 2026).
// - POST https://<worker>/voice/v1/<service>, JSON in/out, UTF-8 (also answered at /<service> and /v1/<service>).
// - Request envelope {"data": {...service fields...}, "call": {...}}; only `data` decides the answer (token,
//   headers, `call`, `aiFlow`, `statementDay`, `intAddressInfoType` are not checked in test).
// - Not in the file: that service's 404 from contract section 4, else 400 INVALID_ARGUMENTS_ERROR (contract §6).

import DATA from "../data/test-customers.json";

const BASE = "/voice/v1";
const SERVICES = ["cards.list", "cards.balance", "statement.week.get", "statement.week.decide",
  "statement.week.change", "contact.email.get", "statement.pdf.send"];
const BY_CUSTOMER = new Set(["cards.list", "contact.email.get", "statement.pdf.send"]);
const BY_WEEK = new Set(["statement.week.decide", "statement.week.change"]);

const CUSTOMERS = new Map(DATA.customers.map((c) => [String(c.customerNo), c]));
// masked card number (as cards.list gives it) -> customer; the keys are unique across the file
const CARDS = new Map();
for (const c of DATA.customers)
  for (const s of SERVICES)
    if (!BY_CUSTOMER.has(s)) for (const card of Object.keys(c.services[s] || {})) CARDS.set(card, c);

// Error bodies: the contract's envelope (section 4), no `data`.
const ORIGIN = "ivr-gateway-test:ivr-channel-v0";
const EXC = "com.freyabank.ivrgateway.ivrchannel.rest.exception.";
function guid() {
  return [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function bankError(code, message, type, rootCause) {
  const g = guid();
  return { result: { guid: g, returnCode: code, messageText: message, code, message, type,
    details: { guid: g, rootCause, errorOrigin: ORIGIN } } };
}
const invalid = (message) => [400, bankError("INVALID_ARGUMENTS_ERROR", message, "ERROR", EXC + "InvalidArgumentsException")];
const notFound = (code, message) => [404, bankError(code, message, "WARNING", EXC + "NotFoundException")];
// "not in the file" answer per service: its 404 from contract §4 where it has one, else 400
const MISSING = {
  "cards.list": () => notFound("FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı."),
  "cards.balance": () => notFound("FB_IVR_CHANNEL_120", "Kart bakiye servisi hatası: kart bulunamadı"),
  "statement.week.get": () => notFound("FB_IVR_CHANNEL_121", "Ekstre haftası servisi hatası: kart bulunamadı"),
  "statement.week.decide": () => invalid("card or statement week not found"),
  "statement.week.change": () => invalid("card or statement week not found"),
  "contact.email.get": () => invalid("customer not found"),
  "statement.pdf.send": () => notFound("FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı"),
};

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8" } });
}

// A scalar request field as a trimmed string, or null when missing / empty.
function field(data, name) {
  const v = data[name];
  if (v === undefined || v === null || typeof v === "object") return null;
  const s = String(v).trim();
  return s === "" ? null : s;
}

// The contract asks for the card number exactly as cards.list gave it ("540000******1234"). Also accepted, since
// the visible digits are unique in the file: the cards.balance mask ("5400********1234") and a full 16-digit number.
function findCard(raw) {
  const c = raw.replace(/[\s-]/g, "");
  if (CARDS.has(c)) return c;
  let head;
  if (/^\d{4}\*{8}\d{4}$/.test(c)) head = c.slice(0, 4);
  else if (/^\d{16}$/.test(c)) head = c.slice(0, 6);
  else return null;
  const hits = [...CARDS.keys()].filter((k) => k.startsWith(head) && k.endsWith(c.slice(-4)));
  return hits.length === 1 ? hits[0] : null;
}

async function serve(service, data) {
  let entry;
  if (BY_CUSTOMER.has(service)) {
    const no = field(data, "customerNo");
    if (!no) return invalid("customer number cannot be empty");
    if (service === "contact.email.get" && "intAddressInfoType" in data && !field(data, "intAddressInfoType"))
      return invalid("intAddressInfoType cannot be empty");
    entry = CUSTOMERS.get(no)?.services[service];
  } else {
    const raw = field(data, "cardNumber");
    if (!raw) return invalid("card number cannot be empty");
    const card = findCard(raw);
    entry = card && CARDS.get(card).services[service]?.[card];
    if (entry && BY_WEEK.has(service)) {
      const w = field(data, "newStatementWeek");
      if (!w) return invalid("newStatementWeek cannot be empty");
      entry = /^\d+$/.test(w) ? entry[String(Number(w))] : undefined;
    }
  }
  if (!entry) return MISSING[service]();
  const delay = entry.delaySeconds ?? entry.gecikmeSaniye;
  if (delay) await new Promise((r) => setTimeout(r, delay * 1000));
  return [entry.http, entry.response ?? entry.yanit];
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (path === "/" || path === "/health" || path === BASE + "/health")
      return json(200, { ok: true, customers: CUSTOMERS.size, cards: CARDS.size,
        routes: Object.fromEntries(SERVICES.map((s) => [`${BASE}/${s}`, `POST ${s}`])) });
    const service = path.split("/").pop();
    const prefix = path.slice(0, -service.length - 1);
    if (!SERVICES.includes(service) || !["", "/v1", BASE].includes(prefix))
      return json(404, bankError("NOT_FOUND", "No such service: " + path, "ERROR", "NotFound"));
    let body = {};
    try { body = await request.json(); } catch { body = {}; }
    // the contract's envelope is {"data": {...}}; a flat body is read as data too
    const data = body?.data && typeof body.data === "object" ? body.data : (body && typeof body === "object" ? body : {});
    const [status, out] = await serve(service, data);
    return json(status, out);
  },
};
