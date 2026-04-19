#!/usr/bin/env node
/**
 * diagnose-feedback-r2.mjs — Verify round-2 UI feedback fixes:
 *   1. Click empty area in transcript clears the active-char highlight
 *   2. Stats tiles (男/女/其他) are now compact horizontal rows
 *   3. Gender-legend "中性" label is visible at center; "女声方向" aligns
 *      with the bar's right edge (not pushed to dead center).
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

// ── 1. Stats tile geometry ────────────────────────────────────
const statsGeom = await page.evaluate(() => {
	const cards = Array.from(document.querySelectorAll(".stat-card"));
	return cards.map((c) => {
		const r = c.getBoundingClientRect();
		const cs = getComputedStyle(c);
		return {
			cls: c.className,
			height: Math.round(r.height),
			width: Math.round(r.width),
			flexDir: cs.flexDirection,
			padding: cs.padding,
		};
	});
});
const totalStatsHeight = await page.evaluate(() => {
	const r = document.querySelector(".stats-section").getBoundingClientRect();
	return Math.round(r.height);
});

// ── 2. Gender legend label positions ──────────────────────────
const legendGeom = await page.evaluate(() => {
	const get = (sel) => {
		const el = document.querySelector(sel);
		if (!el) return null;
		const r = el.getBoundingClientRect();
		const cs = getComputedStyle(el);
		return {
			text: el.textContent?.trim().slice(0, 12),
			left: Math.round(r.left),
			right: Math.round(r.right),
			centerX: Math.round(r.left + r.width / 2),
			width: Math.round(r.width),
			visible: r.width > 0 && r.height > 0 && cs.visibility !== "hidden",
		};
	};
	const wrap = document.querySelector(".vga-gender-legend__bar-wrap");
	const wrapR = wrap.getBoundingClientRect();
	return {
		bar: { left: Math.round(wrapR.left), right: Math.round(wrapR.right), centerX: Math.round(wrapR.left + wrapR.width / 2) },
		left: get(".vga-gender-legend__label--left"),
		mid: get(".vga-gender-legend__label--mid"),
		right: get(".vga-gender-legend__label--right"),
		info: get(".vga-gender-legend__info"),
	};
});

// ── 3. Click-to-dismiss behaviour ─────────────────────────────
// Click a phone first to ensure something is highlighted, then click empty
// space inside the transcript group and confirm aria-current is cleared.
await page.locator(".vga-transcript .phone").first().click();
await page.waitForTimeout(150);
const beforeClear = await page.evaluate(
	() => document.querySelectorAll('.vga-transcript .phone[aria-current="true"]').length,
);

// Click on the .vga-transcript element itself (the parent of buttons), at a
// point that lands on padding (not on any button).  Use an offset that stays
// within the group rect but not on any child.  A reliable way: click at the
// far right edge of the transcript group.
await page.evaluate(() => {
	// Synthesize a click on the group itself (not a button).
	const group = document.querySelector(".vga-transcript");
	const r = group.getBoundingClientRect();
	const ev = new MouseEvent("click", { bubbles: true, clientX: r.right - 4, clientY: r.bottom - 4 });
	group.dispatchEvent(ev);
});
await page.waitForTimeout(150);
const afterClear = await page.evaluate(
	() => document.querySelectorAll('.vga-transcript .phone[aria-current="true"]').length,
);

console.log(
	JSON.stringify(
		{
			stats_total_height_px: totalStatsHeight,
			stats_cards: statsGeom,
			legend: legendGeom,
			dismiss: {
				active_before_clear: beforeClear,
				active_after_clear: afterClear,
				pass: beforeClear >= 1 && afterClear === 0,
			},
		},
		null,
		2,
	),
);

// Take screenshots: stats area + legend area, both desktop (1400) and mobile (390).
await page.locator("#stats-section").scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await page.locator("#stats-section").screenshot({ path: "/tmp/vga-r2-stats-desktop.png" });
await page.locator(".vga-gender-legend").screenshot({ path: "/tmp/vga-r2-legend-desktop.png" });

await page.setViewportSize({ width: 390, height: 800 });
await page.waitForTimeout(400);
await page.locator("#stats-section").scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await page.locator("#stats-section").screenshot({ path: "/tmp/vga-r2-stats-mobile.png" });
await page.locator(".vga-gender-legend").scrollIntoViewIfNeeded();
await page.locator(".vga-gender-legend").screenshot({ path: "/tmp/vga-r2-legend-mobile.png" });

await browser.close();
