// freya-mock: our own copy of the bank's tool services, on a Cloudflare Worker.
//
// A port of bank/server.py (behaviour proven against the organizers' practice bank): same tools, same answers,
// same error texts, same ledger. Plain JS, no build step, no npm dependencies.
//
// Routes (every route also works without the /v1 prefix):
//   POST /v1/<tool>                        a tool call; the body carries the customer id
//   GET  /v1/health
//   GET  /v1/practice/ledger/<customer_id>   ?history=1 adds the archived earlier conversations
//   POST /v1/practice/sessions             {"case": "<id in customers.json>"} or {"customer": {...}} -> a fresh c_... id
//   POST /v1/practice/reset/<customer_id>  archive the current conversation and start a fresh one
//
// State: one SQLite-backed Durable Object per customer id (free plan, `new_sqlite_classes` migration in wrangler.toml).
//
// To adapt to a new service contract, edit only the CONTRACT section and, if the behaviour of a tool changed,
// its handler in the TOOL LOGIC section. Everything below "PLUMBING" is contract-independent.

import { DurableObject } from "cloudflare:workers";
import CUSTOMERS from "../data/customers.json";

// =====================================================================================================
// CONTRACT: wire names, enums, rules. This is the part to edit at 20:00.
// =====================================================================================================

// The canonical tool roles, and the canonical request fields of each. Handlers below read canonical names only.
const CANONICAL_FIELDS = {
  verify_identity: ["field", "answer"],
  get_account: [],
  create_promise: ["product_id", "amount", "date"],
  add_note: ["product_id", "reason", "text"],
  schedule_callback: ["date", "time"],
  transfer_to_agent: ["queue"],
  close_call: ["outcome", "reason"],
};
const TOOLS = Object.keys(CANONICAL_FIELDS);

const CONTRACT = {
  // role -> path name on the wire (POST /v1/<name>). Rename here, e.g. {verify_identity: "check_identity"}.
  tools: Object.fromEntries(TOOLS.map((t) => [t, t])),
  // role -> {canonical field -> wire field}. Rename here, e.g. {create_promise: {date: "promise_date"}}.
  fields: Object.fromEntries(TOOLS.map((t) => [t, Object.fromEntries(CANONICAL_FIELDS[t].map((f) => [f, f]))])),
  // the wire name of the customer id in every request body
  customer_id_field: "customer_id",

  max_wrong: 3, // wrong identity answers in total before "identity check is over"
  // identity field -> how an answer is compared: "date" (spoken forms, day/month swap hint), "digits" (non-digits
  // stripped), "text" (case, spaces and dashes ignored). Fields not listed are typed from the customer's answer.
  identity_types: { date_of_birth: "date", phone_last4: "digits" },
  note_reasons: ["refused", "hardship", "dispute", "paid", "service_error"],
  queues: ["restructuring", "general", "support"],
  // outcome -> allowed reasons. [] = the outcome takes no reason; "any" = any non-empty string.
  outcome_reasons: {
    promise: [],
    paid: [],
    transferred: ["restructuring", "human", "support"],
    no_promise: ["refused", "hardship", "dispute", "service_error"],
    not_verified: ["failed", "declined"],
    not_reached: ["callback", "no_callback", "wrong_number", "deceased", "unclear"],
  },

  // observed-but-undocumented behaviours of the organizers' bank; each can be switched off
  hint_once: true, // the day_month_swapped hint is given once per conversation, the next swap counts as wrong
  passed_field_omits_all_verified: true, // a field that already passed answers success without `all_verified`
  note_product_unchecked: true, // add_note accepts any or no product_id
  reason_rejected_on_reasonless: true, // a reason sent with promise/paid is rejected (off: ignored, stored as null)

  // Hosting for days: the same customer id is called by many evaluation conversations, one after another.
  // A new conversation starts (the old ledger is archived) when the last tool call is older than this ...
  fresh_after_idle_ms: 10 * 60 * 1000,
  // ... or when verify_identity arrives after close_call.
  fresh_on_verify_after_close: true,
  history_keep: 50, // archived ledgers kept per customer
};

const ERR_FAULT = { ok: false, error: "service unavailable, nothing was recorded" };
const ERR_CLOSED = { ok: false, error: "the call is already closed" };
const ERR_NOT_VERIFIED = { ok: false, error: "identity not verified" };

// =====================================================================================================
// TOOL LOGIC: one handler per role. s = mutable conversation state, a = args by canonical name,
// c = the customer (identity, products, profile). Return the response body (always HTTP 200).
// =====================================================================================================

