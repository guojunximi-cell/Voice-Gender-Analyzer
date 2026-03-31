/**
 * metrics-panel.js — Right panel: acoustic features of a selected segment.
 * Called whenever a segment is clicked (waveform overlay or list item).
 */

import { sigmaRescale, LABEL_META } from '../utils.js'

// ─── Animated number counter ──────────────────────────────────
function animNum(el, target, suffix = '', duration = 600) {
  if (!el) return
  const start = performance.now()
  const from  = parseFloat(el.dataset.current || 0) || 0
  el.dataset.current = target
  function tick(now) {
    const p = Math.min((now - start) / duration, 1)
    const ease = 1 - Math.pow(1 - p, 3)
    el.textContent = Math.round(from + (target - from) * ease) + suffix
    if (p < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

function animBar(el, pct, delay = 0) {
  if (!el) return
  setTimeout(() => { el.style.width = `${Math.max(0, Math.min(100, pct))}%` }, delay)
}

// ─── Sub-score row builder ────────────────────────────────────
const SUB_SCORE_DEFS = [
  { key: 'pitch_score',     label: '音高',   weight: '45%' },
  { key: 'formant_score',   label: '共振峰', weight: '30%' },
  { key: 'resonance_score', label: '共鸣',   weight: '15%' },
  { key: 'tilt_score',      label: '倾斜',   weight: '10%' },
]

function renderSubScores(a) {
  const el = document.getElementById('mc-subscores')
  if (!el) return
  el.innerHTML = ''
  for (const def of SUB_SCORE_DEFS) {
    const val = a[def.key] ?? null
    const row = document.createElement('div')
    row.className = 'subscore-row'
    row.innerHTML = `
      <span class="subscore-label">${def.label} <span class="subscore-weight">(${def.weight})</span></span>
      <div class="subscore-bar-wrap">
        <div class="subscore-bar-fill" style="width:0%"></div>
      </div>
      <span class="subscore-val">${val != null ? Math.round(val) + '%' : '—'}</span>
    `
    el.appendChild(row)
    if (val != null) {
      requestAnimationFrame(() => {
        const fill = row.querySelector('.subscore-bar-fill')
        if (fill) fill.style.width = `${val}%`
      })
    }
  }
}

// ─── Gender spectrum bar ──────────────────────────────────────
// confidence: 0–1 from Engine A; label: 'female'|'male'
function renderGenderBar(confidence, label) {
  const thumb   = document.getElementById('mc-gender-thumb')
  const scoreEl = document.getElementById('mc-gender-score')
  if (!thumb || !scoreEl) return

  const scaledConf = Math.min(confidence, 1)
  const pct = label === 'female'
    ? 50 + scaledConf * 50
    : 50 - scaledConf * 50

  requestAnimationFrame(() => { thumb.style.left = `${pct}%` })
  thumb.dataset.gender = label

  const pctDisplay = Math.min(Math.round(confidence * 100), 100)
  const symbol = label === 'female' ? '♀' : '♂'
  scoreEl.textContent = `${pctDisplay}% ${symbol}`
}

// ─── Public: render metrics for a segment ────────────────────
export function renderMetricsPanel(segment) {
  const empty   = document.getElementById('metrics-empty')
  const content = document.getElementById('metrics-content')
  if (!empty || !content) return

  // Segments without acoustic data (music, noise, noEnergy, or too-short voiced)
  if (!segment?.acoustics) {
    const name = (LABEL_META[segment?.label] || {}).zh || segment?.label || '该片段'
    const isVoiced = segment?.label === 'male' || segment?.label === 'female'
    const msg = isVoiced ? `${name} — 片段过短，无法分析` : `${name} — 无声学特征数据`
    empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>${msg}</span>`
    empty.hidden  = false
    content.hidden = true
    return
  }

  empty.hidden  = true
  content.hidden = false

  const a = segment.acoustics

  // ── F0 card ──────────────────────────────────────────────
  animNum(document.getElementById('mc-f0-median'), a.f0_median_hz, ' Hz')
  const stdEl = document.getElementById('mc-f0-std')
  if (stdEl) stdEl.textContent = `±${a.f0_std_hz ?? '—'} Hz`

  // ── Resonance card ───────────────────────────────────────
  animNum(document.getElementById('mc-res-val'), Math.round(a.resonance_pct), '%')
  animBar(document.getElementById('mc-res-bar'), a.resonance_pct, 80)

  // ── Formants ─────────────────────────────────────────────
  const setFormant = (id, val) => {
    const el = document.getElementById(id)
    if (el) el.textContent = val ? `${val} Hz` : '—'
  }
  setFormant('mc-f1', a.f1_hz)
  setFormant('mc-f2', a.f2_hz)
  setFormant('mc-f3', a.f3_hz)

  // ── Spectral Tilt ────────────────────────────────────────
  const tiltEl = document.getElementById('mc-tilt-val')
  if (tiltEl) {
    tiltEl.textContent = a.spectral_tilt_db_oct != null
      ? `${a.spectral_tilt_db_oct.toFixed(1)} dB/oct`
      : '—'
  }

  // ── Pitch range reference bar ────────────────────────────
  const pitchIndicator = document.getElementById('mc-pitch-indicator')
  if (pitchIndicator && a.f0_median_hz) {
    // Map 80–320 Hz log scale to 0–100%
    const logMin = Math.log2(80), logMax = Math.log2(320)
    const logVal = Math.log2(Math.max(80, Math.min(320, a.f0_median_hz)))
    const pct = ((logVal - logMin) / (logMax - logMin)) * 100
    requestAnimationFrame(() => { pitchIndicator.style.left = `${pct}%` })
  }

  // ── Gender score bar (Engine A confidence as primary) ────
  const conf = segment.confidence != null ? segment.confidence : (a.gender_score / 100)
  renderGenderBar(conf, segment.label)

  // Reference: Engine B acoustic gender_score
  const refEl = document.getElementById('mc-gender-score-ref')
  if (refEl) refEl.textContent = a.gender_score != null ? `${Math.round(a.gender_score)}%` : '—'

  // ── Sub-scores ───────────────────────────────────────────
  renderSubScores(a)

  // ── Segment label in header ──────────────────────────────
  const headerLabel = document.getElementById('mc-segment-label')
  if (headerLabel) {
    const meta = LABEL_META[segment.label] || { zh: segment.label }
    headerLabel.textContent = `${meta.zh}  ${_fmtTime(segment.start_time)}–${_fmtTime(segment.end_time)}`
  }
}

// ─── Clear panel ─────────────────────────────────────────────
export function clearMetricsPanel() {
  const empty   = document.getElementById('metrics-empty')
  const content = document.getElementById('metrics-content')
  if (empty) {
    empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>点击音段<br/>查看声学特征</span>`
    empty.hidden = false
  }
  if (content) content.hidden = true
}

function _fmtTime(sec) {
  if (sec == null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
