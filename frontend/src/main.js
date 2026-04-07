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
         clearMetricsPanel,
         renderConfidenceDistribution }      from './modules/metrics-panel.js'
import { initScatter, addSession,
         loadAllSessions, selectSession,
         clearAllSessions, removeSession as scatterRemoveSession,
         redraw as scatterRedraw }           from './modules/scatter.js'
import { loadSessions, saveSession,
         clearSessions, removeSession as storeRemoveSession } from './modules/session-store.js'
import { nextSessionColor }                  from './utils.js'
import { setupRecorder }                      from './modules/recorder.js'

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
// Fake animation messages (batch mode only)
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
let _engineAInterp = null

// ── Real progress: set duck bar to exact percentage ──────────
function _setDuckProgress(pct, msg) {
  const bar   = $('duck-progress')
  const fill  = $('duck-fill')
  const emoji = $('duck-emoji')
  const label = $('duck-label')
  if (!fill) return

  bar.hidden = false
  fill.style.width = pct + '%'
  emoji.style.left = Math.max(3, Math.min(97, pct)) + '%'
  if (msg && label) label.textContent = msg
}

// ── Engine A interpolation (slow visual hint while Engine A blocks) ──
function _startEngineAInterp() {
  _stopEngineAInterp()
  const start = Date.now()
  const FROM = 10, TO = 45
  const DURATION_MS = 90_000

  function tick() {
    const elapsed = Date.now() - start
    const t = Math.min(1, Math.sqrt(elapsed / DURATION_MS))
    const pct = FROM + t * (TO - FROM)
    _setDuckProgress(pct, null)
    _engineAInterp = requestAnimationFrame(tick)
  }
  _engineAInterp = requestAnimationFrame(tick)
}

function _stopEngineAInterp() {
  if (_engineAInterp) {
    cancelAnimationFrame(_engineAInterp)
    _engineAInterp = null
  }
}

// ── Finish duck: snap to 100% then hide ─────────────────────
function _finishDuck() {
  _stopEngineAInterp()
  const bar   = $('duck-progress')
  const fill  = $('duck-fill')
  const emoji = $('duck-emoji')
  const label = $('duck-label')
  if (!fill) return

  fill.style.width  = '100%'
  emoji.style.left  = '97%'
  if (label) label.textContent = '分析完成 🎉'
  setTimeout(() => {
    if (bar) bar.hidden = true
    fill.style.width  = '0%'
    emoji.style.left  = '3%'
  }, 800)
}

// ── Hide duck immediately (error / cancel) ──────────────────
function _hideDuck() {
  _stopEngineAInterp()
  const bar  = $('duck-progress')
  const fill = $('duck-fill')
  const emoji = $('duck-emoji')
  if (!fill) return
  if (bar) bar.hidden = true
  fill.style.width = '0%'
  emoji.style.left = '3%'
}

// ── Fake animation (batch mode only) ────────────────────────
function _startDuckFake() {
  const bar   = $('duck-progress')
  const fill  = $('duck-fill')
  const emoji = $('duck-emoji')
  const label = $('duck-label')
  if (!bar) return

  bar.hidden = false
  fill.style.width  = '0%'
  emoji.style.left  = '3%'

  const start = Date.now()
  const MAX_PCT = 88
  const DURATION_MS = 100_000

  function tick() {
    const elapsed = Date.now() - start
    const pct = Math.min(MAX_PCT, Math.sqrt(elapsed / DURATION_MS) * MAX_PCT)
    fill.style.width = pct + '%'
    emoji.style.left = Math.max(3, Math.min(97, pct)) + '%'
    _duckRaf = requestAnimationFrame(tick)
  }
  _duckRaf = requestAnimationFrame(tick)

  let msgIdx = 0
  label.textContent = _DUCK_MESSAGES[0]
  _duckMsgTimer = setInterval(() => {
    msgIdx = (msgIdx + 1) % _DUCK_MESSAGES.length
    label.textContent = _DUCK_MESSAGES[msgIdx]
  }, 4000)
}

