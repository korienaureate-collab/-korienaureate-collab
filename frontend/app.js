/**
 * Golf Tracking System — Frontend Application
 *
 * Architecture:
 *   GolfApp       — root controller, owns state
 *   SocketManager — WebSocket connection lifecycle
 *   UI            — DOM manipulation helpers
 *   Audio         — Web Audio API sound effects
 *   Api           — fetch wrappers for REST endpoints
 */

'use strict';

/* ==========================================================================
   Audio Engine (Web Audio API — no external files needed)
   ========================================================================== */

class AudioEngine {
  constructor() {
    this._ctx = null;
  }

  _getCtx() {
    if (!this._ctx) {
      this._ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return this._ctx;
  }

  _tone(freq, type = 'sine', duration = 0.12, gain = 0.25) {
    try {
      const ctx = this._getCtx();
      const osc = ctx.createOscillator();
      const amp = ctx.createGain();
      osc.connect(amp);
      amp.connect(ctx.destination);
      osc.type = type;
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      amp.gain.setValueAtTime(gain, ctx.currentTime);
      amp.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + duration);
    } catch (_) { /* audio not supported */ }
  }

  playSuccess() {
    this._tone(660, 'sine', 0.1, 0.2);
    setTimeout(() => this._tone(880, 'sine', 0.15, 0.18), 80);
  }

  playMismatch() {
    this._tone(300, 'sawtooth', 0.15, 0.15);
    setTimeout(() => this._tone(220, 'sawtooth', 0.2, 0.1), 100);
  }

  playError() {
    this._tone(200, 'square', 0.25, 0.12);
  }

  playReset() {
    [440, 370, 294].forEach((f, i) => setTimeout(() => this._tone(f, 'sine', 0.12, 0.15), i * 70));
  }
}


/* ==========================================================================
   API Layer
   ========================================================================== */

