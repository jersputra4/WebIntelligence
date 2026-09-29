// Specter Intel dashboard — vanilla JS, no build step.
// All provider data is rendered through textContent / DOM APIs (never innerHTML).

const $ = (sel) => document.querySelector(sel);

const PLATFORM_LABEL = { twitter: "X / Twitter", instagram: "Instagram", tiktok: "TikTok", all: "All Platforms" };
const ERROR_COPY = {
  USERNAME_REQUIRED: "Username is required.",
  INVALID_USERNAME: "Username may only contain letters, numbers, '.', '_' or '-' (max 30 characters).",
  PROVIDER_TIMEOUT: "Service temporarily unavailable. The data provider did not respond in time.",
  PROVIDER_UNAVAILABLE: "Service temporarily unavailable. Please try again shortly.",
  PROVIDER_RATE_LIMITED: "The data provider quota or rate limit has been reached. Please try again later.",
  PROVIDER_UNAUTHORIZED: "The server's EnsembleData credentials were rejected. Contact the administrator.",
  PROVIDER_NOT_CONFIGURED: "The EnsembleData API key is not configured on the server.",
};
const GENERIC_ERROR = "Unable to retrieve account information. Please try again.";

const state = {
  searching: false,
  results: [],
  active: 0,
  meta: null,
  historyOffset: 0,
};

/* ------------------------------------------------------------ DOM helper */
function h(tag, attrs = {}, ...children) {
  const svg = ["svg", "path", "circle", "line", "text", "defs", "linearGradient", "stop", "g"].includes(tag);
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/* ------------------------------------------------------------ formatting */
const nf = new Intl.NumberFormat("en-US");
function compact(n) {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(abs >= 1e10 ? 1 : 2).replace(/\.0+$/, "") + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (abs >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return nf.format(n);
}
function full(n) { return n === null || n === undefined ? "—" : nf.format(n); }
function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff)) return "—";
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}
function fmtMonthYear(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}
function yearsSince(iso) {
  const d = new Date(iso);
  return isNaN(d) ? null : (Date.now() - d.getTime()) / (365.25 * 86400 * 1000);
}
function initials(text) {
  return (text || "?").replace(/^Demo · /, "").trim().slice(0, 1).toUpperCase() || "?";
}
function avatarSrc(url) {
  return url ? `/api/avatar?url=${encodeURIComponent(url)}` : null;
}
function avatarNode(url, label, cls) {
  const box = h("div", { class: cls }, initials(label));
  const src = avatarSrc(url);
  if (src) {
    const img = h("img", { src, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
    img.addEventListener("load", () => { box.textContent = ""; box.append(img); });
  }
  return box;
}

/* ------------------------------------------------------------------- API */
class ApiError extends Error {
  constructor(status, code, message, retryAfter) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" }, ...options });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the backend server.");
  }
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON */ }
  if (!response.ok || !body || body.success === false) {
    const err = body && body.error ? body.error : {};
    throw new ApiError(response.status, err.code || "UNKNOWN", err.message || GENERIC_ERROR,
      Number(response.headers.get("Retry-After")) || null);
  }
  return body;
}

/* ---------------------------------------------------------------- search */
function setSearching(on) {
  state.searching = on;
  $("#search-btn").disabled = on;
  $("#search-btn-label").textContent = on ? "SEARCHING..." : "SEARCH INTEL";
}

function showFieldError(message) {
  const el = $("#field-error");
  el.textContent = message || "";
  el.hidden = !message;
  $(".input-wrap").classList.toggle("invalid", Boolean(message));
}

async function searchAccount(event) {
  if (event) event.preventDefault();
  if (state.searching) return;
  const input = $("#username");
  const username = input.value.trim().replace(/^@/, "");
  const platform = $("#platform").value;

  if (!username) return showFieldError("Username is required.");
  if (!/^[A-Za-z0-9._-]{1,30}$/.test(username)) return showFieldError(ERROR_COPY.INVALID_USERNAME);
  showFieldError("");

  setSearching(true);
  renderLoading(platform);
  try {
    const data = await api(`/api/search?username=${encodeURIComponent(username)}&platform=${encodeURIComponent(platform)}`);
    state.results = data.results;
    state.meta = data.meta;
    state.active = 0;
    state.warnings = data.warnings || [];
    if (!data.results.length) renderNotFound(username, platform, state.warnings);
    else renderResults();
  } catch (error) {
    renderError(error);
  } finally {
    setSearching(false);
    refreshSidebar();
  }
}

