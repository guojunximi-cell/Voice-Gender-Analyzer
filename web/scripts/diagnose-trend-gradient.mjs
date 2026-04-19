#!/usr/bin/env node
/**
 * diagnose-trend-gradient.mjs — Verify the trend chart's two series render as
 * a vertical y-value gradient (top=pink, bottom=blue) instead of a flat color.
 *
 * Approach: load the app, run analysis, then inspect the chart canvas pixel-by-
 * pixel along each line.  Sample the rendered pixel at (x, y(line, x)) for a
 * handful of x positions and report the RGB.  If gradient is working, the line
 * colors should vary with the data value, not be a single hex.
 *
 * Also captures a screenshot of the chart for human review.
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
await page.waitForSelector(".vga-trend-wrap canvas", { timeout: 30000 });
await page.waitForTimeout(1500);

const result = await page.evaluate(() => {
	const wrap = document.querySelector(".vga-trend-wrap");
	const canvas = wrap.querySelector("canvas");
	const rect = canvas.getBoundingClientRect();

	// Pull RGB at a few interior y positions to confirm gradient varies.
	const ctx = canvas.getContext("2d");
	const cw = canvas.width;
	const ch = canvas.height;
	const dpr = window.devicePixelRatio || 1;

	// Sample a vertical strip near the middle x (where both lines pass through
	// somewhere).  Just dump several y bands to show the palette progresses.
	const xSample = Math.floor(cw * 0.5);
	const ySamples = [0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9].map((f) => Math.floor(ch * f));
	const verticalStrip = ySamples.map((y) => {
		const px = ctx.getImageData(xSample, y, 1, 1).data;
		return { y, rgb: `rgb(${px[0]},${px[1]},${px[2]})`, alpha: px[3] };
	});

	// Walk along the canvas at multiple x positions and find non-bg pixels in a
	// vertical band — pixels with non-zero saturation that aren't background grid.
	function sampleLineColor(xPx) {
		// scan top→bottom, return first colored pixel that's not pure white/grey
		for (let y = 5; y < ch - 5; y++) {
			const px = ctx.getImageData(xPx, y, 1, 1).data;
			const [r, g, b, a] = px;
			if (a < 200) continue;
			// Skip near-white (background) and near-grey (gridlines)
			const max = Math.max(r, g, b);
			const min = Math.min(r, g, b);
			if (max > 235 && min > 220) continue; // background
			if (max - min < 12) continue; // grey grid
			return { y, rgb: `rgb(${r},${g},${b})` };
		}
		return null;
	}

	const xPositions = [0.15, 0.3, 0.45, 0.6, 0.75, 0.9].map((f) => Math.floor(cw * f));
	const lineSamples = xPositions.map((x) => ({ xFrac: (x / cw).toFixed(2), top: sampleLineColor(x) }));

	return {
		canvas: { w: cw, h: ch, cssW: rect.width, cssH: rect.height, dpr },
		verticalStrip,
		lineSamples,
	};
});

console.log(JSON.stringify(result, null, 2));

// Screenshot the chart element directly so we don't have to guess viewport y.
const chartEl = page.locator(".vga-trend-wrap").first();
await chartEl.scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await chartEl.screenshot({ path: "/tmp/vga-trend-gradient.png" });

await browser.close();