const Api = {
  async getData() {
    const res = await fetch('/data');
    if (!res.ok) throw new Error(`GET /data failed: ${res.status}`);
    return res.json();
  },

  async submitShot(ballId, zone) {
    const res = await fetch('/shot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ball_id: ballId, zone }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body?.data?.error || `POST /shot failed: ${res.status}`);
    return body;
  },

  async resetSession() {
    const res = await fetch('/reset', { method: 'POST' });
    if (!res.ok) throw new Error(`POST /reset failed: ${res.status}`);
    return res.json();
  },
};


/* ==========================================================================
   UI Helpers
   ========================================================================== */

const UI = {
  // --- Element cache ---
  el(id) { return document.getElementById(id); },

  setText(id, text) {
    const el = this.el(id);
    if (el) el.textContent = text;
  },

  // --- Toast ---
  showToast(title, message = '', type = 'info', duration = 4000) {
    const container = this.el('toast-container');
    const toast = document.createElement('div');
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
      <span class="toast__icon">${icons[type] || 'ℹ️'}</span>
      <div class="toast__body">
        <div class="toast__title">${this._esc(title)}</div>
        ${message ? `<div class="toast__message">${this._esc(message)}</div>` : ''}
      </div>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('toast--out');
      setTimeout(() => toast.remove(), 350);
    }, duration);
  },

  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  },

  // --- Connection status ---
  setConnection(state) {
    // state: 'online' | 'offline' | 'connecting'
    const dot   = this.el('conn-indicator');
    const label = this.el('conn-label');
    dot.className = `status-dot status-dot--${state}`;
    const labels = { online: 'Connected', offline: 'Disconnected', connecting: 'Connecting…' };
    label.textContent = labels[state] || state;
  },

  // --- Score ---
  updateScore(value) {
    const el = this.el('score-value');
    el.textContent = value >= 0 ? `+${value}` : String(value);
    el.className = 'score-display__value' + (value < 0 ? ' score--negative' : '');
    el.classList.add('score-pop');
    el.addEventListener('animationend', () => el.classList.remove('score-pop'), { once: true });
  },

  // --- Stats ---
  updateStats(state) {
    this.setText('stat-total',    state.total_shots);
    this.setText('stat-valid',    state.valid_shots);
    this.setText('stat-mismatch', state.mismatch_shots);
    this.setText('stat-rejected', state.rejected_shots);
    this.setText('stat-accuracy', `${state.accuracy}%`);
    this.setText('session-id-display', state.session_id || '—');
  },

  // --- Session timer ---
  updateDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts = [];
    if (h) parts.push(`${h}h`);
    if (m || h) parts.push(`${m}m`);
    parts.push(`${s}s`);
    this.setText('session-duration', parts.join(' '));
  },

  // --- Last shot ---
  updateLastShot(shot) {
    const container = this.el('last-shot-card');
    const deltaClass = shot.score_delta > 0
      ? 'score-delta--positive'
      : shot.score_delta < 0 ? 'score-delta--negative' : 'score-delta--zero';
    const deltaLabel = shot.score_delta >= 0 ? `+${shot.score_delta}` : String(shot.score_delta);

    container.innerHTML = `
      <div class="shot-info-grid">
        <div class="shot-info-item">
          <div class="shot-info-item__label">Ball ID</div>
          <div class="shot-info-item__value">${this._esc(shot.ball_id)}</div>
        </div>
        <div class="shot-info-item">
          <div class="shot-info-item__label">Zone</div>
          <div class="shot-info-item__value">${this._esc(shot.zone.toUpperCase())}</div>
        </div>
        <div class="shot-info-item">
          <div class="shot-info-item__label">Result</div>
          <div class="shot-info-item__value">
            <span class="result-badge result-badge--${shot.result}">${shot.result}</span>
          </div>
        </div>
        <div class="shot-info-item">
          <div class="shot-info-item__label">Score Δ</div>
          <div class="shot-info-item__value score-delta ${deltaClass}">${deltaLabel}</div>
        </div>
        <div class="shot-info-item">
          <div class="shot-info-item__label">Shot ID</div>
          <div class="shot-info-item__value">#${this._esc(shot.shot_id)}</div>
        </div>
        <div class="shot-info-item">
          <div class="shot-info-item__label">Time</div>
          <div class="shot-info-item__value">${this._esc(shot.timestamp_formatted)}</div>
        </div>
      </div>`;
  },

  // --- AI Status ---
  updateAI(shot) {
    const conf = shot.ai_confidence;
    const pct  = Math.round(conf * 100);

    this.el('confidence-bar').style.width = `${pct}%`;
    this.setText('confidence-value', `${pct}%`);

    const verdict = this.el('ai-verdict');
    verdict.textContent = shot.result === 'valid' ? 'APPROVED' : 'REJECTED';
    verdict.style.color = shot.result === 'valid'
      ? 'var(--green)'
      : 'var(--red)';

    this.setText('ai-notes',   shot.ai_notes || 'OK');
    this.setText('ai-latency', `${shot.processing_time_ms} ms`);
  },

  // --- Zone map ---
  _zoneCounts: {},
  updateZoneMap(zone) {
    this._zoneCounts[zone] = (this._zoneCounts[zone] || 0) + 1;
    const ids = {
      green: 'zm-green', fairway: 'zm-fairway', rough: 'zm-rough',
      bunker: 'zm-bunker', water: 'zm-water', out_of_bounds: 'zm-oob',
    };
    if (ids[zone]) this.setText(ids[zone], this._zoneCounts[zone]);

    // Flash active tile
    const tiles = document.querySelectorAll('.zone-tile');
    tiles.forEach(t => t.classList.remove('zone-tile--active'));
    const activeTile = document.querySelector(`.zone-tile[data-zone="${zone}"]`);
    if (activeTile) {
      activeTile.classList.add('zone-tile--active');
      setTimeout(() => activeTile.classList.remove('zone-tile--active'), 1500);
    }
  },

  resetZoneMap() {
    this._zoneCounts = {};
    ['zm-green','zm-fairway','zm-rough','zm-bunker','zm-water','zm-oob']
      .forEach(id => this.setText(id, '0'));
  },

  // --- History table ---
  updateHistory(history) {
    const tbody = this.el('history-tbody');
    this.setText('history-count', `${history.length} shots`);

    if (!history.length) {
      tbody.innerHTML = '<tr class="history-empty-row"><td colspan="8">No shots recorded yet</td></tr>';
      return;
    }

    tbody.innerHTML = history.map((shot, idx) => {
      const deltaLabel = shot.score_delta >= 0 ? `+${shot.score_delta}` : String(shot.score_delta);
      const deltaClass = shot.score_delta > 0 ? 'color:var(--green)' : shot.score_delta < 0 ? 'color:var(--red)' : '';
      const resultClass = `result-badge result-badge--${shot.result}`;
      const isNew = idx === 0 ? 'history-row--new' : '';

      return `<tr class="${isNew}">
        <td>${this._esc(shot.timestamp_formatted)}</td>
        <td style="color:var(--text-muted)">#${this._esc(shot.shot_id)}</td>
        <td style="color:var(--accent);font-weight:600">${this._esc(shot.ball_id)}</td>
        <td style="text-transform:capitalize">${this._esc(shot.zone)}</td>
        <td><span class="${resultClass}">${this._esc(shot.result)}</span></td>
        <td>${Math.round(shot.ai_confidence * 100)}%</td>
        <td style="${deltaClass};font-weight:700">${deltaLabel}</td>
        <td style="font-weight:600">${shot.cumulative_score >= 0 ? '+' : ''}${shot.cumulative_score}</td>
      </tr>`;
    }).join('');
  },

  // --- Form feedback ---
  setFeedback(message, type = '') {
    const el = this.el('form-feedback');
    el.textContent = message;
    el.className = `form-feedback${type ? ` form-feedback--${type}` : ''}`;
  },
};


