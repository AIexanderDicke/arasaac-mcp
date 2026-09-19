/**
 * ARASAAC pictogram tools for pi — word-based interface.
 *
 * The agent never sees or handles the numeric pictogram IDs. It searches and
 * refers to pictograms by their German keyword/description; the tools resolve
 * words to files internally.
 *
 * Registered tools:
 *   - search_pictograms        keyword search over descriptions + ARASAAC metadata
 *   - view_pictogram           return a pictogram as image content (visual check)
 *   - render_pictogram_sheet   render an ordered list of words to an image/PDF
 *
 * `icons/` is located relative to the session cwd (override: ARASAAC_ICONS_DIR).
 * Rendering shells out to `uv run make-sheet` (handles the venv, no activation).
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const VALID_ROLES = ["PERSON", "NOUN", "VERB", "QUALITY", "SOCIAL", "MISC"];

interface Pic {
	file: string;
	desc: string;
	keywords: string[];
	extra: string[];
}

let cachedDir: string | null = null;
let cachedIndex: Pic[] | null = null;
let cachedCounts: Map<string, number> | null = null;

function iconsDir(cwd: string): string {
	const candidates = [
		process.env.ARASAAC_ICONS_DIR,
		path.join(cwd, "icons"),
		path.join(cwd, "..", "icons"),
	].filter((value): value is string => Boolean(value));
	for (const candidate of candidates) {
		if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) return candidate;
	}
	return path.join(cwd, "icons");
}

function loadIndex(dir: string): Pic[] {
	if (cachedDir === dir && cachedIndex) return cachedIndex;

	const files = fs.readdirSync(dir).filter((name) => name.endsWith(".png"));
	const byId = new Map<number, string>();
	const descById = new Map<number, string>();
	const unindexed: Pic[] = [];
	for (const file of files) {
		const match = /^(\d+)_(.*)\.png$/.exec(file);
		if (match) {
			byId.set(Number(match[1]), file);
			descById.set(Number(match[1]), match[2].replace(/_/g, " "));
		} else {
			unindexed.push({ file, desc: file, keywords: [], extra: [] });
		}
	}

	const pics: Pic[] = [];
	const metadataPath = path.join(dir, "metadata_de.json");
	if (fs.existsSync(metadataPath)) {
		const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8")) as any[];
		const seen = new Set<string>();
		for (const entry of metadata) {
			const file = byId.get(entry._id);
			if (!file) continue;
			seen.add(file);
			const keywords = (entry.keywords ?? [])
				.map((keyword: any) => keyword?.keyword)
				.filter((keyword: unknown): keyword is string => typeof keyword === "string")
				.map((keyword: string) => keyword.trim())
				.filter(Boolean);
			const extra = [...(entry.tags ?? []), ...(entry.categories ?? [])].filter(
				(value: unknown): value is string => typeof value === "string",
			);
			pics.push({ file, desc: descById.get(entry._id) ?? "", keywords, extra: [...new Set(extra)] });
		}
		for (const file of files) {
			if (seen.has(file)) continue;
			const match = /^(\d+)_(.*)\.png$/.exec(file);
			pics.push({ file, desc: match ? match[2].replace(/_/g, " ") : file, keywords: [], extra: [] });
		}
	} else {
		for (const file of files) {
			const match = /^(\d+)_(.*)\.png$/.exec(file);
			pics.push({ file, desc: match ? match[2].replace(/_/g, " ") : file, keywords: [], extra: [] });
		}
	}

	for (const pic of unindexed) pics.push(pic);

	cachedDir = dir;
	cachedIndex = pics;
	cachedCounts = null;
	return pics;
}

/** How many pictograms share each keyword (used to find a unique qualifier). */
function keywordCounts(dir: string): Map<string, number> {
	if (cachedDir === dir && cachedCounts) return cachedCounts;
	loadIndex(dir);
	const counts = new Map<string, number>();
	for (const pic of cachedIndex ?? []) {
		const seen = new Set<string>();
		for (const keyword of pic.keywords) {
			const key = keyword.toLowerCase();
			if (seen.has(key)) continue;
			seen.add(key);
			counts.set(key, (counts.get(key) ?? 0) + 1);
		}
	}
	cachedCounts = counts;
	return counts;
}