/* -------------------------------------------------------------- renders */
function renderLoading(platform) {
  const root = $("#results");
  root.replaceChildren(
    h("section", { class: "panel result-card" },
      h("div", { class: "result-strip" },
        h("span", { class: "loading-label" }, h("span", { class: "spinner" }),
          `Searching... querying EnsembleData (${PLATFORM_LABEL[platform]})`)),
      h("div", { class: "result-body" },
        h("div", { class: "sk-row" }, h("div", { class: "skeleton sk-avatar" }),
          h("div", { class: "profile-id" },
            h("div", { class: "skeleton sk-line", style: null }),
            h("div", { class: "skeleton sk-line" }))),
        h("div", { class: "skeleton sk-block" }),
        h("div", { class: "stats" }, [1, 2, 3, 4].map(() => h("div", { class: "skeleton sk-block" }))),
        h("div", { class: "skeleton sk-chart" }))));
  // Different widths for skeleton lines (CSSOM is CSP-safe).
  root.querySelectorAll(".sk-line").forEach((el, i) => { el.style.width = i ? "30%" : "55%"; el.style.marginTop = i ? "10px" : "0"; });
}

function renderEmpty() {
  $("#results").replaceChildren(
    h("section", { class: "panel state" },
      h("div", { class: "state-icon" }, "◎"),
      h("h3", {}, "Awaiting target"),
      h("p", {}, "Enter a public username above and choose a platform. The backend validates the handle, queries EnsembleData and returns a normalized profile.")));
}

function renderNotFound(username, platform, warnings) {
  $("#results").replaceChildren(
    warningBar(warnings),
    h("section", { class: "panel state" },
      h("div", { class: "state-icon" }, "∅"),
      h("h3", {}, "No account found."),
      h("p", {}, `No public account matching @${username} was returned for ${PLATFORM_LABEL[platform]}.`)));
}

function renderError(error) {
  const code = error.code || "UNKNOWN";
  let message = ERROR_COPY[code] || (error.status === 400 ? error.message : GENERIC_ERROR);
  if (code === "RATE_LIMITED") message = `Too many requests. Please wait ${error.retryAfter || 60}s before searching again.`;
  if (code === "NETWORK_ERROR") message = "Cannot reach the backend server. Check that the API is running.";
  $("#results").replaceChildren(
    h("section", { class: "panel state error" },
      h("div", { class: "state-icon" }, "!"),
      h("h3", {}, code === "RATE_LIMITED" ? "Rate limit reached" : "Unable to retrieve account information"),
      h("p", {}, message),
      h("div", { class: "code" }, `ERROR CODE: ${code}${error.status ? ` · HTTP ${error.status}` : ""}`)));
}

function warningBar(warnings) {
  if (!warnings || !warnings.length) return null;
  return h("div", { class: "warning-bar" },
    "⚠ Partial result — ",
    warnings.map((w) => `${PLATFORM_LABEL[w.platform] || w.platform}: ${w.code}`).join(" · "));
}

function renderResults() {
  const root = $("#results");
  const nodes = [warningBar(state.warnings)];
  if (state.results.length > 1) {
    nodes.push(h("div", { class: "result-tabs", role: "tablist" },
      state.results.map((r, i) => h("button", {
        type: "button", class: "result-tab", role: "tab", "aria-selected": String(i === state.active),
        onclick: () => { state.active = i; renderResults(); },
      }, `${PLATFORM_LABEL[r.platform]} · @${r.username}`))));
  }
  nodes.push(profileCard(state.results[state.active]));
  root.replaceChildren(...nodes.filter(Boolean));
  loadTrend(state.results[state.active]);
}

function statTile(label, icon, value, note, noteMuted) {
  return h("div", { class: "stat" },
    h("div", { class: "panel-row" }, h("span", { class: "box-label" }, label), h("span", { class: "accent" }, icon)),
    h("div", { class: "stat-value" }, value),
    h("div", { class: `stat-note${noteMuted ? " muted" : ""}` }, note || " "));
}

