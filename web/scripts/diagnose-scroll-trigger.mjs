#!/usr/bin/env node
/**
 * diagnose-scroll-trigger.mjs — Find what scrolls panel-center.
 *
 * Injects a scroll listener + stack capture on the panel, then plays a
 * recording for 6s, harvests all scroll events with timestamps + stacks.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

page.on("console", (msg) => {
	if (msg.type() === "error") console.error("[page err]", msg.text());
});

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
await page.waitForTimeout(500);

console.error("→ install scroll instrumentation");
await page.evaluate(() => {
	const panel = document.querySelector(".panel-center");
	window.__scrollEvents = [];
	window.__scrollStart = performance.now();

	// Wrap scrollIntoView on the Element prototype to see who calls it
	const origSIV = Element.prototype.scrollIntoView;
	Element.prototype.scrollIntoView = function (opts) {
		const err = new Error("scrollIntoView trace");
		window.__scrollEvents.push({
			kind: "scrollIntoView-call",
			t: Math.round(performance.now() - window.__scrollStart),
			on: this.tagName + "." + (this.className || "(no-class)"),
			opts: typeof opts === "object" ? JSON.stringify(opts) : String(opts),
			stack: err.stack?.split("\n").slice(1, 8).join("\n"),
		});
		return origSIV.call(this, opts);
	};

	// Also wrap scrollTo / scrollBy on the panel
	const origScrollTo = panel.scrollTo.bind(panel);
	panel.scrollTo = function (...args) {
		const err = new Error("scrollTo trace");
		window.__scrollEvents.push({
			kind: "panel.scrollTo",
			t: Math.round(performance.now() - window.__scrollStart),
			args: JSON.stringify(args),
			stack: err.stack?.split("\n").slice(1, 8).join("\n"),
		});
		return origScrollTo(...args);
	};

	// Log scroll events with stack
	panel.addEventListener("scroll", () => {
		window.__scrollEvents.push({
			kind: "scroll-event",
			t: Math.round(performance.now() - window.__scrollStart),
			scrollTop: panel.scrollTop,
		});
	});
});

console.error("→ click play");
await page.click("#play-btn");
await page.waitForTimeout(6000);

console.error("→ harvest");
const events = await page.evaluate(() => window.__scrollEvents);

console.log("");
console.log(`Total events: ${events.length}`);
for (const e of events.slice(0, 15)) {
	console.log("---");
	console.log(`t=${e.t}ms  ${e.kind}`);
	if (e.on) console.log(`  on: ${e.on}`);
	if (e.opts) console.log(`  opts: ${e.opts}`);
	if (e.args) console.log(`  args: ${e.args}`);
	if (e.scrollTop != null) console.log(`  scrollTop: ${e.scrollTop}`);
	if (e.stack) console.log(`  stack:\n    ${e.stack.replace(/\n/g, "\n    ")}`);
}
if (events.length > 15) console.log(`\n... (${events.length - 15} more)`);

await browser.close();