/** The word the agent sees and uses: the pictogram's main keyword. */
function wordOf(pic: Pic): string {
	return pic.keywords[0] ?? pic.desc;
}

/**
 * Agent-facing label. If the main word is shared by several pictograms, append
 * a unique synonym in parentheses, e.g. `Schüler (Student)`. Still no numbers.
 */
function labelOf(dir: string, pic: Pic): string {
	const counts = keywordCounts(dir);
	const primary = wordOf(pic);
	if ((counts.get(primary.toLowerCase()) ?? 0) <= 1) return primary;
	const unique = pic.keywords.find((keyword) => (counts.get(keyword.toLowerCase()) ?? 0) === 1);
	return unique && unique.toLowerCase() !== primary.toLowerCase() ? `${primary} (${unique})` : primary;
}

function tokenize(query: string): string[] {
	return query
		.toLowerCase()
		.split(/[^\p{L}\p{N}]+/u)
		.map((token) => token.trim())
		.filter(Boolean);
}

function score(pic: Pic, tokens: string[]): number {
	let total = 0;
	for (const token of tokens) {
		let best = 0;
		for (const keyword of pic.keywords) {
			const value = keyword.toLowerCase();
			if (value === token) best = Math.max(best, 6);
			else if (value.startsWith(token)) best = Math.max(best, 4);
			// Forgiving stem match: "rotes" -> "rot", "Autos" -> "Auto".
			else if (token.length >= 4 && value.length >= 3 && token.startsWith(value)) best = Math.max(best, 4);
			else if (value.includes(token)) best = Math.max(best, 2);
		}
		if (pic.desc.toLowerCase().includes(token)) best = Math.max(best, 3);
		for (const value of pic.extra) {
			if (value.toLowerCase().includes(token)) best = Math.max(best, 1);
		}
		if (best === 0) return 0; // require all tokens to match somewhere
		total += best;
	}
	return total - pic.keywords.length * 0.01;
}

function resolveWord(dir: string, word: string): Pic {
	const pics = loadIndex(dir);
	// Accept both `Schüler` and the qualified label `Schüler (Student)`.
	const match = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(word.trim());
	const base = (match ? match[1] : word).trim();
	const qualifier = (match ? match[2] : "").trim().toLowerCase();
	const baseLower = base.toLowerCase();

	let candidates = pics.filter((pic) => pic.keywords.some((keyword) => keyword.toLowerCase() === baseLower));
	if (candidates.length === 0) candidates = pics.filter((pic) => wordOf(pic).toLowerCase() === baseLower);
	if (qualifier) {
		const qualified = candidates.filter((pic) =>
			pic.keywords.some((keyword) => keyword.toLowerCase() === qualifier),
		);
		if (qualified.length > 0) candidates = qualified;
	}
	if (candidates.length > 0) {
		const exact = candidates.filter((pic) => wordOf(pic).toLowerCase() === baseLower);
		// Prefer the candidate whose (unqualified) label matches the query, so
		// `Auto` resolves to the pictogram labelled `Auto`, not `Auto (KFZ)`.
		const plain = exact.filter((pic) => labelOf(dir, pic).toLowerCase() === baseLower);
		const pool = plain.length > 0 ? plain : exact.length > 0 ? exact : candidates;
		pool.sort((a, b) => a.file.localeCompare(b.file, undefined, { numeric: true }));
		return pool[0];
	}

	// Fall back to fuzzy search over all keywords/tags.
	const tokens = tokenize([base, qualifier].filter(Boolean).join(" "));
	let best: Pic | null = null;
	let bestScore = 0;
	for (const pic of pics) {
		const value = score(pic, tokens);
		if (value > bestScore) {
			bestScore = value;
			best = pic;
		}
	}
	if (!best) {
		throw new Error(`Kein Piktogramm für "${word}" gefunden. Suche nach einem einfacheren Wort oder einem Synonym.`);
	}
	return best;
}

