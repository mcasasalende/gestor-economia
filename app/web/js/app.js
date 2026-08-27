// App controller: UI wiring, period selection, aggregation, rendering.

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

const state = {
  snapshot: null,
  year: null,
  month: "01",
  selectedCategory: null,
  offline: false,
};

// ---- DOM helpers ----

function $(id) { return document.getElementById(id); }

function setStatus(text, mode) {
  const el = $("status");
  el.textContent = text;
  el.className = "status status-" + (mode || "idle");
}

function formatSince(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h ago";
  return Math.floor(h / 24) + "d ago";
}

function euro(n) {
  return "€" + n.toLocaleString("en-IE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// ---- settings UI ----

function openSettings() {
  const s = getSettings();
  $("input-url").value = s.snapshotUrl || "";
  $("input-token").value = s.token || "";
  $("settings").classList.remove("hidden");
}

function closeSettings() {
  $("settings").classList.add("hidden");
}

function saveSettingsUI() {
  const s = getSettings();
  s.snapshotUrl = $("input-url").value.trim();
  s.token = $("input-token").value.trim();
  saveSettings(s);
  closeSettings();
  setStatus("Settings saved. Syncing…", "idle");
  boot();
}

// ---- period ----

function availableYears() {
  const set = new Set();
  for (const t of state.snapshot.transactions) set.add(t.date.slice(0, 4));
  return Array.from(set).sort().reverse();
}

function latestPeriod() {
  let best = null;
  for (const t of state.snapshot.transactions) {
    if (!best || t.date > best) best = t.date;
  }
  return best ? { year: best.slice(0, 4), month: best.slice(5, 7) } : null;
}

function buildChips() {
  const years = availableYears();
  const yearRow = $("year-chips");
  yearRow.innerHTML = "";
  for (const y of years) {
    const c = document.createElement("button");
    c.className = "chip" + (y === state.year ? " active" : "");
    c.textContent = y;
    c.addEventListener("click", () => {
      state.year = y;
      if (!monthsWithData(y).includes(state.month)) {
        const last = monthsWithData(y).at(-1) || "01";
        state.month = last;
      }
      buildChips();
      render();
    });
    yearRow.appendChild(c);
  }

  const monthRow = $("month-chips");
  monthRow.innerHTML = "";
  for (let i = 0; i < 12; i++) {
    const mm = String(i + 1).padStart(2, "0");
    const c = document.createElement("button");
    c.className = "chip" + (mm === state.month ? " active" : "");
    c.textContent = `${mm} - ${MONTH_NAMES[i]}`;
    c.addEventListener("click", () => {
      state.month = mm;
      buildChips();
      render();
    });
    monthRow.appendChild(c);
  }
}

function monthsWithData(year) {
  const set = new Set();
  for (const t of state.snapshot.transactions) {
    if (t.date.slice(0, 4) === year) set.add(t.date.slice(5, 7));
  }
  return Array.from(set).sort();
}

// ---- aggregation ----

function periodTransactions() {
  const period = `${state.year}-${state.month}`;
  return state.snapshot.transactions.filter((t) => t.date.startsWith(period));
}

function expensesByCategory(txs) {
  const map = {};
  for (const t of txs) {
    if (t.amount >= 0) continue;
    const name = t.category_name || "Uncategorized";
    map[name] = (map[name] || 0) + Math.abs(t.amount);
  }
  return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

function monthlyExpenses() {
  const map = {};
  for (const t of state.snapshot.transactions) {
    if (t.amount >= 0) continue;
    const ym = t.date.slice(0, 7);
    map[ym] = (map[ym] || 0) + Math.abs(t.amount);
  }
  return Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]));
}

function cumulativeByCategory() {
  const byCat = {};
  for (const t of state.snapshot.transactions) {
    if (t.amount >= 0) continue;
    const name = t.category_name || "Uncategorized";
    const ym = t.date.slice(0, 7);
    if (!byCat[name]) byCat[name] = {};
    byCat[name][ym] = (byCat[name][ym] || 0) + Math.abs(t.amount);
  }
  return byCat;
}

// ---- rendering ----

function render() {
  const txAll = state.snapshot.transactions;
  if (!txAll.length) {
    $("controls").classList.add("hidden");
    $("dashboard").classList.add("hidden");
    $("empty").textContent = "No data in the snapshot.";
    $("empty").classList.remove("hidden");
    return;
  }

  $("empty").classList.add("hidden");
  $("controls").classList.remove("hidden");
  $("dashboard").classList.remove("hidden");

  buildChips();
  renderKpis();
  renderCategoryChartSection();
  renderMonthly();
  renderStacked();
  renderTransactions();
}

function renderKpis() {
  const txs = periodTransactions();
  let income = 0;
  let expenses = 0;
  for (const t of txs) {
    if (t.amount > 0) income += t.amount;
    else expenses += Math.abs(t.amount);
  }
  const net = income - expenses;
  $("kpi-income").textContent = euro(income);
  $("kpi-expenses").textContent = euro(expenses);
  const netEl = $("kpi-net");
  netEl.textContent = euro(net);
  netEl.className = "kpi-value kpi-net " + (net >= 0 ? "positive" : "negative");
}

