const palette = {
  accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
  accent2: getComputedStyle(document.documentElement).getPropertyValue('--accent-2').trim(),
  positive: getComputedStyle(document.documentElement).getPropertyValue('--positive').trim(),
  negative: getComputedStyle(document.documentElement).getPropertyValue('--negative').trim(),
  text: getComputedStyle(document.documentElement).getPropertyValue('--text').trim(),
  muted: getComputedStyle(document.documentElement).getPropertyValue('--muted').trim(),
  panel: getComputedStyle(document.documentElement).getPropertyValue('--panel').trim(),
  border: getComputedStyle(document.documentElement).getPropertyValue('--border').trim(),
};

function formatNumber(v, digits=2) { return Number(v).toFixed(digits); }
function formatPct(v) { return (Number(v) * 100).toFixed(1) + '%'; }

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${url}`);
  return await res.json();
}

function csrfToken() {
  const match = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('XSRF-TOKEN='));
  if (!match) return null;
  return decodeURIComponent(match.split('=')[1]);
}

async function loadData() {
  try {
    const [candles, trades, stats, drawdown, strategies, symbols, adminSymbols, rules] = await Promise.all([
      fetchJson('/api/candles'),
      fetchJson('/api/trades'),
      fetchJson('/api/stats'),
      fetchJson('/api/drawdown'),
      fetchJson('/api/strategy-performance'),
      fetchJson('/api/symbol-performance'),
      fetchJson('/api/admin/symbols'),
      fetchJson('/api/admin/rules'),
    ]);
    renderCandles(candles);
    renderDrawdown(drawdown);
    renderWinLoss(stats);
    renderStrategies(strategies);
    renderSymbols(symbols);
    renderTrades(trades);
    renderMetrics(stats);
    renderAdminSymbols(adminSymbols);
    fillRulesForm(rules);
  } catch (err) {
    console.error('Dashboard load error:', err);
  }
}

function renderCandles(data) {
  const ctx = document.getElementById('candleChart');
  if (!ctx) return;
  if (!data || data.length === 0) {
    const parent = ctx.parentElement;
    if (parent) {
      parent.innerHTML = '';
      parent.appendChild(emptyState('No candle data yet'));
    }
    return;
  }
  const times = data.map(d => new Date(d.t).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}));
  const closes = data.map(d => d.c);
  const gradient = ctx.getContext('2d').createLinearGradient(0,0,0,300);
  gradient.addColorStop(0, palette.accent);
  gradient.addColorStop(1, palette.accent2);
  new Chart(ctx, {
    type: 'line',
    data: { 
      labels: times,
      datasets: [{ label: 'Price', data: closes, borderColor: palette.accent, backgroundColor: 'rgba(139, 92, 246, 0.1)', tension: 0.25, fill: true }] 
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: palette.muted } } },
      scales: {
        x: { ticks: { color: palette.muted }, grid: { color: palette.border } },
        y: { ticks: { color: palette.muted }, grid: { color: palette.border } },
      },
    },
  });
}

function renderDrawdown(data) {
  const ctx = document.getElementById('drawdownChart');
  if (!ctx) return;
  if (!data || data.length === 0) {
    const parent = ctx.parentElement;
    if (parent) parent.innerHTML = '';
    if (parent) parent.appendChild(emptyState('No drawdown data yet'));
    return;
  }
  new Chart(ctx, {
    type: 'line',
    data: { labels: data.map(d => new Date(d.t)), datasets: [{ label: 'Drawdown', data: data.map(d => d.dd * 100), borderColor: palette.negative, backgroundColor: 'rgba(239,68,68,0.12)', tension: 0.25, fill: true }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: palette.muted } } },
      scales: {
        x: { ticks: { color: palette.muted }, grid: { color: palette.border } },
        y: { ticks: { color: palette.muted, callback: v => v + '%' }, grid: { color: palette.border } },
      },
    },
  });
}

function renderWinLoss(stats) {
  const ctx = document.getElementById('winLossChart');
  if (!ctx) return;
  if (!stats || (stats.win_rate === 0 && stats.loss_rate === 0)) {
    const parent = ctx.parentElement;
    if (parent) parent.innerHTML = '';
    if (parent) parent.appendChild(emptyState('No trades yet'));
    return;
  }
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Wins', 'Losses'],
      datasets: [{
        data: [stats.win_rate, stats.loss_rate],
        backgroundColor: [palette.positive, palette.negative],
        borderColor: palette.panel,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: palette.muted } } },
    },
  });
}

function renderStrategies(data) {
  const ctx = document.getElementById('strategyChart');
  if (!ctx) return;
  if (!data || data.length === 0) {
    const parent = ctx.parentElement;
    if (parent) parent.innerHTML = '';
    if (parent) parent.appendChild(emptyState('No strategy data'));
    return;
  }
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.strategy),
      datasets: [
        { label: 'PnL', data: data.map(d => d.pnl), backgroundColor: palette.accent },
        { label: 'Win %', data: data.map(d => d.win_rate * 100), backgroundColor: palette.accent2 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: palette.muted } } },
      scales: {
        x: { ticks: { color: palette.muted }, grid: { display: false } },
        y: { ticks: { color: palette.muted }, grid: { color: palette.border } },
      },
    },
  });
}

function renderSymbols(data) {
  const ctx = document.getElementById('symbolChart');
  if (!ctx) return;
  if (!data || data.length === 0) {
    const parent = ctx.parentElement;
    if (parent) parent.innerHTML = '';
    if (parent) parent.appendChild(emptyState('No symbol performance yet'));
    return;
  }
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.symbol),
      datasets: [{ label: 'PnL', data: data.map(d => d.pnl), backgroundColor: data.map(d => d.pnl >= 0 ? palette.positive : palette.negative) }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: palette.muted } } },
      scales: {
        x: { ticks: { color: palette.muted }, grid: { display: false } },
        y: { ticks: { color: palette.muted }, grid: { color: palette.border } },
      },
    },
  });
}

function renderTrades(trades) {
  const tbody = document.querySelector('#tradesTable tbody');
  tbody.innerHTML = '';
  if (!trades || trades.length === 0) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 7;
    cell.textContent = 'No trades yet';
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  trades.forEach(t => {
    const row = document.createElement('tr');
    const cells = [
      new Date(t.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}),
      t.symbol,
      t.side.toUpperCase(),
      t.quantity,
      formatNumber(t.price),
      formatNumber(t.realized_pnl),
      t.status,
    ];
    cells.forEach((val, idx) => {
      const td = document.createElement('td');
      td.textContent = val;
      if (idx === 4 || idx === 5) {
        if (t.realized_pnl > 0) td.className = 'badge-positive';
        if (t.realized_pnl < 0) td.className = 'badge-negative';
      }
      row.appendChild(td);
    });
    tbody.appendChild(row);
  });
}

function renderMetrics(stats) {
  const grid = document.getElementById('metricGrid');
  if (!stats) {
    grid.innerHTML = '';
    return;
  }
  const items = [
    { label: 'Realized P&L', value: '$' + formatNumber(stats.realized_pnl) },
    { label: 'Unrealized P&L', value: '$' + formatNumber(stats.unrealized_pnl) },
    { label: 'Win Rate', value: formatPct(stats.win_rate) },
    { label: 'Loss Rate', value: formatPct(stats.loss_rate) },
    { label: 'Trades', value: stats.trades },
    { label: 'Max Drawdown', value: formatPct(stats.max_drawdown) },
    { label: 'Current Drawdown', value: formatPct(stats.current_drawdown) },
  ];
  grid.innerHTML = '';
  items.forEach(item => {
    const box = document.createElement('div');
    box.className = 'metric';
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = item.label;
    const value = document.createElement('div');
    value.className = 'value';
    value.textContent = item.value;
    box.appendChild(label);
    box.appendChild(value);
    grid.appendChild(box);
  });
}

function emptyState(text) {
  const el = document.createElement('div');
  el.className = 'empty-state';
  el.textContent = text;
  return el;
}

function renderAdminSymbols(symbols) {
  const container = document.getElementById('symbolList');
  container.innerHTML = '';
  symbols.forEach(s => {
    const pill = document.createElement('div');
    pill.className = 'pill';
    const label = document.createElement('span');
    label.textContent = s.symbol + (s.enabled ? '' : ' (disabled)');
    const toggle = document.createElement('button');
    toggle.textContent = s.enabled ? 'Disable' : 'Enable';
    toggle.addEventListener('click', async () => {
      await fetch(`/api/admin/symbols/${encodeURIComponent(s.symbol)}`, {
        method: 'PATCH',
        headers: { ...csrfHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !s.enabled }),
      });
      loadData().catch(() => {});
    });
    const remove = document.createElement('button');
    remove.textContent = 'Remove';
    remove.addEventListener('click', async () => {
      await fetch(`/api/admin/symbols/${encodeURIComponent(s.symbol)}`, { method: 'DELETE', headers: csrfHeaders() });
      loadData().catch(() => {});
    });
    pill.appendChild(label);
    pill.appendChild(toggle);
    pill.appendChild(remove);
    container.appendChild(pill);
  });
}

function bindSymbolForm() {
  const form = document.getElementById('symbolForm');
  const input = document.getElementById('symbolInput');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const symbol = input.value.trim();
    if (!symbol) return;
    await fetch('/api/admin/symbols', {
      method: 'POST',
      headers: { ...csrfHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    });
    input.value = '';
    loadData().catch(() => {});
  });
}

function fillRulesForm(rules) {
  const form = document.getElementById('rulesForm');
  form.max_risk_per_trade.value = rules.max_risk_per_trade;
  form.max_daily_loss.value = rules.max_daily_loss;
  form.max_trades_per_day.value = rules.max_trades_per_day;
  form.cooldown_seconds.value = rules.cooldown_seconds;
  form.budget.value = rules.budget;
}

function bindRulesForm() {
  const form = document.getElementById('rulesForm');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      max_risk_per_trade: parseFloat(form.max_risk_per_trade.value),
      max_daily_loss: parseFloat(form.max_daily_loss.value),
      max_trades_per_day: parseInt(form.max_trades_per_day.value, 10),
      cooldown_seconds: parseInt(form.cooldown_seconds.value, 10),
      budget: parseFloat(form.budget.value),
    };
    await fetch('/api/admin/rules', {
      method: 'PUT',
      headers: { ...csrfHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    loadData().catch(() => {});
  });
}

function csrfHeaders() {
  const token = csrfToken();
  if (!token) return {};
  return { 'X-CSRFToken': token };
}

bindSymbolForm();
bindRulesForm();
loadData().catch((err) => console.error('Initial load failed:', err));
