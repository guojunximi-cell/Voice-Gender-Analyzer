import WaveSurfer from 'wavesurfer.js'
import { resolveCSSVar, LABEL_META } from '../utils.js'

// ─── Color map ────────────────────────────────────────────────
const LABEL_VARS = {
  male:     '--male',
  female:   '--female',
  music:    '--music',
  noise:    '--noise',
  noEnergy: '--noenergy',
}

// ─── Module state ─────────────────────────────────────────────
let ws            = null
let duration      = 0
let segments      = []   // full segment objects (including acoustics)
let resizeObserver = null
let _tooltip      = null
let _selectedTint = null  // currently selected tint rect

// ─── DOM helpers ─────────────────────────────────────────────
const $  = id => document.getElementById(id)
const fmt = sec => {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ─── SVG timeline overlay ─────────────────────────────────────
export function drawTimeline(segs) {
  segments = segs || []
  _renderOverlay()
}

function _renderOverlay() {
  const svg = $('segment-overlay')
  if (!svg || !duration) return

  const W  = $('waveform-container').clientWidth
  const H  = 88
  const BAND_H = 8
  const BAND_Y = H - BAND_H

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`)
  svg.innerHTML = ''
  _selectedTint = null
  _tooltip = $('seg-tooltip')

  segments.forEach((seg, idx) => {
    const color   = resolveCSSVar(LABEL_VARS[seg.label] || '--noise') || '#888'
    const x       = (seg.start_time / duration) * W
    const w       = Math.max(2, ((seg.end_time - seg.start_time) / duration) * W)
    const voiced  = seg.label === 'male' || seg.label === 'female'

    // Full-height tint
    const tint = _svgRect(x, 0, w, BAND_Y, color, 0.13)
    svg.appendChild(tint)

    // Bottom band
    const band = _svgRect(x, BAND_Y, w, BAND_H, color, 1, 2)
    svg.appendChild(band)

    // Make voiced segments clickable on the waveform
    if (voiced) {
      const hit = _svgRect(x, 0, w, H, 'transparent', 0)
      hit.style.pointerEvents = 'all'
      hit.style.cursor        = 'pointer'
      hit.setAttribute('data-index', idx)

      hit.addEventListener('mouseenter', () => {
        tint.setAttribute('opacity', 0.22)
        if (_tooltip) {
          const meta = LABEL_META[seg.label] || { zh: seg.label }
          _tooltip.textContent = `${meta.zh}  ${fmt(seg.start_time)}–${fmt(seg.end_time)}`
          const containerW = $('waveform-container').clientWidth
          const centerPct  = ((x + w / 2) / containerW) * 100
          _tooltip.style.left = `${centerPct}%`
          _tooltip.classList.add('visible')
        }
      })

      hit.addEventListener('mouseleave', () => {
        if (tint !== _selectedTint) tint.setAttribute('opacity', 0.13)
        if (_tooltip) _tooltip.classList.remove('visible')
      })

      hit.addEventListener('click', (e) => {
        e.stopPropagation()
        // Clear previous selection
        if (_selectedTint && _selectedTint !== tint) _selectedTint.setAttribute('opacity', 0.13)
        tint.setAttribute('opacity', 0.30)
        _selectedTint = tint
        document.dispatchEvent(new CustomEvent('segment-select', {
          detail: { segment: seg, index: idx }
        }))
      })

      svg.appendChild(hit)
    }
  })
}

function _svgRect(x, y, w, h, fill, opacity, rx = 0) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  el.setAttribute('x', x)
  el.setAttribute('y', y)
  el.setAttribute('width', w)
  el.setAttribute('height', h)
  el.setAttribute('fill', fill)
  el.setAttribute('opacity', opacity)
  if (rx) el.setAttribute('rx', rx)
  return el
}

// ─── Init WaveSurfer ─────────────────────────────────────────
export function initWaveform(file, callbacks = {}) {
  destroyWaveform()

  const loading = $('waveform-loading')
  if (loading) loading.style.display = 'flex'

  ws = WaveSurfer.create({
    container:     '#waveform',
    waveColor:     resolveCSSVar('--wave-color')    || '#555',
    progressColor: resolveCSSVar('--wave-progress') || '#d4a574',
    cursorColor:   resolveCSSVar('--wave-progress') || '#d4a574',
    barWidth:      2,
    barGap:        1,
    barRadius:     2,
    height:        88,
    normalize:     true,
    interact:      true,
    cursorWidth:   1,
  })

  const url = URL.createObjectURL(file)
  ws.load(url)

  ws.on('ready', (dur) => {
    duration = dur
    if (loading) loading.style.display = 'none'

    const pb = $('play-btn'), ab = $('analyze-btn')
    if (pb) pb.disabled = false
    if (ab) ab.disabled = false
    if ($('total-time')) $('total-time').textContent = fmt(dur)

    _renderOverlay()
    callbacks.onReady?.(dur)
  })

  ws.on('audioprocess', t => { _updateSeekUI(t); callbacks.onTimeUpdate?.(t) })
  ws.on('seeking',      t => { _updateSeekUI(t); callbacks.onTimeUpdate?.(t) })
  ws.on('play',  () => _setPlayState(true))
  ws.on('pause', () => _setPlayState(false))
  ws.on('finish', () => _setPlayState(false))

  // Seek bar
  const seekBar = $('seek-bar')
  seekBar?.addEventListener('click', e => {
    if (!ws || !duration) return
    const track = seekBar.querySelector('.seek-track')
    const rect  = track.getBoundingClientRect()
    ws.seekTo(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)))
  })

  resizeObserver = new ResizeObserver(() => {
    ws?.setOptions?.({
      waveColor:     resolveCSSVar('--wave-color')    || '#555',
      progressColor: resolveCSSVar('--wave-progress') || '#d4a574',
    })
    _renderOverlay()
  })
  resizeObserver.observe($('waveform-container'))
}

function _updateSeekUI(t) {
  if (!duration) return
  const pct = (t / duration) * 100
  const sp = $('seek-progress'), st = $('seek-thumb'), ct = $('current-time')
  if (sp) sp.style.width = `${pct}%`
  if (st) st.style.left  = `${pct}%`
  if (ct) ct.textContent = fmt(t)
}

function _setPlayState(playing) {
  const btn = $('play-btn')
  if (!btn) return
  btn.querySelector('.icon-play').hidden  =  playing
  btn.querySelector('.icon-pause').hidden = !playing
}

// ─── Public controls ─────────────────────────────────────────
export function togglePlay()       { ws?.playPause() }
export function seekToTime(sec)    { if (ws && duration) ws.seekTo(sec / duration) }
export function getDuration()      { return duration }
export function getCurrentTime()   { return ws?.getCurrentTime() ?? 0 }

// ─── Theme update ─────────────────────────────────────────────
export function updateWaveformTheme() {
  if (ws) {
    ws.setOptions({
      waveColor:     resolveCSSVar('--wave-color')    || '#555',
      progressColor: resolveCSSVar('--wave-progress') || '#d4a574',
      cursorColor:   resolveCSSVar('--wave-progress') || '#d4a574',
    })
  }
  _renderOverlay()
}

// ─── Cleanup ─────────────────────────────────────────────────
export function destroyWaveform() {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (ws) { try { ws.destroy() } catch (_) {}; ws = null }
  duration = 0; segments = []
  _selectedTint = null
  if (_tooltip) { _tooltip.classList.remove('visible'); _tooltip = null }

  const svg = $('segment-overlay')
  if (svg) svg.innerHTML = ''

  const sp = $('seek-progress'), st = $('seek-thumb'),
        ct = $('current-time'),  tt = $('total-time')
  if (sp) sp.style.width = '0%'
  if (st) st.style.left  = '0%'
  if (ct) ct.textContent = '0:00'
  if (tt) tt.textContent = '0:00'
  _setPlayState(false)
}
