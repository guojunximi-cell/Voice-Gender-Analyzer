#!/usr/bin/env node
/**
 * diagnose-trend-modes.mjs — Verify the trend chart's two-mode toggle:
 *   1. Default mode = global; toggle visible with "整体" active.
 *   2. Click "片段" → chart re-renders with sentence-scoped data; sentence
 *      band hidden; data point count drops to current sentence's char count.
 *   3. Navigate to next sentence (via transcript nav button) → detail chart
 *      re-renders with the new sentence's data.
 *   4. Switch back to "整体" → restores global view + sentence band visible.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on("console", (m) => m.type() === "error" && console.error("[err]", m.text()));

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

// Inspect uPlot's data array via window — we expose it temporarily.
async function snapshot(label) {
	return page.evaluate((label) => {
		const wrap = document.querySelector(".vga-trend-wrap");
		const band = document.querySelector(".vga-trend-sentence-band");
		const activeBtn = document.querySelector(".vga-trend-mode-btn.active");
		// uPlot stores the data on its instance; we don't have a direct ref, so
		// read from the rendered <table> we maintain (vga-sr-only).
		const rows = document.querySelectorAll(".vga-trend-wrap table tbody tr").length;
		const caption = document.querySelector(".vga-trend-wrap table caption")?.textContent;
		const counter = document.querySelector(".vga-sentence-nav__counter")?.textContent;
		return {
			label,
			active_mode: activeBtn?.dataset.mode,
			band_display: band ? getComputedStyle(band).display : null,
			data_point_count: rows,
			a11y_caption: caption,
			sentence_counter: counter,
		};
	}, label);
}

const snaps = [];
snaps.push(await snapshot("initial (default global)"));
await page.locator(".vga-trend-wrap").screenshot({ path: "/tmp/vga-trend-mode-global.png" });

// Switch to detail mode
await page.click('.vga-trend-mode-btn[data-mode="detail"]');
await page.waitForTimeout(400);
snaps.push(await snapshot("after switch to detail"));
await page.locator(".vga-trend-wrap").screenshot({ path: "/tmp/vga-trend-mode-detail-s1.png" });

// Navigate to next sentence (right arrow button) — detail chart should follow.
await page.click(".vga-sentence-nav__btn[aria-label='\u4e0b\u4e00\u53e5']");
await page.waitForTimeout(400);
snaps.push(await snapshot("detail mode, sentence 2"));
await page.locator(".vga-trend-wrap").screenshot({ path: "/tmp/vga-trend-mode-detail-s2.png" });

await page.click(".vga-sentence-nav__btn[aria-label='\u4e0b\u4e00\u53e5']");
await page.waitForTimeout(400);
snaps.push(await snapshot("detail mode, sentence 3"));

// Switch back to global
await page.click('.vga-trend-mode-btn[data-mode="global"]');
await page.waitForTimeout(400);
snaps.push(await snapshot("back to global"));
await page.locator(".vga-trend-wrap").screenshot({ path: "/tmp/vga-trend-mode-back-global.png" });

console.log(JSON.stringify(snaps, null, 2));
await browser.close();
