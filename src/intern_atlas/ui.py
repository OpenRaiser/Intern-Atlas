"""Embedded browser UI for the local evidence workspace."""

from __future__ import annotations

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Intern Atlas Evidence Workspace</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f3ef;
      --sidebar: #eef2f0;
      --panel: #ffffff;
      --panel-soft: #faf8f4;
      --ink: #1f2933;
      --muted: #637083;
      --line: #d9ddd7;
      --blue: #285f83;
      --green: #0f766e;
      --amber: #a15c07;
      --red: #b42318;
      --violet: #5b5f97;
      --shadow: 0 14px 36px rgba(31, 41, 51, 0.09);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
    }
    button, input, select { font: inherit; }
    button {
      min-height: 38px;
      border: 1px solid var(--blue);
      border-radius: 8px;
      background: var(--blue);
      color: #fff;
      padding: 9px 12px;
      font-weight: 760;
      cursor: pointer;
    }
    button.secondary {
      background: #fff;
      color: var(--blue);
      border-color: var(--line);
    }
    button.subtle {
      background: transparent;
      color: var(--muted);
      border-color: var(--line);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.48;
    }
    input, select {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      padding: 9px 10px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(40, 95, 131, 0.15);
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 6px;
      text-transform: uppercase;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 366px minmax(0, 1fr);
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 22px;
      border-right: 1px solid var(--line);
      background: var(--sidebar);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
    }
    .mark {
      width: 40px;
      height: 40px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      font-weight: 900;
    }
    .brand h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.1;
    }
    .brand p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 16px;
    }
    .stat {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.74);
      padding: 10px;
    }
    .stat strong {
      display: block;
      font-size: 20px;
      line-height: 1;
    }
    .stat span {
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 11px;
    }
    .control-group {
      display: grid;
      gap: 11px;
      margin-top: 16px;
    }
    .split {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .triple {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > * { min-width: 0; }
    .segmented {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }
    .segmented.two {
      grid-template-columns: repeat(2, 1fr);
    }
    .segmented button {
      background: #fff;
      color: var(--muted);
      border-color: var(--line);
      padding: 8px 6px;
    }
    .segmented button.is-active {
      color: #fff;
      border-color: var(--green);
      background: var(--green);
    }
    .remote-settings {
      display: none;
      gap: 10px;
      padding: 11px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.62);
    }
    .remote-settings.is-visible {
      display: grid;
    }
    .source-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .checkline {
      display: flex;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .checkline input {
      width: 16px;
      height: 16px;
    }
    .side-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 16px;
    }
    .toast {
      min-height: 19px;
      margin-top: 10px;
      color: var(--red);
      font-size: 12px;
      line-height: 1.45;
    }
    .main {
      min-width: 0;
      padding: 24px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 16px;
    }
    .hero h2 {
      margin: 0;
      font-size: 26px;
      line-height: 1.14;
    }
    .hero p {
      max-width: 850px;
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .status-pill {
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 9px 11px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
      box-shadow: var(--shadow);
    }
    .metric strong {
      display: block;
      font-size: 21px;
      line-height: 1;
    }
    .metric span {
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      min-height: 32px;
      margin: -4px 0 16px;
    }
    .filter-chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--muted);
      padding: 6px 9px;
      font-size: 12px;
      font-weight: 760;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
      gap: 16px;
      align-items: start;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      min-height: 54px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 13px 15px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .panel-head h3 {
      margin: 0;
      font-size: 15px;
    }
    .panel-head span {
      color: var(--muted);
      font-size: 12px;
    }
    .graph-wrap {
      position: relative;
      height: 430px;
      background: var(--panel-soft);
      border-bottom: 1px solid var(--line);
    }
    svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .graph-empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 13px;
      text-align: center;
      padding: 20px;
    }
    .loading-shade {
      position: absolute;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(250, 248, 244, 0.78);
      color: var(--blue);
      font-weight: 800;
      z-index: 2;
    }
    .node circle {
      fill: var(--blue);
      stroke: #fff;
      stroke-width: 2;
    }
    .node {
      cursor: pointer;
    }
    .node.seed circle { fill: var(--green); }
    .node.active circle { fill: var(--amber); }
    .node text {
      fill: var(--ink);
      font-size: 11px;
      paint-order: stroke;
      stroke: #fff;
      stroke-width: 4px;
      stroke-linejoin: round;
    }
    .edge-line {
      stroke: #8c8174;
      stroke-width: 1.5;
      opacity: 0.72;
    }
    .list {
      max-height: 475px;
      overflow: auto;
    }
    .dense-list {
      max-height: 300px;
      overflow: auto;
    }
    .paper-card, .edge-card, .fact-row, .timeline-row {
      border-bottom: 1px solid var(--line);
      padding: 13px 15px;
    }
    .paper-card {
      cursor: pointer;
    }
    .paper-card:hover, .edge-card:hover {
      background: #f4faf8;
    }
    .paper-card.is-active {
      background: #fff7ea;
      border-left: 4px solid var(--amber);
      padding-left: 11px;
    }
    .title {
      font-weight: 800;
      line-height: 1.33;
      overflow-wrap: anywhere;
    }
    .meta {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .abstract {
      margin-top: 8px;
      color: #3f4b57;
      font-size: 13px;
      line-height: 1.45;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 9px;
    }
    .chip {
      border: 1px solid #d5e3e0;
      border-radius: 999px;
      background: #f0f7f5;
      color: var(--green);
      padding: 3px 7px;
      font-size: 11px;
      font-weight: 760;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .edge-type {
      display: inline-flex;
      align-items: center;
      margin-right: 7px;
      border-radius: 999px;
      background: #f7ead8;
      color: var(--amber);
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 850;
    }
    .edge-detail {
      margin-top: 8px;
      color: #3f4b57;
      font-size: 12px;
      line-height: 1.45;
    }
    .right-stack {
      display: grid;
      gap: 16px;
    }
    .download-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 15px;
    }
    .selection {
      padding: 15px;
      border-top: 1px solid var(--line);
      background: #fbfbf8;
    }
    .selection h4 {
      margin: 0 0 6px;
      font-size: 13px;
    }
    .selection p {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .empty {
      padding: 30px 18px;
      color: var(--muted);
      text-align: center;
      font-size: 13px;
      line-height: 1.45;
    }
    @media (max-width: 1180px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; }
      .workspace { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .main, .sidebar { padding: 16px; }
      .hero { flex-direction: column; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .split, .triple, .download-grid, .side-actions { grid-template-columns: 1fr; }
      .graph-wrap { height: 360px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="mark">IA</div>
        <div>
          <h1>Intern Atlas</h1>
          <p>Evidence layer for research agents</p>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><strong id="papersStat">-</strong><span>Papers</span></div>
        <div class="stat"><strong id="methodsStat">-</strong><span>Methods</span></div>
        <div class="stat"><strong id="edgesStat">-</strong><span>Edges</span></div>
      </div>

      <div class="control-group">
        <div>
          <label for="query">Research query</label>
          <input id="query" value="efficient attention" placeholder="efficient attention, LoRA tuning, long context..." />
        </div>

        <div>
          <label>Retrieval mode</label>
          <div class="segmented" role="group" aria-label="Retrieval mode">
            <button type="button" data-mode="light">Light</button>
            <button type="button" data-mode="balanced" class="is-active">Balanced</button>
            <button type="button" data-mode="deep">Deep</button>
          </div>
        </div>

        <div>
          <label>Data source</label>
          <div class="segmented two" role="group" aria-label="Data source">
            <button type="button" data-source="local" class="is-active">Local graph</button>
            <button type="button" data-source="hosted">Hosted API</button>
          </div>
        </div>

        <div id="remoteSettings" class="remote-settings">
          <div>
            <label for="remoteBaseUrl">Hosted base URL</label>
            <input id="remoteBaseUrl" placeholder="https://intern-atlas.opendatalab.org.cn/" />
          </div>
          <div>
            <label for="remoteApiKey">Hosted API key</label>
            <input id="remoteApiKey" type="password" placeholder="optional bearer token" autocomplete="off" />
          </div>
          <button id="remoteHealthBtn" type="button" class="secondary">Check hosted API</button>
          <div class="source-note">Requests are proxied through this local FastAPI server, so localhost frontends avoid browser CORS issues.</div>
        </div>

        <div class="split">
          <div>
            <label for="yearFrom">Year from</label>
            <input id="yearFrom" type="number" min="1900" max="2100" placeholder="any" />
          </div>
          <div>
            <label for="yearTo">Year to</label>
            <input id="yearTo" type="number" min="1900" max="2100" placeholder="any" />
          </div>
        </div>

        <div class="split">
          <div>
            <label for="edgeType">Edge type</label>
            <select id="edgeType">
              <option value="">Any edge</option>
              <option value="extends">extends</option>
              <option value="improves">improves</option>
              <option value="replaces">replaces</option>
              <option value="adapts">adapts</option>
              <option value="combines">combines</option>
              <option value="uses_component">uses_component</option>
              <option value="compares">compares</option>
            </select>
          </div>
          <div>
            <label for="methodFilter">Method filter</label>
            <input id="methodFilter" placeholder="attention, LoRA..." />
          </div>
        </div>

        <div class="triple">
          <div>
            <label for="maxPapers">Papers</label>
            <input id="maxPapers" type="number" min="1" max="100" value="24" />
          </div>
          <div>
            <label for="maxEdges">Edges</label>
            <input id="maxEdges" type="number" min="0" max="300" value="50" />
          </div>
          <div>
            <label for="depth">Depth</label>
            <input id="depth" type="number" min="0" max="4" value="1" />
          </div>
        </div>

        <label class="checkline">
          <input id="includeContext" type="checkbox" checked />
          Include prompt-ready context
        </label>

        <div class="row">
          <button id="runBtn" type="button">Run evidence search</button>
          <button id="resetBtn" type="button" class="secondary">Reset</button>
        </div>
        <div class="side-actions">
          <button id="copyBtn" type="button" class="secondary" disabled>Copy context</button>
          <button id="docsBtn" type="button" class="subtle">API docs</button>
        </div>
        <div id="toast" class="toast"></div>
      </div>
    </aside>

    <main class="main">
      <div class="hero">
        <div>
          <h2>Evidence Workspace</h2>
          <p id="subtitle">Build a query-specific evidence pack, inspect method evolution, and export data for downstream LLM or agent workflows.</p>
        </div>
        <div id="statusPill" class="status-pill">Ready</div>
      </div>

      <div class="metric-grid">
        <div class="metric"><strong id="viewPapers">0</strong><span>Evidence papers</span></div>
        <div class="metric"><strong id="viewEdges">0</strong><span>Method edges</span></div>
        <div class="metric"><strong id="viewBottlenecks">0</strong><span>Bottlenecks</span></div>
        <div class="metric"><strong id="viewMechanisms">0</strong><span>Mechanisms</span></div>
        <div class="metric"><strong id="viewMode">balanced</strong><span>Mode applied</span></div>
      </div>
      <div id="filterBar" class="filter-bar"></div>

      <div class="workspace">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Method Evolution Graph</h3>
              <span id="graphMeta">0 papers, 0 edges</span>
            </div>
            <button id="openNeighborhoodBtn" type="button" class="secondary" disabled>Open neighborhood</button>
          </div>
          <div class="graph-wrap">
            <svg id="graphSvg" role="img" aria-label="methodology evolution graph"></svg>
            <div id="graphEmpty" class="graph-empty">Run an evidence search to draw a graph.</div>
            <div id="loadingShade" class="loading-shade">Searching evidence...</div>
          </div>
          <div class="selection">
            <h4 id="selectionTitle">No paper selected</h4>
            <p id="selectionMeta">Select a node or paper row to inspect a local neighborhood.</p>
          </div>
          <div class="panel-head">
            <h3>Evidence Papers</h3>
            <span id="paperMeta">0 papers</span>
          </div>
          <div id="paperList" class="list"><div class="empty">No papers loaded yet.</div></div>
        </section>

        <div class="right-stack">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Downloads</h3>
                <span>Export the current evidence view</span>
              </div>
            </div>
            <div class="download-grid">
              <button id="downloadJsonBtn" type="button" class="secondary" disabled>Evidence JSON</button>
              <button id="downloadPapersBtn" type="button" class="secondary" disabled>Papers CSV</button>
              <button id="downloadEdgesBtn" type="button" class="secondary" disabled>Edges CSV</button>
              <button id="downloadContextBtn" type="button" class="secondary" disabled>Context MD</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Timeline</h3>
                <span id="timelineMeta">0 entries</span>
              </div>
            </div>
            <div id="timelineList" class="dense-list"><div class="empty">Timeline appears after search.</div></div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Bottlenecks and Mechanisms</h3>
                <span id="factMeta">0 items</span>
              </div>
            </div>
            <div id="factList" class="dense-list"><div class="empty">No bottlenecks or mechanisms loaded.</div></div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Method Edges</h3>
                <span id="edgeMeta">0 edges</span>
              </div>
            </div>
            <div id="edgeList" class="list"><div class="empty">No edges loaded yet.</div></div>
          </section>
        </div>
      </div>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const modePresets = {
      light: { maxPapers: 12, maxEdges: 18, depth: 0 },
      balanced: { maxPapers: 24, maxEdges: 50, depth: 1 },
      deep: { maxPapers: 100, maxEdges: 300, depth: 2 },
    };
    const state = {
      evidence: null,
      papers: {},
      edges: [],
      active: null,
      mode: 'balanced',
      source: 'local',
      resultSource: null,
      busy: false,
      view: 'empty',
      neighborhood: null,
    };

    async function api(path, opts = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API ${res.status}: ${text.slice(0, 220)}`);
      }
      return res.json();
    }

    function setMode(mode, applyPreset = true) {
      state.mode = modePresets[mode] ? mode : 'balanced';
      document.querySelectorAll('[data-mode]').forEach((button) => {
        button.classList.toggle('is-active', button.dataset.mode === state.mode);
      });
      if (applyPreset) {
        const preset = modePresets[state.mode];
        $('maxPapers').value = preset.maxPapers;
        $('maxEdges').value = preset.maxEdges;
        $('depth').value = preset.depth;
      }
      renderModeHint();
    }

    function setSource(source) {
      state.source = source === 'hosted' ? 'hosted' : 'local';
      document.querySelectorAll('[data-source]').forEach((button) => {
        button.classList.toggle('is-active', button.dataset.source === state.source);
      });
      $('remoteSettings').classList.toggle('is-visible', state.source === 'hosted');
      renderModeHint();
      renderFilterBar(state.evidence?.parameters || {});
    }

    function remoteConfig() {
      const baseUrl = $('remoteBaseUrl').value.trim();
      const apiKey = $('remoteApiKey').value.trim();
      const config = {};
      if (baseUrl) config.base_url = baseUrl;
      if (apiKey) config.api_key = apiKey;
      return config;
    }

    function readNumber(id, label, min, max, fallback = null) {
      const raw = $(id).value.trim();
      if (raw === '') return fallback;
      const value = Number(raw);
      if (!Number.isInteger(value)) {
        throw new Error(`${label} must be a whole number.`);
      }
      if (value < min || value > max) {
        throw new Error(`${label} must be between ${min} and ${max}.`);
      }
      return value;
    }

    function buildPayload() {
      const query = $('query').value.trim();
      if (!query) throw new Error('Enter a research query first.');
      const preset = modePresets[state.mode];
      const payload = {
        query,
        mode: state.mode,
        max_papers: readNumber('maxPapers', 'Papers', 1, 100, preset.maxPapers),
        max_edges: readNumber('maxEdges', 'Edges', 0, 300, preset.maxEdges),
        depth: readNumber('depth', 'Depth', 0, 4, null),
        include_prompt_context: $('includeContext').checked,
      };
      let yearFrom = readNumber('yearFrom', 'Year from', 1900, 2100, null);
      let yearTo = readNumber('yearTo', 'Year to', 1900, 2100, null);
      if (yearFrom !== null && yearTo !== null && yearFrom > yearTo) {
        [yearFrom, yearTo] = [yearTo, yearFrom];
        $('yearFrom').value = yearFrom;
        $('yearTo').value = yearTo;
      }
      const edgeType = $('edgeType').value;
      const method = $('methodFilter').value.trim();
      if (yearFrom !== null) payload.year_from = yearFrom;
      if (yearTo !== null) payload.year_to = yearTo;
      if (edgeType) payload.edge_type = edgeType;
      if (method) payload.method = method;
      return payload;
    }

    async function runEvidenceSearch() {
      showMessage('');
      setBusy(true);
      try {
        const payload = buildPayload();
        const endpoint = state.source === 'hosted'
          ? '/api/v1/remote/evidence/context'
          : '/api/v1/evidence/context';
        const requestBody = state.source === 'hosted'
          ? { ...payload, ...remoteConfig() }
          : payload;
        setStatus(`Searching ${state.source} ${payload.mode} evidence...`);
        const data = await api(endpoint, {
          method: 'POST',
          body: JSON.stringify(requestBody),
        });
        applyEvidence(data);
        const p = data.parameters || {};
        setStatus(`Loaded ${data.counts?.papers || 0} papers from ${state.resultSource || state.source}`);
      } catch (error) {
        showMessage(error);
        setStatus('Error');
      } finally {
        setBusy(false);
      }
    }

    function applyEvidence(data) {
      state.evidence = data;
      state.papers = Object.fromEntries((data.papers || []).map((paper) => [paper.paper_id, paper]));
      state.edges = data.method_edges || [];
      state.active = null;
      state.resultSource = data.source === 'hosted' || state.source === 'hosted' ? 'hosted' : 'local';
      state.view = 'evidence';
      state.neighborhood = null;
      renderAll();
    }

    async function openSelectedNeighborhood() {
      if (!state.active) return;
      const centerId = state.active;
      const centerPaper = state.papers[centerId] || {};
      showMessage('');
      setBusy(true);
      try {
        const depth = Math.max(1, readNumber('depth', 'Depth', 0, 4, 1));
        const limit = Math.max(10, readNumber('maxPapers', 'Papers', 1, 100, 80));
        const useHosted = state.resultSource === 'hosted';
        const sg = useHosted
          ? await api('/api/v1/remote/papers/neighborhood', {
              method: 'POST',
              body: JSON.stringify({ paper_id: centerId, depth, limit, ...remoteConfig() }),
            })
          : await api(`/api/v1/papers/${encodeURIComponent(centerId)}/neighborhood?depth=${depth}&limit=${limit}`);
        state.evidence = null;
        state.papers = sg.papers || {};
        state.edges = sg.edges || [];
        state.active = state.papers[centerId] ? centerId : null;
        state.resultSource = useHosted ? 'hosted' : 'local';
        state.view = 'neighborhood';
        state.neighborhood = {
          center_id: centerId,
          title: centerPaper.title || centerId,
          depth,
          limit,
        };
        renderAll();
        setStatus(`Neighborhood loaded: ${short(centerPaper.title || centerId, 42)}`);
      } catch (error) {
        showMessage(error);
        setStatus('Error');
      } finally {
        setBusy(false);
      }
    }

    async function copyContext() {
      const context = currentPromptContext();
      if (!context) return;
      try {
        await navigator.clipboard.writeText(context);
        setStatus('Context copied');
      } catch (error) {
        showMessage('Clipboard permission denied. Use Context MD download instead.');
      }
    }

    function resetFilters() {
      $('query').value = 'efficient attention';
      $('yearFrom').value = '';
      $('yearTo').value = '';
      $('edgeType').value = '';
      $('methodFilter').value = '';
      $('includeContext').checked = true;
      setMode('balanced', true);
      setSource('local');
      showMessage('');
      setStatus('Ready');
      clearWorkspace();
    }

    function clearWorkspace() {
      state.evidence = null;
      state.papers = {};
      state.edges = [];
      state.active = null;
      state.resultSource = null;
      state.view = 'empty';
      state.neighborhood = null;
      renderAll();
    }

    async function loadStats() {
      const s = await api('/api/stats');
      $('papersStat').textContent = s.papers ?? 0;
      $('methodsStat').textContent = s.methods ?? 0;
      $('edgesStat').textContent = s.edges ?? 0;
    }

    async function checkRemoteHealth() {
      showMessage('');
      setBusy(true);
      try {
        const data = await api('/api/v1/remote/health', {
          method: 'POST',
          body: JSON.stringify(remoteConfig()),
        });
        setStatus(`Hosted API ok: ${data.status || 'ok'}`);
      } catch (error) {
        showMessage(error);
        setStatus('Hosted API error');
      } finally {
        setBusy(false);
      }
    }

    function renderAll() {
      renderMetrics();
      renderGraph();
      renderPapers();
      renderTimeline();
      renderFacts();
      renderEdges();
      renderSelection();
      updateDownloadState();
    }

    function renderMetrics() {
      const counts = state.evidence?.counts || {};
      const params = state.evidence?.parameters || {};
      const bottlenecks = currentBottlenecks();
      const mechanisms = currentMechanisms();
      $('viewPapers').textContent = counts.papers ?? Object.keys(state.papers).length;
      $('viewEdges').textContent = counts.method_edges ?? state.edges.length;
      $('viewBottlenecks').textContent = counts.bottlenecks ?? bottlenecks.length;
      $('viewMechanisms').textContent = counts.mechanisms ?? mechanisms.length;
      $('viewMode').textContent = state.view === 'neighborhood' ? 'local' : (params.mode || state.mode);
      if (state.view === 'neighborhood' && state.neighborhood) {
        $('subtitle').textContent = `Local neighborhood around ${state.neighborhood.title}.`;
        renderFilterBar(params);
        return;
      }
      const filters = [];
      if (params.year_from || params.year_to) filters.push(`${params.year_from || 'any'}-${params.year_to || 'any'}`);
      if (params.edge_type) filters.push(params.edge_type);
      if (params.method) filters.push(`method: ${params.method}`);
      $('subtitle').textContent = filters.length
        ? `Evidence pack filtered by ${filters.join(', ')}.`
        : 'Build a query-specific evidence pack, inspect method evolution, and export data for downstream LLM or agent workflows.';
      renderFilterBar(params);
    }

    function renderModeHint() {
      const preset = modePresets[state.mode];
      if (!preset) return;
      setStatus(`${state.source}: ${state.mode}, up to ${preset.maxPapers} papers, ${preset.maxEdges} edges, depth ${preset.depth}`);
    }

    function renderFilterBar(params = {}) {
      if (state.view === 'neighborhood' && state.neighborhood) {
        const chips = [
          'view: neighborhood',
          `center: ${state.neighborhood.title}`,
          `depth: ${state.neighborhood.depth}`,
          `limit: ${state.neighborhood.limit}`,
        ];
        $('filterBar').innerHTML = chips.map((chip) => `<span class="filter-chip">${escapeHtml(chip)}</span>`).join('');
        return;
      }
      const chips = [
        `source: ${state.resultSource || state.source}`,
        `query: ${state.evidence?.query || $('query').value.trim() || 'none'}`,
        `mode: ${params.mode || state.mode}`,
        `depth: ${params.depth ?? $('depth').value}`,
        `papers: ${params.max_papers ?? $('maxPapers').value}`,
        `edges: ${params.max_edges ?? $('maxEdges').value}`,
      ];
      if ((state.resultSource || state.source) === 'hosted') chips.push(`hosted: ${$('remoteBaseUrl').value.trim() || 'default'}`);
      if (params.year_from || params.year_to) chips.push(`years: ${params.year_from || 'any'}-${params.year_to || 'any'}`);
      if (params.edge_type) chips.push(`edge: ${params.edge_type}`);
      if (params.method) chips.push(`method: ${params.method}`);
      $('filterBar').innerHTML = chips.map((chip) => `<span class="filter-chip">${escapeHtml(chip)}</span>`).join('');
    }

    function renderGraph() {
      const svg = $('graphSvg');
      const papers = Object.values(state.papers).slice(0, 80);
      const ids = new Set(papers.map((paper) => paper.paper_id));
      const edges = state.edges.filter((edge) => ids.has(edge.source_paper_id) && ids.has(edge.target_paper_id)).slice(0, 180);
      $('graphMeta').textContent = `${papers.length} papers, ${edges.length} edges`;
      $('graphEmpty').style.display = papers.length ? 'none' : 'grid';
      if (!papers.length) {
        svg.innerHTML = '';
        $('graphEmpty').textContent = state.evidence ? 'No papers matched the current query and filters.' : 'Run an evidence search to draw a graph.';
        return;
      }
      const width = svg.clientWidth || 860;
      const height = svg.clientHeight || 430;
      const padX = 58;
      const padY = 48;
      const years = papers.map((paper) => Number(paper.year)).filter(Boolean);
      const minYear = years.length ? Math.min(...years) : 0;
      const maxYear = years.length ? Math.max(...years) : papers.length - 1;
      const span = Math.max(1, maxYear - minYear);
      const sorted = [...papers].sort((a, b) => (a.year || 9999) - (b.year || 9999) || String(a.title).localeCompare(String(b.title)));
      const pos = {};
      sorted.forEach((paper, index) => {
        const hasYear = Number(paper.year);
        const distributeByIndex = !hasYear || minYear === maxYear;
        const x = distributeByIndex
          ? padX + (index / Math.max(1, sorted.length - 1)) * (width - padX * 2)
          : padX + ((Number(paper.year) - minYear) / span) * (width - padX * 2);
        const lane = index % 5;
        const y = padY + lane * ((height - padY * 2) / 4);
        pos[paper.paper_id] = { x, y };
      });
      const yearLabels = years.length ? Array.from(new Set([minYear, maxYear])).map((year) => {
        const x = padX + ((year - minYear) / span) * (width - padX * 2);
        return `<text x="${x}" y="${height - 18}" text-anchor="middle" fill="#637083" font-size="11">${year}</text>`;
      }).join('') : '';
      const edgeSvg = edges.map((edge) => {
        const older = pos[edge.target_paper_id];
        const newer = pos[edge.source_paper_id];
        if (!older || !newer) return '';
        const midY = (older.y + newer.y) / 2 - 18;
        return `<path class="edge-line" d="M ${older.x} ${older.y} C ${older.x + 40} ${midY}, ${newer.x - 40} ${midY}, ${newer.x} ${newer.y}" fill="none" marker-end="url(#arrow)" />`;
      }).join('');
      const nodeSvg = sorted.map((paper) => {
        const xy = pos[paper.paper_id];
        const active = paper.paper_id === state.active;
        const seed = paper.evidence_role === 'seed';
        const label = escapeHtml(short(paper.title || paper.paper_id, 34));
        const anchor = xy.x > width - 230 ? 'end' : 'start';
        const labelX = anchor === 'end' ? xy.x - 11 : xy.x + 11;
        return `<g class="node ${active ? 'active' : ''} ${seed ? 'seed' : ''}" data-id="${escapeHtml(paper.paper_id)}">
          <circle cx="${xy.x}" cy="${xy.y}" r="${active ? 10 : 7}"></circle>
          <text x="${labelX}" y="${xy.y + 4}" text-anchor="${anchor}">${label}</text>
        </g>`;
      }).join('');
      svg.innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8c8174"></path></marker></defs>${yearLabels}${edgeSvg}${nodeSvg}`;
      svg.querySelectorAll('.node').forEach((node) => {
        node.addEventListener('click', () => selectPaper(node.dataset.id));
      });
    }

    function renderPapers() {
      const papers = Object.values(state.papers);
      $('paperMeta').textContent = `${papers.length} papers`;
      $('paperList').innerHTML = papers.length ? papers.map((paper) => {
        const methods = (paper.methods || []).slice(0, 6).map((method) => `<span class="chip">${escapeHtml(method.canonical_name)}</span>`).join('');
        const meta = [paper.year, paper.venue, paper.evidence_role, paper.paper_id].filter(Boolean).join(' | ');
        return `<article class="paper-card ${state.active === paper.paper_id ? 'is-active' : ''}" data-id="${escapeHtml(paper.paper_id)}">
          <div class="title">${escapeHtml(paper.title || paper.paper_id)}</div>
          <div class="meta">${escapeHtml(meta)}</div>
          <div class="abstract">${escapeHtml(short(paper.abstract, 240))}</div>
          ${methods ? `<div class="chips">${methods}</div>` : ''}
        </article>`;
      }).join('') : '<div class="empty">No papers found for the current filters.</div>';
      document.querySelectorAll('.paper-card').forEach((el) => {
        el.addEventListener('click', () => selectPaper(el.dataset.id));
      });
    }

    function renderTimeline() {
      const timeline = state.evidence?.timeline || buildTimelineFromCurrentPapers();
      $('timelineMeta').textContent = `${timeline.length} entries`;
      $('timelineList').innerHTML = timeline.length ? timeline.map((item) => `
        <div class="timeline-row">
          <div class="title">${escapeHtml(item.year || 'unknown')} | ${escapeHtml(item.title)}</div>
          <div class="meta">${escapeHtml(item.paper_id)}${item.evidence_role ? ' | ' + escapeHtml(item.evidence_role) : ''}</div>
          <div class="chips">${(item.methods || []).slice(0, 5).map((name) => `<span class="chip">${escapeHtml(name)}</span>`).join('')}</div>
        </div>
      `).join('') : '<div class="empty">Timeline appears after search.</div>';
    }

    function currentBottlenecks() {
      if (state.evidence?.bottlenecks) return state.evidence.bottlenecks;
      return state.edges.filter((edge) => edge.bottleneck).map((edge) => ({
        older_paper_id: edge.target_paper_id,
        newer_paper_id: edge.source_paper_id,
        edge_type: edge.edge_type,
        dimension: edge.dimension || 'unknown',
        bottleneck: edge.bottleneck,
        confidence: edge.confidence,
      }));
    }

    function currentMechanisms() {
      if (state.evidence?.mechanisms) return state.evidence.mechanisms;
      return state.edges.filter((edge) => edge.mechanism).map((edge) => ({
        older_paper_id: edge.target_paper_id,
        newer_paper_id: edge.source_paper_id,
        edge_type: edge.edge_type,
        source_method: edge.source_method || '',
        target_method: edge.target_method || '',
        mechanism: edge.mechanism,
        confidence: edge.confidence,
      }));
    }

    function renderFacts() {
      const bottlenecks = currentBottlenecks();
      const mechanisms = currentMechanisms();
      $('factMeta').textContent = `${bottlenecks.length + mechanisms.length} items`;
      const rows = [
        ...bottlenecks.map((item) => ({ kind: 'Bottleneck', text: item.bottleneck, meta: `${item.dimension || 'unknown'} | ${item.older_paper_id} -> ${item.newer_paper_id}` })),
        ...mechanisms.map((item) => ({ kind: 'Mechanism', text: item.mechanism, meta: `${item.source_method || 'method'} | ${item.older_paper_id} -> ${item.newer_paper_id}` })),
      ];
      $('factList').innerHTML = rows.length ? rows.map((row) => `
        <div class="fact-row">
          <div><span class="edge-type">${escapeHtml(row.kind)}</span></div>
          <div class="edge-detail">${escapeHtml(short(row.text, 220))}</div>
          <div class="meta">${escapeHtml(row.meta)}</div>
        </div>
      `).join('') : '<div class="empty">No bottlenecks or mechanisms loaded.</div>';
    }

    function renderEdges() {
      $('edgeMeta').textContent = `${state.edges.length} edges`;
      $('edgeList').innerHTML = state.edges.length ? state.edges.map((edge) => {
        const olderTitle = edge.older_paper?.title || state.papers[edge.target_paper_id]?.title || edge.target_paper_id;
        const newerTitle = edge.newer_paper?.title || state.papers[edge.source_paper_id]?.title || edge.source_paper_id;
        return `<article class="edge-card">
          <div><span class="edge-type">${escapeHtml(edge.edge_type || 'edge')}</span><span class="title">${escapeHtml(olderTitle)} -> ${escapeHtml(newerTitle)}</span></div>
          <div class="meta">${escapeHtml(edge.target_paper_id)} -> ${escapeHtml(edge.source_paper_id)} | confidence ${formatConfidence(edge.confidence)}</div>
          <div class="edge-detail"><strong>Bottleneck:</strong> ${escapeHtml(short(edge.bottleneck, 220))}</div>
          <div class="edge-detail"><strong>Mechanism:</strong> ${escapeHtml(short(edge.mechanism, 220))}</div>
        </article>`;
      }).join('') : '<div class="empty">No edges in current view.</div>';
    }

    function renderSelection() {
      const paper = state.active ? state.papers[state.active] : null;
      $('openNeighborhoodBtn').disabled = !paper || state.busy;
      if (!paper) {
        $('selectionTitle').textContent = 'No paper selected';
        $('selectionMeta').textContent = 'Select a node or paper row to inspect a local neighborhood.';
        return;
      }
      $('selectionTitle').textContent = paper.title || paper.paper_id;
      $('selectionMeta').textContent = [paper.year, paper.venue, paper.paper_id].filter(Boolean).join(' | ');
    }

    function selectPaper(paperId) {
      if (!paperId) return;
      state.active = paperId;
      renderGraph();
      renderPapers();
      renderSelection();
    }

    function updateDownloadState() {
      const hasPapers = Object.keys(state.papers).length > 0;
      const hasEdges = state.edges.length > 0;
      const hasContext = Boolean(currentPromptContext());
      $('downloadJsonBtn').disabled = !hasPapers;
      $('downloadPapersBtn').disabled = !hasPapers;
      $('downloadEdgesBtn').disabled = !hasEdges;
      $('downloadContextBtn').disabled = !hasContext;
      $('copyBtn').disabled = !hasContext || state.busy;
    }

    function downloadJson() {
      const payload = state.evidence || {
        view: state.view,
        source: state.resultSource || state.source,
        neighborhood: state.neighborhood,
        papers: Object.values(state.papers),
        method_edges: state.edges,
        bottlenecks: currentBottlenecks(),
        mechanisms: currentMechanisms(),
        timeline: buildTimelineFromCurrentPapers(),
        counts: {
          papers: Object.keys(state.papers).length,
          method_edges: state.edges.length,
          bottlenecks: currentBottlenecks().length,
          mechanisms: currentMechanisms().length,
        },
      };
      downloadFile('intern-atlas-evidence.json', JSON.stringify(payload, null, 2), 'application/json');
    }

    function downloadPapersCsv() {
      const rows = Object.values(state.papers).map((paper) => ({
        paper_id: paper.paper_id,
        title: paper.title,
        year: paper.year || '',
        venue: paper.venue || '',
        role: paper.evidence_role || '',
        methods: (paper.methods || []).map((item) => item.canonical_name).join('; '),
        abstract: paper.abstract || '',
      }));
      downloadFile('intern-atlas-papers.csv', toCsv(rows), 'text/csv');
    }

    function downloadEdgesCsv() {
      const rows = state.edges.map((edge) => ({
        source_paper_id: edge.source_paper_id,
        target_paper_id: edge.target_paper_id,
        edge_type: edge.edge_type,
        confidence: edge.confidence,
        source_method: edge.source_method || '',
        target_method: edge.target_method || '',
        bottleneck: edge.bottleneck || '',
        mechanism: edge.mechanism || '',
      }));
      downloadFile('intern-atlas-edges.csv', toCsv(rows), 'text/csv');
    }

    function downloadContextMd() {
      const text = currentPromptContext();
      downloadFile('intern-atlas-context.md', text, 'text/markdown');
    }

    function currentPromptContext() {
      if (state.evidence?.suggested_prompt_context) return state.evidence.suggested_prompt_context;
      const papers = Object.values(state.papers);
      if (!papers.length) return '';
      const lines = [
        'Use this Intern Atlas evidence view to support research idea generation.',
        'Ground claims in the listed paper IDs and avoid inventing papers or results.',
        `Source: ${state.resultSource || state.source}`,
        `Research query: ${state.evidence?.query || $('query').value.trim() || 'not specified'}`,
        '',
        'Papers:',
      ];
      buildTimelineFromCurrentPapers().slice(0, 30).forEach((paper, index) => {
        const year = paper.year || 'unknown';
        const methods = (paper.methods || []).join(', ') || 'methods not extracted';
        lines.push(`${index + 1}. [${year}] ${paper.title} (${paper.paper_id}): ${methods}`);
      });
      lines.push('', 'Method-evolution edges:');
      state.edges.slice(0, 50).forEach((edge, index) => {
        const older = state.papers[edge.target_paper_id]?.title || edge.target_paper_id;
        const newer = state.papers[edge.source_paper_id]?.title || edge.source_paper_id;
        lines.push(
          `${index + 1}. ${older} -> ${newer}: ${edge.edge_type || 'edge'}; ` +
          `bottleneck=${edge.bottleneck || ''}; mechanism=${edge.mechanism || ''}`
        );
      });
      return lines.join('\n');
    }

    function toCsv(rows) {
      if (!rows.length) return '';
      const headers = Object.keys(rows[0]);
      const quote = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
      return [headers.join(','), ...rows.map((row) => headers.map((header) => quote(row[header])).join(','))].join('\n');
    }

    function downloadFile(filename, text, type) {
      const blob = new Blob([text], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(`Downloaded ${filename}`);
    }

    function buildTimelineFromCurrentPapers() {
      return Object.values(state.papers).map((paper) => ({
        year: paper.year,
        paper_id: paper.paper_id,
        title: paper.title,
        evidence_role: paper.evidence_role || '',
        methods: (paper.methods || []).map((item) => item.canonical_name),
      })).sort((a, b) => (a.year || 9999) - (b.year || 9999));
    }

    function setBusy(value) {
      state.busy = value;
      $('runBtn').disabled = value;
      $('resetBtn').disabled = value;
      $('remoteHealthBtn').disabled = value;
      $('runBtn').textContent = value ? 'Searching...' : 'Run evidence search';
      $('loadingShade').style.display = value ? 'grid' : 'none';
      renderSelection();
      updateDownloadState();
    }

    function setStatus(text) {
      $('statusPill').textContent = text;
    }

    function showMessage(message) {
      $('toast').textContent = message ? String(message.message || message) : '';
    }

    function short(text, n = 180) {
      text = String(text || '');
      return text.length > n ? text.slice(0, n - 1) + '...' : text;
    }

    function formatConfidence(value) {
      const num = Number(value || 0);
      return num ? num.toFixed(2) : 'n/a';
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }[ch]));
    }

    document.querySelectorAll('[data-mode]').forEach((button) => {
      button.addEventListener('click', () => setMode(button.dataset.mode, true));
    });
    document.querySelectorAll('[data-source]').forEach((button) => {
      button.addEventListener('click', () => setSource(button.dataset.source));
    });
    $('runBtn').addEventListener('click', runEvidenceSearch);
    $('resetBtn').addEventListener('click', resetFilters);
    $('copyBtn').addEventListener('click', copyContext);
    $('docsBtn').addEventListener('click', () => { window.location.href = '/api/docs'; });
    $('remoteHealthBtn').addEventListener('click', checkRemoteHealth);
    $('openNeighborhoodBtn').addEventListener('click', openSelectedNeighborhood);
    $('downloadJsonBtn').addEventListener('click', downloadJson);
    $('downloadPapersBtn').addEventListener('click', downloadPapersCsv);
    $('downloadEdgesBtn').addEventListener('click', downloadEdgesCsv);
    $('downloadContextBtn').addEventListener('click', downloadContextMd);
    $('query').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runEvidenceSearch();
    });

    setMode('balanced', true);
    setSource('local');
    updateDownloadState();
    loadStats().catch(showMessage).finally(runEvidenceSearch);
  </script>
</body>
</html>"""
