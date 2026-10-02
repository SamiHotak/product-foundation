// Load test for the product API (k6). Read docs/LOADTEST.md first.
//
//   what it does   50 people use the app at the same time (each with their own session): they
//                  open pages (several API calls at once), wait a little, and a few change their
//                  profile. Meanwhile an uptime check pings /health/ready and some people log in.
//   what it checks the quality bars from the Foundation spec (API p95 under 200 ms) and that
//                  almost nothing fails. No AI calls and no payments are made.
//   safety         it only runs against your own machine, or a server you name with
//                  I_OWN_THIS_SERVER=yes. Never run it against somebody else's site.
//
// Settings (environment variables):
//   BASE_URL            where the API is, default http://localhost:8000
//   APP_ORIGIN          the website address the server expects (APP_URL), default = BASE_URL
//   USERS_FILE          the file made by `python -m app.scripts.loadtest_users`
//   VUS                 people at the same time, default 50
//   DURATION            how long the steady part lasts, default 60s
//   PAGES=1             also load the website pages (/, /pricing, /login): needs the frontend
//   P95_MS              the "fast enough" limit for API calls, default 200
//   I_OWN_THIS_SERVER   must be "yes" for any address that is not localhost
import http from "k6/http";
import { check, group, sleep } from "k6";
import exec from "k6/execution";
import { SharedArray } from "k6/data";
import { Counter } from "k6/metrics";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const APP_ORIGIN = (__ENV.APP_ORIGIN || BASE_URL).replace(/\/$/, "");
const VUS = parseInt(__ENV.VUS || "50", 10);
const DURATION = __ENV.DURATION || "60s";
const P95_MS = parseInt(__ENV.P95_MS || "200", 10);
const PAGES = __ENV.PAGES === "1";

const data = new SharedArray("users", () => {
  const parsed = JSON.parse(open(__ENV.USERS_FILE || "../users.json"));
  return [parsed];
})[0];

const unexpected = new Counter("unexpected_responses");

const scenarios = {
  // Real use: open a page (many calls at once), read for 1-3 seconds, repeat.
  browsing: {
    executor: "ramping-vus",
    exec: "browsing",
    startVUs: 0,
    stages: [
      { duration: "20s", target: VUS },
      { duration: DURATION, target: VUS },
      { duration: "10s", target: 0 },
    ],
    gracefulRampDown: "10s",
  },
  // The uptime monitor (and Caddy) check this all the time.
  health: {
    executor: "constant-arrival-rate",
    exec: "health",
    rate: 5,
    timeUnit: "1s",
    duration: DURATION,
    preAllocatedVUs: 2,
    maxVUs: 10,
    startTime: "20s",
  },
  // A few people save their profile (a write). Fewer than the readers.
  writes: {
    executor: "constant-arrival-rate",
    exec: "writes",
    rate: Math.max(1, Math.round(VUS / 10)),
    timeUnit: "1s",
    duration: DURATION,
    preAllocatedVUs: 5,
    maxVUs: 20,
    startTime: "20s",
  },
  // Logging in is slow ON PURPOSE (Argon2) and limited to 20 per minute per address.
  logins: {
    executor: "constant-arrival-rate",
    exec: "logins",
    rate: 6,
    timeUnit: "1m",
    duration: DURATION,
    preAllocatedVUs: 2,
    maxVUs: 4,
    startTime: "20s",
  },
};
if (PAGES) {
  scenarios.pages = {
    executor: "constant-arrival-rate",
    exec: "pages",
    rate: 5,
    timeUnit: "1s",
    duration: DURATION,
    preAllocatedVUs: 5,
    maxVUs: 30,
    startTime: "20s",
  };
}

export const options = {
  scenarios,
  thresholds: {
    // The quality bar: normal API requests (not login, not AI) are fast.
    "http_req_duration{kind:api}": [`p(95)<${P95_MS}`],
    "http_req_duration{kind:health}": ["p(95)<300"],
    "http_req_duration{kind:login}": ["p(95)<2000"],
    "http_req_duration{kind:page}": ["p(95)<800"],
    // And almost nothing may fail or answer something we did not expect.
    "http_req_failed{kind:api}": ["rate<0.01"],
    "http_req_failed{kind:health}": ["rate<0.001"],
    unexpected_responses: ["count<5"],
    checks: ["rate>0.99"],
  },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "max"],
  noConnectionReuse: false,
  userAgent: "k6-loadtest",
};

function isLocal(url) {
  return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\]|host\.docker\.internal)(:|\/|$)/.test(url);
}

export function setup() {
  if (!isLocal(BASE_URL) && __ENV.I_OWN_THIS_SERVER !== "yes") {
    exec.test.abort(
      `BASE_URL ${BASE_URL} is not your own computer. Only test a server that is yours, ` +
        `and then add I_OWN_THIS_SERVER=yes.`,
    );
  }
  const res = http.get(`${BASE_URL}/api/health/ready`);
  if (res.status !== 200) {
    exec.test.abort(`The server answered ${res.status} on /api/health/ready. Is it running?`);
  }
  if (!data.users || data.users.length === 0) {
    exec.test.abort("The users file is empty. Run: python -m app.scripts.loadtest_users");
  }
  return {};
}

