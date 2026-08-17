#!/usr/bin/env python3
"""
Sprint 1 RECONSTRUCTION patch for brazil-news-bot (Boris).

⚠️ THIS IS NOT THE ORIGINAL apply_sprint1_patch.py. That script's text was
not available when this was written — only its byte-level anchors, inferred
from what apply_sprint2_patch.py and apply_sprint3_patch.py expect to find
in index.js (they hard-abort without it), plus the two-sentence summary in
handoff.md's "Спринт 1" entry. This script reconstructs the same *contract*
(exact function name, exact constant names, exact /reset behavior, exact
help/status text fragments) so sprint 2 and 3 apply cleanly on top of it.
The internal implementation (prompt wording, error handling style) is new
code written to match the codebase's existing conventions — it was not
recovered from the original. Treat this as a documented gap-fill, not a
restoration.

PREREQUISITE: none beyond sprint 0 (this targets the pre-sprint-1 index.js
shape: global boolean settings.awaitingFeedback, VERSION '14.1', no
generateConversationalReply). If sprint 1 (real or previously reconstructed)
is already applied, every step below is a no-op.

What this does:
  1. Adds CHAT_MODEL constant + VIBE_API_KEY-adjacent constants block,
     bumps VERSION 14.1 -> 14.2 (matches the version sprint 3 later bumps
     from, per its own anchor).
  2. Adds MAX_HISTORY_TURNS + conversationHistory Map (dialogId -> turns).
  3. Adds generateConversationalReply(dialogId, text, userName) — calls the
     same /v1/chat/completions endpoint generateDigest() uses, with a short
     system prompt establishing Boris's persona, plus the last
     MAX_HISTORY_TURNS turns for that dialog as context. Falls back to null
     on any API error so the caller can show a menu instead of a broken
     reply.
  4. Wires it into the message handler: when getCasualReply() (regex,
     personality.js) doesn't recognize the input, call the LLM instead of
     showing the static greeting menu. Trims conversationHistory to
     MAX_HISTORY_TURNS after each turn.
  5. Adds /reset command: clears conversationHistory for that dialog.
  6. /help and /status mention /reset and the LLM dialog feature, using the
     exact text fragments apply_sprint2_patch.py's anchors expect.
  7. process-level crash guards (uncaughtException / unhandledRejection) —
     log and keep the process alive rather than let one bad event kill
     the whole bot (the galaxy platform expects a long-lived server).

Usage:
    python3 apply_sprint1_reconstruction_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run multiple times. Backs up index.js before writing.
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
    print("       Pass the path explicitly: python3 apply_sprint1_reconstruction_patch.py /path/to/brazil-news-bot")
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

    # 1. Constants block: CHAT_MODEL + VERSION bump 14.1 -> 14.2
    content = replace_once(
        content,
        old=(
            "const BOT_NAME = 'Борис';\n"
            "const VERSION = '14.1';\n"
        ),
        new=(
            "const BOT_NAME = 'Борис';\n"
            "const VERSION = '14.2';\n"
            "\n"
            "// LLM model used both for the daily digest and for conversational replies.\n"
            "const CHAT_MODEL = 'bitrix/bitrixgpt-5.5';\n"
        ),
        label="add CHAT_MODEL, bump VERSION 14.1 -> 14.2",
        already_applied_marker="const CHAT_MODEL = 'bitrix/bitrixgpt-5.5';",
    )

    # 2. conversationHistory Map + MAX_HISTORY_TURNS, placed right after the
    #    settings load (mirrors where sprint 2 later adds the sibling
    #    awaitingFeedback Set, per its own anchor expectations).
    content = replace_once(
        content,
        old=(
            "// Bot settings (loaded from disk, falls back to defaults)\n"
            "let settings = loadSettings();"
        ),
        new=(
            "// Bot settings (loaded from disk, falls back to defaults)\n"
            "let settings = loadSettings();\n"
            "\n"
            "// Short-term memory for free-form (non-command) conversation, so replies\n"
            "// can refer back to what was just said instead of being stateless.\n"
            "const MAX_HISTORY_TURNS = 8; // user+assistant pairs kept per dialog\n"
            "const conversationHistory = new Map(); // dialogId -> [{role, content}, ...]"
        ),
        label="add MAX_HISTORY_TURNS + conversationHistory Map",
        already_applied_marker="const conversationHistory = new Map();",
    )

    # 3. generateConversationalReply() — placed right after generateDigest(),
    #    reusing the same HTTP call shape.
    content = replace_once(
        content,
        old=(
            "async function collectRawNews() {\n"
            "  const dates = getDates();"
        ),
        new=(
            "// Free-form conversational reply via LLM, used when personality.js's\n"
            "// regex patterns don't recognize the input. Keeps a short per-dialog\n"
            "// history so the bot can hold a real back-and-forth instead of answering\n"
            "// each message in isolation. Returns null on any failure so the caller\n"
            "// can fall back to the static menu instead of showing a broken reply.\n"
            "async function generateConversationalReply(dialogId, text, userName) {\n"
            "  const lang = settings.lang;\n"
            "  const name = (userName || '').trim().split(/\\s+/)[0];\n"
            "  const systemPrompt = lang === 'ru'\n"
            "    ? `Ты — Борис, дружелюбный AI-куратор интересных и трендовых новостей. ` +\n"
            "      `Ты уже поздоровался и объяснил, что умеешь, если это было нужно — сейчас просто ` +\n"
            "      `отвечай на сообщение пользователя живо, тепло и по делу, 1-3 предложения. ` +\n"
            "      `Если уместно, предложи посмотреть свежие истории (/news), тренды (/showtrends) ` +\n"
            "      `или случайную историю (/surprise). Не повторяй списки команд без необходимости.` +\n"
            "      (name ? ` Имя пользователя: ${name}.` : '')\n"
            "    : `Você é o Boris, um curador de notícias e tendências simpático e direto. ` +\n"
            "      `Responda à mensagem do usuário de forma calorosa e objetiva, em 1-3 frases. ` +\n"
            "      `Se fizer sentido, sugira ver histórias recentes (/news), tendências (/showtrends) ` +\n"
            "      `ou uma história aleatória (/surprise). Não repita listas de comandos sem necessidade.` +\n"
            "      (name ? ` Nome do usuário: ${name}.` : '');\n"
            "\n"
            "  const history = conversationHistory.get(dialogId) || [];\n"
            "  const messages = [\n"
            "    { role: 'system', content: systemPrompt },\n"
            "    ...history,\n"
            "    { role: 'user', content: text }\n"
            "  ];\n"
            "\n"
            "  try {\n"
            "    const result = await makeRequest('https://vibecode.bitrix24.tech/v1/chat/completions', {\n"
            "      method: 'POST',\n"
            "      headers: {\n"
            "        'X-Api-Key': VIBE_API_KEY,\n"
            "        'Content-Type': 'application/json'\n"
            "      },\n"
            "      body: {\n"
            "        model: CHAT_MODEL,\n"
            "        messages: messages,\n"
            "        temperature: 0.6,\n"
            "        max_tokens: 400\n"
            "      }\n"
            "    });\n"
            "\n"
            "    if (result.status === 200 && result.data && result.data.choices && result.data.choices[0]) {\n"
            "      const reply = result.data.choices[0].message.content;\n"
            "      const updated = [...history, { role: 'user', content: text }, { role: 'assistant', content: reply }];\n"
            "      // Keep only the last MAX_HISTORY_TURNS turns (each turn = 1 user + 1 assistant message)\n"
            "      conversationHistory.set(dialogId, updated.slice(-MAX_HISTORY_TURNS * 2));\n"
            "      return reply;\n"
            "    }\n"
            "    console.error('Conversational AI error:', result.status, JSON.stringify(result.data).substring(0, 300));\n"
            "    return null;\n"
            "  } catch (error) {\n"
            "    console.error('Conversational AI failed:', error.message);\n"
            "    return null;\n"
            "  }\n"
            "}\n"
            "\n"
            "async function collectRawNews() {\n"
            "  const dates = getDates();"
        ),
        label="add generateConversationalReply()",
        already_applied_marker="async function generateConversationalReply(",
    )

    # 4. Wire into message handler: LLM fallback instead of static menu when
    #    getCasualReply() returns null.
    content = replace_once(
        content,
        old=(
            "          const casual = getCasualReply(text, data.user?.name);\n"
            "          if (casual) {\n"
            "            await sendBotMessage(dialogId, casual.text, casual.keyboard || getMainKeyboard());\n"
            "          } else {\n"
            "            const h = new Date().getHours();\n"
            "            const greet = h >= 5 && h < 12 ? 'Доброе утро' : (h >= 12 && h < 18 ? 'Добрый день' : 'Добрый вечер');\n"
            "            const who = (data.user?.name || '').trim().split(/\\s+/)[0];\n"
            "            await sendBotMessage(dialogId,\n"
            "              `${greet}${who ? ', ' + who : ''}! Я Борис ✨ — твой куратор интересных историй.\\n\\n` +\n"
            "              `Могу показать свежие истории, тренды или рассказать о себе. С чего начнём?\\n\\n` +\n"
            "              `• ✨ Интересное сейчас — /news\\n` +\n"
            "              `• 🔥 Тренды — /showtrends\\n` +\n"
            "              `• 🎲 Случайная история — /surprise\\n` +\n"
            "              `• 💬 «Что ты умеешь?» — о моих возможностях`,\n"
            "              getMainKeyboard());\n"
            "          }"
        ),
        new=(
            "          const casual = getCasualReply(text, data.user?.name);\n"
            "          if (casual) {\n"
            "            await sendBotMessage(dialogId, casual.text, casual.keyboard || getMainKeyboard());\n"
            "          } else {\n"
            "            // Not a recognized regex pattern — hand off to the LLM for a real\n"
            "            // conversational reply instead of always showing the static menu.\n"
            "            await showTyping(dialogId, 'IMBOT_AGENT_ACTION_THINKING', 20);\n"
            "            const aiReply = await generateConversationalReply(dialogId, text, data.user?.name);\n"
            "            if (aiReply) {\n"
            "              await sendBotMessage(dialogId, aiReply, getMainKeyboard());\n"
            "            } else {\n"
            "              const h = new Date().getHours();\n"
            "              const greet = h >= 5 && h < 12 ? 'Доброе утро' : (h >= 12 && h < 18 ? 'Добрый день' : 'Добрый вечер');\n"
            "              const who = (data.user?.name || '').trim().split(/\\s+/)[0];\n"
            "              await sendBotMessage(dialogId,\n"
            "                `${greet}${who ? ', ' + who : ''}! Я Борис ✨ — твой куратор интересных историй.\\n\\n` +\n"
            "                `Могу показать свежие истории, тренды или рассказать о себе. С чего начнём?\\n\\n` +\n"
            "                `• ✨ Интересное сейчас — /news\\n` +\n"
            "                `• 🔥 Тренды — /showtrends\\n` +\n"
            "                `• 🎲 Случайная история — /surprise\\n` +\n"
            "                `• 💬 «Что ты умеешь?» — о моих возможностях`,\n"
            "                getMainKeyboard());\n"
            "            }\n"
            "          }"
        ),
        label="message handler: LLM fallback instead of static menu",
        already_applied_marker="const aiReply = await generateConversationalReply(",
    )

    # 5. /help mentions /reset (exact fragment sprint 2 later extends with
    #    /sourcehealth) + /reset command case (exact fragment sprint 2's
    #    /status block anchor expects immediately after it).
    content = replace_once(
        content,
        old=(
            "        '• /feedback good|bad — оценка\\n\\n' +\n"
            "        '*Темы:*\\n' +"
        ),
        new=(
            "        '• /feedback good|bad — оценка\\n' +\n"
            "        '• /reset — очистить память диалога\\n\\n' +\n"
            "        '*Темы:*\\n' +"
        ),
        label="/help mentions /reset",
        already_applied_marker="'• /reset — очистить память диалога\\n\\n' +",
    )

    content = replace_once(
        content,
        old=(
            "    case 'status':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `📊 *Статус Бориса*\\n\\n` +\n"
            "        `✅ Бот активен\\n` +\n"
            "        `📰 Тем: ${settings.topics.length}\\n` +\n"
            "        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +\n"
            "        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +\n"
            "        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +\n"
            "        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +\n"
            "        `🧠 AI-генерация: включена\\n` +\n"
            "        `🔧 Версия: ${VERSION}`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;\n"
            "      \n"
            "    case 'lang':"
        ),
        new=(
            "    case 'status':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `📊 *Статус Бориса*\\n\\n` +\n"
            "        `✅ Бот активен\\n` +\n"
            "        `📰 Тем: ${settings.topics.length}\\n` +\n"
            "        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +\n"
            "        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +\n"
            "        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +\n"
            "        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +\n"
            "        `🧠 AI-генерация дайджеста: включена\\n` +\n"
            "        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +\n"
            "        `🔧 Версия: ${VERSION}`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;\n"
            "\n"
            "    case 'reset':\n"
            "      conversationHistory.delete(dialogId);\n"
            "      await sendBotMessage(dialogId, '🧹 Память этого диалога очищена. Начинаем с чистого листа!', getMainKeyboard());\n"
            "      break;\n"
            "      \n"
            "    case 'lang':"
        ),
        label="/status mentions LLM dialog + /reset command",
        already_applied_marker="case 'reset':",
    )

    # 6. Process-level crash guards — placed right before server.listen(...).
    content = replace_once(
        content,
        old=(
            "server.listen(PORT, () => {"
        ),
        new=(
            "// Keep the long-lived server process alive through unexpected errors —\n"
            "// one bad event/message should not take the whole bot down until the\n"
            "// next scheduled wake-up.\n"
            "process.on('uncaughtException', (err) => {\n"
            "  console.error('[fatal-ish] uncaughtException:', err && err.stack || err);\n"
            "});\n"
            "process.on('unhandledRejection', (reason) => {\n"
            "  console.error('[fatal-ish] unhandledRejection:', reason);\n"
            "});\n"
            "\n"
            "server.listen(PORT, () => {"
        ),
        label="process-level crash guards",
        already_applied_marker="process.on('uncaughtException'",
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
    print("  2. Review the diff, then run apply_sprint2_patch.py and apply_sprint3_patch.py.")


if __name__ == "__main__":
    main()
