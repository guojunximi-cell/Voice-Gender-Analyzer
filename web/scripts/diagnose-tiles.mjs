#!/usr/bin/env node
/**
 * diagnose-tiles.mjs — Headless DOM inspection for stats-section tiles.
 *
 * Usage: node web/scripts/diagnose-tiles.mjs
 * Requires: Vite dev server on :5174 + backend on :8080 + all 3 Docker containers.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_10s.wav";
const URL = "http://localhost:5174/";
const SCREENSHOT = "/tmp/vga-tiles-diag.png";

const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

page.on("console", (msg) => {
	if (msg.type() === "error") console.error("[page err]", msg.text());
});

console.error("→ navigate");
await page.goto(URL, { waitUntil: "domcontentloaded" });

console.error("→ upload audio");
// File input may be hidden behind a drop zone — set files directly on the input.
const fileInput = page.locator('input[type="file"]').first();
await fileInput.setInputFiles({
	name: "zh_10s.wav",
	mimeType: "audio/wav",
	buffer: audio,
});

console.error("→ wait for analyze button enable + click");
await page.waitForSelector("#analyze-btn:not([disabled])", { timeout: 15000 });
await page.click("#analyze-btn");

console.error("→ wait for analysis complete (stats visible)");
await page.waitForSelector("#stats-section:not([hidden])", { timeout: 120000 });

// Engine C needs extra time (FunASR + MFA + Praat). Wait for real rects
// in the heatmap (exclude the <defs><pattern> template rect).
await page.waitForFunction(
	() => document.querySelectorAll(".vga-heatmap > rect").length > 0,
	{ timeout: 60000 },
);
await page.waitForTimeout(2000);

console.error("→ run diagnostic");
const diag = await page.evaluate(() => {
	const stats = document.querySelector("#stats-section");
	const timeline = document.querySelector("#phone-timeline-root");
	const panel = document.querySelector(".panel-center");
	if (!stats || !panel) return { error: "elements not found" };

	const rect = stats.getBoundingClientRect();
	const trect = timeline.getBoundingClientRect();
	const prect = panel.getBoundingClientRect();

	// Midpoint of the tiles area (relative to panel scroll, not viewport)
	const midX = rect.left + rect.width / 2;
	const midY = rect.top + rect.height / 2;
	const topAt = document.elementFromPoint(midX, midY);
	const elementsAt = document.elementsFromPoint(midX, midY).slice(0, 8);

	return {
		viewport: { w: innerWidth, h: innerHeight },
		stats: {
			hidden_attr: stats.hidden,
			display: getComputedStyle(stats).display,
			rect: { top: rect.top, bottom: rect.bottom, height: rect.height, width: rect.width },
			in_viewport: rect.bottom > 0 && rect.top < innerHeight,
			in_panel: rect.bottom > prect.top && rect.top < prect.bottom,
		},
		timeline: {
			rect: { top: trect.top, bottom: trect.bottom, height: trect.height },
		},
		panel: {
			rect: { top: prect.top, bottom: prect.bottom, height: prect.height },
			scrollTop: panel.scrollTop,
			scrollHeight: panel.scrollHeight,
			clientHeight: panel.clientHeight,
			overflow_y: getComputedStyle(panel).overflowY,
			can_scroll_down: panel.scrollHeight - panel.scrollTop - panel.clientHeight,
		},
		stacking_at_tile_midpoint:
			rect.top < innerHeight && rect.bottom > 0
				? {
						element_at_point:
							topAt?.tagName + "." + (topAt?.className || "(no-class)"),
						top_8: elementsAt.map(
							(el) => el.tagName + "." + (el.className || "(no-class)"),
						),
					}
				: "tiles-off-screen",
	};
});

console.log(JSON.stringify(diag, null, 2));

console.error("→ screenshot → " + SCREENSHOT);
await page.screenshot({ path: SCREENSHOT, fullPage: true });

// Second screenshot: scroll panel-center to bottom to see if tiles render there
await page.evaluate(() => {
	const panel = document.querySelector(".panel-center");
	if (panel) panel.scrollTop = panel.scrollHeight;
});
await page.waitForTimeout(500);
await page.screenshot({ path: SCREENSHOT.replace(".png", "-scrolled.png"), fullPage: true });

await browser.close();
console.error("done");
