#!/usr/bin/env node
/**
 * diagnose-transcript-overlap.mjs — Capture the transcript row at desktop and
 * mobile widths, plus measure each visible .phone__pitch / .phone__res span's
 * bounding-box right edge vs its parent button's right edge.  Any span whose
 * right edge exceeds the button's right edge is the smoking gun for visual
 * overlap into the adjacent button's cell.
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
await page.waitForSelector(".vga-transcript .phone", { timeout: 180000 });
await page.waitForTimeout(800);

// Measure every visible .phone__pitch right edge vs its parent .phone right edge.
// If pitch_right > phone_right by more than 1px, that span is bleeding outside.
const measurements = await page.evaluate(() => {
	const out = [];
	const phones = document.querySelectorAll(".vga-transcript .phone");
	phones.forEach((p, i) => {
		const pr = p.getBoundingClientRect();
		const pitch = p.querySelector(".phone__pitch");
		const res = p.querySelector(".phone__res");
		const ch = p.querySelector(".phone__char");
		const pitchR = pitch?.getBoundingClientRect();
		const resR = res?.getBoundingClientRect();
		const chR = ch?.getBoundingClientRect();
		out.push({
			i,
			phone_w: Math.round(pr.width),
			phone_l: Math.round(pr.left),
			phone_r: Math.round(pr.right),
			pitch_text: pitch?.textContent,
			pitch_w: pitchR ? Math.round(pitchR.width) : null,
			pitch_overflow_right: pitchR ? Math.round(pitchR.right - pr.right) : null,
			res_text: res?.textContent,
			res_w: resR ? Math.round(resR.width) : null,
			res_overflow_right: resR ? Math.round(resR.right - pr.right) : null,
			char_overflow_right: chR ? Math.round(chR.right - pr.right) : null,
		});
	});
	return out.slice(0, 8);
});

console.log(JSON.stringify(measurements, null, 2));

const tlEl = page.locator(".vga-timeline__transcript").first();
await tlEl.scrollIntoViewIfNeeded();
await page.waitForTimeout(200);
await tlEl.screenshot({ path: "/tmp/vga-transcript-mobile.png" });

await browser.close();