function profileCard(r) {
  const latency = state.meta ? `${(state.meta.latency_ms / 1000).toFixed(1)}s` : "—";
  const years = r.created_at ? yearsSince(r.created_at) : null;
  const ratio = r.followers !== null && r.following ? `Ratio: ${compact(Math.round(r.followers / r.following))}:1` : "Ratio: —";
  const perDay = r.posts !== null && years ? `~${(r.posts / (years * 365.25)).toFixed(1)} posts/day` : null;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: `${r.platform}_${r.username}.json` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const copyLink = async (btn) => {
    try { await navigator.clipboard.writeText(r.profile_url); btn.textContent = "✓"; }
    catch { btn.textContent = "✕"; }
    setTimeout(() => { btn.textContent = "⧉"; }, 1200);
  };

  return h("section", { class: "panel result-card" },
    h("div", { class: "result-strip" },
      h("span", { class: "tag tag-platform" }, PLATFORM_LABEL[r.platform].toUpperCase()),
      r.verified ? h("span", { class: "tag tag-verified" }, "✓ Verified Entity") : null,
      r.private ? h("span", { class: "tag tag-private" }, "Private") : null,
      r.source === "demo" ? h("span", { class: "tag tag-demo" }, "DEMO DATA") : null,
      r.user_id ? h("span", { class: "muted" }, `ID: ${r.user_id}`) : null,
      h("span", { class: "right" }, h("span", { class: "dot dot-ok" }), ` Refreshed: just now • Latency: ${latency}`)),
    h("div", { class: "result-body" },
      h("div", { class: "profile-head" },
        avatarNode(r.avatar, r.display_name || r.username, "avatar"),
        h("div", { class: "profile-id" },
          h("div", { class: "profile-name" }, r.display_name || r.username, r.verified ? h("span", { class: "check", title: "Verified" }, "✔") : null),
          h("div", { class: "profile-handle" }, `@${r.username}`),
          h("div", { class: "profile-meta" },
            r.location ? h("span", {}, `⌖ ${r.location}`) : null,
            r.external_url ? h("a", { href: r.external_url, target: "_blank", rel: "noopener noreferrer nofollow" }, r.external_url.replace(/^https?:\/\//, "").slice(0, 40)) : null)),
        h("div", { class: "profile-actions" },
          r.profile_url ? h("a", { class: "btn btn-sm", href: r.profile_url, target: "_blank", rel: "noopener noreferrer" }, "↗ Open Profile") : null,
          h("button", { type: "button", class: "btn btn-sm", onclick: exportJson }, "⤓ Export JSON"),
          h("button", { type: "button", class: "btn btn-sm", title: "Copy profile URL", onclick: (e) => copyLink(e.currentTarget) }, "⧉"))),
      h("div", { class: "bio-box" },
        h("div", { class: "box-label" }, "Account Biography & Stated Mission"),
        h("p", { class: "bio-text" }, r.bio || "No biography provided.")),
      h("div", { class: "stats" },
        statTile("Followers", "◉", compact(r.followers), r.followers !== null ? full(r.followers) : null, true),
        statTile("Following", "⇄", compact(r.following), ratio, true),
        statTile(r.platform === "tiktok" ? "Videos" : "Posts", "▤", compact(r.posts), perDay),
        r.created_at
          ? statTile("Created Date", "▦", fmtMonthYear(r.created_at), `${years.toFixed(1)} yrs active`, true)
          : statTile(r.likes !== null ? "Total Likes" : "Created Date", "♥", r.likes !== null ? compact(r.likes) : "—",
              r.likes !== null ? null : "Not provided by platform", true)),
      h("div", { class: "trend", id: "trend" },
        h("div", { class: "trend-head" }, h("strong", {}, "30-DAY FOLLOWER SIGNAL"), h("span", { class: "right" }, "Loading snapshots…"))),
      h("details", { class: "raw" },
        h("summary", {}, h("span", { class: "accent" }, "▣"), "Normalized JSON Payload [EnsembleData Engine]",
          h("span", { class: "right" }, "200 OK"), h("span", { class: "chev" }, "⌄")),
        h("pre", {}, JSON.stringify(r, null, 2)))));
}

/* ----------------------------------------------------------------- trend */
async function loadTrend(r) {
  let points = [];
  try {
    const data = await api(`/api/accounts/${encodeURIComponent(r.platform)}/${encodeURIComponent(r.username)}/trend?days=30`);
    points = data.points.filter((p) => p.followers !== null);
  } catch { /* keep empty */ }
  const box = $("#trend");
  if (!box || state.results[state.active] !== r) return;
  box.replaceChildren(trendView(points, Math.max(300, box.clientWidth - 28)));
}

function trendView(points, width = 640) {
  const head = h("div", { class: "trend-head" }, h("strong", {}, "30-DAY FOLLOWER SIGNAL"));
  const frag = [head];
  if (points.length) {
    const delta = points[points.length - 1].followers - points[0].followers;
    head.append(h("span", { class: `trend-delta${delta < 0 ? " neg" : ""}` }, `${delta >= 0 ? "+" : ""}${compact(delta)} Net`));
  }
  head.append(h("span", { class: "right" }, `Snapshots: ${points.length} · Source: local telemetry`));

  if (points.length < 2) {
    frag.push(h("div", { class: "trend-empty" },
      points.length
        ? "Baseline snapshot recorded. The trend line builds as this account is re-queried over time."
        : "No snapshots available yet."));
    return h("div", {}, frag);
  }

  const W = Math.round(width), H = 150, P = { l: 44, r: 8, t: 10, b: 20 };
  const xs = points.map((p) => new Date(p.captured_at).getTime());
  const ys = points.map((p) => p.followers);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (minY === maxY) { minY -= 1; maxY += 1; }
  const minX = xs[0], maxX = xs[xs.length - 1] === xs[0] ? xs[0] + 1 : xs[xs.length - 1];
  const x = (v) => P.l + ((v - minX) / (maxX - minX)) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - (v - minY) / (maxY - minY)) * (H - P.t - P.b);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(xs[i]).toFixed(1)},${y(ys[i]).toFixed(1)}`).join(" ");
  const area = `${line} L${x(xs[xs.length - 1]).toFixed(1)},${H - P.b} L${x(xs[0]).toFixed(1)},${H - P.b} Z`;
  const last = points.length - 1;

  const svg = h("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Follower count over time" },
    h("defs", {}, h("linearGradient", { id: "trendFill", x1: "0", y1: "0", x2: "0", y2: "1" },
      h("stop", { offset: "0%", "stop-color": "#67e8f9", "stop-opacity": "0.35" }),
      h("stop", { offset: "100%", "stop-color": "#67e8f9", "stop-opacity": "0" }))),
    [0, 0.5, 1].map((f) => h("line", { x1: P.l, x2: W - P.r, y1: P.t + f * (H - P.t - P.b), y2: P.t + f * (H - P.t - P.b), stroke: "#1e2a45", "stroke-dasharray": "3 4" })),
    h("text", { x: 4, y: P.t + 4, class: "trend-axis" }, compact(maxY)),
    h("text", { x: 4, y: H - P.b, class: "trend-axis" }, compact(minY)),
    h("text", { x: P.l, y: H - 4, class: "trend-axis" }, new Date(xs[0]).toLocaleDateString()),
    h("text", { x: W - P.r, y: H - 4, class: "trend-axis", "text-anchor": "end" }, new Date(xs[last]).toLocaleDateString()),
    h("path", { d: area, fill: "url(#trendFill)" }),
    h("path", { d: line, fill: "none", stroke: "#67e8f9", "stroke-width": "2", "vector-effect": "non-scaling-stroke" }),
    points.map((p, i) => h("circle", { cx: x(xs[i]), cy: y(ys[i]), r: i === last ? 4 : 2.5, fill: i === last ? "#e6eaf5" : "#67e8f9" },
      h("title", {}, `${new Date(p.captured_at).toLocaleString()} — ${full(p.followers)} followers`))));
  frag.push(svg);
  return h("div", {}, frag);
}

/* --------------------------------------------------------------- sidebar */
function statusClass(item) {
  if (item.status === "success") return "status-ok";
  if (item.status === "not_found") return "status-empty";
  return "status-err";
}
function statusText(item) {
  if (item.status === "success") return "200 OK";
  if (item.status === "not_found") return "NO MATCH";
  return `${item.status_code} ERR`;
}

async function loadRecent() {
  const list = $("#recent-list");
  try {
    const data = await api("/api/history?limit=5");
    $("#view-all-btn").textContent = `View All Historical Telemetry (${data.total} queries)`;
    if (!data.items.length) {
      list.replaceChildren(h("li", { class: "empty" }, "No inquiries logged yet."));
      return;
    }
    list.replaceChildren(...data.items.map((item) => h("li", {},
      h("button", { type: "button", class: "inquiry", onclick: () => rerun(item) },
        avatarNode(item.avatar, item.display_name || item.username, "inquiry-avatar"),
        h("div", { class: "inquiry-main" },
          h("div", { class: "inquiry-name" }, item.display_name || `@${item.username}`, item.verified ? h("span", { class: "check" }, " ✔") : null),
          h("div", { class: "inquiry-sub" }, `@${item.username} · ${PLATFORM_LABEL[item.result_platform || item.platform] || item.platform}`)),
        h("div", { class: "inquiry-side" },
          h("div", { class: statusClass(item) }, statusText(item)),
          h("div", { class: "muted" }, timeAgo(item.searched_at)))))));
  } catch {
    list.replaceChildren(h("li", { class: "empty" }, "History unavailable."));
  }
}

function rerun(item) {
  $("#username").value = item.username;
  $("#platform").value = item.platform;
  syncClear();
  closeModals();
  searchAccount();
  window.scrollTo({ top: $("#query").offsetTop - 10, behavior: "smooth" });
}

async function loadStatus() {
  let s;
  try { s = await api("/api/system/status"); }
  catch {
    $("#provider-label").textContent = "Backend: Offline";
    $("#provider-dot").className = "dot state-offline";
    $("#engine-dot").className = "dot state-offline";
    return;
  }
  const p = s.provider;
  const stateLabel = { online: "Online", demo: "Demo Mode", degraded: "Degraded", unauthorized: "Auth Failed", not_configured: "No API Key" }[p.state] || p.state;
  $("#provider-label").textContent = `EnsembleData API: ${stateLabel}`;
  $("#provider-latency").textContent = `(Latency ${p.last_latency_ms !== null ? p.last_latency_ms + "ms" : "—"})`;
  $("#provider-dot").className = `dot state-${p.state}`;
  $("#engine-dot").className = `dot state-${p.state}`;

  const badge = $("#mode-badge");
  badge.textContent = p.mode === "live" ? "LIVE MODE" : "DEMO MODE";
  badge.className = `badge ${p.mode === "live" ? "badge-live" : "badge-demo"}`;

  const inq = s.inquiries;
  $("#kpi-inquiries").textContent = full(inq.today);
  const delta = $("#kpi-inquiries-delta");
  delta.textContent = inq.change_pct === null ? "" : `${inq.change_pct >= 0 ? "+" : ""}${inq.change_pct}%`;
  delta.className = inq.change_pct !== null && inq.change_pct < 0 ? "down" : "up";

  $("#kpi-quota").textContent = s.quota.remaining !== null ? full(s.quota.remaining) : (p.mode === "live" ? "N/A" : "∞");
  $("#kpi-quota-total").textContent = s.quota.daily_units ? `/${full(s.quota.daily_units)}` : (p.mode === "live" ? "" : "demo");

  const avg = inq.avg_latency_ms;
  $("#kpi-latency").textContent = avg !== null ? `${(avg / 1000).toFixed(1)}s` : "—";
  const note = $("#kpi-latency-note");
  note.textContent = avg === null ? "" : avg < 5000 ? "Normal" : "Slow";
  note.className = avg !== null && avg >= 5000 ? "down" : "up";

  const rl = s.rate_limit;
  $("#rl-used").textContent = rl.used;
  $("#rl-limit").textContent = rl.limit;
  const pct = Math.min(100, (rl.used / rl.limit) * 100);
  const meter = $("#rl-meter");
  meter.style.width = `${pct}%`;
  meter.classList.toggle("hot", pct >= 80);
  $("#rl-reset").textContent = `Window Reset: ${rl.reset_in ? rl.reset_in + "s" : "—"}`;
  const rlState = $("#rl-state");
  rlState.textContent = rl.remaining === 0 ? "Throttled" : pct >= 80 ? "Near limit" : "Healthy";
  rlState.className = rl.remaining === 0 ? "status-err" : pct >= 80 ? "status-empty" : "ok";

  $("#security-line").textContent = `🔒 Server-side proxy · Input validation · Timeout ${p.timeout_seconds}s · Retries ${p.retries}`;
  $("#footer-telemetry").textContent = `TELEMETRY: ${p.state === "online" || p.state === "demo" ? "STABLE" : "DEGRADED"}`;
  $("#footer-env").textContent = `ENV: ${String(s.app_env).toUpperCase()}`;
  renderSettings(s);
}

function renderSettings(s) {
  const p = s.provider;
  const rows = [
    ["Provider", p.name],
    ["Mode", p.mode === "live" ? "LIVE (EnsembleData)" : "DEMO (synthetic data)"],
    ["Status", p.state],
    ["API key", p.api_key_configured ? "Configured on server ✓ (hidden)" : "Not configured — set ENSEMBLEDATA_API_KEY"],
    ["Base URL", p.base_url],
    ["Request timeout", `${p.timeout_seconds}s`],
    ["Retries", String(p.retries)],
    ["Daily units", s.quota.daily_units !== null ? full(s.quota.daily_units) : "—"],
    ["Units used today", s.quota.used_units !== null ? full(s.quota.used_units) : "—"],
    ["Rate limit", `${s.rate_limit.limit} requests / ${s.rate_limit.window_seconds}s per IP`],
    ["Last provider error", p.last_error_code || "—"],
    ["Environment", s.app_env],
  ];
  $("#settings-list").replaceChildren(...rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
}

function refreshSidebar() {
  loadRecent();
  loadStatus();
}

/* ---------------------------------------------------------------- modals */
function openModal(id) {
  const modal = document.getElementById(id);
  modal.hidden = false;
  if (id === "history-modal") { state.historyOffset = 0; $("#history-body").replaceChildren(); loadHistoryPage(); }
  modal.querySelector("[data-close].icon-btn")?.focus();
}
function closeModals() { document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; }); }

async function loadHistoryPage() {
  const limit = 25;
  try {
    const data = await api(`/api/history?limit=${limit}&offset=${state.historyOffset}`);
    const body = $("#history-body");
    if (!data.items.length && state.historyOffset === 0) {
      body.replaceChildren(h("tr", {}, h("td", { colspan: "6", class: "muted" }, "No history yet.")));
    }
    body.append(...data.items.map((item) => h("tr", { class: "clickable", onclick: () => rerun(item), title: "Run this query again" },
      h("td", {}, new Date(item.searched_at).toLocaleString()),
      h("td", {}, `@${item.username}`),
      h("td", {}, PLATFORM_LABEL[item.platform] || item.platform),
      h("td", { class: statusClass(item) }, item.error_code || statusText(item)),
      h("td", {}, String(item.result_count)),
      h("td", {}, item.latency_ms !== null ? `${item.latency_ms}ms` : "—"))));
    state.historyOffset += data.items.length;
    $("#history-count").textContent = `Showing ${state.historyOffset} of ${data.total}`;
    $("#history-more").hidden = state.historyOffset >= data.total;
  } catch {
    $("#history-count").textContent = "History unavailable.";
  }
}

/* ------------------------------------------------------------------ init */
function syncClear() { $("#clear-btn").hidden = !$("#username").value; }

function init() {
  $("#year").textContent = new Date().getFullYear();
  $("#search-form").addEventListener("submit", searchAccount);
  $("#username").addEventListener("input", () => { syncClear(); showFieldError(""); });
  $("#clear-btn").addEventListener("click", () => { $("#username").value = ""; syncClear(); $("#username").focus(); });
  document.querySelectorAll("[data-target]").forEach((chip) => chip.addEventListener("click", () => {
    $("#username").value = chip.dataset.target;
    syncClear();
    searchAccount();
  }));
  document.querySelectorAll("[data-open]").forEach((btn) => btn.addEventListener("click", () => openModal(btn.dataset.open)));
  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModals));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });
  $("#history-more").addEventListener("click", loadHistoryPage);
  $("#clear-log").addEventListener("click", async () => {
    if (!confirm("Clear all search history?")) return;
    try { await api("/api/history", { method: "DELETE" }); } catch { /* ignore */ }
    refreshSidebar();
  });

  renderEmpty();
  refreshSidebar();
  setInterval(loadStatus, 15000);
}

init();
