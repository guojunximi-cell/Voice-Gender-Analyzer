import { setupUploader, validateFile,
         RESTRICTED_MAX_BYTES } from './modules/uploader.js'
import { initWaveform, destroyWaveform,
         togglePlay, drawTimeline,
         updateWaveformTheme }               from './modules/waveform.js'
import { analyzeAudio, cancelAnalysis }      from './modules/analyzer.js'
import { renderStats, renderSegments,
         highlightActiveSegment,
         resetResults }                      from './modules/results.js'
import { renderMetricsPanel,
         clearMetricsPanel }                 from './modules/metrics-panel.js'
import { initScatter, addSession,
         loadAllSessions, selectSession,
         clearAllSessions, removeSession as scatterRemoveSession,
         redraw as scatterRedraw }           from './modules/scatter.js'
import { loadSessions, saveSession,
         clearSessions, removeSession as storeRemoveSession } from './modules/session-store.js'
import { nextSessionColor }                  from './utils.js'

// ─── State ────────────────────────────────────────────────────
// phases: idle | loaded | analyzing | results
let phase            = 'idle'
let currentFile      = null
let analysisData     = null   // current API response
let _batchInProgress = false  // true while batch multi-file analysis is running

// ─── DOM shortcuts ────────────────────────────────────────────
const $ = id => document.getElementById(id)

// ─── Toast ────────────────────────────────────────────────────
let toastTimer = null
function showToast(msg, type = '') {
  const toast = $('toast')
  if (!toast) return
  clearTimeout(toastTimer)
  toast.textContent = msg
  toast.className = `toast show ${type}`
  toastTimer = setTimeout(() => toast.classList.remove('show'), 4500)
}

// ─── Theme ────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('theme')
  const preferred = saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  applyTheme(preferred)
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('theme', theme)
  updateWaveformTheme()
  scatterRedraw()
}

$('theme-toggle')?.addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme')
  applyTheme(cur === 'dark' ? 'light' : 'dark')
})

// ─── Duck progress bar ───────────────────────────────────────
const _DUCK_MESSAGES = [
  '正在聆听声纹…',
  '鸭鸭努力工作中…',
  '鸭鸭竖起了耳朵…',
  '鸭鸭在分析音高特征…',
  '鸭鸭在计算共振峰…',
  '鸭鸭快好了…',
]
let _duckRaf = null
let _duckMsgTimer = null

function _startDuck() {
  const bar   = $('duck-progress')
  const fill  = $('duck-fill')
  const emoji = $('duck-emoji')
  const label = $('duck-label')
  if (!bar) return

  bar.hidden = false
  fill.style.transition = ''
  fill.style.width  = '0%'
  emoji.style.left  = '3%'

  const start = Date.now()
  const MAX_PCT = 88
  const DURATION_MS = 100_000   // reach ~88% in ~100s

  function tick() {
    const elapsed = Date.now() - start
    const pct = Math.min(MAX_PCT, Math.sqrt(elapsed / DURATION_MS) * MAX_PCT)
    fill.style.width = pct + '%'
    emoji.style.left = Math.max(3, Math.min(97, pct)) + '%'
    _duckRaf = requestAnimationFrame(tick)
  }
  _duckRaf = requestAnimationFrame(tick)

  // Rotate messages
  let msgIdx = 0
  label.textContent = _DUCK_MESSAGES[0]
  _duckMsgTimer = setInterval(() => {
    msgIdx = (msgIdx + 1) % _DUCK_MESSAGES.length
    label.textContent = _DUCK_MESSAGES[msgIdx]
  }, 4000)
}

function _stopDuck(success = true) {
  cancelAnimationFrame(_duckRaf)
  clearInterval(_duckMsgTimer)
  _duckRaf = null

  const bar   = $('duck-progress')
  const fill  = $('duck-fill')
  const emoji = $('duck-emoji')
  const label = $('duck-label')
  if (!fill) return

  if (success) {
    fill.style.transition  = 'width 0.4s ease'
    emoji.style.transition = 'left 0.4s ease'
    fill.style.width  = '100%'
    emoji.style.left  = '97%'
    if (label) label.textContent = '分析完成 🎉'
    setTimeout(() => {
      if (bar) bar.hidden = true
      fill.style.transition  = ''
      emoji.style.transition = ''
      fill.style.width  = '0%'
      emoji.style.left  = '3%'
    }, 800)
  } else {
    if (bar) bar.hidden = true
    fill.style.width  = '0%'
    emoji.style.left  = '3%'
  }
}

