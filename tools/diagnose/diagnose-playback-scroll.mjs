#!/usr/bin/env node
/**
 * diagnose-playback-scroll.mjs — Verify no auto-scroll during playback.
 *
 * Loads a 30s Chinese recording, runs analysis, plays the first ~10s,
 * and continuously samples .panel-center.scrollTop.
 *
 * Pass: min === max === scrollAtLoad (no scroll event during playback).
 * Fail: report the timestamp and trigger where scrollTop changed.
 *
 * Requires: Vite dev server on :5174, backend on :8080, 3 containers up.
 * Run with LD_LIBRARY_PATH pointed at ~/chrome-deps/extracted/usr/lib/...
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const URL = "http://localhost:5174/";
const PLAY_DURATION_MS = 10_000;
const SAMPLE_INTERVAL_MS = 100;

const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

page.on("console", (msg) => {
	if (msg.type() === "error") console.error("[page err]", msg.text());
});

console.error("→ navigate");
await page.goto(URL, { waitUntil: "domcontentloaded" });

console.error("→ upload audio (zh_30s.wav)");
await page.locator('input[type="file"]').first().setInputFiles({
	name: "zh_30s.wav",
	mimeType: "audio/wav",
	buffer: audio,
});

console.error("→ click analyze");
await page.waitForSelector("#analyze-btn:not([disabled])", { timeout: 15000 });
await page.click("#analyze-btn");

console.error("→ wait for stats + heatmap");
await page.waitForSelector("#stats-section:not([hidden])", { timeout: 180000 });
await page.waitForFunction(
	() => document.querySelectorAll(".vga-heatmap > rect").length > 0,
	{ timeout: 60000 },
);
await page.waitForTimeout(1000);

console.error("→ snapshot initial scrollTop + sentence info");
const baseline = await page.evaluate(() => {
	const panel = document.querySelector(".panel-center");
	const monitor = window._scrollMonitor;
	const totalSentences = document.querySelector(".vga-sentence-nav__counter")?.textContent;
	return {
		target: monitor?.target,
		scrollAtLoad: monitor?.scrollAtLoad,
		currentScrollTop: panel?.scrollTop,
		clientHeight: panel?.clientHeight,
		scrollHeight: panel?.scrollHeight,
		canScrollDown: panel ? panel.scrollHeight - panel.scrollTop - panel.clientHeight : null,
		sentenceCounter: totalSentences,
	};
});
console.error("   baseline:", JSON.stringify(baseline));

console.error("→ click play");
await page.click("#play-btn");

console.error(`→ sample scrollTop every ${SAMPLE_INTERVAL_MS}ms for ${PLAY_DURATION_MS}ms`);
// Instrument page: capture (time, scrollTop, currentSentenceCounter) at each sample
await page.evaluate(() => {
	window.__scrollSamples = [];
	window.__scrollStart = performance.now();
	const panel = document.querySelector(".panel-center");
	window.__scrollSampler = setInterval(() => {
		const counter = document.querySelector(".vga-sentence-nav__counter")?.textContent;
		const time = Math.round(performance.now() - window.__scrollStart);
		window.__scrollSamples.push({ t: time, top: panel.scrollTop, sent: counter });
	}, 100);
});

await page.waitForTimeout(PLAY_DURATION_MS);

console.error("→ stop sampling + harvest");
const samples = await page.evaluate(() => {
	clearInterval(window.__scrollSampler);
	return window.__scrollSamples;
});

// Pause playback for cleanliness
await page.click("#play-btn").catch(() => {});

console.error(`→ got ${samples.length} samples`);
const tops = samples.map((s) => s.top);
const min = Math.min(...tops);
const max = Math.max(...tops);
const base = baseline.scrollAtLoad ?? baseline.currentScrollTop ?? 0;

console.log("");
console.log("=== Playback scroll verification ===");
console.log(`Audio: zh_30s.wav, played first ${PLAY_DURATION_MS / 1000}s`);
console.log(`Target: ${baseline.target}`);
console.log(`Baseline scrollTop: ${base}`);
console.log(`Samples: ${samples.length}`);
console.log(`Observed scrollTop: min=${min}, max=${max}`);

// Sentence transitions observed during sampling
const sentenceTransitions = [];
let lastSent = samples[0]?.sent;
for (const s of samples) {
	if (s.sent !== lastSent) {
		sentenceTransitions.push({ t_ms: s.t, from: lastSent, to: s.sent, scrollTop: s.top });
		lastSent = s.sent;
	}
}
console.log(`Sentence transitions during playback: ${sentenceTransitions.length}`);
for (const t of sentenceTransitions) {
	console.log(
		`   t=${t.t_ms}ms  sentence ${t.from} → ${t.to}  (scrollTop=${t.scrollTop})`,
	);
}

console.log("");
const pass = min === base && max === base;
if (pass) {
	console.log("PASS ✓  scrollTop never changed during playback");
} else {
	console.log("FAIL ✗  scrollTop changed during playback");
	// Find first deviation
	const firstDev = samples.find((s) => s.top !== base);
	if (firstDev) {
		console.log(
			`  first deviation at t=${firstDev.t}ms: scrollTop ${base} → ${firstDev.top}, sentence=${firstDev.sent}`,
		);
	}
}
console.log("");

await browser.close();
process.exit(pass ? 0 : 1);