/* ==========================================================================
   WebSocket Manager
   ========================================================================== */

class SocketManager {
  constructor(onShot, onState, onError) {
    this._onShot  = onShot;
    this._onState = onState;
    this._onError = onError;
    this._socket  = null;
  }

  connect() {
    UI.setConnection('connecting');
    this._socket = io({ transports: ['websocket', 'polling'] });

    this._socket.on('connect', () => {
      UI.setConnection('online');
      console.info('[WS] Connected:', this._socket.id);
    });

    this._socket.on('disconnect', () => {
      UI.setConnection('offline');
      console.warn('[WS] Disconnected');
    });

    this._socket.on('connect_error', (err) => {
      UI.setConnection('offline');
      console.error('[WS] Connect error:', err.message);
    });

    this._socket.on('shot_update', (payload) => {
      console.debug('[WS] shot_update', payload);
      this._onShot(payload);
    });

    this._socket.on('state_update', (payload) => {
      console.debug('[WS] state_update', payload);
      this._onState(payload);
    });

    this._socket.on('error_event', (payload) => {
      this._onError(payload);
    });
  }

  disconnect() {
    if (this._socket) this._socket.disconnect();
  }
}


/* ==========================================================================
   Main Application
   ========================================================================== */

class GolfApp {
  constructor() {
    this._audio   = new AudioEngine();
    this._sockets = new SocketManager(
      (p) => this._onShotUpdate(p),
      (p) => this._onStateUpdate(p),
      (p) => this._onServerError(p),
    );
    this._sessionStart = Date.now();
    this._timerHandle  = null;
    this._submitting   = false;
    this._state        = null;
  }

  // ------------------------------------------------------------------
  // Bootstrap
  // ------------------------------------------------------------------

  async init() {
    this._bindForm();
    this._bindReset();
    this._bindZonePills();
    this._sockets.connect();
    this._startTimer();

    // Hydrate from REST on load (in case WS is slow)
    try {
      const data = await Api.getData();
      if (data.ok) this._applyState(data.data);
    } catch (err) {
      console.warn('[App] Initial hydration failed:', err.message);
    }
  }

  // ------------------------------------------------------------------
  // Event handlers
  // ------------------------------------------------------------------

  _onShotUpdate({ shot, state }) {
    UI.updateScore(state.score);
    UI.updateStats(state);
    UI.updateLastShot(shot);
    UI.updateAI(shot);
    UI.updateZoneMap(shot.zone);

    // Fetch full history from server (history not in shot_update)
    Api.getData().then(d => {
      if (d.ok) UI.updateHistory(d.data.history);
    }).catch(() => {});

    // Feedback
    if (shot.result === 'valid') {
      this._audio.playSuccess();
      UI.showToast('Shot Recorded', `${shot.ball_id} → ${shot.zone} (+${shot.score_delta} pts)`, 'success', 3000);
    } else if (shot.result === 'mismatch') {
      this._audio.playMismatch();
      UI.showToast('Mismatch Detected', shot.ai_notes || 'Ball ID changed mid-sequence', 'warning', 4000);
    } else {
      this._audio.playError();
      UI.showToast('Shot Rejected', shot.ai_notes || shot.result, 'error', 4000);
    }
  }

