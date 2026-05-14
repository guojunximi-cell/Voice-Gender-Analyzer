import { fmt } from "../utils.js";
import { getMode } from "./classify-mode.js";
import { setBlockHasContent } from "./dashboard.js";

// ─── Animated counter ────────────────────────────────────────
function animateCounter(el, target, suffix = "%", duration = 700) {
	if (!el) return;
	const start = performance.now();
	function tick(now) {
		const p = Math.min((now - start) / duration, 1);
		const ease = 1 - Math.pow(1 - p, 3);
		el.textContent = Math.round(target * ease) + suffix;
		if (p < 1) requestAnimationFrame(tick);
	}
	requestAnimationFrame(tick);
}

// ─── Compute stats from analysis array ───────────────────────
function computeStats(analysis) {
	const totals = {};
	for (const seg of analysis) {
		const d = seg.end_time - seg.start_time;
		totals[seg.label] = (totals[seg.label] || 0) + d;
	}
	return { totals };
}

// ─── Stats cards ─────────────────────────────────────────────
// Engine A (NN) emits male/female only — neutral row stays hidden.
// Pitch / Resonance modes split into three zones (see zones.js).
export function renderStats(analysis) {
	const { totals } = computeStats(analysis);
	const maleDur = totals["male"] || 0;
	const neutralDur = totals["neutral"] || 0;
	const femaleDur = totals["female"] || 0;

	const showNeutral = getMode() !== "engineA";
	const total = maleDur + femaleDur + (showNeutral ? neutralDur : 0);
	const pct = (d) => (total ? Math.round((d / total) * 100) : 0);
	const malePct = pct(maleDur);
	const neutralPct = showNeutral ? pct(neutralDur) : 0;
	// Force the visible rows to sum to 100 so rounding doesn't leave us at 99.
	const femalePct = total ? 100 - malePct - neutralPct : 0;

	animateCounter(document.getElementById("male-pct"), malePct);
	animateCounter(document.getElementById("female-pct"), femalePct);

	const setDur = (id, sec) => {
		const el = document.getElementById(id);
		if (el) el.textContent = fmt(sec);
	};
	setDur("male-duration", maleDur);
	setDur("female-duration", femaleDur);

	const neutralRow = document.querySelector(".stat-neutral");
	if (neutralRow) neutralRow.hidden = !showNeutral;
	if (showNeutral) {
		animateCounter(document.getElementById("neutral-pct"), neutralPct);
		setDur("neutral-duration", neutralDur);
	}

	requestAnimationFrame(() => {
		const setBar = (id, p) => {
			const el = document.getElementById(id);
			if (el) el.style.width = `${Math.max(0, p)}%`;
		};
		setBar("male-bar", malePct);
		setBar("female-bar", femalePct);
		if (showNeutral) setBar("neutral-bar", neutralPct);
	});

	// Mark dominant voice type — among visible rows.
	const winner = total
		? [["male", maleDur], ["female", femaleDur], ...(showNeutral ? [["neutral", neutralDur]] : [])].reduce((b, p) =>
				p[1] > b[1] ? p : b,
			)[0]
		: null;
	document.querySelector(".stat-male")?.classList.toggle("dominant", winner === "male");
	document.querySelector(".stat-female")?.classList.toggle("dominant", winner === "female");
	if (neutralRow) neutralRow.classList.toggle("dominant", winner === "neutral");

	const section = document.getElementById("stats-section");
	if (section) section.hidden = false;
	setBlockHasContent("stats", true);
}

// ─── Reset ────────────────────────────────────────────────────
export function resetResults() {
	const statsSection = document.getElementById("stats-section");
	if (statsSection) statsSection.hidden = true;
	setBlockHasContent("stats", false);

	const ids = ["male-pct", "female-pct", "male-duration", "female-duration", "neutral-pct", "neutral-duration"];
	ids.forEach((id) => {
		const el = document.getElementById(id);
		if (el) el.textContent = "—";
	});

	["male-bar", "female-bar", "neutral-bar"].forEach((id) => {
		const el = document.getElementById(id);
		if (el) el.style.width = "0%";
	});
}
