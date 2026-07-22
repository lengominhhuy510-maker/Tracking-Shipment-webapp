// QA-13 — IMO resolver parse + dedup, OFFLINE (Spec §6.7a, IC§3.3, IC§4.1, IC§9).
//
// WHERE THE LOGIC LIVES (grep-verified): all HTML→imo/mmsi parsing, name
// normalize, dedup-by-IMO, exact-name filter, ambiguous_name / not_found and
// confidence live in playwright-mcp/src/jobs/imo_resolve.ts (IC§0.1: Node runs
// the deterministic Playwright script; Python only polls + Pydantic-validates +
// writes DB). So the parse/dedup PASS-criterion is tested HERE, in TypeScript.
//
// OFFLINE STRATEGY: mock the "playwright" module so `runImoResolve` runs against
// fixture data with NO real network / no browser launch. `page.$$eval(sel, cb)`
// invokes the REAL callback in imo_resolve.ts against fixture anchor objects
// (faithful to the production DOM read), and `page.content()` returns fixture
// HTML for the MMSI regex + anti-bot detection. No async signature is faked
// loosely — every mocked method is `async` so there are no unhandled rejections.
//
// RUN (Node >=20; verified on v24):
//   cd playwright-mcp
//   node --test --experimental-strip-types --experimental-test-module-mocks tests/qa/imo_resolver.qa.test.ts

import { test, mock, before } from "node:test";
import assert from "node:assert/strict";

// ---- Fixture-driven fake browser ------------------------------------------

interface AnchorFixture {
  href: string;
  slna?: string | null; // .slna textContent (ship name only) — null => absent
  text?: string; // anchor textContent fallback (name + ship type)
}

interface Scenario {
  anchors: AnchorFixture[];
  detail: Record<string, string>; // detailUrl -> page HTML (MMSI / anti-bot)
  searchContent?: string; // search page HTML (anti-bot)
  urlOverride?: Record<string, string>; // goto url -> reported page.url()
  gotoThrows?: Set<string>; // urls whose goto() rejects (nav timeout)
}

let currentScenario: Scenario;

function makeAnchor(a: AnchorFixture) {
  return {
    getAttribute(name: string): string | null {
      return name === "href" ? a.href : null;
    },
    querySelector(sel: string): { textContent: string } | null {
      if (sel === ".slna" && a.slna != null) return { textContent: a.slna };
      return null;
    },
    textContent: a.text ?? "",
  };
}

function makePage() {
  let currentUrl = "about:blank";
  return {
    setDefaultTimeout(_ms: number): void {},
    async goto(url: string): Promise<void> {
      if (currentScenario.gotoThrows?.has(url)) {
        throw new Error("simulated nav timeout");
      }
      currentUrl = currentScenario.urlOverride?.[url] ?? url;
    },
    url(): string {
      return currentUrl;
    },
    async content(): Promise<string> {
      if (currentUrl.includes("/vessels?name=")) {
        return currentScenario.searchContent ?? "<html><body>results</body></html>";
      }
      return currentScenario.detail[currentUrl] ?? "<html><body>detail</body></html>";
    },
    async $$eval<T>(_selector: string, cb: (els: unknown[]) => T): Promise<T> {
      // Faithfully drive the REAL mapping callback in imo_resolve.ts.
      return cb(currentScenario.anchors.map(makeAnchor));
    },
  };
}

function makeContext() {
  return {
    async newPage() {
      return makePage();
    },
    async close(): Promise<void> {},
  };
}

const fakeChromium = {
  async launch(): Promise<unknown> {
    return {
      isConnected(): boolean {
        return true;
      },
      async newContext() {
        return makeContext();
      },
    };
  },
};

// Module mock must be installed before importing the SUT.
mock.module("playwright", {
  namedExports: { chromium: fakeChromium },
});

// Dynamic import AFTER the mock is registered.
let runImoResolve: (typeof import("../../src/jobs/imo_resolve.ts"))["runImoResolve"];

before(async () => {
  ({ runImoResolve } = await import("../../src/jobs/imo_resolve.ts"));
});

const DETAIL = (imo: string) => `https://www.vesselfinder.com/vessels/details/${imo}`;