/** Turn a word into a resolved icon node (word -> file + concept). */
function iconNode(dir: string, word: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
	const pic = resolveWord(dir, word);
	return { type: "icon", file: pic.file, concept: labelOf(dir, pic), ...extra };
}

/**
 * Recursively resolve every word in a layout tree to `file`/`concept`.
 * Strings are words (shorthand for an icon), arrays become columns, and grid
 * cells are resolved as icon content. Headers stay text.
 */
function resolveLayoutNode(dir: string, node: unknown): Record<string, unknown> | null {
	if (node === null || node === undefined) return null;
	if (typeof node === "string") return iconNode(dir, node);
	if (Array.isArray(node)) {
		return {
			type: "column",
			gap: 6,
			children: node.map((child) => resolveLayoutNode(dir, child)).filter(Boolean),
		};
	}
	if (typeof node !== "object") {
		throw new Error(`Ungültiger Layout-Knoten: ${JSON.stringify(node)}`);
	}
	const out = { ...(node as Record<string, unknown>) };
	if (typeof out.word === "string") {
		const pic = resolveWord(dir, out.word);
		if (out.file == null) out.file = pic.file;
		if (out.concept == null && out.text == null) out.concept = labelOf(dir, pic);
		delete out.word;
	}
	if (out.role != null) {
		const role = String(out.role).toUpperCase();
		if (!VALID_ROLES.includes(role)) {
			throw new Error(`Ungültige Rolle "${out.role}" (erwartet: ${VALID_ROLES.join(", ")})`);
		}
		out.role = role;
	}
	for (const key of ["children", "items"] as const) {
		if (out[key] != null) {
			const value = out[key];
			const list = Array.isArray(value) ? value : [value];
			out[key] = list.map((child) => resolveLayoutNode(dir, child)).filter(Boolean);
		}
	}
	for (const key of ["child", "node"] as const) {
		if (out[key] != null) out[key] = resolveLayoutNode(dir, out[key]);
	}
	if (Array.isArray(out.cells)) {
		// Keep positions: an empty cell is `null`, not a removed entry.
		out.cells = out.cells.map((cell) => resolveLayoutNode(dir, cell));
	}
	if (Array.isArray(out.rows)) {
		out.rows = out.rows.map((row) => {
			if (Array.isArray(row)) return { cells: row.map((cell) => resolveLayoutNode(dir, cell)) };
			const copy = { ...(row as Record<string, unknown>) };
			if (Array.isArray(copy.cells)) {
				copy.cells = copy.cells.map((cell) => resolveLayoutNode(dir, cell));
			}
			return copy;
		});
	}
	return out;
}

/** Deduplicate search hits by the label the agent will use. */
function dedupeByWord(dir: string, hits: { pic: Pic; value: number }[]): { pic: Pic; value: number }[] {
	const seen = new Map<string, { pic: Pic; value: number }>();
	for (const hit of hits) {
		const key = labelOf(dir, hit.pic).toLowerCase();
		const current = seen.get(key);
		if (!current || hit.value > current.value) seen.set(key, hit);
	}
	return [...seen.values()];
}

