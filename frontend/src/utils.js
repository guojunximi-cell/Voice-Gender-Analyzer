// ─── Time formatting ─────────────────────────────────────────
export function fmt(sec) {
  if (sec == null || isNaN(sec)) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ─── Sigmoid rescale (0–100 → 0–100, stretches middle) ───────
// Used to convert raw gender_score to display X-axis position on scatter plot.
// Score of 50 maps to 50; extremes are compressed; middle region stretched.
export function sigmaRescale(x) {
  const t = (x / 100 - 0.5) * 5.5
  return (1 / (1 + Math.exp(-t))) * 100
}

// ─── Session color palette ────────────────────────────────────
const PALETTE = [
  '#5b8def', '#e07aaa', '#d4b86a', '#7ec8a4',
  '#c98ef0', '#ef8f5b', '#5bbfef', '#ef5b88',
]
let _colorIdx = 0
export function nextSessionColor() {
  return PALETTE[_colorIdx++ % PALETTE.length]
}

// ─── Label meta ──────────────────────────────────────────────
export const LABEL_META = {
  male:     { zh: '男声', cssVar: 'var(--male)'    },
  female:   { zh: '女声', cssVar: 'var(--female)'  },
  music:    { zh: '音乐', cssVar: 'var(--music)'   },
  noise:    { zh: '噪音', cssVar: 'var(--noise)'   },
  noEnergy: { zh: '静音', cssVar: 'var(--noenergy)'},
}

// ─── Resolve CSS custom property to hex/rgb string ───────────
export function resolveCSSVar(varName) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(varName.replace('var(', '').replace(')', '').trim())
    .trim()
}
