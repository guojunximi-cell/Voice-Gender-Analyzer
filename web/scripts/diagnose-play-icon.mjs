#!/usr/bin/env node
/**
 * diagnose-play-icon.mjs — Check whether the play-btn icon swaps to "pause"
 * during playback.  Bug report: it stays as the play triangle.
 */

import fs from "node:fs";
import { chromium } from "playwright";

const AUDIO = "/home/yaya/Voice-Gender-Analyzer/tests/fixtures/audio/zh_30s.wav";
const audio = fs.readFileSync(AUDIO);

const browser = await chromium.launch({
	headless: true,
	args: ["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on("console", (m) => m.type() === "error" && console.error("[err]", m.text()));

await page.goto("http://localhost:5174/", { waitUntil: "domcontentloaded" });
await page.locator('input[type="file"]').first().setInputFiles({
	name: "zh_30s.wav",
	mimeType: "audio/wav",
	buffer: audio,
});
await page.waitForSelector("#play-btn:not([disabled])", { timeout: 30000 });

// Wrap getWaveSurfer indirectly: monkey-patch HTMLAudioElement & log all events.
await page.evaluate(() => {
	const origAddEventListener = EventTarget.prototype.addEventListener;
	EventTarget.prototype.addEventListener = function (type, listener, opts) {
		if (this.tagName === "AUDIO" || this.tagName === "VIDEO") {
			console.log(`[addEvtLis] ${this.tagName} ${type}`);
		}
		return origAddEventListener.call(this, type, listener, opts);
	};
});

async function snapshot(label) {
	return page.evaluate((label) => {
		const btn = document.getElementById("play-btn");
		const playSvg = btn.querySelector(".icon-play");
		const pauseSvg = btn.querySelector(".icon-pause");
		const audio = document.querySelector("audio") || document.querySelector("video");
		return {
			label,
			btn_classes: btn.className,
			btn_aria_label: btn.getAttribute("aria-label"),
			play_display: getComputedStyle(playSvg).display,
			pause_display: getComputedStyle(pauseSvg).display,
			audio_paused: audio?.paused,
			audio_currentTime: audio?.currentTime,
		};
	}, label);
}

// Listen for any wavesurfer-related console output
page.on("console", (m) => console.log(`[browser:${m.type()}]`, m.text()));

// Inject a wavesurfer-event sniffer: hook into the global ws (we don't expose
// it normally, so try via the audio element + DOM)
await page.evaluate(() => {
	// Wait for the audio element to exist and log its play/pause events
	const obs = new MutationObserver(() => {
		const a = document.querySelector("audio");
		if (a && !a._sniffed) {
			a._sniffed = true;
			a.addEventListener("play", () => console.log("[audio-event] play"));
			a.addEventListener("pause", () => console.log("[audio-event] pause"));
			a.addEventListener("playing", () => console.log("[audio-event] playing"));
			obs.disconnect();
		}
	});
	obs.observe(document.body, { childList: true, subtree: true });
});

const snaps = [];
snaps.push(await snapshot("before play"));

await page.click("#play-btn");
await page.waitForTimeout(800);
snaps.push(await snapshot("after click play (should be playing)"));

await page.click("#play-btn");
await page.waitForTimeout(500);
snaps.push(await snapshot("after second click (should be paused)"));

console.log(JSON.stringify(snaps, null, 2));
await browser.close();
