/**
 * Offline test for the pictogram extension (no LLM needed).
 *
 * Loads .pi/extensions/pictograms.ts through jiti with a mock ExtensionAPI,
 * then exercises each registered tool directly:
 *   - search_pictograms   against the real metadata
 *   - view_pictogram      returns real PNG image content
 *   - render_pictogram_sheet  really runs `uv run make-sheet` and returns an image
 *
 * Run from the repo root:  node scripts/test_extension.mjs
 */

import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PI = "/opt/proto/tools/node/22.23.2/lib/node_modules/@earendil-works/pi-coding-agent";
const EXTENSION = path.join(ROOT, ".pi", "extensions", "pictograms.ts");

function fail(message) {
	console.error(`FAIL: ${message}`);
	process.exitCode = 1;
}

function ok(message) {
	console.log(`ok   ${message}`);
}

function exec(command, args, options = {}) {
	return new Promise((resolve) => {
		const child = spawn(command, args, { cwd: options.cwd, signal: options.signal });
		let stdout = "";
		let stderr = "";
		child.stdout.on("data", (data) => (stdout += data));
		child.stderr.on("data", (data) => (stderr += data));
		child.on("error", (error) => resolve({ stdout, stderr: String(error), code: 1, killed: false }));
		child.on("close", (code) => resolve({ stdout, stderr, code: code ?? 0, killed: false }));
	});
}

const { createJiti } = require(`${PI}/node_modules/jiti`);
const jiti = createJiti(import.meta.url, {
	alias: {
		typebox: path.join(PI, "node_modules/typebox/build/index.mjs"),
	},
	interopDefault: true,
});

const mod = await jiti.import(EXTENSION, { default: true });
const factory = typeof mod === "function" ? mod : mod.default;
if (typeof factory !== "function") {
	fail("extension does not export a factory function");
	process.exit(1);
}

const tools = new Map();
factory({
	registerTool: (definition) => tools.set(definition.name, definition),
	exec,
});

const ctx = { cwd: ROOT };

// ---------------------------------------------------------------------------
console.log("\n== search_pictograms ==");
const search = tools.get("search_pictograms");
if (!search) fail("search_pictograms not registered");
const found = await search.execute("t1", { query: "Regen", limit: 5 }, undefined, undefined, ctx);
const foundText = found.content[0].text;
console.log(foundText);
if (!/^1\. Regen\b/m.test(foundText)) fail("search did not return the word 'Regen' first");
else ok("found word 'Regen'");
if (/\d+_/.test(foundText)) fail("search output must not contain numeric file names");
else ok("search output has no numeric ids");

const synonym = await search.execute("t2", { query: "PKW", limit: 5 }, undefined, undefined, ctx);
const synonymText = synonym.content[0].text;
if (!synonymText.includes("Auto")) fail("synonym search PKW did not surface word 'Auto'");
else ok("synonym PKW -> word 'Auto'");

const andQuery = await search.execute("t3", { query: "rotes auto", limit: 5 }, undefined, undefined, ctx);
console.log(andQuery.content[0].text.split("\n")[0]);

// ---------------------------------------------------------------------------
console.log("\n== view_pictogram ==");
const view = tools.get("view_pictogram");
if (!view) fail("view_pictogram not registered");
const viewed = await view.execute("t4", { word: "Auto" }, undefined, undefined, ctx);
const image = viewed.content.find((part) => part.type === "image");
if (!image || image.mimeType !== "image/png" || image.data.length < 1000)
	fail("view_pictogram did not return image content");
else ok(`returned image for word 'Auto' (${Math.round(image.data.length / 1024)} KiB base64)`);

let missingThrew = false;
try {
	await view.execute("t5", { word: "does_not_exist" }, undefined, undefined, ctx);
} catch {
	missingThrew = true;
}
if (!missingThrew) fail("view_pictogram should throw for an unknown word");
else ok("unknown word throws");

// Qualified labels (e.g. "Auto (KFZ)") must round-trip back to the same pictogram.
let checked = 0;
let mismatches = 0;
for (const query of ["Schüler", "Auto", "vor", "Sport", "Regen", "Familie"]) {
	const hits = await search.execute("rt", { query, limit: 12 }, undefined, undefined, ctx);
	for (const line of hits.content[0].text.split("\n").slice(1)) {
		const label = line.replace(/^\d+\.\s*/, "").split(" — ")[0].trim();
		const resolved = await view.execute("rt", { word: label }, undefined, undefined, ctx);
		checked++;
		if (String(resolved.details.word).toLowerCase() !== label.toLowerCase()) {
			mismatches++;
			fail(`label does not round-trip: ${label} -> ${resolved.details.word}`);
		}
	}
}
ok(`${checked - mismatches}/${checked} search labels round-trip to themselves`);

// ---------------------------------------------------------------------------
console.log("\n== render_pictogram_sheet ==");
const render = tools.get("render_pictogram_sheet");
if (!render) fail("render_pictogram_sheet not registered");
const rendered = await render.execute(
	"t6",
	{
		words: ["Regen", "alle", "Schüler", "drinnen"],
		roles: ["NOUN", "NOUN", "PERSON", "MISC"],
		sentence: "Wenn es regnet, müssen alle Schüler drin bleiben.",
		meaning: "Bei Regen bleiben alle Schüler im Gebäude.",
	},
	undefined,
	undefined,
	ctx,
);
const renderedImage = rendered.content.find((part) => part.type === "image");
const outputPath = rendered.details?.path;
if (!renderedImage) fail("render_pictogram_sheet returned no image");
else ok(`returned image (${Math.round(renderedImage.data.length / 1024)} KiB base64)`);
if (!outputPath || !fs.existsSync(outputPath)) fail("render output file missing");
else ok(`wrote ${path.relative(ROOT, outputPath)} (${fs.statSync(outputPath).size} bytes)`);

console.log(process.exitCode ? "\nSOME CHECKS FAILED" : "\nALL CHECKS PASSED");