// ─── Phase transitions ────────────────────────────────────────
function setPhase(next) {
  phase = next

  $('upload-section').hidden  = (next !== 'idle')
  $('player-section').hidden  = (next === 'idle')

  // Hide waveform skeleton whenever we're not in 'loaded' phase (skeleton is shown by onFileSelected)
  if (next !== 'loaded') {
    const wl = $('waveform-loading')
    if (wl) wl.style.display = 'none'
  }

  const analyzing = next === 'analyzing'
  const done      = next === 'results'
  if ($('analyze-text'))    $('analyze-text').textContent    = analyzing ? '分析中…' : done ? '已分析' : '开始分析'
  if ($('analyze-spinner')) $('analyze-spinner').hidden      = !analyzing
  if ($('analyze-btn')) {
    $('analyze-btn').disabled = analyzing || done
    const icon = $('analyze-btn').querySelector('svg')
    if (icon) icon.style.display = analyzing ? 'none' : ''
  }

  if (next === 'analyzing') _startDuck()
  else if (next === 'results') _stopDuck(true)
  else if (!_batchInProgress) _stopDuck(false)
}

// ─── File loaded ──────────────────────────────────────────────
function onFileSelected(file) {
  cancelAnalysis()
  currentFile  = file
  analysisData = null
  resetResults()
  clearMetricsPanel()

  $('file-name').textContent = file.name

  setPhase('loaded')
  $('waveform-loading').style.display = 'flex'

  initWaveform(file, {
    onReady: (_dur) => { /* controls already enabled in waveform.js */ },
    onTimeUpdate: (t) => {
      if (analysisData) highlightActiveSegment(t, analysisData.analysis)
    },
  })
}

// ─── Batch analyze (multiple files, no waveform preview) ─────
async function _silentAnalyzeAndSave(file) {
  try {
    const data = await analyzeAudio(file)
    if (data.summary?.overall_f0_median_hz != null) {
      const session = {
        id:           Date.now().toString() + Math.random().toString(36).slice(2, 8),
        filename:     data.filename,
        f0_median:    data.summary.overall_f0_median_hz,
        gender_score: data.summary.overall_gender_score,
        confidence:   data.summary.overall_confidence,
        label:        data.summary.dominant_label,
        color:        nextSessionColor(),
        summary:      data.summary,
        analysis:     data.analysis,
      }
      saveSession(session)
      addSession(session)
    }
    return data
  } catch (err) {
    if (err.name !== 'AbortError') showToast(`${file.name} 失败：${err.message}`, 'error')
    return null
  }
}

async function onMultipleFilesSelected(files) {
  _batchInProgress = true
  onFileSelected(files[0])   // 加载第一个文件的波形，setPhase('loaded') 但不会停鸭鸭

  // 手动触发处理中状态
  if ($('analyze-text'))    $('analyze-text').textContent = '处理中…'
  if ($('analyze-spinner')) $('analyze-spinner').hidden   = false
  if ($('analyze-btn')) {
    $('analyze-btn').disabled = true
    const icon = $('analyze-btn').querySelector('svg')
    if (icon) icon.style.display = 'none'
  }
  _startDuck()

  const results = await Promise.allSettled(files.map(f => _silentAnalyzeAndSave(f)))
  const ok = results.filter(r => r.status === 'fulfilled' && r.value).length

  _batchInProgress = false
  _stopDuck(ok > 0)

  // 恢复按钮到 loaded 状态（第一个文件仍可单独分析）
  if ($('analyze-text'))    $('analyze-text').textContent = '开始分析'
  if ($('analyze-spinner')) $('analyze-spinner').hidden   = true
  if ($('analyze-btn')) {
    $('analyze-btn').disabled = false
    const icon = $('analyze-btn').querySelector('svg')
    if (icon) icon.style.display = ''
  }

  showToast(`批量分析完成：${ok} / ${files.length} 个成功`)
}

// ─── Uploaders ────────────────────────────────────────────────
async function initUploaders() {
  let allowConcurrent = false
  try {
    const cfg = await fetch('/api/config').then(r => r.json())
    allowConcurrent = cfg.allow_concurrent ?? false
  } catch (_) {}

  const maxBytes = allowConcurrent ? undefined : RESTRICTED_MAX_BYTES

  // 更新上传区提示文字
  const hint = document.querySelector('.upload-hint')
  if (hint) {
    const sizeLabel = allowConcurrent ? '200 MB' : '1 MB'
    hint.textContent = `支持 MP3 · WAV · OGG · M4A · FLAC · 最大 ${sizeLabel}`
  }

  setupUploader({
    onFile:   onFileSelected,
    onFiles:  allowConcurrent ? onMultipleFilesSelected : null,
    onError:  msg => showToast(msg, 'error'),
    multiple: allowConcurrent,
    maxBytes,
  })

  // Scatter panel upload button (always available, single file only)
  $('scatter-file-input')?.addEventListener('change', e => {
    const file = e.target.files?.[0]
    if (!file) { e.target.value = ''; return }
    const err = validateFile(file, maxBytes)
    if (err) { showToast(err, 'error'); e.target.value = ''; return }
    onFileSelected(file)
    e.target.value = ''
  })
}