const wire = (p, role, canon) => (p.fields[role] || {})[canon] || canon;
const isDay = (x) => /^\d{4}-\d{2}-\d{2}$/.test(String(x ?? ""));
const allVerified = (s, c) => Object.keys(c.identity).length > 0 && Object.keys(c.identity).every((f) => s.verified[f]);

const HANDLERS = {
  verify_identity(s, a, c) {
    const p = c.profile;
    let field = a.field;
    const answer = a.answer;
    const left = () => Math.max(0, p.max_wrong - s.wrong);
    const fields = Object.keys(c.identity);
    if (field == null && fields.length === 1) field = fields[0]; // a one-question API names no question
    if (typeof field !== "string" || !fields.includes(field))
      return { ok: false, error: wire(p, "verify_identity", "field") + " must be " + fields.join(" or ") };
    if (left() <= 0) return { ok: false, verified: false, wrong_answers_left: 0, error: "identity check is over" };
    if (s.verified[field]) {
      const r = { ok: true, verified: true, wrong_answers_left: left() };
      if (!p.passed_field_omits_all_verified) r.all_verified = allVerified(s, c);
      return r;
    }
    let kind = p.identity_types[field] || "text";
    const truth = c.identity[field];
    if (kind === "text" && isDay(truth)) kind = "date"; // the stored truth says it is a date
    let right;
    if (kind === "date") {
      const got = readDate(answer), want = readDate(truth);
      if (!got) return { ok: false, error: "answer is not a date. Send it as YYYY-MM-DD." };
      right = sameDate(got, want);
      if (!right && want && sameDate([got[0], got[2], got[1]], want) && (!s.hinted || !p.hint_once)) {
        s.hinted = true;
        return { ok: true, verified: false, wrong_answers_left: left(), hint: "day_month_swapped" };
      }
    } else if (kind === "digits") {
      right = str(answer).replace(/\D/g, "") === str(truth).replace(/\D/g, "");
    } else {
      const norm = (x) => str(x).replace(/[\s-]/g, "").toLowerCase();
      right = norm(answer) === norm(truth);
    }
    if (right) {
      s.verified[field] = true;
      return { ok: true, verified: true, wrong_answers_left: left(), all_verified: allVerified(s, c) };
    }
    s.wrong += 1;
    return { ok: true, verified: false, wrong_answers_left: left(), all_verified: false };
  },

  get_account(s, a, c) {
    if (!allVerified(s, c)) return { ...ERR_NOT_VERIFIED };
    return { ok: true, products: clone(c.products) };
  },

  create_promise(s, a, c) {
    const p = c.profile;
    if (!allVerified(s, c)) return { ...ERR_NOT_VERIFIED };
    const product = c.products.find((x) => x.product_id === a.product_id);
    if (!product) return { ok: false, error: "unknown " + wire(p, "create_promise", "product_id") };
    const raw = a.amount;
    const amount = typeof raw === "number" ? raw : typeof raw === "string" && raw.trim() ? Number(raw) : 0;
    if (!(amount > 0)) return { ok: false, error: wire(p, "create_promise", "amount") + " must be a positive number" };
    if (!isDay(a.date)) return { ok: false, error: wire(p, "create_promise", "date") + " must be YYYY-MM-DD" };
    if (s.promises.some((x) => x.product_id === product.product_id)) return { ok: false, error: "this product already has a promise" };
    const promise_id = "pr" + (s.promises.length + 1);
    s.promises.push({ promise_id, product_id: product.product_id, type: product.type ?? null, amount, date: a.date });
    return { ok: true, promise_id };
  },

  add_note(s, a, c) {
    const p = c.profile;
    if (!p.note_product_unchecked && !c.products.some((x) => x.product_id === a.product_id))
      return { ok: false, error: "unknown " + wire(p, "add_note", "product_id") };
    if (!p.note_reasons.includes(a.reason)) return { ok: false, error: "unknown " + wire(p, "add_note", "reason") };
    s.notes.push({ product_id: a.product_id ?? null, reason: a.reason, text: a.text || "" });
    return { ok: true };
  },

  schedule_callback(s, a, c) {
    const p = c.profile;
    if (!isDay(a.date) || !/^\d{2}:\d{2}$/.test(String(a.time ?? "")))
      return { ok: false, error: wire(p, "schedule_callback", "date") + " must be YYYY-MM-DD and " + wire(p, "schedule_callback", "time") + " HH:MM" };
    s.callbacks.push({ date: a.date, time: a.time });
    return { ok: true };
  },

  transfer_to_agent(s, a, c) {
    if (!c.profile.queues.includes(a.queue)) return { ok: false, error: "unknown " + wire(c.profile, "transfer_to_agent", "queue") };
    s.transfers.push({ queue: a.queue });
    return { ok: true };
  },

  close_call(s, a, c) {
    const p = c.profile;
    const outcome = a.outcome;
    const reasons = typeof outcome === "string" && Object.hasOwn(p.outcome_reasons, outcome) ? p.outcome_reasons[outcome] : undefined;
    if (reasons === undefined) return { ok: false, error: "unknown " + wire(p, "close_call", "outcome") };
    let reason = a.reason;
    const o = wire(p, "close_call", "outcome"), r = wire(p, "close_call", "reason");
    if (reasons === "any") {
      if (typeof reason !== "string" || !reason) return { ok: false, error: "this " + o + " needs a " + r };
    } else if (reasons.length === 0 && !p.reason_rejected_on_reasonless) {
      reason = null;
    } else if ((reasons.length || reason != null) && !reasons.includes(reason)) {
      return { ok: false, error: "this " + o + " needs one of these " + r + "s: " + reasons.join(", ") };
    }
    s.outcome = outcome;
    s.reason = reason ?? null;
    s.closed = true;
    return { ok: true };
  },
};

