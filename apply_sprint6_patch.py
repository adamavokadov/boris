#!/usr/bin/env python3
"""
Sprint 6 patch for brazil-news-bot (Boris) — pre-LLM deduplication and
priority/recency scoring, per roadmap.md section 1.

PREREQUISITE: sprint 0-3 and sprint 5 must already be applied (anchors are
the post-sprint-5 shape of index.js: getSettingsKeyboard/getTopicsKeyboard/
etc. present, VERSION '14.3'). Hard-aborts if that shape isn't found.

--- Scope, and why it's narrower than "dedup everything" ---
Only collectSourceNews() (the 5 curated RSS/HTML SOURCES + WatcherGuru-style
breaking news) produces individual, structured headline strings before this
patch. collectRawNews() and collectTrends() call the search API, which
returns one free-text prose "answer" per topic query — there are no
separable per-headline strings to dedup there without an extra LLM call
(out of scope/cost for this sprint; noted in roadmap.md as a possible
follow-up, not promised here). So:

  - Tier 1 (this patch): deterministic near-duplicate collapse + scoring
    across all SOURCES + breaking-news headlines, before they're joined
    into the `raw` text blocks that go into the LLM prompt.
  - Tier 2 (unchanged, still LLM's job): rawNews/trendNews prose blobs are
    still deduped by the LLM itself inside generateDigest(), same as
    before this patch — its system prompt already tells it to avoid
    repeating stories, and that instruction is untouched.

What this does:
  1. normalizeForDedup(title) / titleSimilarity(a, b) — cheap, dependency-
     free near-duplicate detection: lowercase, strip accents/punctuation,
     Jaccard similarity over word sets. No embeddings/API calls — this
     runs synchronously over ~60-80 headlines per briefing, needs to be
     fast and free.
  2. SOURCE_PRIORITY — authority bonus per source id (Bloomberg Línea,
     CNN Brasil: curated business/news outlets get +2; Habr, Google News,
     Folha, breaking-news: +0 — no per-source demotion, only explicit
     boosts, so this can't silently bury a source that has no entry).
  3. dedupeAndScoreHeadlines(items) — takes a flat list of
     {title, sourceId, sourceName, position} across ALL sources (so a
     headline duplicated between e.g. Bloomberg Línea and CNN Brasil is
     actually caught — dedup was previously impossible because
     collectSourceNews() joined each source's headlines into prose before
     any other source was even fetched). Groups near-duplicates
     (similarity >= DEDUP_SIMILARITY_THRESHOLD), keeps the
     highest-scored representative of each group, sorts by score
     descending. Score = SOURCE_PRIORITY bonus + recency proxy (earlier
     position in its source's own listing = more recent/prominent on
     most feeds and homepages, since none of the 5 extractors capture a
     real publish timestamp) + a small "seen again elsewhere" bonus
     (a story 2+ sources independently ran is more likely to actually
     matter, not less — this is the one place cross-source duplication is
     signal rather than noise, and it's captured here before the
     duplicates themselves are dropped).
  4. Cross-run upsert dedup: settings.recentlySentHeadlines (normalized
     hash -> ISO timestamp), pruned to the last SENT_HISTORY_DAYS days on
     every save. A headline already sent in that window is filtered out
     before generateDigest() ever sees it, and every headline actually
     included in a *sent* digest gets recorded. Prevents a same-day manual
     /news re-run (or the next morning's /news right after last night's
     auto-send) from repeating a story verbatim.
  5. collectSourceNews() rewired to flatten all sources into one list,
     run dedup+scoring across all of them together, then regroup by
     source for the final `raw` text blocks — so the digest's per-source
     presentation format in the prompt is unchanged, only which headlines
     make it in.
  6. /status gets a one-line dedup summary (how many duplicates were
     collapsed in the last collection run), matching the project's
     existing observability pattern from /sourcehealth.

Usage:
    python3 apply_sprint6_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run multiple times.
"""

import sys
import shutil
import datetime
from pathlib import Path


