import { seekToTime } from './waveform.js'
import { LABEL_META, fmt } from '../utils.js'

// ─── Animated counter ────────────────────────────────────────
function animateCounter(el, target, suffix = '%', duration = 700) {
  if (!el) return
  const start = performance.now()
  function tick(now) {
    const p = Math.min((now - start) / duration, 1)
    const ease = 1 - Math.pow(1 - p, 3)
    el.textContent = Math.round(target * ease) + suffix
    if (p < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// ─── Compute stats from analysis array ───────────────────────
function computeStats(analysis) {
  const totals = {}
  let total = 0
  for (const seg of analysis) {
    const d = seg.end_time - seg.start_time
    totals[seg.label] = (totals[seg.label] || 0) + d
    total += d
  }
  return { totals, total }
}

// ─── Stats cards ─────────────────────────────────────────────
export function renderStats(analysis) {
  const { totals, total } = computeStats(analysis)
  const maleDur   = totals['male']   || 0
  const femaleDur = totals['female'] || 0
  const otherDur  = total - maleDur - femaleDur

  const malePct   = total ? Math.round((maleDur   / total) * 100) : 0
  const femalePct = total ? Math.round((femaleDur / total) * 100) : 0
  const otherPct  = Math.max(0, 100 - malePct - femalePct)

  animateCounter(document.getElementById('male-pct'),   malePct)
  animateCounter(document.getElementById('female-pct'), femalePct)
  animateCounter(document.getElementById('other-pct'),  otherPct)

  const setDur = (id, sec) => {
    const el = document.getElementById(id)
    if (el) el.textContent = fmt(sec)
  }
  setDur('male-duration',   maleDur)
  setDur('female-duration', femaleDur)
  setDur('other-duration',  otherDur)

  requestAnimationFrame(() => {
    const setBar = (id, pct) => {
      const el = document.getElementById(id)
      if (el) el.style.width = `${Math.max(0, pct)}%`
    }
    setBar('male-bar',   malePct)
    setBar('female-bar', femalePct)
    setBar('other-bar',  otherPct)
  })

  // Mark dominant voice type for visual emphasis
  const maxPct = Math.max(malePct, femalePct, otherPct)
  const domMap = { male: malePct, female: femalePct, other: otherPct }
  for (const [key, pct] of Object.entries(domMap)) {
    const el = document.querySelector(`.stat-${key}`)
    if (el) el.classList.toggle('dominant', pct === maxPct && maxPct > 0)
  }

  const section = document.getElementById('stats-section')
  if (section) section.hidden = false
}

// ─── Segment list ─────────────────────────────────────────────
export function renderSegments(analysis) {
  const list    = document.getElementById('segments-list')
  const count   = document.getElementById('segment-count')
  const section = document.getElementById('segments-section')
  if (!list || !section) return

  section.hidden = false
  if (count) count.textContent = `${analysis.length} 段`

  list.innerHTML = ''

  analysis.forEach((seg, i) => {
    const meta = LABEL_META[seg.label] || { zh: seg.label, cssVar: 'var(--noise)' }
    const dur  = seg.end_time - seg.start_time
    const hasAcoustics = !!seg.acoustics

    const item = document.createElement('div')
    item.className = 'segment-item'
    if (!hasAcoustics) item.classList.add('no-acoustics')
    item.dataset.index = i

    const swatch = document.createElement('span')
    swatch.className = 'segment-swatch'
    swatch.style.background = meta.cssVar

    const label = document.createElement('span')
    label.className = 'segment-label'
    label.textContent = meta.zh

    const time = document.createElement('span')
    time.className = 'segment-time'
    time.textContent = `${fmt(seg.start_time)} – ${fmt(seg.end_time)}`

    const duration = document.createElement('span')
    duration.className = 'segment-duration'
    duration.textContent = fmt(dur)

    // Acoustic indicator dot (shows that Engine B data is available)
    item.appendChild(swatch)
    item.appendChild(label)
    item.appendChild(time)
    item.appendChild(duration)

    if (hasAcoustics) {
      const dot = document.createElement('span')
      dot.className = 'segment-acoustic-dot'
      dot.title = '含声学分析'
      item.appendChild(dot)
    }

    // Confidence micro-bar for voiced segments
    const voiced = seg.label === 'female' || seg.label === 'male'
    if (voiced && seg.confidence != null) {
      const bar = document.createElement('div')
      bar.className = 'segment-conf-bar'
      bar.style.setProperty('--conf', seg.confidence)
      bar.title = `置信度 ${Math.round(seg.confidence * 100)}%`
      item.appendChild(bar)
    }

    item.addEventListener('click', () => {
      // Seek waveform
      seekToTime(seg.start_time)

      // Highlight in list
      list.querySelectorAll('.segment-item').forEach(el => el.classList.remove('active'))
      item.classList.add('active')

      // Fire event → main.js → metrics-panel
      document.dispatchEvent(new CustomEvent('segment-select', {
        detail: { segment: seg, index: i }
      }))
    })

    list.appendChild(item)
  })
}

// ─── Sync active segment during playback ─────────────────────
export function highlightActiveSegment(currentSec, analysis) {
  const list = document.getElementById('segments-list')
  if (!list) return

  for (let i = 0; i < analysis.length; i++) {
    const seg  = analysis[i]
    const item = list.querySelector(`[data-index="${i}"]`)
    if (!item) continue

    const isActive = currentSec >= seg.start_time && currentSec < seg.end_time
    item.classList.toggle('active', isActive)

    if (isActive && !item.dataset.scrolled) {
      item.dataset.scrolled = '1'
      item.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

      // Also update metrics panel while audio plays through segments
      document.dispatchEvent(new CustomEvent('segment-select', {
        detail: { segment: seg, index: i }
      }))
    } else if (!isActive) {
      delete item.dataset.scrolled
    }
  }
}

// ─── Reset ────────────────────────────────────────────────────
export function resetResults() {
  const statsSection    = document.getElementById('stats-section')
  const segmentsSection = document.getElementById('segments-section')
  if (statsSection)    statsSection.hidden    = true
  if (segmentsSection) segmentsSection.hidden = true

  const ids = ['male-pct','female-pct','other-pct','male-duration','female-duration','other-duration']
  ids.forEach(id => { const el = document.getElementById(id); if (el) el.textContent = '—' })

  const bars = ['male-bar','female-bar','other-bar']
  bars.forEach(id => { const el = document.getElementById(id); if (el) el.style.width = '0%' })

  const list = document.getElementById('segments-list')
  if (list) list.innerHTML = ''
}