// Request args (wire names) -> canonical names, through the customer's profile.
function canonicalArgs(p, role, args) {
  const names = p.fields[role] || {};
  const out = {};
  for (const [canon, w] of Object.entries(names)) if (Object.hasOwn(args, w)) out[canon] = args[w];
  if (role === "verify_identity" && !("answer" in out)) {
    // a one-question API: no question field, the answer travels under its own name (e.g. `birth_date`)
    const leftover = Object.keys(args).filter((k) => !Object.values(names).includes(k));
    if (leftover.length === 1) out.answer = args[leftover[0]];
  }
  return out;
}

// =====================================================================================================
// PLUMBING: customers, dates, the Durable Object, routing. Contract-independent.
// =====================================================================================================

const MONTHS = Object.fromEntries(
  ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"].map((m, i) => [m, i + 1]),
);
const str = (x) => (x == null ? "" : String(x));
const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const sameDate = (a, b) => !!a && !!b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

// A spoken or written date as [year, month, day], unchecked, or null. Numbers only are day, month, year,
// except the ISO form year-month-day.
function readDate(text) {
  const s = str(text).trim();
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return [+m[1], +m[2], +m[3]];
  m = s.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/);
  if (m) return [+m[3], +m[2], +m[1]];
  m = s.match(/^(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+),?\s+(\d{4})$/);
  if (m && MONTHS[m[2].toLowerCase()]) return [+m[3], MONTHS[m[2].toLowerCase()], +m[1]];
  m = s.match(/^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$/);
  if (m && MONTHS[m[1].toLowerCase()]) return [+m[3], MONTHS[m[1].toLowerCase()], +m[2]];
  return null;
}

// CONTRACT with a customer's `profile` overrides; nested maps (fields, tools, identity_types) merge per key.
function mergeProfile(overrides) {
  const p = clone(CONTRACT);
  for (const [k, v] of Object.entries(overrides || {})) {
    if (k === "fields" && v && typeof v === "object") for (const [t, names] of Object.entries(v)) p.fields[t] = { ...(p.fields[t] || {}), ...(names || {}) };
    else if ((k === "tools" || k === "identity_types") && v && typeof v === "object") p[k] = { ...p[k], ...v };
    else p[k] = clone(v);
  }
  return p;
}

// The derived, read-only view of a customer spec (an entry of customers.json or a practice session).
function customerOf(spec) {
  const profile = mergeProfile(spec.profile);
  const identity = { ...(spec.identity || {}) };
  for (const [f, ans] of Object.entries(identity)) {
    if (profile.identity_types[f]) continue;
    const t = str(ans);
    profile.identity_types[f] = /^\d+$/.test(t) ? "digits" : readDate(t) ? "date" : "text";
  }
  const products = (spec.products || []).map((p, i) => {
    const { product_id, ...rest } = p;
    return { product_id: product_id ?? "p" + (i + 1), ...rest };
  });
  const faults = (spec.faults || []).map((f) => ({
    tool: f.tool, fail_first_n: +f.fail_first_n || 0, fail_on_call: +f.fail_on_call || 0, on_call: +f.on_call || 0, slow_ms: +f.slow_ms || 0,
  }));
  return { profile, identity, products, faults, variables: spec.variables || {} };
}

