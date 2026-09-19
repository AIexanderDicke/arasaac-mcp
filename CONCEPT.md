# Konzept: Satz → ARASAAC-Piktogramme

Ein Helfer, der einen Satz (typischerweise Deutsch) in eine **symbolische
Piktogrammfolge** umwandelt, damit Menschen mit kognitiven oder sprachlichen
Einschränkungen den Inhalt eines Satzes verstehen können.

Der zugehörige Modell-Prompt liegt in [`prompt.md`](./prompt.md).

---

## 1. Ziel

- Eingabe: ein Satz, z. B. *"Wenn es regnet, müssen alle Schüler drin bleiben."*
- Ausgabe: eine geordnete Liste von ARASAAC-Piktogramm-Dateien, z. B.
  `3123_Regen.png, 36081_alle.png, 32666_Schüler.png, 5439_drinnen.png`
- Das Ergebnis soll den **Sinn/Kontext** transportieren, **nicht** den Satz Wort
  für Wort nachmalen.

## 2. Kernidee

Nicht transliterieren, sondern **Bedeutung verdichten**:

1. Satz verstehen (wer, was, wo, wann, wie, warum).
2. Nur die Konzepte behalten, die zum Verständnis nötig sind.
3. Für jedes Konzept das eindeutigste Piktogramm suchen.
4. Reihenfolge festlegen, die den Inhalt am klarsten wiedergibt.
5. Mehrere sinnvolle Varianten anbieten → menschliche Auswahl.

Piktogramme liegen in `icons/` und heißen `[nummer]_[beschreibung].png`. Die
Nummer ist bedeutungslos; gesucht wird nur über die Beschreibung (deutsche
Keywords, Unterstriche statt Leerzeichen, Umlaute bleiben erhalten, z. B.
`24986_Hundertfüßer.png`).

## 3. Entscheidungen aus der Diskussion

- **Dateinamen statt IDs** ausgeben; die Zahl im Namen ignorieren.
- **Keine 1:1-Übersetzung.** Der Satz wird auf seine Kernaussage reduziert.
- **Irreführende Piktogramme weglassen.** Lieber ein Bild weniger als ein
  falsches. Bekannte Beispiele aus der Praxis:
  - `13368_stehen.png` (Person) passt nicht zu einem *stehenden Auto*.
  - `7044_vor.png` / `13028_vor.png` sind kein brauchbares räumliches *"vor"*.
  - `27206_verbleiben.png` zeigt kein *"bleiben"*.
  - Für *"vor"* gibt es kein gutes Symbol → in *"rotes Auto vor Berg"* wurde es
    bewusst weggelassen.
- **Redundanz vermeiden.** Ein Icon, das ein Merkmal schon enthält, macht ein
  zweites überflüssig: Das ARASAAC-`Auto`-Icon ist bereits rot, also kein
  separates `rot`-Icon.
- **Funktionswörter streichen**, wenn sie keinen eigenen klaren Bildsinn haben:
  Artikel, Hilfsverben, Flexion, die meisten Präpositionen. Behalten werden nur
  bedeutungstragende Wörter (Negation, Quantität, Modalität, Zeit).
- **Varianten statt einer einzigen Lösung.** Anfangs wurden bewusst drei
  Vorschläge geliefert, damit ein Mensch auswählen kann. Beispiel:
  *"Ein rotes Auto steht vor einem Berg."*
  - `2339_Auto.png, 2909_Berg.png` (minimal)
  - `2339_Auto.png, 2808_rot.png, 5438_vorne.png, 2909_Berg.png`
  - `6981_Auto.png, 13368_stehen.png, 5438_vorne.png, 2909_Berg.png`
- **Mensch bleibt im Loop.** Die Auswahl/Varianten sind für Fachpersonen oder
  Angehörige gedacht, nicht für eine unbeaufsichtigte Endausgabe.

## 4. Recherche / Stand der Praxis

Die Idee folgt etablierten AAC-Konventionen:

- **Fitzgerald-Key / ARASAAC-Farbcodes** (Edith Fitzgerald, 1954): Wörter werden
  nach ihrer Funktion im Satz eingefärbt.
  - Personen / Eigennamen → **gelb**
  - Substantive → **orange**
  - Verben → **grün**
  - Adjektive / Eigenschaften → **blau**
  - Soziale Ausdrücke → **pink**
  - Sonstiges (Artikel, Präpositionen, Konjunktionen, Zahlen, Alphabet) →
    **ohne Farbe**
- **ARASAAC-Anleitung zum Untertiteln mit Piktogrammen**:
  - Es geht um *Verständnis und Barrierefreiheit*, nicht um Lesenlernen.
  - Piktogramme, die keine Bedeutung beitragen (z. B. Artikel), entfernen.
  - *"Visuellen Lärm"* vermeiden, nicht überladen.
  - Der geschriebene Satz begleitet die Piktogramme.
  - Einfache Sprache, eine Idee pro Satz, möglichst bejahend und aktiv.
  - Der Umgang mit Funktionswörtern wird im Team entschieden.
- **AAC-Grammatik (AssistiveWare)**: korrekte Wortstellung modellieren,
  Kernvokabular (core vocabulary) nutzen, schrittweise erweitern.
