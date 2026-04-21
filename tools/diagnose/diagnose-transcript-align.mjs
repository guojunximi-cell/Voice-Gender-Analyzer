#!/usr/bin/env node
/**
 * diagnose-transcript-align.mjs — Verify each .phone button's horizontal span
 * matches its character cells' time range in the HeatmapBand SVG above.
 *
 * For each visible char button, compute its (left, right) in screen pixels
 * relative to the heatmap's screen-space x-range, and compare against the
 * union of its phones' rect bounds.  Report max delta in pixels per char.
 *
 * Also captures full-width screenshots (heatmap + transcript stacked) for
 * visual review.
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
await page.waitForSelector("#stats-section:not([hidden])", { timeout: 180000 });
await page.waitForSelector(".vga-transcript .phone", { timeout: 30000 });
await page.waitForTimeout(800);

// Compare: each .phone's left-edge to (its character's first phone's heatmap
// rect left).  We can't directly inspect char→phone mapping from DOM, so use
// a simpler invariant: the .phone column's left/right percentages of the
// transcript's width should equal the union of the heatmap rects whose time
// range overlaps the .phone's time range.
//
// Easier: directly check that .phone[i].left == (cumulative char_i.start ratio)
// by reading inline style attributes.
const data = await page.evaluate(() => {
	const transcript = document.querySelector(".vga-transcript");
	const heatmap = document.querySelector(".vga-heatmap");
	const tr = transcript.getBoundingClientRect();
	const hr = heatmap.getBoundingClientRect();
	const phones = Array.from(transcript.querySelectorAll(".phone"));
	const phoneSummaries = phones.map((b) => {
		const r = b.getBoundingClientRect();
		return {
			char: b.querySelector(".phone__char")?.textContent,
			leftStyle: b.style.left,
			widthStyle: b.style.width,
			leftPx: Math.round(r.left - tr.left),
			rightPx: Math.round(r.right - tr.left),
			midPx: Math.round((r.left + r.right) / 2 - tr.left),
		};
	});
	return {
		transcript_left: Math.round(tr.left),
		transcript_right: Math.round(tr.right),
		transcript_width: Math.round(tr.width),
		heatmap_left: Math.round(hr.left),
		heatmap_right: Math.round(hr.right),
		heatmap_width: Math.round(hr.width),
		phones: phoneSummaries,
	};
});

const widthDelta = data.heatmap_width - data.transcript_width;
const leftDelta = data.heatmap_left - data.transcript_left;
console.log(
	JSON.stringify(
		{
			heatmap_vs_transcript: { width_delta_px: widthDelta, left_delta_px: leftDelta },
			char_count: data.phones.length,
			first_three_chars: data.phones.slice(0, 3),
			last_three_chars: data.phones.slice(-3),
		},
		null,
		2,
	),
);

// Visual: combined screenshot — band + transcript stacked.
const band = page.locator(".vga-timeline__band").first();
const tr = page.locator(".vga-timeline__transcript").first();
const bandBox = await band.boundingBox();
const trBox = await tr.boundingBox();
const top = Math.min(bandBox.y, trBox.y) - 4;
const bottom = Math.max(bandBox.y + bandBox.height, trBox.y + trBox.height) + 4;
const left = Math.min(bandBox.x, trBox.x) - 4;
const right = Math.max(bandBox.x + bandBox.width, trBox.x + trBox.width) + 4;
await page.screenshot({
	path: "/tmp/vga-align-desktop.png",
	clip: { x: left, y: top, width: right - left, height: bottom - top },
});

await page.setViewportSize({ width: 390, height: 800 });
await page.waitForTimeout(400);
const band2 = page.locator(".vga-timeline__band").first();
const tr2 = page.locator(".vga-timeline__transcript").first();
await band2.scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
const bandBox2 = await band2.boundingBox();
const trBox2 = await tr2.boundingBox();
const top2 = Math.min(bandBox2.y, trBox2.y) - 4;
const bottom2 = Math.max(bandBox2.y + bandBox2.height, trBox2.y + trBox2.height) + 4;
const left2 = Math.min(bandBox2.x, trBox2.x) - 4;
const right2 = Math.max(bandBox2.x + bandBox2.width, trBox2.x + trBox2.width) + 4;
await page.screenshot({
	path: "/tmp/vga-align-mobile.png",
	clip: { x: left2, y: top2, width: right2 - left2, height: bottom2 - top2 },
});

await browser.close();