// server.ts toErrorCode checks err.MESSAGE.startsWith(code); assert.rejects with a
// regex matches String(err) ("Error: <code>: ..."), so assert on .message directly.
function startsWithCode(code: string) {
  return (err: unknown): boolean => {
    assert.ok(err instanceof Error, "expected Error");
    assert.ok(err.message.startsWith(code + ":"), `message ${JSON.stringify(err.message)} must start with ${code}:`);
    return true;
  };
}


// Common good detail page with a 9-digit MMSI.
function detailWithMmsi(mmsi: string): string {
  return `<html><body><table><tr><td>MMSI</td><td>${mmsi}</td></tr></table></body></html>`;
}

// ---- PARSE: extract imo / mmsi / normalized vessel_name -------------------

test("parse: extracts imo, mmsi and normalized vessel_name (name via .slna, ship-type stripped)", async () => {
  currentScenario = {
    // .slna carries the clean name; anchor textContent has trailing ship type.
    anchors: [{ href: `/vessels/details/9811000`, slna: "  ever   given ", text: "ever given CONTAINER SHIP" }],
    detail: { [DETAIL("9811000")]: detailWithMmsi("235095435") },
  };
  const r = await runImoResolve({ vessel_name: "ever given", voyage_no: "V123" });
  assert.equal(r.imo, "9811000");
  assert.match(r.imo, /^\d{7}$/);
  assert.equal(r.mmsi, "235095435");
  assert.match(r.mmsi!, /^\d{9}$/);
  assert.equal(r.vessel_name, "EVER GIVEN"); // normalizeName: trim/collapse/upper, no ship type
  assert.equal(r.matched_voyage, "V123");
  assert.equal(r.confidence, "cao"); // single candidate, no narrowing
  assert.equal(r.source_url, DETAIL("9811000"));
});

test("parse: anchor without .slna falls back to textContent for the name", async () => {
  currentScenario = {
    anchors: [{ href: `/vessels/details/9074729`, slna: null, text: "  MAERSK   ALABAMA " }],
    detail: { [DETAIL("9074729")]: detailWithMmsi("219000123") },
  };
  const r = await runImoResolve({ vessel_name: "maersk alabama" });
  assert.equal(r.imo, "9074729");
  assert.equal(r.vessel_name, "MAERSK ALABAMA");
});

// ---- DEDUP / same-name filtering ------------------------------------------

test("dedup: same IMO appearing on multiple rows collapses to ONE candidate (confidence cao)", async () => {
  currentScenario = {
    anchors: [
      { href: `/vessels/details/9321483`, slna: "EVER GIVEN" },
      { href: `/vessels/details/9321483`, slna: "EVER GIVEN" }, // duplicate row, same ship
    ],
    detail: { [DETAIL("9321483")]: detailWithMmsi("636092932") },
  };
  const r = await runImoResolve({ vessel_name: "EVER GIVEN" });
  assert.equal(r.imo, "9321483");
  assert.equal(r.confidence, "cao"); // deduped to a single candidate → not narrowed
});

test("dedup: exact-name match is picked out of voyage/name noise — never the wrong ship (seed lô 1+4, IC§13)", async () => {
  // Only ONE row's name exactly equals the wanted name; the others are near
  // matches (different ships). The exact filter must select the right IMO.
  currentScenario = {
    anchors: [
      { href: `/vessels/details/1111111`, slna: "EVER GIVEN CONTAINER" }, // different name
      { href: `/vessels/details/2222222`, slna: "EVER GIVEN" }, // exact
      { href: `/vessels/details/3333333`, slna: "EVER GIVING" }, // different name
    ],
    detail: { [DETAIL("2222222")]: detailWithMmsi("240000001") },
  };
  const r = await runImoResolve({ vessel_name: "ever given", voyage_no: "0FK6ES1MA" });
  assert.equal(r.imo, "2222222"); // the exact-name ship, not 1111111 / 3333333
  assert.equal(r.confidence, "trung_binh"); // narrowed from >1 candidate → medium
  assert.equal(r.matched_voyage, "0FK6ES1MA");
});

test("dedup: multiple DIFFERENT ships with the SAME exact name → ambiguous_name (does not guess)", async () => {
  currentScenario = {
    anchors: [
      { href: `/vessels/details/4444444`, slna: "PACIFIC STAR" },
      { href: `/vessels/details/5555555`, slna: "PACIFIC STAR" }, // same name, different IMO
    ],
    detail: {},
  };
  await assert.rejects(
    runImoResolve({ vessel_name: "pacific star", voyage_no: "V9" }),
    startsWithCode("ambiguous_name"),
  );
});

