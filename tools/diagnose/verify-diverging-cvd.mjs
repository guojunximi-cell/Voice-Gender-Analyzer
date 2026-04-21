#!/usr/bin/env node
/**
 * verify-diverging-cvd.mjs — CLI CVD check for diverging.js palette.
 *
 * Usage:   node web/scripts/verify-diverging-cvd.mjs
 * Exit 0 if every adjacent-stop ΔE₇₆ > 3 under both deuteranopia and
 * protanopia; exit 1 otherwise.
 *
 * Prints a ΔE matrix suitable for pasting into docs/COLOR_SCHEME.md.
 */

import { _verifyCVD, DIVERGING_HEX } from "../src/modules/diverging.js";

const result = _verifyCVD();

const pad = (s, n) => String(s).padEnd(n, " ");
const fmt = (x) => x.toFixed(2);

console.log("");
console.log("Diverging palette CVD verification (Viénot-Brettel-Mollon + CIE76 ΔE)");
console.log("");
console.log(`Stops: ${DIVERGING_HEX.join(" ")}`);
console.log("");
console.log(`${pad("Adjacent pair", 22)}${pad("Normal", 10)}${pad("Deutan", 10)}${pad("Protan", 10)}`);
console.log("-".repeat(52));
for (const r of result.rows) {
	console.log(
		`${pad(r.pair, 22)}${pad(fmt(r.normal), 10)}${pad(fmt(r.deut), 10)}${pad(fmt(r.prot), 10)}`,
	);
}
console.log("-".repeat(52));
console.log(
	`${pad("End-to-end (0 → 8)", 22)}` +
		`${pad(fmt(result.endToEnd.normal), 10)}` +
		`${pad(fmt(result.endToEnd.deut), 10)}` +
		`${pad(fmt(result.endToEnd.prot), 10)}`,
);
console.log("");
console.log(`Min ΔE₇₆ across CVD views: ${fmt(result.minCvd)}  (threshold > 3)`);
console.log(result.pass ? "PASS ✓" : "FAIL ✗");
console.log("");

process.exit(result.pass ? 0 : 1);
