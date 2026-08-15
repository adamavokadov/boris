#!/usr/bin/env python3
"""
Sprint 2 patch for brazil-news-bot (Boris).

PREREQUISITE: run apply_sprint1_patch.py first (this patch's anchors assume
the sprint 1 changes — conversationHistory, CHAT_MODEL, /reset, etc. — are
already applied). Running this against a pre-sprint-1 index.js will just
warn and skip every step.

What this does:
  1. Source scrape health tracking
     - Adds settings.sourceHealth (persisted): consecutive-empty-fetch streak
       and last-success timestamp per source.
     - recordSourceHealth()/getUnhealthySources() helpers.
     - Wires health recording into fetchSourceHeadlines() (the 5 RSS/HTML
       SOURCES), fetchTrends24(), and fetchGoogleTrends() — the three
       regex/HTML scrapers that can silently start returning 0 items forever
       if a site changes its markup.
     - New /sourcehealth command: per-source 🟢/🟡/🔴 status.
     - /status now shows a one-line health summary and points to
       /sourcehealth when something is degraded.
     - /help mentions /sourcehealth.

  2. Fix global awaitingFeedback race condition
     - `settings.awaitingFeedback` was a single process-wide boolean: a 👎
       in one dialog, followed by an unrelated message in a *different*
       dialog, would wrongly record that unrelated message as a dislike and
       leave the original dialog stuck waiting forever.
     - Replaced with a per-dialog `Set` (awaitingFeedback.add/has/delete),
       same pattern as the sprint 1 conversationHistory Map. Removed the
       field from DEFAULT_SETTINGS/persisted settings entirely — it's
       in-memory only now (matches conversationHistory's lifetime).

Usage:
    python3 apply_sprint2_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run twice. Writes a timestamped .bak of every file it
touches before modifying it.
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
    print("       Pass the path explicitly: python3 apply_sprint2_patch.py /path/to/brazil-news-bot")
    sys.exit(1)


def backup(path: Path):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, bak)
    print(f"  backup: {bak.name}")


def replace_once(content, old, new, label, already_applied_marker, required=True):
    if already_applied_marker in content:
        print(f"  [skip] {label} (already applied)")
        return content
    count = content.count(old)
    if count == 0:
        level = "ERROR" if required else "WARN"
        print(f"  [{level}] {label}: anchor text not found — skipping.")
        if required:
            print(f"         This usually means sprint 1's patch hasn't been applied yet.")
            print(f"         Run apply_sprint1_patch.py first, then retry this script.")
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

    # --- Pre-flight: refuse to run partially against a pre-sprint-1 file ---
    # Several of this patch's edits are independent of each other and would
    # otherwise apply even without sprint 1 in place, leaving the file in an
    # inconsistent state (e.g. recordSourceHealth() wired in, but the
    # awaitingFeedback Set it needs never declared -> ReferenceError at
    # runtime, which `node --check` would NOT catch since it's syntactically
    # valid). Require the sprint 1 marker up front and do nothing at all if
    # it's missing, rather than applying some hunks and skipping others.
    SPRINT1_MARKER = "async function generateConversationalReply("
    if SPRINT1_MARKER not in content:
        print("  [ABORT] sprint 1 changes not found in this file (no generateConversationalReply()).")
        print("          Run apply_sprint1_patch.py first — sprint 2 depends on it and refuses")
        print("          to apply a partial patch. No changes were made.")
        return

    # 1. DEFAULT_SETTINGS: drop awaitingFeedback field, add sourceHealth
    content = replace_once(
        content,
        old=(
            "  feedback: {\n"
            "    good: 0,\n"
            "    bad: 0,\n"
            "    dislikes: []\n"
            "  },\n"
            "  awaitingFeedback: false\n"
            "};"
        ),
        new=(
            "  feedback: {\n"
            "    good: 0,\n"
            "    bad: 0,\n"
            "    dislikes: []\n"
            "  },\n"
            "  // Per-source scrape health: lets /status and /sourcehealth surface silent\n"
            "  // degradation (e.g. a site changes its HTML and our regex extractor\n"
            "  // starts returning 0 headlines) instead of failing invisibly forever.\n"
            "  sourceHealth: {}\n"
            "};"
        ),
        label="DEFAULT_SETTINGS: drop awaitingFeedback, add sourceHealth",
        already_applied_marker="sourceHealth: {}\n};",
    )

    # 2. Add awaitingFeedback Set next to conversationHistory
    content = replace_once(
        content,
        old=(
            "const MAX_HISTORY_TURNS = 8; // user+assistant pairs kept per dialog\n"
            "const conversationHistory = new Map(); // dialogId -> [{role, content}, ...]"
        ),
        new=(
            "const MAX_HISTORY_TURNS = 8; // user+assistant pairs kept per dialog\n"
            "const conversationHistory = new Map(); // dialogId -> [{role, content}, ...]\n"
            "\n"
            "// Was `settings.awaitingFeedback` (a single global boolean) — that meant a\n"
            "// 👎 in one dialog, followed by an unrelated message in a *different*\n"
            "// dialog, would wrongly record that unrelated message as a dislike, and\n"
            "// leave the original dialog stuck waiting forever. Track it per-dialog\n"
            "// instead, same pattern as conversationHistory.\n"
            "const awaitingFeedback = new Set(); // dialogIds currently waiting for a \"what didn't you like?\" reply"
        ),
        label="add per-dialog awaitingFeedback Set",
        already_applied_marker="const awaitingFeedback = new Set();",
    )

    # 3. Health tracking helpers + wire into fetchSourceHeadlines
    content = replace_once(
        content,
        old='''async function fetchSourceHeadlines(source) {
  // Retry once to handle transient network/TLS failures
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const result = await makeRequest(source.url, {
        method: 'GET',
        headers: {
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml'
        }
      });
      if (result.status !== 200) {
        console.error(`[source:${source.id}] fetch error: ${result.status}`);
        if (attempt === 1) { await new Promise(r => setTimeout(r, 1500)); continue; }
        return [];
      }
      const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);
      const titles = source.extract(html);
      console.log(`[source:${source.id}] extracted ${titles.length} headlines`);
      return titles;
    } catch (error) {
      console.error(`[source:${source.id}] attempt ${attempt} failed: ${error.message}`);
      if (attempt === 1) { await new Promise(r => setTimeout(r, 1500)); continue; }
      return [];
    }
  }
  return [];
}''',
        new='''// --- Source scrape health tracking -----------------------------------------
// Regex/HTML scraping is brittle: a site can change its markup and the
// extractor silently starts returning 0 items forever, with nothing but a
// buried log line to notice it. Track consecutive-empty-fetch streaks per
// source (persisted in settings) so degradation becomes visible in
// /status and /sourcehealth instead of failing invisibly.
const SOURCE_HEALTH_ALERT_THRESHOLD = 3; // consecutive empty fetches -> "red"

function recordSourceHealth(sourceId, itemCount, errorMessage) {
  if (!settings.sourceHealth) settings.sourceHealth = {};
  const prev = settings.sourceHealth[sourceId] || { consecutiveEmpty: 0, lastSuccessAt: null, lastError: null };
  const now = new Date().toISOString();
  if (itemCount > 0) {
    settings.sourceHealth[sourceId] = {
      consecutiveEmpty: 0,
      lastSuccessAt: now,
      lastCount: itemCount,
      lastError: null
    };
  } else {
    const consecutiveEmpty = (prev.consecutiveEmpty || 0) + 1;
    settings.sourceHealth[sourceId] = {
      consecutiveEmpty,
      lastSuccessAt: prev.lastSuccessAt || null,
      lastCount: 0,
      lastError: errorMessage || prev.lastError || null
    };
    if (consecutiveEmpty === SOURCE_HEALTH_ALERT_THRESHOLD) {
      console.error(`[sourcehealth] "${sourceId}" has returned 0 items ${consecutiveEmpty}x in a row — likely broken extractor or dead source.`);
    }
  }
  saveSettings();
}

function getUnhealthySources() {
  if (!settings.sourceHealth) return [];
  return Object.entries(settings.sourceHealth)
    .filter(([, h]) => (h.consecutiveEmpty || 0) >= SOURCE_HEALTH_ALERT_THRESHOLD)
    .map(([id, h]) => ({ id, ...h }));
}

async function fetchSourceHeadlines(source) {
  // Retry once to handle transient network/TLS failures
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const result = await makeRequest(source.url, {
        method: 'GET',
        headers: {
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml'
        }
      });
      if (result.status !== 200) {
        console.error(`[source:${source.id}] fetch error: ${result.status}`);
        if (attempt === 1) { await new Promise(r => setTimeout(r, 1500)); continue; }
        recordSourceHealth(source.id, 0, `HTTP ${result.status}`);
        return [];
      }
      const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);
      const titles = source.extract(html);
      console.log(`[source:${source.id}] extracted ${titles.length} headlines`);
      recordSourceHealth(source.id, titles.length, titles.length === 0 ? 'extractor returned 0 items' : null);
      return titles;
    } catch (error) {
      console.error(`[source:${source.id}] attempt ${attempt} failed: ${error.message}`);
      if (attempt === 1) { await new Promise(r => setTimeout(r, 1500)); continue; }
      recordSourceHealth(source.id, 0, error.message);
      return [];
    }
  }
  return [];
}''',
        label="health-tracking helpers + wire into fetchSourceHeadlines()",
        already_applied_marker="function recordSourceHealth(sourceId, itemCount, errorMessage) {",
    )

    # 4. Wire health tracking into fetchTrends24()
    content = replace_once(
        content,
        old=(
            "    if (unique.length === 0) {\n"
            "      console.log('No trends extracted from trends24');\n"
            "      return [];\n"
            "    }\n"
            "    \n"
            "    console.log(`Extracted ${unique.length} real trends from trends24.in`);\n"
            "    return [{\n"
            "      topic: 'Tendências reais (trends24.in/brazil)',\n"
            "      raw: 'Tendências reais do X/Twitter no Brasil nas últimas 24 horas:\\n' + unique.join(', ')\n"
            "    }];\n"
            "  } catch (error) {\n"
            "    console.error('fetchTrends24 failed:', error.message);\n"
            "    return [];\n"
            "  }\n"
            "}"
        ),
        new=(
            "    if (unique.length === 0) {\n"
            "      console.log('No trends extracted from trends24');\n"
            "      recordSourceHealth('trends24', 0, 'extractor returned 0 items');\n"
            "      return [];\n"
            "    }\n"
            "    \n"
            "    console.log(`Extracted ${unique.length} real trends from trends24.in`);\n"
            "    recordSourceHealth('trends24', unique.length, null);\n"
            "    return [{\n"
            "      topic: 'Tendências reais (trends24.in/brazil)',\n"
            "      raw: 'Tendências reais do X/Twitter no Brasil nas últimas 24 horas:\\n' + unique.join(', ')\n"
            "    }];\n"
            "  } catch (error) {\n"
            "    console.error('fetchTrends24 failed:', error.message);\n"
            "    recordSourceHealth('trends24', 0, error.message);\n"
            "    return [];\n"
            "  }\n"
            "}"
        ),
        label="wire health tracking into fetchTrends24()",
        already_applied_marker="recordSourceHealth('trends24', unique.length, null);",
    )

    # 5. Wire health tracking into fetchGoogleTrends()
    content = replace_once(
        content,
        old=(
            "    if (result.status !== 200) {\n"
            "      console.error('google trends fetch error:', result.status);\n"
            "      return [];\n"
            "    }\n"
            "    const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);\n"
            "    const titles = html.match(/<title>(.*?)<\\/title>/gs) || [];\n"
            "    const trends = titles.map(t => {\n"
            "      const m = t.match(/<title>(.*?)<\\/title>/s);\n"
            "      return m ? m[1].replace(/<!\\[CDATA\\[|\\]\\]>/g, '').replace(/&amp;/g, '&').trim() : '';\n"
            "    }).filter(t => t.length > 2 && !/Daily Search Trends|Google/i.test(t)).slice(0, 10);\n"
            "    if (trends.length === 0) return [];\n"
            "    console.log(`Extracted ${trends.length} real-time trends from Google Trends`);\n"
            "    return [{\n"
            "      topic: 'Google Trends Brasil (realtime)',\n"
            "      raw: 'Что ищут бразильцы прямо сейчас (Google Trends, последние 4 часа):\\n' + trends.join(', ')\n"
            "    }];\n"
            "  } catch (error) {\n"
            "    console.error('fetchGoogleTrends failed:', error.message);\n"
            "    return [];\n"
            "  }\n"
            "}"
        ),
        new=(
            "    if (result.status !== 200) {\n"
            "      console.error('google trends fetch error:', result.status);\n"
            "      recordSourceHealth('google_trends', 0, `HTTP ${result.status}`);\n"
            "      return [];\n"
            "    }\n"
            "    const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);\n"
            "    const titles = html.match(/<title>(.*?)<\\/title>/gs) || [];\n"
            "    const trends = titles.map(t => {\n"
            "      const m = t.match(/<title>(.*?)<\\/title>/s);\n"
            "      return m ? m[1].replace(/<!\\[CDATA\\[|\\]\\]>/g, '').replace(/&amp;/g, '&').trim() : '';\n"
            "    }).filter(t => t.length > 2 && !/Daily Search Trends|Google/i.test(t)).slice(0, 10);\n"
            "    if (trends.length === 0) {\n"
            "      recordSourceHealth('google_trends', 0, 'extractor returned 0 items');\n"
            "      return [];\n"
            "    }\n"
            "    console.log(`Extracted ${trends.length} real-time trends from Google Trends`);\n"
            "    recordSourceHealth('google_trends', trends.length, null);\n"
            "    return [{\n"
            "      topic: 'Google Trends Brasil (realtime)',\n"
            "      raw: 'Что ищут бразильцы прямо сейчас (Google Trends, последние 4 часа):\\n' + trends.join(', ')\n"
            "    }];\n"
            "  } catch (error) {\n"
            "    console.error('fetchGoogleTrends failed:', error.message);\n"
            "    recordSourceHealth('google_trends', 0, error.message);\n"
            "    return [];\n"
            "  }\n"
            "}"
        ),
        label="wire health tracking into fetchGoogleTrends()",
        already_applied_marker="recordSourceHealth('google_trends', trends.length, null);",
    )

    # 6. /help mentions /sourcehealth
    content = replace_once(
        content,
        old=(
            "        '• /feedback good|bad — оценка\\n' +\n"
            "        '• /reset — очистить память диалога\\n\\n' +\n"
            "        '*Темы:*\\n' +"
        ),
        new=(
            "        '• /feedback good|bad — оценка\\n' +\n"
            "        '• /reset — очистить память диалога\\n' +\n"
            "        '• /sourcehealth — состояние источников новостей\\n\\n' +\n"
            "        '*Темы:*\\n' +"
        ),
        label="/help mentions /sourcehealth",
        already_applied_marker="'• /sourcehealth — состояние источников новостей\\n\\n' +",
    )

    # 7. /status shows source health summary + new /sourcehealth command,
    #    and awaitingFeedback usages become per-dialog (Set) instead of
    #    settings.awaitingFeedback (boolean).
    content = replace_once(
        content,
        old='''    case 'status':
      await sendBotMessage(dialogId,
        `📊 *Статус Бориса*\\n\\n` +
        `✅ Бот активен\\n` +
        `📰 Тем: ${settings.topics.length}\\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +
        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +
        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +
        `🧠 AI-генерация дайджеста: включена\\n` +
        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +
        `🔧 Версия: ${VERSION}`,
        getMainKeyboard()
      );
      break;

    case 'reset':
      conversationHistory.delete(dialogId);
      await sendBotMessage(dialogId, '🧹 Память этого диалога очищена. Начинаем с чистого листа!', getMainKeyboard());
      break;
      
    case 'lang':''',
        new='''    case 'status':
      const unhealthy = getUnhealthySources();
      const healthLine = unhealthy.length > 0
        ? `⚠️ Проблемные источники (0 результатов ${SOURCE_HEALTH_ALERT_THRESHOLD}+ раз подряд): ${unhealthy.map(h => h.id).join(', ')} — см. /sourcehealth\\n`
        : `✅ Все источники в норме\\n`;
      await sendBotMessage(dialogId,
        `📊 *Статус Бориса*\\n\\n` +
        `✅ Бот активен\\n` +
        `📰 Тем: ${settings.topics.length}\\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +
        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +
        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +
        `🧠 AI-генерация дайджеста: включена\\n` +
        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +
        healthLine +
        `🔧 Версия: ${VERSION}`,
        getMainKeyboard()
      );
      break;

    case 'sourcehealth':
      const allIds = [...SOURCES.map(s => s.id), 'trends24', 'google_trends'];
      const lines = allIds.map(id => {
        const h = (settings.sourceHealth && settings.sourceHealth[id]) || null;
        if (!h || (h.lastSuccessAt === null && (h.consecutiveEmpty || 0) === 0)) {
          return `⚪ ${id} — ещё не запускался`;
        }
        const icon = (h.consecutiveEmpty || 0) >= SOURCE_HEALTH_ALERT_THRESHOLD ? '🔴' : ((h.consecutiveEmpty || 0) > 0 ? '🟡' : '🟢');
        const lastOk = h.lastSuccessAt ? new Date(h.lastSuccessAt).toLocaleString('pt-BR') : 'никогда';
        const streak = h.consecutiveEmpty > 0 ? `, ${h.consecutiveEmpty} пустых подряд` : '';
        return `${icon} ${id} — посл. успех: ${lastOk}${streak}`;
      });
      await sendBotMessage(dialogId,
        `🩺 *Здоровье источников*\\n\\n${lines.join('\\n')}\\n\\n` +
        `🔴 = вероятно сломан экстрактор/сайт изменился (${SOURCE_HEALTH_ALERT_THRESHOLD}+ пустых подряд)\\n` +
        `🟡 = недавно были пустые ответы, но не критично\\n` +
        `🟢 = работает нормально`,
        getMainKeyboard()
      );
      break;

    case 'reset':
      conversationHistory.delete(dialogId);
      await sendBotMessage(dialogId, '🧹 Память этого диалога очищена. Начинаем с чистого листа!', getMainKeyboard());
      break;
      
    case 'lang':''',
        label="/status health summary + new /sourcehealth command",
        already_applied_marker="case 'sourcehealth':",
    )

    # 8. feedback bad handler: settings.awaitingFeedback -> awaitingFeedback.add(dialogId)
    content = replace_once(
        content,
        old=(
            "      } else if (params === 'bad') {\n"
            "        settings.feedback.bad++;\n"
            "        settings.awaitingFeedback = true;\n"
            "        saveSettings();"
        ),
        new=(
            "      } else if (params === 'bad') {\n"
            "        settings.feedback.bad++;\n"
            "        awaitingFeedback.add(dialogId);\n"
            "        saveSettings();"
        ),
        label="/feedback bad uses per-dialog awaitingFeedback.add()",
        already_applied_marker="awaitingFeedback.add(dialogId);",
    )

    # 9. message handler: settings.awaitingFeedback -> awaitingFeedback.has/delete(dialogId)
    content = replace_once(
        content,
        old=(
            "        // If we just asked \"what didn't you like?\", capture the reply as a dislike\n"
            "        if (settings.awaitingFeedback) {\n"
            "          settings.awaitingFeedback = false;\n"
            "          settings.feedback.dislikes.push(text.trim());"
        ),
        new=(
            "        // If we just asked \"what didn't you like?\" *in this dialog*, capture\n"
            "        // the reply as a dislike. Per-dialog (not global) so an unrelated\n"
            "        // message in another dialog can't be mistaken for feedback.\n"
            "        if (awaitingFeedback.has(dialogId)) {\n"
            "          awaitingFeedback.delete(dialogId);\n"
            "          settings.feedback.dislikes.push(text.trim());"
        ),
        label="message handler uses per-dialog awaitingFeedback.has()/delete()",
        already_applied_marker="if (awaitingFeedback.has(dialogId)) {",
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
    print("  1. Review the diff: git -C '%s' diff" % bot_dir)
    print("  2. Syntax-check:    node --check '%s'" % (bot_dir / "index.js"))
    print("  3. Commit & push (see accompanying shell commands).")


if __name__ == "__main__":
    main()
