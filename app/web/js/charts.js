// Chart.js v4 renderers. Each function destroys any previous chart on the
// same canvas before redrawing.

const PALETTE = [
  "#38bdf8", "#34d399", "#f472b6", "#fbbf24", "#a78bfa", "#f87171",
  "#2dd4bf", "#fb923c", "#4ade80", "#e879f9", "#60a5fa", "#facc15",
];

const COLOR_MAP = {};

function categoryColor(name) {
  if (!COLOR_MAP[name]) {
    COLOR_MAP[name] = PALETTE[Object.keys(COLOR_MAP).length % PALETTE.length];
  }
  return COLOR_MAP[name];
}

function euro(n) {
  return "€" + n.toLocaleString("en-IE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const charts = {};

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

const commonOptions = {
  responsive: true,
  maintainAspectRatio: false,
  color: "#94a3b8",
};

function renderCategoryChart(canvasId, labels, values, onSelect) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  charts[canvasId] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map(categoryColor),
        borderColor: "#1e293b",
        borderWidth: 2,
      }],
    },
    options: {
      ...commonOptions,
      cutout: "60%",
      plugins: {
        legend: { position: "bottom", labels: { color: "#94a3b8", boxWidth: 12 } },
        tooltip: { callbacks: { label: (item) => ` ${item.label}: ${euro(item.parsed)}` } },
      },
      onClick: (evt, elements) => {
        if (elements.length > 0 && onSelect) onSelect(elements[0].index);
      },
    },
  });
}

function renderMonthlyChart(canvasId, labels, values) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: "#38bdf8",
        borderRadius: 4,
        maxBarThickness: 28,
      }],
    },
    options: {
      ...commonOptions,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => ` ${euro(item.parsed.y)}` } },
      },
      scales: {
        x: { ticks: { color: "#94a3b8", maxRotation: 45, font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "#334155" } },
      },
    },
  });
}

function renderStackedChart(canvasId, labels, series) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: series.map((s) => ({
        label: s.category,
        data: s.values,
        backgroundColor: s.color,
        maxBarThickness: 20,
      })),
    },
    options: {
      ...commonOptions,
      plugins: {
        legend: { position: "bottom", labels: { color: "#94a3b8", boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: (item) => ` ${item.dataset.label}: ${euro(item.parsed.y)}` } },
      },
      scales: {
        x: {
          stacked: true,
          ticks: { color: "#94a3b8", maxRotation: 45, font: { size: 10 } },
          grid: { display: false },
        },
        y: {
          stacked: true,
          ticks: { color: "#94a3b8", font: { size: 10 } },
          grid: { color: "#334155" },
        },
      },
    },
  });
}
