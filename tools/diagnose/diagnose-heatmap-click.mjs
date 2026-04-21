#!/usr/bin/env node
/**
 * diagnose-heatmap-click.mjs — Reproduce the "click on heatmap rect →
 * weird big black rect" bug.  Captures DOM state + computed style of the
 * clicked rect before/after the click.
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
await page.waitForSelector(".vga-heatmap > rect", { timeout: 180000 });
await page.waitForTimeout(800);

const before = await page.evaluate(() => {
	const rects = Array.from(document.querySelectorAll(".vga-heatmap > rect"));
	return rects.slice(0, 5).map((r) => ({
		x: r.getAttribute("x"),
		w: r.getAttribute("width"),
		fill: r.getAttribute("fill"),
		cls: r.getAttribute("class") || "",
	}));
});

// Click the third visible rect (avoid edge cases at boundaries)
const target = page.locator(".vga-heatmap > rect").nth(3);
await target.click();
await page.waitForTimeout(400);

const after = await page.evaluate(() => {
	const rects = Array.from(document.querySelectorAll(".vga-heatmap > rect"));
	const focused = document.activeElement;
	return {
		active_tag: focused?.tagName,
		active_role: focused?.getAttribute?.("role"),
		active_phoneIdx: focused?.dataset?.phoneIdx,
		active_in_heatmap: focused?.closest?.(".vga-heatmap") != null,
		focus_outline: focused
			? {
					outline_color: getComputedStyle(focused).outlineColor,
					outline_style: getComputedStyle(focused).outlineStyle,
					outline_width: getComputedStyle(focused).outlineWidth,
					outline_offset: getComputedStyle(focused).outlineOffset,
				}
			: null,
		rects_with_active_class: rects.filter((r) => r.classList.contains("active")).length,
		first_5_after: rects.slice(0, 5).map((r) => ({
			x: r.getAttribute("x"),
			w: r.getAttribute("width"),
			fill: r.getAttribute("fill"),
			cls: r.getAttribute("class") || "",
			stroke: getComputedStyle(r).stroke,
			strokeWidth: getComputedStyle(r).strokeWidth,
		})),
	};
});

console.log(JSON.stringify({ before_first5: before, after_click: after }, null, 2));

// Screenshot the heatmap area
const band = page.locator(".vga-timeline__band").first();
await band.screenshot({ path: "/tmp/vga-heatmap-after-click.png" });

await browser.close();