  _onStateUpdate({ state }) {
    if (state?.state) {
      this._applyState(state);
    } else if (state?.state || state) {
      this._applyState(state.state ? state : { state });
    }
  }

  _onServerError({ message }) {
    UI.showToast('Server Error', message, 'error');
    this._audio.playError();
  }

  _applyState(payload) {
    // Handle both { state: {…}, history: […] } and nested formats
    const st   = payload.state  || payload;
    const hist = payload.history || [];

    this._state = st;
    this._sessionStart = st.session_start
      ? st.session_start * 1000
      : this._sessionStart;

    UI.updateScore(st.score || 0);
    UI.updateStats(st);
    UI.updateHistory(hist);
  }

  // ------------------------------------------------------------------
  // Timer
  // ------------------------------------------------------------------

  _startTimer() {
    this._timerHandle = setInterval(() => {
      const elapsed = Math.floor((Date.now() - this._sessionStart) / 1000);
      UI.updateDuration(elapsed);
    }, 1000);
  }

  // ------------------------------------------------------------------
  // Form
  // ------------------------------------------------------------------

  _bindForm() {
    const form = document.getElementById('shot-form');
    const btn  = document.getElementById('btn-submit');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (this._submitting) return;

      const ballId = document.getElementById('ball-id-input').value.trim();
      const zone   = document.getElementById('zone-select').value;

      if (!ballId) {
        UI.setFeedback('Ball ID is required.', 'error');
        return;
      }
      if (!zone) {
        UI.setFeedback('Please select a zone.', 'error');
        return;
      }

      this._submitting = true;
      btn.disabled = true;
      UI.setFeedback('Processing…');

      try {
        await Api.submitShot(ballId, zone);
        UI.setFeedback('');
        // Keep ball ID pre-filled for rapid sequential entry
        document.getElementById('zone-select').value = '';
        document.querySelectorAll('.zone-pill.active').forEach(p => p.classList.remove('active'));
      } catch (err) {
        UI.setFeedback(err.message, 'error');
        this._audio.playError();
        UI.showToast('Submission Failed', err.message, 'error');
      } finally {
        this._submitting = false;
        btn.disabled = false;
        document.getElementById('ball-id-input').focus();
      }
    });
  }

  _bindReset() {
    document.getElementById('btn-reset').addEventListener('click', async () => {
      if (!confirm('Reset the current session? All data will be cleared.')) return;
      try {
        await Api.resetSession();
        this._sessionStart = Date.now();
        UI.resetZoneMap();
        UI.updateHistory([]);
        UI.updateScore(0);
        UI.setText('stat-total', 0);
        UI.setText('stat-valid', 0);
        UI.setText('stat-mismatch', 0);
        UI.setText('stat-rejected', 0);
        UI.setText('stat-accuracy', '0%');
        UI.el('last-shot-card').innerHTML =
          '<div class="last-shot__placeholder">No shots yet this session</div>';
        this._audio.playReset();
        UI.showToast('Session Reset', 'A new session has been started.', 'info');
        UI.setFeedback('');
      } catch (err) {
        UI.showToast('Reset Failed', err.message, 'error');
      }
    });
  }

  _bindZonePills() {
    document.getElementById('zone-pills').addEventListener('click', (e) => {
      const pill = e.target.closest('.zone-pill');
      if (!pill) return;

      document.querySelectorAll('.zone-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');

      const zone = pill.dataset.zone;
      document.getElementById('zone-select').value = zone;
      UI.setFeedback('');
    });
  }
}


/* ==========================================================================
   Bootstrap
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  const app = new GolfApp();
  app.init().catch(err => {
    console.error('[App] Init failed:', err);
    UI.showToast('Startup Error', err.message, 'error', 8000);
  });

  // Dev helper: expose to console for quick testing
  window.__golf = {
    submit: (ballId, zone) => Api.submitShot(ballId, zone),
    reset:  () => Api.resetSession(),
    data:   () => Api.getData(),
  };
});
