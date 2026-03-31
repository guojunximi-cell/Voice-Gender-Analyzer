// POST /api/analyze-voice
// FormData field: "files" (one or more)
// Response: { status, filename, summary, analysis: [{label, start_time, end_time, duration}] }

const _controllers = new Set()

const TIMEOUT_MS = 120_000  // 2 minutes

export async function analyzeAudio(file) {
  const controller = new AbortController()
  _controllers.add(controller)
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS)

  const formData = new FormData()
  formData.append('files', file)

  try {
    const response = await fetch('/api/analyze-voice', {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })

    clearTimeout(timeoutId)

    if (!response.ok) {
      let msg = `请求失败 (${response.status})`
      try {
        const err = await response.json()
        msg = err.detail || err.message || msg
      } catch (_) {}
      throw new Error(msg)
    }

    const data = await response.json()

    if (data.status === 'error') {
      throw new Error(data.message || '后端分析出错')
    }

    return data
  } catch (err) {
    clearTimeout(timeoutId)
    throw err
  } finally {
    _controllers.delete(controller)
  }
}

export function cancelAnalysis() {
  for (const c of _controllers) c.abort()
  _controllers.clear()
}
