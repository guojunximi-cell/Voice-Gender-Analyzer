#!/usr/bin/env node
/**
 * diagnose-chart-mobile-width.mjs — Investigate why the trend chart leaves
 * dead space on the right in portrait/mobile viewports.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 390, height: 800 } });
const page = await ctx.newPage();
page.on("console", (m) => m.type() === "error" && console.error("[err]", m.text()));

await page.goto("http://localhost:5174/", { waitUntil: "domcontentloaded" });
await page.locator('input[type="file"]').first().setInputFiles({
	name: "zh_30s.wav",
	mimeType: "audio/wav",
	buffer: audio,
});
await page.waitForSelector("#analyze-btn:not([disabled])", { timeout: 15000 });
await page.click("#analyze-btn");
await page.waitForSelector(".vga-trend-wrap", { timeout: 180000 });
await page.waitForTimeout(800);

const m = await page.evaluate(() => {
	const measure = (sel) => {
		const el = document.querySelector(sel);
		if (!el) return null;
		const r = el.getBoundingClientRect();
		const cs = getComputedStyle(el);
		return {
			width: Math.round(r.width),
			height: Math.round(r.height),
			left: Math.round(r.left),
			right: Math.round(r.right),
			padding_h: cs.paddingLeft + " / " + cs.paddingRight,
			boxSizing: cs.boxSizing,
		};
	};
	const canvases = Array.from(document.querySelectorAll(".vga-trend-wrap canvas")).map((c) => ({
		w: c.width,
		h: c.height,
		cssW: Math.round(c.getBoundingClientRect().width),
		cssH: Math.round(c.getBoundingClientRect().height),
	}));
	const uplot = document.querySelector(".vga-trend-wrap .uplot");
	return {
		viewport: { w: window.innerWidth, h: window.innerHeight },
		panel_center: measure(".panel-center"),
		stats_section: measure("#stats-section"),
		timeline_root: measure("#phone-timeline-root"),
		vga_timeline: measure(".vga-timeline"),
		timeline_chart_div: measure(".vga-timeline__chart"),
		trend_wrap: measure(".vga-trend-wrap"),
		uplot_root: uplot ? { width: Math.round(uplot.getBoundingClientRect().width) } : null,
		canvases,
	};
});

console.log(JSON.stringify(m, null, 2));

const tlEl = page.locator(".vga-timeline").first();
await tlEl.scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await tlEl.screenshot({ path: "/tmp/vga-mobile-chart.png" });

await browser.close();
