#!/usr/bin/env node
/**
 * diagnose-stats-position.mjs — Confirm stats-section now sits directly above
 * segments-section in DOM order (and on screen below the timeline / chart).
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
await page.waitForSelector("#segments-section:not([hidden])", { timeout: 30000 });
await page.waitForTimeout(800);

const order = await page.evaluate(() => {
	const ids = ["player-section", "phone-timeline-root", "stats-section", "segments-section"];
	const els = ids.map((id) => document.getElementById(id));
	return els.map((el) => {
		if (!el) return null;
		const r = el.getBoundingClientRect();
		return { id: el.id, top: Math.round(r.top), bottom: Math.round(r.bottom) };
	});
});

const statsTop = order.find((e) => e.id === "stats-section").top;
const segTop = order.find((e) => e.id === "segments-section").top;
const tlTop = order.find((e) => e.id === "phone-timeline-root").top;

console.log(JSON.stringify({
	order,
	stats_above_segments: statsTop < segTop,
	stats_below_timeline: statsTop > tlTop,
	pass: statsTop < segTop && statsTop > tlTop,
}, null, 2));

await page.locator("#stats-section").scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await page.screenshot({ path: "/tmp/vga-stats-segments.png", fullPage: false });

await browser.close();
