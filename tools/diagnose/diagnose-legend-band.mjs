#!/usr/bin/env node
/**
 * diagnose-legend-band.mjs — Visual smoke test for changes 3 + 4.
 *
 * Loads zh_30s.wav, captures DOM state + a screenshot at each of three
 * sentences (0, 3, 7) to confirm:
 *   • TrendChart sentence band: position changes, no border, gradient bg
 *   • GenderLegend: marker repositions, highlight clip changes per sentence
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
await page.waitForFunction(
	() => document.querySelectorAll(".vga-heatmap > rect").length > 0,
	{ timeout: 60000 },
);
await page.waitForTimeout(800);

async function snapshot(label) {
	return page.evaluate((label) => {
		const wrap = document.querySelector(".vga-gender-legend__bar-wrap");
		const highlight = document.querySelector(".vga-gender-legend__bar-highlight");
		const marker = document.querySelector(".vga-gender-legend__marker");
		const band = document.querySelector(".vga-trend-sentence-band");
		const counter = document.querySelector(".vga-sentence-nav__counter")?.textContent;
		const chip = getComputedStyle(highlight);
		return {
			label,
			sentence: counter,
			legend: {
				has_highlight_class: wrap.classList.contains("has-highlight"),
				clip_left: highlight.style.getPropertyValue("--clip-left"),
				clip_right: highlight.style.getPropertyValue("--clip-right"),
				marker_left: marker.style.left,
				marker_hidden: marker.hidden,
				highlight_opacity: chip.opacity,
			},
			band: {
				display: getComputedStyle(band).display,
				left: band.style.left,
				width: band.style.width,
				border_left_width: getComputedStyle(band).borderLeftWidth,
				border_right_width: getComputedStyle(band).borderRightWidth,
				bg_image_starts_with: getComputedStyle(band).backgroundImage.slice(0, 30),
				top: getComputedStyle(band).top,
				bottom: getComputedStyle(band).bottom,
			},
		};
	}, label);
}

const results = [];
results.push(await snapshot("sentence-1 (initial)"));
await page.screenshot({ path: "/tmp/vga-s1.png", clip: { x: 220, y: 240, width: 900, height: 620 } });

// Use the next-button to step to sentence 4 and 8 (manual nav so it's fast)
for (let step = 0; step < 3; step++) {
	await page.click(".vga-sentence-nav__btn[aria-label='\u4e0b\u4e00\u53e5']");
	await page.waitForTimeout(250);
}
results.push(await snapshot("sentence-4"));
await page.screenshot({ path: "/tmp/vga-s4.png", clip: { x: 220, y: 240, width: 900, height: 620 } });

for (let step = 0; step < 4; step++) {
	await page.click(".vga-sentence-nav__btn[aria-label='\u4e0b\u4e00\u53e5']");
	await page.waitForTimeout(250);
}
results.push(await snapshot("sentence-8"));
await page.screenshot({ path: "/tmp/vga-s8.png", clip: { x: 220, y: 240, width: 900, height: 620 } });

console.log(JSON.stringify(results, null, 2));
await browser.close();