initUploaders()

// Change file button in player
$('change-file-btn')?.addEventListener('click', () => {
  cancelAnalysis()
  destroyWaveform()
  resetResults()
  clearMetricsPanel()
  currentFile  = null
  analysisData = null
  setPhase('idle')
})

// ─── Play / Pause ─────────────────────────────────────────────
$('play-btn')?.addEventListener('click', togglePlay)

// ─── Analyze ──────────────────────────────────────────────────
$('analyze-btn')?.addEventListener('click', async () => {
  if (!currentFile || phase === 'analyzing') return

  setPhase('analyzing')
  resetResults()
  clearMetricsPanel()

  try {
    const data = await analyzeAudio(currentFile)
    analysisData = data

    // Draw timeline overlay on waveform
    drawTimeline(data.analysis)

    // Render stats + segment list
    renderStats(data.analysis)
    renderSegments(data.analysis)

    setPhase('results')

    // ── Save session & update scatter plot ─────────────────
    if (data.summary.overall_f0_median_hz != null)
    {
      const session = {
        id:           Date.now().toString(),
        filename:     data.filename,
        f0_median:    data.summary.overall_f0_median_hz,
        gender_score: data.summary.overall_gender_score,
        confidence:   data.summary.overall_confidence,
        label:        data.summary.dominant_label,
        color:        nextSessionColor(),
        summary:      data.summary,
        analysis:     data.analysis,
      }
      saveSession(session)
      addSession(session)
      selectSession(session.id)
    }

  } catch (err) {
    if (err.name === 'AbortError') {
      if (phase === 'analyzing') setPhase('loaded')
      return
    }
    showToast(`分析失败：${err.message}`, 'error')
    setPhase('loaded')
  }
})

// ─── Segment select → metrics panel ──────────────────────────
document.addEventListener('segment-select', e => {
  renderMetricsPanel(e.detail.segment)
})

// ─── Scatter dot click → restore session ────────────────────
let _selectedSessionId = null

function onScatterDotClick(session) {
  _selectedSessionId = session.id
  $('delete-session-btn').hidden = false
  analysisData = session   // use stored data

  // Restore segment timeline (no waveform audio — show static state)
  drawTimeline(session.analysis)
  renderStats(session.analysis)
  renderSegments(session.analysis)

  // Show player section in "static" mode (no audio loaded)
  if ($('file-name'))      $('file-name').textContent  = session.filename
  if ($('player-section')) $('player-section').hidden  = false
  if ($('upload-section')) $('upload-section').hidden  = true

  clearMetricsPanel()
}

function onScatterDeselect() {
  _selectedSessionId = null
  $('delete-session-btn').hidden = true
}

// ─── Delete single session ────────────────────────────────────
$('delete-session-btn')?.addEventListener('click', () => {
  if (!_selectedSessionId) return
  storeRemoveSession(_selectedSessionId)
  scatterRemoveSession(_selectedSessionId)
  _selectedSessionId = null
  $('delete-session-btn').hidden = true
})

// ─── Clear sessions ───────────────────────────────────────────
$('clear-sessions-btn')?.addEventListener('click', () => {
  if (!confirm('清空所有历史分析记录？')) return
  clearSessions()
  clearAllSessions()
  _selectedSessionId = null
  analysisData = null
  $('delete-session-btn').hidden = true
  resetResults()
  clearMetricsPanel()
  if (phase === 'results') setPhase(currentFile ? 'loaded' : 'idle')
})

// ─── Init scatter with stored sessions ───────────────────────
function initScatterFromStorage() {
  initScatter($('scatter-canvas'), {
    onDotClick: onScatterDotClick,
    onDeselect: onScatterDeselect,
  })
  const stored = loadSessions()
  if (stored.length) loadAllSessions(stored)
}

// ─── Boot ─────────────────────────────────────────────────────
initTheme()
setPhase('idle')
initScatterFromStorage()
