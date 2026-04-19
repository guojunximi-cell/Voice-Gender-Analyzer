#!/usr/bin/env node
/**
 * diagnose-trend-click-seek.mjs — Verify clicking on the trend chart seeks
 * audio playback to the corresponding time, in both global and detail modes.
 *
 * Approach: read the seek-bar progress + current-time before/after a click
 * at a known x position in the chart's plot area, and confirm the time
 * jumped to roughly the value that x maps to in the chart's scale.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on("console", (m) => console.log(`[browser:${m.type()}]`, m.text()));

await page.goto("http://localhost:5174/", { waitUntil: "domcontentloaded" });
await page.locator('input[type="file"]').first().setInputFiles({
	name: "zh_30s.wav",
	mimeType: "audio/wav",
	buffer: audio,
});
await page.waitForSelector("#analyze-btn:not([disabled])", { timeout: 15000 });
await page.click("#analyze-btn");
await page.waitForSelector(".vga-trend-mode-toggle", { timeout: 180000 });
await page.waitForTimeout(800);

async function readTime() {
	return page.evaluate(() => document.getElementById("current-time")?.textContent);
}

async function clickAtFraction(fracX) {
	// Use Playwright's real mouse click so it triggers the same DOM events
	// as a user action — uPlot installs pointer listeners that may swallow
	// synthetic events.
	const box = await page.evaluate(() => {
		const over = document.querySelector(".vga-trend-wrap .u-over");
		if (!over) return null;
		const r = over.getBoundingClientRect();
		return { left: r.left, top: r.top, width: r.width, height: r.height };
	});
	if (!box) return null;
	const x = box.left + box.width * fracX;
	const y = box.top + box.height / 2;
	await page.mouse.click(x, y);
	return { clicked_at_x_frac: fracX, plot_width: box.width };
}

async function activeSentenceCounter() {
	return page.evaluate(() => document.querySelector(".vga-sentence-nav__counter")?.textContent);
}

const log = [];

// ── Global mode (default) ──────────────────────────────────────
log.push({ phase: "global, before any click", time: await readTime(), sentence: await activeSentenceCounter() });

// Click at 25% of plot width — global x-scale spans ~0..30s, so expect t ≈ 7.5s
await clickAtFraction(0.25);
await page.waitForTimeout(400);
log.push({ phase: "global, after click @25%", time: await readTime(), sentence: await activeSentenceCounter() });

// Click at 75% → expect t ≈ 22.5s
await clickAtFraction(0.75);
await page.waitForTimeout(400);
log.push({ phase: "global, after click @75%", time: await readTime(), sentence: await activeSentenceCounter() });

// ── Detail mode ────────────────────────────────────────────────
await page.click('.vga-trend-mode-btn[data-mode="detail"]');
await page.waitForTimeout(400);
log.push({ phase: "switched to detail", time: await readTime(), sentence: await activeSentenceCounter() });

// Click at 50% of plot width in detail mode — should land in the middle of
// the current sentence (whatever it is right now), so the sentence number
// stays the same and the time jumps within that sentence's range.
const sentenceBeforeDetailClick = await activeSentenceCounter();
const timeBeforeDetailClick = await readTime();
await clickAtFraction(0.5);
await page.waitForTimeout(400);
log.push({
	phase: "detail, after click @50% of current sentence",
	time: await readTime(),
	sentence: await activeSentenceCounter(),
	delta: { sentence_before: sentenceBeforeDetailClick, time_before: timeBeforeDetailClick },
});

console.log(JSON.stringify(log, null, 2));
await browser.close();