function faultFor(faults, role, n) {
  for (const f of faults) {
    if (f.tool !== role) continue;
    if (f.fail_first_n && n <= f.fail_first_n) return f;
    if (f.fail_on_call && n === f.fail_on_call) return f;
    if (f.slow_ms && (!f.on_call || n === f.on_call) && !f.fail_first_n && !f.fail_on_call) return f;
  }
  return null;
}

function hashText(t) {
  let h = 5381;
  for (let i = 0; i < t.length; i++) h = ((h * 33) ^ t.charCodeAt(i)) >>> 0;
  return h.toString(16);
}

const LEDGER_KEYS = ["case", "team", "now", "verified", "wrong", "hinted", "promises", "notes", "callbacks", "transfers", "outcome", "reason", "failures", "calls", "last_at"];

function freshState(cid, spec, team = "") {
  return {
    customer_id: cid, case: spec.id ?? cid, team, now: (spec.variables || {}).now ?? null, spec_hash: hashText(JSON.stringify(spec)),
    started_at: Date.now(), tool_calls: {}, verified: {}, wrong: 0, hinted: false, promises: [], notes: [], callbacks: [], transfers: [],
    outcome: null, reason: null, closed: false, failures: {}, calls: [], last_at: 0,
  };
}
const ledgerOf = (s) => ({ ok: true, ...Object.fromEntries(LEDGER_KEYS.map((k) => [k, clone(s[k])])) });

// One instance per customer id. Read-modify-write on storage is atomic between awaits that are not storage calls
// (the input gate), so concurrent calls for one customer do not lose updates.
export class BankCustomer extends DurableObject {
  async spec(cid) {
    return Object.hasOwn(CUSTOMERS, cid) ? CUSTOMERS[cid] : (await this.ctx.storage.get("spec")) || null;
  }

  async archive(s) {
    if (!s || !s.calls.length) return;
    const st = this.ctx.storage;
    await st.put("history:" + String(s.started_at).padStart(15, "0"), ledgerOf(s));
    const keys = [...(await st.list({ prefix: "history:" })).keys()];
    if (keys.length > CONTRACT.history_keep) await st.delete(keys.slice(0, keys.length - CONTRACT.history_keep));
  }

  // The current conversation, or a fresh one when the data changed, the line went idle, or a closed call is re-verified.
  async current(cid, spec, role) {
    const s = await this.ctx.storage.get("state");
    if (!s) return freshState(cid, spec);
    const stale =
      s.spec_hash !== hashText(JSON.stringify(spec)) ||
      (s.last_at && Date.now() - s.last_at > CONTRACT.fresh_after_idle_ms) ||
      (s.closed && role === "verify_identity" && CONTRACT.fresh_on_verify_after_close);
    if (!stale) return s;
    await this.archive(s);
    return freshState(cid, spec, s.team);
  }

  async call(cid, role, args) {
    const spec = await this.spec(cid);
    if (!spec) return [404, { ok: false, error: "unknown customer_id" }];
    const c = customerOf(spec);
    let s = await this.current(cid, spec, role);
    const n = (s.tool_calls[role] = (s.tool_calls[role] || 0) + 1);
    await this.ctx.storage.put("state", s);
    const fault = faultFor(c.faults, role, n);
    if (fault && fault.slow_ms) {
      await new Promise((r) => setTimeout(r, fault.slow_ms));
      s = await this.ctx.storage.get("state"); // other calls may have run meanwhile
    }
    s.failures[role] = s.failures[role] || 0;
    let status = 200, result;
    if (s.closed) result = { ...ERR_CLOSED };
    else if (fault && (fault.fail_first_n || fault.fail_on_call)) {
      s.failures[role] += 1;
      status = 500;
      result = { ...ERR_FAULT };
    } else result = HANDLERS[role](s, canonicalArgs(c.profile, role, args), c);
    s.calls.push({ n: s.calls.length + 1, tool: role, args, status, result });
    s.last_at = Date.now();
    await this.ctx.storage.put("state", s);
    return [status, result];
  }

  async ledger(cid, withHistory) {
    const spec = await this.spec(cid);
    if (!spec) return [404, { ok: false, error: "unknown customer_id" }];
    const s = (await this.ctx.storage.get("state")) || freshState(cid, spec);
    const out = ledgerOf(s);
    if (withHistory) out.history = [...(await this.ctx.storage.list({ prefix: "history:" })).values()];
    return [200, out];
  }