function renderCategoryChartSection() {
  const txs = periodTransactions();
  const rows = expensesByCategory(txs);
  $("title-category").textContent = `Expenses by Category (${state.year}-${state.month})`;

  const emptyEl = $("empty-category");
  if (!rows.length) {
    emptyEl.classList.remove("hidden");
    $("chart-category").closest(".chart-wrap").classList.add("hidden");
    return;
  }
  emptyEl.classList.add("hidden");
  $("chart-category").closest(".chart-wrap").classList.remove("hidden");

  const labels = rows.map((r) => r[0]);
  const values = rows.map((r) => r[1]);

  renderCategoryChart("chart-category", labels, values, (idx) => {
    const clicked = labels[idx];
    state.selectedCategory = clicked === state.selectedCategory ? null : clicked;
    renderCategoryChartSection();
    renderTransactions();
  });
}

function renderMonthly() {
  const rows = monthlyExpenses();
  const labels = rows.map((r) => {
    const [y, m] = r[0].split("-");
    return `${MONTH_NAMES[Number(m) - 1]} ${y.slice(2)}`;
  });
  renderMonthlyChart("chart-monthly", labels, rows.map((r) => r[1]));
}

function renderStacked() {
  const byCat = cumulativeByCategory();
  const months = Array.from(
    new Set(Object.values(byCat).flatMap((m) => Object.keys(m)))
  ).sort();
  const labels = months.map((ym) => {
    const [y, m] = ym.split("-");
    return `${MONTH_NAMES[Number(m) - 1]} ${y.slice(2)}`;
  });

  const series = Object.entries(byCat)
    .map(([category, m]) => {
      let total = 0;
      const values = months.map((ym) => {
        const v = m[ym] || 0;
        total += v;
        return v;
      });
      return { category, values, total, color: categoryColor(category) };
    })
    .sort((a, b) => b.total - a.total);

  renderStackedChart("chart-stacked", labels, series);
}

function renderTransactions() {
  const card = $("transactions-card");
  const title = $("transactions-title");
  const list = $("transactions-list");

  if (!state.selectedCategory) {
    card.classList.add("hidden");
    return;
  }

  const txs = periodTransactions()
    .filter((t) => (t.category_name || "Uncategorized") === state.selectedCategory)
    .sort((a, b) => b.date.localeCompare(a.date));

  title.textContent = `${state.selectedCategory} (${state.year}-${state.month})`;
  list.innerHTML = "";

  if (!txs.length) {
    const li = document.createElement("li");
    li.textContent = "No transactions for this category in this period.";
    li.style.color = "var(--fg-muted)";
    list.appendChild(li);
  } else {
    for (const t of txs) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="tx-info">
          <span class="tx-desc"></span>
          <span class="tx-date"></span>
        </div>
        <span class="tx-amount ${t.amount > 0 ? "income" : ""}"></span>`;
      li.querySelector(".tx-desc").textContent = t.description;
      li.querySelector(".tx-date").textContent = t.date;
      li.querySelector(".tx-amount").textContent =
        (t.amount > 0 ? "+" : "") + euro(Math.abs(t.amount));
      list.appendChild(li);
    }
  }
  card.classList.remove("hidden");
}

// ---- boot / sync ----

function applySnapshot(snapshot, offline) {
  state.snapshot = snapshot;
  state.offline = offline;
  const latest = latestPeriod();
  state.year = latest ? latest.year : null;
  state.month = latest ? latest.month : "01";
  state.selectedCategory = null;
  render();
}

async function boot() {
  const s = getSettings();
  if (s.lastSynced) setStatus(`Cached ${formatSince(s.lastSynced)}`, "offline");
  else setStatus("…", "idle");

  try {
    const snapshot = await syncNow();
    applySnapshot(snapshot, false);
    setStatus(`Synced ${formatSince(getSettings().lastSynced)}`, "ok");
  } catch (err) {
    const cached = await getCachedSnapshot();
    if (cached) {
      applySnapshot(cached, true);
      const last = getSettings().lastSynced;
      setStatus(last ? `Offline — data from ${formatSince(last)}` : "Offline — cached data", "offline");
    } else {
      $("empty").textContent = "Can't sync: " + err.message + ". Open settings and set the snapshot URL.";
      setStatus("Offline", "error");
    }
  }
}

function bindEvents() {
  $("btn-settings").addEventListener("click", () => {
    if ($("settings").classList.contains("hidden")) openSettings();
    else closeSettings();
  });
  $("btn-save").addEventListener("click", saveSettingsUI);
  $("btn-refresh").addEventListener("click", boot);
  $("btn-clear-cache").addEventListener("click", async () => {
    await clearSnapshotCache();
    const s = getSettings();
    delete s.lastSynced;
    saveSettings(s);
    closeSettings();
    setStatus("Cache cleared", "idle");
    boot();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  boot();
});
