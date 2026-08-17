#!/usr/bin/env python3
"""
Sprint 5 patch for brazil-news-bot (Boris) — interactive settings UI.

PREREQUISITE: sprint 0-3 (or the sprint 1 reconstruction) must already be
applied — this patch's anchors are the post-sprint-3 shape of index.js
(VERSION '14.3', /sourcehealth, /reset, per-dialog awaitingFeedback Set).
Hard-aborts (does nothing) if that shape isn't found.

What this does:
  Replaces the "type a slash command with arguments" flow for settings,
  topics, schedule, and source health with tappable keyboards, so nothing
  in those four screens requires the user to type anything by hand (adding
  a new topic is the one exception — Bitrix24 has no text-input keyboard
  button type, so that still asks for a follow-up message, exactly like
  the existing "what didn't you like?" feedback flow already does).

  1. getSettingsKeyboard() — toggle language / trends / autosend with one
     tap each, plus buttons into the Topics and Schedule sub-screens.
  2. getTopicsKeyboard() — one ❌ button per topic (removes it immediately,
     no need to type/retype the exact topic name) + "add a topic" + back.
     Guarded: if there are more than MAX_TOPIC_BUTTONS topics, falls back
     to the existing plain-text numbered list (still with an add/back
     keyboard) rather than emitting a huge, unreliable keyboard.
  3. getScheduleKeyboard() — a few common send-time presets as one-tap
     buttons, plus on/off and back. /settime <HH:MM> still works too, for
     any time not in the presets.
  4. getSourceHealthKeyboard() — refresh (re-runs /sourcehealth) + back.
  5. /settings, /topics, /schedule, /sourcehealth, and /help now show
     their matching contextual keyboard instead of always getMainKeyboard().
  6. New /menu command (also reachable via a "⬅️ Назад" button) — same
     text as /start's greeting, using getMainKeyboard(). Gives every
     sub-screen a way back to the top without retyping "/start".
  7. "➕ Добавить тему" now actually works in one tap + one message: it
     puts the dialog into an `awaitingTopic` state (same Set-based pattern
     sprint 2 already uses for awaitingFeedback), then the next plain-text
     message the user sends is captured as the new topic — no need to type
     "/addtopic <тема>" by hand. /addtopic <тема> with an argument still
     works exactly as before, unchanged.

  Existing text commands (/lang, /trends, /addtopic, /removetopic,
  /settime, /on, /off) are UNCHANGED and keep working exactly as before —
  the buttons just send those same commands, so this is purely additive.

Usage:
    python3 apply_sprint5_patch.py [path/to/brazil-news-bot]

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
    print("       Pass the path explicitly: python3 apply_sprint5_patch.py /path/to/brazil-news-bot")
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

    # --- Pre-flight: refuse to run against a pre-sprint-3 file ---
    PREREQ_MARKER = "case 'sourcehealth':"
    if PREREQ_MARKER not in content:
        print("  [ABORT] sprint 0-3 changes not found in this file (no /sourcehealth command).")
        print("          Run sprint 0-3 (or apply_sprint1_reconstruction_patch.py +")
        print("          apply_sprint2_patch.py + apply_sprint3_patch.py) first.")
        print("          No changes were made.")
        return

    # 1. awaitingTopic Set, added right next to awaitingFeedback (same
    #    per-dialog pattern sprint 2 established).
    content = replace_once(
        content,
        old=(
            "const awaitingFeedback = new Set(); // dialogIds currently waiting for a \"what didn't you like?\" reply"
        ),
        new=(
            "const awaitingFeedback = new Set(); // dialogIds currently waiting for a \"what didn't you like?\" reply\n"
            "const awaitingTopic = new Set(); // dialogIds currently waiting for a new topic name (via the \"➕ Добавить тему\" button)"
        ),
        label="add per-dialog awaitingTopic Set",
        already_applied_marker="const awaitingTopic = new Set();",
    )

    # 2. New keyboards, added right after getFeedbackKeyboard().
    content = replace_once(
        content,
        old=(
            "function getFeedbackKeyboard() {\n"
            "  return [\n"
            "    { TEXT: '👍 Полезно', ACTION: 'SEND', ACTION_VALUE: '/feedback good', BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '👎 Не понравилось', ACTION: 'SEND', ACTION_VALUE: '/feedback bad', BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' }\n"
            "  ];\n"
            "}\n"
        ),
        new=(
            "function getFeedbackKeyboard() {\n"
            "  return [\n"
            "    { TEXT: '👍 Полезно', ACTION: 'SEND', ACTION_VALUE: '/feedback good', BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '👎 Не понравилось', ACTION: 'SEND', ACTION_VALUE: '/feedback bad', BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' }\n"
            "  ];\n"
            "}\n"
            "\n"
            "// Bitrix24 has no text-input keyboard button, so any settings screen that\n"
            "// needs free-form text (adding a topic, a custom time) still falls back to\n"
            "// asking for a typed reply — same pattern as the /feedback bad flow.\n"
            "const MAX_TOPIC_BUTTONS = 15; // above this, a per-topic keyboard gets unwieldy\n"
            "\n"
            "// Settings hub: one-tap toggles + links into the Topics/Schedule sub-screens.\n"
            "function getSettingsKeyboard() {\n"
            "  return [\n"
            "    { TEXT: settings.lang === 'ru' ? '🌐 Язык: RU → PT' : '🌐 Idioma: PT → RU', ACTION: 'SEND', ACTION_VALUE: settings.lang === 'ru' ? '/lang pt' : '/lang ru', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: settings.includeTrends ? '🔥 Тренды: выкл' : '🔥 Тренды: вкл', ACTION: 'SEND', ACTION_VALUE: '/trends', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: settings.autoSend ? '⏰ Автосбор: выкл' : '⏰ Автосбор: вкл', ACTION: 'SEND', ACTION_VALUE: settings.autoSend ? '/off' : '/on', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '📚 Темы', ACTION: 'SEND', ACTION_VALUE: '/topics', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '⏱ Расписание', ACTION: 'SEND', ACTION_VALUE: '/schedule', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/menu', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }\n"
            "  ];\n"
            "}\n"
            "\n"
            "// One ❌ button per topic (removes it with a single tap, no retyping the\n"
            "// exact topic string) + add/back. Falls back to no per-topic buttons if the\n"
            "// list has grown past MAX_TOPIC_BUTTONS, to keep the keyboard usable.\n"
            "function getTopicsKeyboard() {\n"
            "  const buttons = [];\n"
            "  if (settings.topics.length <= MAX_TOPIC_BUTTONS) {\n"
            "    for (const t of settings.topics) {\n"
            "      buttons.push({ TEXT: `❌ ${t}`, ACTION: 'SEND', ACTION_VALUE: `/removetopic ${t}`, BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' });\n"
            "    }\n"
            "  }\n"
            "  buttons.push({ TEXT: '➕ Добавить тему', ACTION: 'SEND', ACTION_VALUE: '/addtopic', BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' });\n"
            "  buttons.push({ TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/settings', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });\n"
            "  return buttons;\n"
            "}\n"
            "\n"
            "// Common send-time presets as one-tap buttons; /settime <HH:MM> still works\n"
            "// for anything not in this list.\n"
            "const SCHEDULE_TIME_PRESETS = ['08:00', '09:00', '09:20', '10:00'];\n"
            "function getScheduleKeyboard() {\n"
            "  const buttons = SCHEDULE_TIME_PRESETS.map(t => ({\n"
            "    TEXT: t === settings.time ? `✅ ${t}` : t,\n"
            "    ACTION: 'SEND',\n"
            "    ACTION_VALUE: `/settime ${t}`,\n"
            "    BG_COLOR_TOKEN: t === settings.time ? 'primary' : 'secondary',\n"
            "    DISPLAY: 'LINE'\n"
            "  }));\n"
            "  buttons.push({ TEXT: settings.autoSend ? '⏸ Выключить автосбор' : '▶️ Включить автосбор', ACTION: 'SEND', ACTION_VALUE: settings.autoSend ? '/off' : '/on', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });\n"
            "  buttons.push({ TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/settings', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });\n"
            "  return buttons;\n"
            "}\n"
            "\n"
            "function getSourceHealthKeyboard() {\n"
            "  return [\n"
            "    { TEXT: '🔄 Обновить', ACTION: 'SEND', ACTION_VALUE: '/sourcehealth', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },\n"
            "    { TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/menu', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }\n"
            "  ];\n"
            "}\n"
        ),
        label="add getSettingsKeyboard/getTopicsKeyboard/getScheduleKeyboard/getSourceHealthKeyboard",
        already_applied_marker="function getSourceHealthKeyboard() {",
    )

    # 2. /settings uses getSettingsKeyboard()
    content = replace_once(
        content,
        old=(
            "    case 'settings':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `⚙️ *Настройки Бориса*\\n\\n` +\n"
            "        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'} (/lang pt|ru)\\n` +\n"
            "        `🔥 Тренды: ${settings.includeTrends ? 'вкл' : 'выкл'} (/trends)\\n` +\n"
            "        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone}) (/on|/off)\\n` +\n"
            "        `📰 Тем: ${settings.topics.length} (/topics)\\n\\n` +\n"
            "        `*Команды:*\\n` +\n"
            "        `• /lang pt|ru — язык\\n` +\n"
            "        `• /trends — вкл/выкл тренды\\n` +\n"
            "        `• /addtopic <тема> — добавить тему\\n` +\n"
            "        `• /removetopic <тема> — убрать тему\\n` +\n"
            "        `• /settime <ЧЧ:ММ> — время\\n` +\n"
            "        `• /on|/off — автосбор\\n` +\n"
            "        `• /feedback good|bad — оценка`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;"
        ),
        new=(
            "    case 'settings':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `⚙️ *Настройки Бориса*\\n\\n` +\n"
            "        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +\n"
            "        `🔥 Тренды: ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +\n"
            "        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +\n"
            "        `📰 Тем: ${settings.topics.length}\\n\\n` +\n"
            "        `Нажми кнопку, чтобы изменить — или используй команды из /help.`,\n"
            "        getSettingsKeyboard()\n"
            "      );\n"
            "      break;"
        ),
        label="/settings uses getSettingsKeyboard()",
        already_applied_marker="getSettingsKeyboard()\n      );\n      break;",
    )

    # 3. /topics uses getTopicsKeyboard()
    content = replace_once(
        content,
        old=(
            "    case 'topics':\n"
            "      await sendBotMessage(dialogId, `📰 *Темы (${settings.topics.length}):*\\n\\n${settings.topics.map((t,i) => `${i+1}. ${t}`).join('\\n')}\\n\\nДобавить: /addtopic <тема>\\nУбрать: /removetopic <тема>`, getMainKeyboard());\n"
            "      break;"
        ),
        new=(
            "    case 'topics':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `📰 *Темы (${settings.topics.length}):*\\n\\n${settings.topics.map((t,i) => `${i+1}. ${t}`).join('\\n')}\\n\\n` +\n"
            "        (settings.topics.length <= MAX_TOPIC_BUTTONS\n"
            "          ? `Нажми ❌ на теме, чтобы убрать её, или добавь новую.`\n"
            "          : `Тем многовато для кнопок — убрать: /removetopic <тема>`),\n"
            "        getTopicsKeyboard()\n"
            "      );\n"
            "      break;"
        ),
        label="/topics uses getTopicsKeyboard()",
        already_applied_marker="getTopicsKeyboard()\n      );\n      break;",
    )

    # 4. /schedule uses getScheduleKeyboard()
    content = replace_once(
        content,
        old=(
            "    case 'schedule':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `⏰ *Расписание*\\n\\n` +\n"
            "        `Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'}\\n` +\n"
            "        `Время: ${settings.time} (${settings.timezone})\\n` +\n"
            "        `Дни: Пн-Пт\\n\\n` +\n"
            "        `Изменить время: /settime <ЧЧ:ММ>\\n` +\n"
            "        `Вкл/выкл: /on или /off`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;"
        ),
        new=(
            "    case 'schedule':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `⏰ *Расписание*\\n\\n` +\n"
            "        `Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'}\\n` +\n"
            "        `Время: ${settings.time} (${settings.timezone})\\n` +\n"
            "        `Дни: Пн-Пт\\n\\n` +\n"
            "        `Выбери время кнопкой ниже, или укажи своё: /settime <ЧЧ:ММ>`,\n"
            "        getScheduleKeyboard()\n"
            "      );\n"
            "      break;"
        ),
        label="/schedule uses getScheduleKeyboard()",
        already_applied_marker="getScheduleKeyboard()\n      );\n      break;",
    )

    # 5. /sourcehealth uses getSourceHealthKeyboard()
    content = replace_once(
        content,
        old=(
            "      await sendBotMessage(dialogId,\n"
            "        `🩺 *Здоровье источников*\\n\\n${lines.join('\\n')}\\n\\n` +\n"
            "        `🔴 = вероятно сломан экстрактор/сайт изменился (${SOURCE_HEALTH_ALERT_THRESHOLD}+ пустых подряд)\\n` +\n"
            "        `🟡 = недавно были пустые ответы, но не критично\\n` +\n"
            "        `🟢 = работает нормально`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;\n"
            "\n"
            "    case 'reset':"
        ),
        new=(
            "      await sendBotMessage(dialogId,\n"
            "        `🩺 *Здоровье источников*\\n\\n${lines.join('\\n')}\\n\\n` +\n"
            "        `🔴 = вероятно сломан экстрактор/сайт изменился (${SOURCE_HEALTH_ALERT_THRESHOLD}+ пустых подряд)\\n` +\n"
            "        `🟡 = недавно были пустые ответы, но не критично\\n` +\n"
            "        `🟢 = работает нормально`,\n"
            "        getSourceHealthKeyboard()\n"
            "      );\n"
            "      break;\n"
            "\n"
            "    case 'reset':"
        ),
        label="/sourcehealth uses getSourceHealthKeyboard()",
        already_applied_marker="getSourceHealthKeyboard()\n      );\n      break;\n\n    case 'reset':",
    )

    # 6. New /menu command — same greeting as /start, reachable from every
    #    sub-screen's "⬅️ Назад" button. Placed right before the default case.
    content = replace_once(
        content,
        old=(
            "    default:\n"
            "      await sendBotMessage(dialogId, `❌ Неизвестная команда: /${command}. /help — список команд`, getMainKeyboard());\n"
            "  }\n"
            "}"
        ),
        new=(
            "    case 'menu':\n"
            "      await sendBotMessage(dialogId,\n"
            "        `Меню Бориса ✨ — выбери, с чего начать:`,\n"
            "        getMainKeyboard()\n"
            "      );\n"
            "      break;\n"
            "\n"
            "    default:\n"
            "      await sendBotMessage(dialogId, `❌ Неизвестная команда: /${command}. /help — список команд`, getMainKeyboard());\n"
            "  }\n"
            "}"
        ),
        label="add /menu command",
        already_applied_marker="case 'menu':",
    )

    # 7. /help mentions the new /menu command, right after the /reset line.
    content = replace_once(
        content,
        old=(
            "        '• /reset — очистить память диалога\\n' +\n"
            "        '• /sourcehealth — состояние источников новостей\\n\\n' +"
        ),
        new=(
            "        '• /reset — очистить память диалога\\n' +\n"
            "        '• /sourcehealth — состояние источников новостей\\n' +\n"
            "        '• /menu — открыть меню с кнопками\\n\\n' +"
        ),
        label="/help mentions /menu",
        already_applied_marker="'• /menu — открыть меню с кнопками\\n\\n' +",
    )

    # 8. /addtopic without an argument (i.e. tapped from the keyboard) now
    #    puts the dialog into awaitingTopic instead of just erroring out.
    #    /addtopic <тема> with an argument is unchanged.
    content = replace_once(
        content,
        old=(
            "    case 'addtopic':\n"
            "      if (params) {\n"
            "        settings.topics.push(params);\n"
            "        saveSettings();\n"
            "        await sendBotMessage(dialogId, `✅ Тема «${params}» добавлена. Теперь тем: ${settings.topics.length}`, getMainKeyboard());\n"
            "      } else {\n"
            "        await sendBotMessage(dialogId, '❌ Укажите тему: /addtopic <тема>', getMainKeyboard());\n"
            "      }\n"
            "      break;"
        ),
        new=(
            "    case 'addtopic':\n"
            "      if (params) {\n"
            "        settings.topics.push(params);\n"
            "        saveSettings();\n"
            "        await sendBotMessage(dialogId, `✅ Тема «${params}» добавлена. Теперь тем: ${settings.topics.length}`, getTopicsKeyboard());\n"
            "      } else {\n"
            "        awaitingTopic.add(dialogId);\n"
            "        await sendBotMessage(dialogId, '✏️ Напиши название новой темы одним сообщением.', getMainKeyboard());\n"
            "      }\n"
            "      break;"
        ),
        label="/addtopic without args waits for the next message",
        already_applied_marker="awaitingTopic.add(dialogId);",
    )

    # 9. Message handler: capture the next plain-text message as the new
    #    topic when awaitingTopic is set for this dialog. Checked before the
    #    existing awaitingFeedback branch (order doesn't matter functionally
    #    since they're disjoint per dialog, but keeping feedback's original
    #    position keeps this diff minimal).
    content = replace_once(
        content,
        old=(
            "        if (awaitingFeedback.has(dialogId)) {\n"
            "          awaitingFeedback.delete(dialogId);\n"
            "          settings.feedback.dislikes.push(text.trim());\n"
            "          saveSettings();\n"
            "          await sendBotMessage(dialogId, `👌 Понял, учту: «${text.trim()}». Спасибо за обратную связь!`, getMainKeyboard());\n"
            "        } else {"
        ),
        new=(
            "        if (awaitingTopic.has(dialogId)) {\n"
            "          awaitingTopic.delete(dialogId);\n"
            "          const newTopic = text.trim();\n"
            "          settings.topics.push(newTopic);\n"
            "          saveSettings();\n"
            "          await sendBotMessage(dialogId, `✅ Тема «${newTopic}» добавлена. Теперь тем: ${settings.topics.length}`, getTopicsKeyboard());\n"
            "        } else if (awaitingFeedback.has(dialogId)) {\n"
            "          awaitingFeedback.delete(dialogId);\n"
            "          settings.feedback.dislikes.push(text.trim());\n"
            "          saveSettings();\n"
            "          await sendBotMessage(dialogId, `👌 Понял, учту: «${text.trim()}». Спасибо за обратную связь!`, getMainKeyboard());\n"
            "        } else {"
        ),
        label="message handler captures next message as new topic when awaitingTopic",
        already_applied_marker="if (awaitingTopic.has(dialogId)) {",
    )

    # 10. /lang and /trends now return to getSettingsKeyboard() instead of
    #     getMainKeyboard(), so tapping a toggle from the Settings screen
    #     keeps you on that screen for further taps instead of bouncing you
    #     back to the top-level menu.
    content = replace_once(
        content,
        old=(
            "      if (params === 'pt' || params === 'ru') {\n"
            "        settings.lang = params;\n"
            "        saveSettings();\n"
            "        await sendBotMessage(dialogId, `✅ Язык изменен на ${params === 'ru' ? 'Русский' : 'Português'}.`, getMainKeyboard());\n"
            "      } else {\n"
            "        await sendBotMessage(dialogId, '❌ Формат: /lang pt или /lang ru', getMainKeyboard());\n"
            "      }\n"
            "      break;\n"
            "      \n"
            "    case 'trends':\n"
            "      settings.includeTrends = !settings.includeTrends;\n"
            "      saveSettings();\n"
            "      await sendBotMessage(dialogId, `✅ Тренды (макс 72ч): ${settings.includeTrends ? 'включены' : 'выключены'}.`, getMainKeyboard());\n"
            "      break;"
        ),
        new=(
            "      if (params === 'pt' || params === 'ru') {\n"
            "        settings.lang = params;\n"
            "        saveSettings();\n"
            "        await sendBotMessage(dialogId, `✅ Язык изменен на ${params === 'ru' ? 'Русский' : 'Português'}.`, getSettingsKeyboard());\n"
            "      } else {\n"
            "        await sendBotMessage(dialogId, '❌ Формат: /lang pt или /lang ru', getSettingsKeyboard());\n"
            "      }\n"
            "      break;\n"
            "      \n"
            "    case 'trends':\n"
            "      settings.includeTrends = !settings.includeTrends;\n"
            "      saveSettings();\n"
            "      await sendBotMessage(dialogId, `✅ Тренды (макс 72ч): ${settings.includeTrends ? 'включены' : 'выключены'}.`, getSettingsKeyboard());\n"
            "      break;"
        ),
        label="/lang and /trends return to getSettingsKeyboard()",
        already_applied_marker="getSettingsKeyboard());\n      } else {\n        await sendBotMessage(dialogId, '❌ Формат: /lang pt или /lang ru', getSettingsKeyboard());",
    )

    # 11. /removetopic (with an argument, i.e. tapped ❌ button) returns to
    #     getTopicsKeyboard() instead of getMainKeyboard(), so removing
    #     several topics in a row doesn't require re-opening /topics each time.
    content = replace_once(
        content,
        old=(
            "    case 'removetopic':\n"
            "      if (params) {\n"
            "        const idx = settings.topics.findIndex(t => t.toLowerCase() === params.toLowerCase());\n"
            "        if (idx >= 0) {\n"
            "          settings.topics.splice(idx, 1);\n"
            "          saveSettings();\n"
            "          await sendBotMessage(dialogId, `✅ Тема «${params}» удалена. Осталось: ${settings.topics.length}`, getMainKeyboard());\n"
            "        } else {\n"
            "          await sendBotMessage(dialogId, `❌ Тема «${params}» не найдена. /topics — список тем`, getMainKeyboard());\n"
            "        }\n"
            "      } else {\n"
            "        await sendBotMessage(dialogId, '❌ Укажите тему: /removetopic <тема>', getMainKeyboard());\n"
            "      }\n"
            "      break;"
        ),
        new=(
            "    case 'removetopic':\n"
            "      if (params) {\n"
            "        const idx = settings.topics.findIndex(t => t.toLowerCase() === params.toLowerCase());\n"
            "        if (idx >= 0) {\n"
            "          settings.topics.splice(idx, 1);\n"
            "          saveSettings();\n"
            "          await sendBotMessage(dialogId, `✅ Тема «${params}» удалена. Осталось: ${settings.topics.length}`, getTopicsKeyboard());\n"
            "        } else {\n"
            "          await sendBotMessage(dialogId, `❌ Тема «${params}» не найдена. /topics — список тем`, getTopicsKeyboard());\n"
            "        }\n"
            "      } else {\n"
            "        await sendBotMessage(dialogId, '❌ Укажите тему: /removetopic <тема>', getTopicsKeyboard());\n"
            "      }\n"
            "      break;"
        ),
        label="/removetopic returns to getTopicsKeyboard()",
        already_applied_marker="удалена. Осталось: ${settings.topics.length}`, getTopicsKeyboard());",
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
    print("  2. Review the diff, test /settings, /topics, /schedule, /sourcehealth in Telegram.")
    print("  3. Commit & push (see accompanying shell commands).")


if __name__ == "__main__":
    main()