function _stopDuckFake(success = true) {
  cancelAnimationFrame(_duckRaf)
  clearInterval(_duckMsgTimer)
  _duckRaf = null

  if (success) {
    _finishDuck()
  } else {
    _hideDuck()
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

  if (next === 'analyzing') _setDuckProgress(0, '准备中…')
  else if (next === 'results') _finishDuck()
  else if (!_batchInProgress) _hideDuck()
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
  _startDuckFake()

  // 分批发送请求（每次最多 2 个），避免同时发出所有请求导致服务器 503
  const BATCH_SIZE = 2
  let ok = 0
  for (let i = 0; i < files.length; i += BATCH_SIZE) {
    const batch = files.slice(i, i + BATCH_SIZE)
    const results = await Promise.allSettled(batch.map(f => _silentAnalyzeAndSave(f)))
    ok += results.filter(r => r.status === 'fulfilled' && r.value).length
  }

  _batchInProgress = false
  _stopDuckFake(ok > 0)

  // 批量完成后标记为 results 状态，防止用户重复分析第一个文件
  setPhase('results')

  showToast(`批量分析完成：${ok} / ${files.length} 个成功`)
}

// ─── Uploaders ────────────────────────────────────────────────
async function initUploaders() {
  let allowConcurrent = false
  let maxFileSizeMb = 5
  let maxDurationSec = 180
  try {
    const cfg = await fetch('/api/config').then(r => r.json())
    allowConcurrent = cfg.allow_concurrent ?? (cfg.max_concurrent > 1)
    maxFileSizeMb = cfg.max_file_size_mb ?? 5
    maxDurationSec = cfg.max_audio_duration_sec ?? 180
  } catch (_) {}

  const maxBytes = maxFileSizeMb * 1024 * 1024

  // 更新上传区提示文字
  const hint = document.querySelector('.upload-hint')
  if (hint) {
    hint.textContent = `支持 MP3 · WAV · OGG · M4A · FLAC · 最大 ${maxFileSizeMb} MB / ${Math.floor(maxDurationSec / 60)} 分钟`
  }

  setupUploader({
    onFile:   onFileSelected,
    onFiles:  allowConcurrent ? onMultipleFilesSelected : null,
    onError:  msg => showToast(msg, 'error'),
    multiple: allowConcurrent,
    maxBytes,
  })

  setupRecorder({
    onFile:  onFileSelected,
    onError: msg => showToast(msg, 'error'),
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
    const data = await analyzeAudio(currentFile, {
      onProgress(pct, msg) {
        if (pct > 10) _stopEngineAInterp()

        if (pct === 10) {
          _setDuckProgress(10, msg)
          _startEngineAInterp()
        } else {
          _setDuckProgress(pct, msg)
        }
      },
    })
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
  renderConfidenceDistribution(e.detail.segment)
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

// ─── Mobile: collapsible left panel ──────────────────────────
;(function initMobilePanel() {
  const mq = matchMedia('(max-width: 780px)')
  const leftPanel = document.querySelector('.panel-left')
  const leftHeader = leftPanel?.querySelector('.panel-header')
  if (!leftPanel || !leftHeader) return

  // Start expanded on mobile so the chart is visible by default
  if (mq.matches) leftPanel.classList.add('panel-expanded')

  leftHeader.addEventListener('click', () => {
    if (!mq.matches) return
    leftPanel.classList.toggle('panel-expanded')
  })

  // Reset on resize to desktop; expand when entering mobile
  mq.addEventListener('change', e => {
    if (!e.matches) leftPanel.classList.remove('panel-expanded')
    else leftPanel.classList.add('panel-expanded')
  })
})()

// ─── Mobile: tabs for segments / metrics ─────────────────────
;(function initMobileTabs() {
  const mq = matchMedia('(max-width: 780px)')
  const tabBar = $('mobile-tabs')
  const segSection = $('segments-section')
  const rightPanel = document.querySelector('.panel-right')
  if (!tabBar || !rightPanel) return

  const tabs = tabBar.querySelectorAll('.mobile-tab')
  let activeTab = 'segments'

  function applyTab(tab) {
    activeTab = tab
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab))
    if (!mq.matches) {
      // Desktop: show everything
      segSection?.classList.remove('mobile-hidden')
      rightPanel.classList.remove('mobile-hidden')
      return
    }
    if (tab === 'segments') {
      segSection?.classList.remove('mobile-hidden')
      rightPanel.classList.add('mobile-hidden')
    } else {
      segSection?.classList.add('mobile-hidden')
      rightPanel.classList.remove('mobile-hidden')
    }
  }

  tabBar.addEventListener('click', e => {
    const btn = e.target.closest('.mobile-tab')
    if (!btn) return
    applyTab(btn.dataset.tab)
  })

  // Show tab bar when stats are visible (results phase)
  const observer = new MutationObserver(() => {
    const statsVisible = !$('stats-section')?.hidden
    tabBar.hidden = !statsVisible
    if (statsVisible && mq.matches) applyTab(activeTab)
  })
  const statsEl = $('stats-section')
  if (statsEl) observer.observe(statsEl, { attributes: true, attributeFilter: ['hidden'] })

  // Auto-switch to metrics when a segment is clicked on mobile
  document.addEventListener('segment-select', () => {
    if (mq.matches) {
      applyTab('metrics')
      rightPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  })

  // Reset on resize to desktop
  mq.addEventListener('change', e => {
    if (!e.matches) {
      segSection?.classList.remove('mobile-hidden')
      rightPanel.classList.remove('mobile-hidden')
    } else {
      applyTab(activeTab)
    }
  })
})()

// ─── Boot ─────────────────────────────────────────────────────
initTheme()
setPhase('idle')
initScatterFromStorage()