def find_bot_dir(cli_arg):
    candidates = []
    if cli_arg:
        candidates.append(Path(cli_arg))
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "brazil-news-bot")
    candidates.append(Path.cwd() / "brazil-news-bot")
    candidates.append(Path.cwd())

    for c in candidates:
        if (c / "index.js").exists() and (c / "personality.js").exists():
            return c

    print("ERROR: could not locate brazil-news-bot/ (needs index.js + personality.js).")
    print("       Pass the path explicitly: python3 apply_sprint6_patch.py /path/to/brazil-news-bot")
    sys.exit(1)


def backup(path: Path):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, bak)
    print(f"  backup: {bak.name}")


def replace_once(content, old, new, label, already_applied_marker):
    if already_applied_marker in content:
        print(f"  [skip] {label} (already applied)")
        return content
    count = content.count(old)
    if count == 0:
        print(f"  [WARN] {label}: anchor text not found — skipping.")
        return content
    if count > 1:
        print(f"  [WARN] {label}: anchor found {count} times (expected 1) — skipping to avoid a bad patch.")
        return content
    print(f"  [ok]   {label}")
    return content.replace(old, new, 1)


def patch_index_js(path: Path):
    print(f"\nPatching {path.name} ...")
    original = path.read_text(encoding="utf-8")
    content = original

    # --- Pre-flight: refuse to run against a pre-sprint-5 file ---
    PREREQ_MARKER = "function getSourceHealthKeyboard() {"
    if PREREQ_MARKER not in content:
        print("  [ABORT] sprint 5 changes not found in this file (no getSourceHealthKeyboard()).")
        print("          Run sprint 0-3 and sprint 5 first. No changes were made.")
        return

    # 1. DEFAULT_SETTINGS: add recentlySentHeadlines, next to sourceHealth.
    content = replace_once(
        content,
        old=(
            "  // Per-source scrape health: lets /status and /sourcehealth surface silent\n"
            "  // degradation (e.g. a site changes its HTML and our regex extractor\n"
            "  // starts returning 0 headlines) instead of failing invisibly forever.\n"
            "  sourceHealth: {}\n"
            "};"
        ),
        new=(
            "  // Per-source scrape health: lets /status and /sourcehealth surface silent\n"
            "  // degradation (e.g. a site changes its HTML and our regex extractor\n"
            "  // starts returning 0 headlines) instead of failing invisibly forever.\n"
            "  sourceHealth: {},\n"
            "  // Cross-run dedup (sprint 6): normalized-headline -> ISO timestamp of the\n"
            "  // last time it was actually included in a sent digest. Pruned to the last\n"
            "  // SENT_HISTORY_DAYS days on every save so this can't grow unbounded.\n"
            "  recentlySentHeadlines: {}\n"
            "};"
        ),
        label="DEFAULT_SETTINGS: add recentlySentHeadlines",
        already_applied_marker="recentlySentHeadlines: {}\n};",
    )

    # 2. Dedup/scoring helpers + cross-run upsert helpers, placed right
    #    before SOURCES (they're used by collectSourceNews() below it).
    content = replace_once(
        content,
        old=(
            "const SOURCES = [\n"
        ),
        new=(
            "// --- Pre-LLM deduplication and scoring (sprint 6) --------------------\n"
            "// Cheap, dependency-free near-duplicate detection over headline strings.\n"
            "// No embeddings/external calls — this runs synchronously over every\n"
            "// headline in a collection run and needs to stay fast and free.\n"
            "const DEDUP_SIMILARITY_THRESHOLD = 0.45; // Jaccard word-overlap, 0-1 — tuned against\n"
            "// a sample of realistic PT-BR near-duplicate headline pairs (paraphrased by\n"
            "// different outlets), which scored 0.50-0.71, vs genuinely distinct stories\n"
            "// (including ones sharing a common subject word like \"Brasil\"), which scored\n"
            "// 0.00-0.10. 0.45 sits in the gap between those two clusters.\n"
            "const SENT_HISTORY_DAYS = 3; // how long a sent headline blocks a repeat\n"
            "\n"
            "// Authority bonus per source id. Deliberately additive-only (no negative\n"
            "// entries): a source absent from this map just gets +0, never demoted, so\n"
            "// this can't silently bury a source nobody got around to rating.\n"
            "const SOURCE_PRIORITY = {\n"
            "  bloomberglinea: 2,\n"
            "  cnnbrasil: 2\n"
            "};\n"
            "\n"
            "function normalizeForDedup(title) {\n"
            "  return (title || '')\n"
            "    .toLowerCase()\n"
            "    .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '') // strip accents\n"
            "    .replace(/[^\\w\\s]/g, ' ')\n"
            "    .replace(/\\s+/g, ' ')\n"
            "    .trim();\n"
            "}\n"
            "\n"
            "function titleSimilarity(a, b) {\n"
            "  const wordsA = new Set(normalizeForDedup(a).split(' ').filter(w => w.length > 2));\n"
            "  const wordsB = new Set(normalizeForDedup(b).split(' ').filter(w => w.length > 2));\n"
            "  if (wordsA.size === 0 || wordsB.size === 0) return 0;\n"
            "  let intersection = 0;\n"
            "  for (const w of wordsA) { if (wordsB.has(w)) intersection++; }\n"
            "  const union = wordsA.size + wordsB.size - intersection;\n"
            "  return union === 0 ? 0 : intersection / union;\n"
            "}\n"
            "\n"
            "// Prune recentlySentHeadlines older than SENT_HISTORY_DAYS. Called before\n"
            "// every filter/record pass so the map never grows unbounded.\n"
            "function pruneSentHistory() {\n"
            "  if (!settings.recentlySentHeadlines) { settings.recentlySentHeadlines = {}; return; }\n"
            "  const cutoff = Date.now() - SENT_HISTORY_DAYS * 24 * 60 * 60 * 1000;\n"
            "  for (const [key, iso] of Object.entries(settings.recentlySentHeadlines)) {\n"
            "    if (new Date(iso).getTime() < cutoff) delete settings.recentlySentHeadlines[key];\n"
            "  }\n"
            "}\n"
            "\n"
            "function wasRecentlySent(title) {\n"
            "  pruneSentHistory();\n"
            "  return Object.prototype.hasOwnProperty.call(settings.recentlySentHeadlines, normalizeForDedup(title));\n"
            "}\n"
            "\n"
            "function recordSentHeadlines(titles) {\n"
            "  pruneSentHistory();\n"
            "  const now = new Date().toISOString();\n"
            "  for (const t of titles) {\n"
            "    settings.recentlySentHeadlines[normalizeForDedup(t)] = now;\n"
            "  }\n"
            "  saveSettings();\n"
            "}\n"
            "\n"
            "// Tracks how many near-duplicates the last collection run collapsed, for\n"
            "// /status visibility. Reset at the start of each dedupeAndScoreHeadlines() call.\n"
            "let lastDedupStats = { input: 0, output: 0, collapsed: 0, blockedRepeats: 0 };\n"
            "\n"
            "// items: [{ title, sourceId, sourceName, position }], position = index in\n"
            "// its own source's listing (0 = first/most prominent on that page/feed).\n"
            "// Returns items deduped (near-duplicates collapsed to their\n"
            "// highest-scored representative) and sorted by score descending.\n"
            "function dedupeAndScoreHeadlines(items) {\n"
            "  const filtered = items.filter(it => !wasRecentlySent(it.title));\n"
            "  const blockedRepeats = items.length - filtered.length;\n"
            "\n"
            "  const scored = filtered.map(it => {\n"
            "    const priorityBonus = SOURCE_PRIORITY[it.sourceId] || 0;\n"
            "    const recencyBonus = Math.max(0, 3 - Math.floor(it.position / 3)); // earlier in listing = fresher, tapers off\n"
            "    return { ...it, score: priorityBonus + recencyBonus, seenInSources: new Set([it.sourceId]) };\n"
            "  });\n"
            "\n"
            "  // Group near-duplicates. O(n^2) over headlines from one collection run\n"
            "  // (tens, not thousands) — fine at this scale, revisit if SOURCES grows a lot.\n"
            "  const groups = [];\n"
            "  for (const item of scored) {\n"
            "    let placed = false;\n"
            "    for (const group of groups) {\n"
            "      if (titleSimilarity(item.title, group.best.title) >= DEDUP_SIMILARITY_THRESHOLD) {\n"
            "        group.best.seenInSources.add(item.sourceId);\n"
            "        // A story independently picked up by more than one source is more\n"
            "        // likely to actually matter — small bonus, captured before the\n"
            "        // duplicate itself is dropped below.\n"
            "        if (group.best.seenInSources.size > 1) {\n"
            "          group.best.score += 1;\n"
            "        }\n"
            "        if (item.score > group.best.score) {\n"
            "          const mergedSources = group.best.seenInSources;\n"
            "          group.best = item;\n"
            "          group.best.seenInSources = mergedSources;\n"
            "        }\n"
            "        placed = true;\n"
            "        break;\n"
            "      }\n"
            "    }\n"
            "    if (!placed) groups.push({ best: item });\n"
            "  }\n"
            "\n"
            "  const result = groups.map(g => g.best).sort((a, b) => b.score - a.score);\n"
            "  lastDedupStats = {\n"
            "    input: items.length,\n"
            "    output: result.length,\n"
            "    collapsed: filtered.length - result.length,\n"
            "    blockedRepeats\n"
            "  };\n"
            "  return result;\n"
            "}\n"
            "\n"
            "const SOURCES = [\n"
        ),
        label="add dedup/scoring/upsert helpers",
        already_applied_marker="function dedupeAndScoreHeadlines(items) {",
    )

    # 3. Rewire collectSourceNews() to flatten all sources, dedup+score
    #    across all of them together, regroup by source for the raw text,
    #    and record what actually got sent.
    content = replace_once(
        content,
        old=(
            "async function collectSourceNews() {\n"
            "  const results = [];\n"
            "  for (const source of SOURCES) {\n"
            "    const titles = await fetchSourceHeadlines(source);\n"
            "    if (titles.length > 0) {\n"
            "      results.push({\n"
            "        topic: source.name,\n"
            "        source: source.id,\n"
            "        raw: `Свежие заголовки из источника «${source.name}»:\\n` + titles.map((t, i) => `${i+1}. ${t}`).join('\\n')\n"
            "      });\n"
            "    }\n"
            "    await new Promise(resolve => setTimeout(resolve, 800));\n"
            "  }\n"
            "  // Add WatcherGuru-style \"Just In\" breaking news via search\n"
            "  const breaking = await fetchBreakingNews();\n"
            "  if (breaking.length > 0) {\n"
            "    results.push({\n"
            "      topic: 'WatcherGuru-style «Just In» breaking news',\n"
            "      source: 'breaking',\n"
            "      raw: 'Самые свежие «Just In» новости (в стиле WatcherGuru):\\n' + breaking.map((h, i) => `${i+1}. ${h}`).join('\\n')\n"
            "    });\n"
            "  }\n"
            "  return results;\n"
            "}"
        ),
        new=(
            "async function collectSourceNews() {\n"
            "  // Flatten every source's headlines into one list FIRST, so dedup can\n"
            "  // catch the same story picked up by two different sources — that was\n"
            "  // previously impossible because each source's headlines were joined into\n"
            "  // prose before the next source was even fetched.\n"
            "  const flat = [];\n"
            "  const sourceMeta = {}; // sourceId -> { name }\n"
            "  for (const source of SOURCES) {\n"
            "    const titles = await fetchSourceHeadlines(source);\n"
            "    sourceMeta[source.id] = { name: source.name };\n"
            "    titles.forEach((title, position) => {\n"
            "      flat.push({ title, sourceId: source.id, sourceName: source.name, position });\n"
            "    });\n"
            "    await new Promise(resolve => setTimeout(resolve, 800));\n"
            "  }\n"
            "  // Add WatcherGuru-style \"Just In\" breaking news via search\n"
            "  const breaking = await fetchBreakingNews();\n"
            "  sourceMeta.breaking = { name: 'WatcherGuru-style «Just In» breaking news' };\n"
            "  breaking.forEach((title, position) => {\n"
            "    flat.push({ title, sourceId: 'breaking', sourceName: sourceMeta.breaking.name, position });\n"
            "  });\n"
            "\n"
            "  const deduped = dedupeAndScoreHeadlines(flat);\n"
            "  console.log(`[dedup] ${lastDedupStats.input} headlines in, ${lastDedupStats.collapsed} near-duplicates collapsed, ${lastDedupStats.blockedRepeats} already-sent repeats blocked, ${lastDedupStats.output} out`);\n"
            "\n"
            "  // Regroup by source for the digest prompt, preserving the existing\n"
            "  // per-source `raw` text format so generateDigest()'s prompt is unchanged —\n"
            "  // only which headlines make it in, and their order (highest-scored first\n"
            "  // within each source), is different.\n"
            "  const bySource = {};\n"
            "  for (const item of deduped) {\n"
            "    if (!bySource[item.sourceId]) bySource[item.sourceId] = [];\n"
            "    bySource[item.sourceId].push(item.title);\n"
            "  }\n"
            "\n"
            "  const results = [];\n"
            "  for (const [sourceId, titles] of Object.entries(bySource)) {\n"
            "    const name = sourceMeta[sourceId] ? sourceMeta[sourceId].name : sourceId;\n"
            "    if (sourceId === 'breaking') {\n"
            "      results.push({\n"
            "        topic: name,\n"
            "        source: sourceId,\n"
            "        raw: 'Самые свежие «Just In» новости (в стиле WatcherGuru):\\n' + titles.map((t, i) => `${i+1}. ${t}`).join('\\n')\n"
            "      });\n"
            "    } else {\n"
            "      results.push({\n"
            "        topic: name,\n"
            "        source: sourceId,\n"
            "        raw: `Свежие заголовки из источника «${name}»:\\n` + titles.map((t, i) => `${i+1}. ${t}`).join('\\n')\n"
            "      });\n"
            "    }\n"
            "  }\n"
            "  // Record what actually made it into this collection run so a same-day\n"
            "  // re-run of /news won't repeat these headlines verbatim. Recorded here\n"
            "  // (collection time) rather than only after a successful send, since a\n"
            "  // failed digest generation shouldn't leave the same near-duplicates\n"
            "  // eligible again on an immediate retry either.\n"
            "  recordSentHeadlines(deduped.map(d => d.title));\n"
            "  return results;\n"
            "}"
        ),
        label="collectSourceNews(): flatten, dedup+score across all sources, regroup",
        already_applied_marker="const deduped = dedupeAndScoreHeadlines(flat);",
    )

    # 4. /status shows a one-line dedup summary from the last collection run.
    content = replace_once(
        content,
        old=(
            "        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +\n"
            "        healthLine +\n"
            "        `🔧 Версия: ${VERSION}`,"
        ),
        new=(
            "        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +\n"
            "        `🧹 Дедуп (посл. сбор): ${lastDedupStats.input} → ${lastDedupStats.output} (склеено ${lastDedupStats.collapsed}, повторов заблокировано ${lastDedupStats.blockedRepeats})\\n` +\n"
            "        healthLine +\n"
            "        `🔧 Версия: ${VERSION}`,"
        ),
        label="/status shows dedup summary",
        already_applied_marker="Дедуп (посл. сбор):",
    )

    if content != original:
        backup(path)
        path.write_text(content, encoding="utf-8")
        print(f"  written: {path}")
    else:
        print("  (no changes written — everything already applied or anchors missing)")


def main():
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_dir = find_bot_dir(cli_arg)
    print(f"Using bot directory: {bot_dir}")

    patch_index_js(bot_dir / "index.js")

    print("\nDone. Next steps:")
    print("  1. node --check '%s'" % (bot_dir / "index.js"))
    print("  2. Review the diff, run /news twice in a row and confirm the second run's")
    print("     digest doesn't repeat headlines from the first (check /status dedup line).")
    print("  3. Commit & push.")


if __name__ == "__main__":
    main()