  async open(cid, spec, team) {
    await this.ctx.storage.put("spec", spec);
    await this.ctx.storage.put("state", freshState(cid, spec, team));
    return [200, { ok: true, variables: { customer_id: cid, ...(spec.variables || {}) } }];
  }

  async reset(cid) {
    const spec = await this.spec(cid);
    if (!spec) return [404, { ok: false, error: "unknown customer_id" }];
    const s = await this.ctx.storage.get("state");
    await this.archive(s);
    await this.ctx.storage.put("state", freshState(cid, spec, s ? s.team : ""));
    return [200, { ok: true, customer_id: cid }];
  }
}

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const ROLE_BY_WIRE = Object.fromEntries(Object.entries(CONTRACT.tools).map(([role, name]) => [name, role]));
const knownId = (cid) => Object.hasOwn(CUSTOMERS, cid) || /^c_[0-9a-f]{12}$/.test(cid); // c_... = a practice session
const stub = (env, cid) => env.BANK.get(env.BANK.idFromName(cid));

async function readBody(req) {
  try {
    const b = JSON.parse((await req.text()) || "{}");
    return b && typeof b === "object" && !Array.isArray(b) ? b : {};
  } catch {
    return {};
  }
}

async function teamHash(req) {
  const key = req.headers.get("x-team-key") || "";
  if (!key) return "";
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    let path = url.pathname.replace(/\/+$/, "");
    if (path === "/v1" || path.startsWith("/v1/")) path = path.slice(3);
    const seg = path.split("/").filter(Boolean).map(decodeURIComponent);
    const admin = () => !env.ADMIN_KEY || req.headers.get("x-admin-key") === env.ADMIN_KEY;

    if (req.method === "GET" && (path === "" || path === "/health"))
      return json(200, { ok: true, service: "freya-mock", customers: Object.keys(CUSTOMERS).length, tools: Object.values(CONTRACT.tools) });

    if (req.method === "GET" && seg[0] === "practice" && seg[1] === "ledger" && seg.length === 3) {
      const cid = seg[2].trim();
      if (!knownId(cid)) return json(404, { ok: false, error: "unknown customer_id" });
      return json(...(await stub(env, cid).ledger(cid, url.searchParams.has("history"))));
    }

    if (req.method !== "POST") return json(404, { ok: false, error: "not found" });
    const body = await readBody(req);

    if (seg[0] === "practice" && seg[1] === "sessions" && seg.length === 2) {
      if (!admin()) return json(403, { ok: false, error: "forbidden" });
      let spec;
      if (body.customer && typeof body.customer === "object") spec = body.customer;
      else if (typeof body.case === "string" && Object.hasOwn(CUSTOMERS, body.case)) spec = { id: body.case, ...CUSTOMERS[body.case] };
      else return json(404, { ok: false, error: "unknown case" });
      const cid = "c_" + crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      return json(...(await stub(env, cid).open(cid, spec, await teamHash(req))));
    }

    if (seg[0] === "practice" && seg[1] === "reset" && seg.length === 3) {
      if (!admin()) return json(403, { ok: false, error: "forbidden" });
      const cid = seg[2].trim();
      if (!knownId(cid)) return json(404, { ok: false, error: "unknown customer_id" });
      return json(...(await stub(env, cid).reset(cid)));
    }

    if (seg.length !== 1) return json(404, { ok: false, error: "not found" });
    const role = ROLE_BY_WIRE[seg[0]] || (TOOLS.includes(seg[0]) ? seg[0] : null);
    if (!role) return json(404, { ok: false, error: "not found" });
    // Optional: when the TOOL_KEY secret is set, tool calls need `Authorization: Bearer <key>` or `x-api-key: <key>`.
    if (env.TOOL_KEY) {
      const auth = req.headers.get("authorization") || "", key = req.headers.get("x-api-key") || "";
      if (auth !== "Bearer " + env.TOOL_KEY && key !== env.TOOL_KEY) return json(401, { ok: false, error: "unauthorized" });
    }
    const idf = CONTRACT.customer_id_field;
    const raw = body[idf] ?? body.customer_id ?? url.searchParams.get(idf) ?? url.searchParams.get("customer_id") ?? req.headers.get("x-customer-id");
    const cid = raw == null ? "" : String(raw).trim();
    if (!cid || !knownId(cid)) return json(404, { ok: false, error: "unknown customer_id" });
    const args = Object.fromEntries(Object.entries(body).filter(([k]) => k !== idf && k !== "customer_id"));
    return json(...(await stub(env, cid).call(cid, role, args)));
  },
};
