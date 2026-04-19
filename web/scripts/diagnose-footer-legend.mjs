#!/usr/bin/env node
/**
 * diagnose-footer-legend.mjs — Verify the new shared-footer layout:
 *   • timeline DOM order is band → transcript → chart → footer
 *   • footer contains: mode toggle (left), gender legend (center), line keys (right)
 *   • gender legend has NO marker / NO highlight overlay any more
 *   • mode toggle is no longer absolute-overlaying the chart
 *   • line strokes still exist (sanity check that darkening didn't break them)
 *
 * Captures a screenshot of the chart + footer for visual review of the
 * darkened line gradient.
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
await page.waitForSelector(".vga-timeline__footer", { timeout: 180000 });
await page.waitForTimeout(800);

const summary = await page.evaluate(() => {
	const tl = document.querySelector(".vga-timeline");
	const order = Array.from(tl.children).map((c) => c.className);
	const footer = document.querySelector(".vga-timeline__footer");
	const fr = footer?.getBoundingClientRect();
	const chart = document.querySelector(".vga-trend-wrap");
	const cr = chart?.getBoundingClientRect();
	const toggle = document.querySelector(".vga-trend-mode-toggle");
	const tr = toggle?.getBoundingClientRect();
	const legend = document.querySelector(".vga-gender-legend");
	const lr = legend?.getBoundingClientRect();
	const keys = document.querySelector(".vga-timeline__footer-keys");
	const kr = keys?.getBoundingClientRect();
	return {
		timeline_children: order,
		toggle_in_footer: footer?.contains(toggle),
		legend_in_footer: footer?.contains(legend),
		keys_in_footer: footer?.contains(keys),
		toggle_top: Math.round(tr?.top || 0),
		legend_top: Math.round(lr?.top || 0),
		keys_top: Math.round(kr?.top || 0),
		chart_bottom: Math.round(cr?.bottom || 0),
		footer_top: Math.round(fr?.top || 0),
		footer_below_chart: fr && cr ? fr.top >= cr.bottom - 1 : false,
		gender_marker_present: !!document.querySelector(".vga-gender-legend__marker"),
		bar_highlight_present: !!document.querySelector(".vga-gender-legend__bar-highlight"),
		line_key_count: document.querySelectorAll(".vga-line-key").length,
		mode_toggle_position: toggle ? getComputedStyle(toggle).position : null,
	};
});

console.log(JSON.stringify(summary, null, 2));

const tlEl = page.locator(".vga-timeline").first();
await tlEl.scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await tlEl.screenshot({ path: "/tmp/vga-footer-layout.png" });

// Closeup on chart + footer to inspect the darkened line gradient
const chartArea = page.locator(".vga-timeline__chart, .vga-timeline__footer");
const chartBox = await page.locator(".vga-timeline__chart").boundingBox();
const footerBox = await page.locator(".vga-timeline__footer").boundingBox();
await page.screenshot({
	path: "/tmp/vga-chart-darkened.png",
	clip: {
		x: chartBox.x - 4,
		y: chartBox.y - 4,
		width: Math.max(chartBox.width, footerBox.width) + 8,
		height: footerBox.y + footerBox.height - chartBox.y + 8,
	},
});

await browser.close();