- **Quellen**
  - ARASAAC Farbcodes: <https://aulaabierta.arasaac.org/en/tutorial-caa-how-to-recognize-the-keys-of-color-of-the-pictograms>
  - ARASAAC Text-Untertitelung: <https://aulaabierta.arasaac.org/en/tutorial-caa-subtitle-texts-with-pictograms>
  - ARASAAC Lernportal: <https://aulaabierta.arasaac.org/en/augmentive_and_alternative_communicacion_aac>
  - AssistiveWare Grammatik: <https://www.assistiveware.com/learn-aac/teach-grammar>
  - Wikipedia AAC (Fitzgerald Key): <https://en.wikipedia.org/wiki/Augmentative_and_alternative_communication>
  - Icon-Metadaten: <https://api.arasaac.org/v1/pictograms/all/de>

## 5. Vorgeschlagene Pipeline

```
Satz
  │
  ▼
(1) Semantische Analyse        LLM: Paraphrase + Konzeptliste + Rollen
  │
  ▼
(2) Reduktion                  Funktionswörter streichen, Kernaussage behalten
  │
  ▼
(3) Retrieval                  Suche über Icon-Beschreibungen (Volltext/Embeddings)
  │
  ▼
(4) Auswahl & Prüfung          beste Kandidaten, ggf. Bild visuell verifizieren
  │
  ▼
(5) Reihenfolge                Satzreihenfolge als Default, Umstellen wenn klarer
  │
  ▼
(6) Ausgabe                    1 Hauptfolge + Alternativen + Begründung
                               (optional Farbrahmen, geschriebener Satz)
```

## 6. Offene Fragen / nächste Schritte

- **Ausgabeformat**: Soll am Ende ein gerendertes Bild/PDF (Piktogramme + Text)
  entstehen oder nur die Dateiliste? Bisher: Dateiliste.
- **Funktionswörter**: feste Politik (immer streichen) oder abhängig vom
  Nutzer-/Abstraktionsniveau? ARASAAC empfiehlt die Entscheidung im Team.
- **Verifikation**: Der Agent sollte Kandidatenbilder tatsächlich ansehen, weil
  Dateinamen irreführen können. Wie stark automatisieren?
- **Suche**: Reicht `grep` über Dateinamen, oder braucht es einen Index mit
  Synonymen, Wortstämmen und Genus/Numerus-Varianten (Schüler/Schülerin,
  Plural)?
- **Bewertung**: Wie messen wir Qualität? Vorschlag: Fachpersonen bewerten
  Verständlichkeit der Folgen an echten Sätzen.
- **Mehrsprachigkeit**: Aktuell Deutsch; ARASAAC liefert viele Sprachen über
  die API.
- **Lizenz**: ARASAAC-Piktogramme stehen unter **CC BY-NC-SA** (Namensnennung,
  nicht kommerziell, Weitergabe unter gleichen Bedingungen) — bei
  Veröffentlichung beachten.
- **Nächter konkreter Schritt**: `prompt.md` an einer kleinen Satzsammlung
  testen und die Regeln anhand der Ergebnisse schärfen.

## 7. Projektdateien

- `download_icons.py` — lädt alle ARASAAC-Piktogramme für eine Sprache.
- `icons/` — ~13.800 Piktogramme (`[id]_[beschreibung].png`).
- `prompt.md` — Prompt/Regelwerk für das Modell.
- `CONCEPT.md` — dieses Dokument.

---

## 8. Ausblick / geplante Architektur

Next step: Der Transcriber wird als **eigenständiger Agent** betrieben, der nur
projektspezifische Tools hat, statt dem Modell freien Shell-Zugriff zu geben.

- **Tools statt Bash.** Statt `ls | grep` bekommt das Modell:
  - `search_pictograms` — Suche über Dateinamen **und** die ARASAAC-Metadaten
    (`icons/metadata_de.json`: Keywords, Tags, Kategorien; deckt Synonyme wie
    *PKW/KFZ* für *Auto* ab).
  - `view_pictogram` — liefert das Bild als Bild-Content, damit das Modell
    Kandidaten wirklich ansieht (prompt.md-Regel „verify visually“).
  - `render_pictogram_sheet` — rendert die gewählte Folge als Bild/PDF
    (der in `layout.py` gebaute Renderer).
- **MCP-Server + Skill.** Dieselben drei Tools werden später als MCP-Server
  bereitgestellt; ein Skill bündelt den Workflow/die Regeln aus `prompt.md`.
  So kann der Transcriber in verschiedenen Harnesses (pi, Claude, …) laufen.
  Der Skill entspricht der heutigen Agent-Definition.
- **Bessere Icon-Beschreibungen.** Die ARASAAC-Keywords sind knapp und teils
  irreführend (Beispiele in §3). Perspektivisch eigene, geprüfte Beschreibungen
  und Synonym-/Wortstamm-Listen (Schüler/Schülerin, Singular/Plural) sowie
  Embeddings statt reiner Textsuche.
- **Allgemeineres Layout.** Nicht nur Satz-Strips: Raster, Zeitpläne
  (z. B. Stundenplan), freie Anordnung, mehrere Seiten/Alternativen, Presets.
- **Evaluation.** Kleine Satzsammlung, mit der der Agent wiederholt getestet
  wird; Bewertung durch Fachpersonen (Verständlichkeit, nicht Worttreue).

Referenz-Implementierung für den ersten Agenten:

- `.pi/extensions/pictograms.ts` — registriert die drei Tools.
- `.pi/agents/pictogram-transcriber.md` — Systemprompt (aus `prompt.md`) plus
  `tools:`-Allowlist; so hat der Agent **nur** diese Tools.
- `scripts/run_transcriber.py` — Test-Harness, der den Agenten headless startet.