function me() {
  const u = data.users[(exec.vu.idInTest - 1) % data.users.length];
  return { cookie: `${data.cookie_name}=${u.token}`, user: u };
}

function api(path, who, extra = {}) {
  const res = http.get(`${BASE_URL}/api${path}`, {
    headers: { Cookie: who.cookie },
    tags: { kind: "api", name: `GET ${path}` },
    ...extra,
  });
  const ok = check(res, { [`${path} is 200`]: (r) => r.status === 200 });
  if (!ok) unexpected.add(1);
  return res;
}

// What the app asks when a signed-in person opens a page.
export function browsing() {
  const who = me();
  group("open the dashboard", () => {
    const responses = http.batch(
      [
        "/auth/me",
        "/organizations/current/onboarding",
        "/billing/current",
        "/jobs",
        "/files",
      ].map((p) => [
        "GET",
        `${BASE_URL}/api${p}`,
        null,
        { headers: { Cookie: who.cookie }, tags: { kind: "api", name: `GET ${p}` } },
      ]),
    );
    for (const r of responses) {
      const ok = check(r, { "dashboard call is 200": (x) => x.status === 200 });
      if (!ok) unexpected.add(1);
    }
  });
  sleep(1 + Math.random() * 2);
  group("open the team page", () => {
    api("/organizations/current/members", who);
    api("/organizations/current/invites", who);
  });
  sleep(1 + Math.random() * 2);
  group("open settings", () => {
    api("/organizations/current/api-keys", who);
    api("/organizations/current/audit-log", who);
    api("/billing/plans", who);
  });
  sleep(1 + Math.random() * 2);
}

export function health() {
  const res = http.get(`${BASE_URL}/api/health/ready`, { tags: { kind: "health" } });
  if (!check(res, { "ready is 200": (r) => r.status === 200 })) unexpected.add(1);
}

export function writes() {
  const who = me();
  const res = http.patch(
    `${BASE_URL}/api/account/profile`,
    JSON.stringify({ name: `Load Test ${exec.vu.idInTest}` }),
    {
      headers: {
        Cookie: who.cookie,
        "Content-Type": "application/json",
        Origin: APP_ORIGIN,
      },
      tags: { kind: "api", name: "PATCH /account/profile" },
    },
  );
  if (!check(res, { "profile save is 200": (r) => r.status === 200 })) unexpected.add(1);
}

export function logins() {
  const idx = Math.floor(Math.random() * Math.min(data.users.length, 10));
  const u = data.users[idx];
  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ email: u.email, password: u.password }),
    {
      headers: { "Content-Type": "application/json", Origin: APP_ORIGIN },
      tags: { kind: "login", name: "POST /auth/login" },
      jar: new http.CookieJar(), // a fresh browser each time
    },
  );
  // 429 would mean we hit the per-address limit: that is the limit working, not a failure.
  if (!check(res, { "login is 200": (r) => r.status === 200 })) unexpected.add(1);
}

export function pages() {
  const base = __ENV.SITE_URL || BASE_URL;
  const path = ["/", "/pricing", "/login"][Math.floor(Math.random() * 3)];
  const res = http.get(`${base}${path}`, { tags: { kind: "page", name: `GET ${path}` } });
  if (!check(res, { "page is 200": (r) => r.status === 200 })) unexpected.add(1);
}

// A short plain-English verdict at the end. Set SUMMARY_FILE=/loadtest/results/summary.json to
// also save every number k6 measured.
export function handleSummary(summary) {
  const m = summary.metrics;
  const p95 = (name) => {
    const v = m[name] && m[name].values && m[name].values["p(95)"];
    return v === undefined ? "n/a" : `${Math.round(v)} ms`;
  };
  const failed = Object.values(m).some((x) => x.thresholds && Object.values(x.thresholds).some((t) => t.ok === false));
  const lines = [
    "",
    "================ LOAD TEST VERDICT ================",
    `People at once:        ${VUS}`,
    `API p95 (limit ${P95_MS} ms): ${p95("http_req_duration{kind:api}")}`,
    `Health p95:            ${p95("http_req_duration{kind:health}")}`,
    `Login p95:             ${p95("http_req_duration{kind:login}")}`,
    PAGES ? `Page p95:              ${p95("http_req_duration{kind:page}")}` : "Pages: not tested (add PAGES=1)",
    `Requests:              ${m.http_reqs ? m.http_reqs.values.count : 0} (${m.http_reqs ? Math.round(m.http_reqs.values.rate) : 0} per second)`,
    `Unexpected answers:    ${m.unexpected_responses ? m.unexpected_responses.values.count : 0}`,
    failed ? "RESULT: NOT GOOD ENOUGH (a limit above was missed, see the red lines)" : "RESULT: PASSED",
    "===================================================",
    "",
  ];
  const out = { stdout: lines.join("\n") };
  if (__ENV.SUMMARY_FILE) out[__ENV.SUMMARY_FILE] = JSON.stringify(summary, null, 2);
  return out;
}
