const KEY = 'voicescope_sessions'
const MAX_SESSIONS = 20   // cap to avoid localStorage bloat

/** Load all sessions from localStorage. */
export function loadSessions() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || []
  } catch {
    return []
  }
}

/**
 * Save a new session.
 * session = { id, filename, f0_median, gender_score, color, summary, analysis }
 * Returns the updated sessions array.
 */
export function saveSession(session) {
  const sessions = loadSessions()
  sessions.push(session)

  // Keep only the most recent MAX_SESSIONS entries
  const trimmed = sessions.slice(-MAX_SESSIONS)
  try {
    localStorage.setItem(KEY, JSON.stringify(trimmed))
  } catch (e) {
    // Storage quota exceeded — drop the oldest and retry
    trimmed.shift()
    try { localStorage.setItem(KEY, JSON.stringify(trimmed)) } catch (_) {}
  }
  return trimmed
}

/** Remove all sessions. */
export function clearSessions() {
  localStorage.removeItem(KEY)
}

/** Remove a single session by id. */
export function removeSession(id) {
  const sessions = loadSessions().filter(s => s.id !== id)
  localStorage.setItem(KEY, JSON.stringify(sessions))
  return sessions
}