export default function (pi: ExtensionAPI) {
	/** Write a contract, run `uv run make-sheet`, return the rendered PNG path. */
	async function renderContract(
		ctx: { cwd: string },
		dir: string,
		contract: Record<string, unknown>,
		extraArgs: string[],
		signal: AbortSignal | undefined,
	): Promise<string> {
		const tmp = path.join(
			os.tmpdir(),
			`arasaac-sheet-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}.json`,
		);
		fs.writeFileSync(tmp, JSON.stringify(contract, null, 2), "utf8");

		const outputDir = path.join(ctx.cwd, "output");
		fs.mkdirSync(outputDir, { recursive: true });
		const outputPath = path.join(
			outputDir,
			`sheet_${Date.now()}-${Math.random().toString(36).slice(2, 6)}.png`,
		);

		const args = ["run", "make-sheet", "--json", tmp, "-o", outputPath, "--icons-dir", dir, ...extraArgs];
		try {
			const result = await pi.exec("uv", args, { signal });
			if (result.code !== 0) {
				throw new Error(`make-sheet failed (exit ${result.code}): ${result.stderr || result.stdout}`);
			}
		} finally {
			try {
				fs.unlinkSync(tmp);
			} catch {
				/* ignore */
			}
		}
		return outputPath;
	}

	pi.registerTool({
		name: "search_pictograms",
		label: "Piktogramme suchen",
		description:
			"Durchsucht die ARASAAC-Piktogrammbibliothek nach deutschem Stichwort. Sucht in " +
			"Beschreibungen sowie in den offiziellen Metadaten (Synonyme, Tags, Kategorien). " +
			"Liefert Piktogramme nur per WORT, nie per Dateiname oder Nummer.",
		promptSnippet: "ARASAAC-Piktogramme nach deutschem Stichwort suchen; liefert Wörter",
		promptGuidelines: [
			"Nutze search_pictograms, um für jedes Konzept ein Piktogramm zu finden; suche nach dem deutschen Wort und probiere Synonyme. Beziehe dich auf Ergebnisse immer mit ihrem Wort.",
		],
		parameters: Type.Object({
			query: Type.String({ description: "Ein oder mehrere Stichwörter, durch Leerzeichen/Kommas getrennt (Deutsch)." }),
			limit: Type.Optional(
				Type.Number({ description: "Maximale Anzahl zurückgegebener Wörter (Standard 25).", default: 25 }),
			),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const dir = iconsDir(ctx.cwd);
			const tokens = tokenize(params.query ?? "");
			if (tokens.length === 0) {
				return { content: [{ type: "text", text: "Leere Suchanfrage." }], details: {} };
			}
			const limit = Math.max(1, Math.min(params.limit ?? 25, 100));
			const scored = dedupeByWord(
				dir,
				loadIndex(dir)
					.map((pic) => ({ pic, value: score(pic, tokens) }))
					.filter((item) => item.value > 0),
			)
				.sort((a, b) => b.value - a.value)
				.slice(0, limit);

			if (scored.length === 0) {
				return {
					content: [
						{ type: "text", text: `Keine Piktogramme zu "${params.query}" gefunden. Probiere ein Synonym oder ein einfacheres Substantiv.` },
					],
					details: {},
				};
			}

			const lines = scored.map((item, index) => {
				const label = labelOf(dir, item.pic);
				const synonyms = item.pic.keywords.slice(1).join(", ");
				const extras = item.pic.extra.slice(0, 4).join(", ");
				const detail = [synonyms && `Synonyme: ${synonyms}`, extras && `Tags: ${extras}`]
					.filter(Boolean)
					.join("; ");
				return `${index + 1}. ${label}${detail ? ` — ${detail}` : ""}`;
			});
			return {
				content: [
					{
						type: "text",
						text: `Gefunden: ${scored.length} Treffer für "${params.query}":\n${lines.join("\n")}`,
					},
				],
				details: { query: params.query, words: scored.map((item) => labelOf(dir, item.pic)) },
			};
		},
	});

	pi.registerTool({
		name: "view_pictogram",
		label: "Piktogramm ansehen",
		description:
			"Gibt das Bild eines Piktogramms zurück, identifiziert per WORT, damit du visuell " +
			"prüfen kannst, was es tatsächlich darstellt. Nutze es für mehrdeutige Kandidaten, " +
			"bevor du sie auswählst.",
		promptSnippet: "Ein Piktogrammbild (per Wort) ansehen, um seine Bedeutung zu prüfen",
		promptGuidelines: [
			"Nutze view_pictogram mit dem Ergebniswort, um mehrdeutige Piktogramm-Kandidaten visuell zu prüfen, bevor du sie auswählst.",
		],
		parameters: Type.Object({
			word: Type.String({ description: 'Das Piktogrammwort, z. B. "Regen" oder ein Synonym.' }),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const dir = iconsDir(ctx.cwd);
			const pic = resolveWord(dir, params.word);
			const data = fs.readFileSync(path.join(dir, pic.file)).toString("base64");
			const synonyms = pic.keywords.slice(1).join(", ");
			return {
				content: [
					{ type: "text", text: `Zeige "${labelOf(dir, pic)}"${synonyms ? ` (Synonyme: ${synonyms})` : ""}` },
					{ type: "image", data, mimeType: "image/png" },
				],
				details: { word: labelOf(dir, pic) },
			};
		},
	});

	pi.registerTool({
		name: "render_pictogram_sheet",
		label: "Piktogrammfolge rendern",
		description:
			"Rendert eine geordnete Liste von Piktogramm-WÖRTERN zu einem einzelnen Bild " +
			"(Bildfolge) und gibt es samt Ausgabedateipfad zurück. Optional Kopfzeile/Erklärung " +
			"und Fitzgerald-Farbrahmen über Rollen.",
		promptSnippet: "Die gewählte Piktogramm-Wortfolge als Bild rendern",
		promptGuidelines: [
			"Nutze render_pictogram_sheet, sobald du die primäre Piktogrammfolge gewählt hast, und übergib die Wörter in der richtigen Reihenfolge.",
		],
		parameters: Type.Object({
			words: Type.Array(Type.String(), { description: "Geordnete Piktogrammwörter, z. B. [\"Regen\", \"alle\"]." }),
			roles: Type.Optional(
				Type.Array(Type.String(), {
					description: "Optionale Rolle pro Wort: PERSON, NOUN, VERB, QUALITY, SOCIAL, MISC.",
				}),
			),
			sentence: Type.Optional(Type.String({ description: "Kurze Kopfzeile in einfacher Sprache (Aussage, Situation oder Regel)." })),
			meaning: Type.Optional(Type.String({ description: "Einfache Erklärung darunter (z. B. für Betreuungspersonen)." })),
			labels: Type.Optional(Type.Boolean({ description: "Jedes Icon beschriften (Standard true).", default: true })),
			columns: Type.Optional(Type.Number({ description: "Spaltenzahl erzwingen." })),
			icon_size: Type.Optional(Type.Number({ description: "Icon-Boxgröße in px (Standard 300)." })),
		}),
		async execute(_id, params, signal, _onUpdate, ctx) {
			const dir = iconsDir(ctx.cwd);
			if (!params.words || params.words.length === 0) {
				throw new Error("words darf nicht leer sein");
			}
			if (params.roles && params.roles.length !== params.words.length) {
				throw new Error("roles muss dieselbe Länge wie words haben");
			}
			if (params.roles) {
				for (const role of params.roles) {
					if (!VALID_ROLES.includes(role.toUpperCase())) {
						throw new Error(`Ungültige Rolle "${role}" (erwartet: ${VALID_ROLES.join(", ")})`);
					}
				}
			}

			const resolved = params.words.map((word) => resolveWord(dir, word));
			const sequence = resolved.map((pic, index) => {
				const entry: Record<string, string> = { file: pic.file, concept: labelOf(dir, pic) };
				if (params.roles?.[index]) entry.role = params.roles[index].toUpperCase();
				return entry;
			});
			const contract = { sentence: params.sentence, meaning: params.meaning, sequence };

			const extraArgs: string[] = [];
			if (params.labels !== false) extraArgs.push("--labels");
			if (params.columns) extraArgs.push("--columns", String(params.columns));
			if (params.icon_size) extraArgs.push("--icon-size", String(params.icon_size));

			const outputPath = await renderContract(ctx, dir, contract, extraArgs, signal);

			const data = fs.readFileSync(outputPath).toString("base64");
			const wordsLine = resolved.map((pic) => labelOf(dir, pic)).join(", ");
			return {
				content: [
					{ type: "text", text: `Gerendertes Piktogrammblatt: ${outputPath}\n${wordsLine}` },
					{ type: "image", data, mimeType: "image/png" },
				],
				details: { path: outputPath, words: wordsLine },
			};
		},
	});

	pi.registerTool({
		name: "render_pictogram_layout",
		label: "Piktogramm-Layout rendern",
		description:
			"Rendert eine freie Anordnung von Piktogramm-WÖRTERN zu einem Bild: Raster/Tabellen " +
			"(z. B. Stundenplan mit Spalten und Zeilen), Karten, Pfeile, freie Positionen. " +
			"Übergib einen Layout-Baum (JSON). Icon-Knoten nennen ein Wort statt einer Datei. " +
			"Knotentypen: icon {word, role?, concept?}, text {text}, row/column {children}, " +
			"card {children, dashed?}, grid {columns, rows} (Tabelle/Stundenplan), " +
			"canvas {children:[{x,y,node}]}, arrow {direction}, spacer. Statt eines Objekts " +
			"darf ein Icon-Knoten auch direkt das Wort als String sein; Listen werden zu Spalten.",
		promptSnippet: "Eine freie Piktogramm-Anordnung (Tabelle, Karten, Raster) als Bild rendern",
		promptGuidelines: [
			"Nutze render_pictogram_layout, wenn die Piktogramme NICHT als einfache Zeile erscheinen sollen: für Stundenpläne/Tabellen (grid mit columns und rows), Karten mit Pfeilen oder freie Anordnungen (canvas).",
		],
		parameters: Type.Object({
			layout: Type.Any({
				description:
					"Layout-Baum, z. B. {\"type\":\"grid\",\"columns\":[\"Montag\"],\"rows\":[{\"header\":\"1.\",\"cells\":[\"Mathe\"]}]}. " +
					"Icon-Knoten nutzen 'word' (z. B. {\"type\":\"icon\",\"word\":\"Mathe\",\"role\":\"NOUN\"}); ein bloßer String gilt ebenfalls als Icon-Wort.",
			}),
			sentence: Type.Optional(Type.String({ description: "Kurze Kopfzeile in einfacher Sprache." })),
			meaning: Type.Optional(Type.String({ description: "Einfache Erklärung darunter." })),
			page_size: Type.Optional(
				Type.String({ description: "Feste Seitengröße, z. B. 'a4', 'a4-landscape' oder '1200x800' (px)." }),
			),
			labels: Type.Optional(Type.Boolean({ description: "Icons beschriften (Standard true).", default: true })),
			icon_size: Type.Optional(Type.Number({ description: "Icon-Boxgröße in px, wenn kein size am Knoten steht (Standard 300)." })),
		}),
		async execute(_id, params, signal, _onUpdate, ctx) {
			const dir = iconsDir(ctx.cwd);
			if (!params.layout || typeof params.layout !== "object") {
				throw new Error("layout muss ein Layout-Objekt sein");
			}
			const layout = resolveLayoutNode(dir, params.layout);
			const contract = { sentence: params.sentence, meaning: params.meaning, layout };

			const extraArgs: string[] = [];
			if (params.labels !== false) extraArgs.push("--labels");
			if (params.icon_size) extraArgs.push("--icon-size", String(params.icon_size));
			if (params.page_size) extraArgs.push("--page-size", params.page_size);

			const outputPath = await renderContract(ctx, dir, contract, extraArgs, signal);

			const data = fs.readFileSync(outputPath).toString("base64");
			return {
				content: [
					{ type: "text", text: `Gerendertes Piktogramm-Layout: ${outputPath}` },
					{ type: "image", data, mimeType: "image/png" },
				],
				details: { path: outputPath },
			};
		},
	});
}