// ---- EDGE cases ------------------------------------------------------------

test("edge: no candidates → not_found, and NO fabricated imo (throws, returns nothing)", async () => {
  currentScenario = { anchors: [], detail: {} };
  await assert.rejects(runImoResolve({ vessel_name: "ghost vessel" }), startsWithCode("not_found"));
});

test("edge: rows exist but none carry a /vessels/details/<7digit> href → not_found (no invented identity)", async () => {
  currentScenario = {
    anchors: [
      { href: `/help/about`, slna: "SOME LINK" }, // not a detail link
      { href: `/vessels/details/12345`, slna: "BAD IMO" }, // only 5 digits → no match
    ],
    detail: {},
  };
  await assert.rejects(runImoResolve({ vessel_name: "whatever" }), startsWithCode("not_found"));
});

test("edge: unusual characters in the name are preserved through normalize (collapse+upper only)", async () => {
  currentScenario = {
    anchors: [{ href: `/vessels/details/9700000`, slna: "cma cgm  a.lincoln (ex-star)" }],
    detail: { [DETAIL("9700000")]: detailWithMmsi("228386000") },
  };
  const r = await runImoResolve({ vessel_name: "cma cgm a.lincoln (ex-star)" });
  assert.equal(r.imo, "9700000");
  assert.equal(r.vessel_name, "CMA CGM A.LINCOLN (EX-STAR)");
});

test("edge: detail page has no MMSI → mmsi is null (valid), imo still returned", async () => {
  currentScenario = {
    anchors: [{ href: `/vessels/details/9600000`, slna: "NORTHERN LIGHT" }],
    detail: { [DETAIL("9600000")]: "<html><body>no mmsi here</body></html>" },
  };
  const r = await runImoResolve({ vessel_name: "northern light" });
  assert.equal(r.imo, "9600000");
  assert.equal(r.mmsi, null);
});

test("edge: MMSI with wrong digit count on detail page is rejected by the 9-digit regex → mmsi null", async () => {
  currentScenario = {
    anchors: [{ href: `/vessels/details/9600001`, slna: "SOUTHERN CROSS" }],
    // 8 digits only → MMSI regex requires exactly 9 → no match → null
    detail: { [DETAIL("9600001")]: "<html><body>MMSI 23509543</body></html>" },
  };
  const r = await runImoResolve({ vessel_name: "southern cross" });
  assert.equal(r.mmsi, null);
});

test("edge: detail navigation failure does NOT lose the imo — mmsi degrades to null", async () => {
  currentScenario = {
    anchors: [{ href: `/vessels/details/9800000`, slna: "ATLANTIC" }],
    detail: {},
    gotoThrows: new Set([DETAIL("9800000")]), // detail page nav rejects
  };
  const r = await runImoResolve({ vessel_name: "atlantic" });
  assert.equal(r.imo, "9800000");
  assert.equal(r.mmsi, null);
});

// ---- Anti-bot / terminal error codes (startsWith contract, server.ts) -----

test("blocked: search page returns captcha markup → captcha error (not not_found)", async () => {
  currentScenario = {
    anchors: [],
    detail: {},
    searchContent: "<html><body><div class='g-recaptcha'>are you a human</div></body></html>",
  };
  await assert.rejects(runImoResolve({ vessel_name: "blocked ship" }), startsWithCode("captcha"));
});

test("blocked: redirect to /login → login_required", async () => {
  const searchUrl = `https://www.vesselfinder.com/vessels?name=${encodeURIComponent("PRIVATE SHIP")}`;
  currentScenario = {
    anchors: [],
    detail: {},
    urlOverride: { [searchUrl]: "https://www.vesselfinder.com/login?next=/vessels" },
  };
  await assert.rejects(runImoResolve({ vessel_name: "private ship" }), startsWithCode("login_required"));
});

test("blocked: search page nav timeout → timeout error", async () => {
  const searchUrl = `https://www.vesselfinder.com/vessels?name=${encodeURIComponent("SLOW SHIP")}`;
  currentScenario = { anchors: [], detail: {}, gotoThrows: new Set([searchUrl]) };
  await assert.rejects(runImoResolve({ vessel_name: "slow ship" }), startsWithCode("timeout"));
});
