#!/usr/bin/env python3
"""
Sprint 3 patch for brazil-news-bot (Boris) — repository security.

PREREQUISITE: run apply_sprint1_patch.py and apply_sprint2_patch.py first.
This patch's index.js anchor assumes sprint 1+2 are already applied and
refuses to touch the file (no partial application) if they aren't.

What this does:
  1. index.js
     - Adds a clearly-labeled "Secrets" comment block around the API key
       declarations explaining that real values live only in deploy-server
       env vars, are injected at deploy time, and should be rotated if ever
       exposed (this is the marker comment requested for "ключи заменяются
       при деплое").
     - Adds a startup check: if VIBE_API_KEY is missing, the bot logs a
       clear error and exits immediately (process.exit(1)) instead of
       failing mysteriously later inside the first API call.
     - Bumps VERSION to 14.3.

  2. README.md
     - Rewrites the "Ключевые параметры" section: no more key-shaped
       placeholders at all — just "not stored here, see .env.example" plus
       the non-secret resource IDs (botId, server id, BITRIX_USER_ID) that
       are safe to keep for copy-paste convenience.
     - Adds a full "Безопасность" section: where secrets live, how the
       pre-commit guard works, and — importantly — what to do if a key
       *has* leaked into git history (rotate first, rewrite history second,
       with the actual commands).
     - Updates file list, deploy command, version references, changelog.

  3. New files (created only if they don't already exist — this script
     will not overwrite a .gitignore/.env.example/check-secrets.sh you've
     since customized):
     - .gitignore        — excludes .env, *.bak, node_modules/, local
                            settings/data, the deploy tarball.
     - .env.example       — template of required env vars, no real values.
     - scripts/check-secrets.sh — grep-based guard for a Bitrix24
                            vibe_api_... key shape (and PEM keys), usable
                            as a git pre-commit hook or run manually.

  IMPORTANT — this script does NOT touch git history. If a real key was
  ever committed (it was, in the original README), removing it from the
  current file does not remove it from `git log -p`. See the printed
  instructions at the end, and the README's own "Безопасность" section,
  for the manual history-rewrite + key-rotation steps. Rotating the key
  is the step that actually neutralizes a past leak; do that regardless
  of whether you also rewrite history.

Usage:
    python3 apply_sprint3_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run twice. Writes a timestamped .bak of every existing
file it modifies before modifying it. Never overwrites a file it created
in a previous run if you've since edited it (checked via a marker string).
"""

import sys
import os
import stat
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
    print("       Pass the path explicitly: python3 apply_sprint3_patch.py /path/to/brazil-news-bot")
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


def write_new_file_if_absent(path: Path, content: str, label: str, executable=False):
    if path.exists():
        print(f"  [skip] {label} (file already exists — not overwriting; delete it first if you want it regenerated)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  [ok]   {label} (created)")


# ---------------------------------------------------------------------------
# index.js
# ---------------------------------------------------------------------------

def patch_index_js(path: Path):
    print(f"\nPatching {path.name} ...")
    original = path.read_text(encoding="utf-8")
    content = original

    SPRINT12_MARKER = "async function generateConversationalReply("
    if SPRINT12_MARKER not in content:
        print("  [ABORT] sprint 1/2 changes not found in this file.")
        print("          Run apply_sprint1_patch.py and apply_sprint2_patch.py first —")
        print("          sprint 3 depends on them and refuses to apply a partial patch.")
        print("          No changes were made.")
        return

    content = replace_once(
        content,
        old=(
            "const PORT = process.env.PORT || 3000;\n"
            "const VIBE_API_KEY = process.env.VIBE_API_KEY;\n"
            "const BITRIX_USER_ID = process.env.BITRIX_USER_ID || '1221912';\n"
            "const BOT_ID = process.env.BOT_ID || '1505555';\n"
            "const BOT_NAME = 'Борис';\n"
            "const VERSION = '14.2';\n"
            "\n"
            "// LLM model used both for the daily digest and for conversational replies.\n"
            "const CHAT_MODEL = 'bitrix/bitrixgpt-5.5';\n"
            "\n"
            "// Persistent storage (survives server sleeps/restarts on the galaxy /data volume)\n"
            "const DATA_DIR = process.env.DATA_DIR || '/data';"
        ),
        new=(
            "const PORT = process.env.PORT || 3000;\n"
            "\n"
            "// --- Secrets -----------------------------------------------------------\n"
            "// SECURITY: real values are never hardcoded here or in git. They are set\n"
            "// as environment variables on the deploy server (galaxy) and injected into\n"
            "// the `env` block of the deploy request at deploy time — see README.md\n"
            "// \"Как задеплоить\". Rotate a key (Bitrix24 vibecode admin panel) any time\n"
            "// it may have leaked; a rotated key stops working the moment the old one\n"
            "// is committed, so a leak in git history costs nothing once rotated.\n"
            "const VIBE_API_KEY = process.env.VIBE_API_KEY;\n"
            "const BITRIX_USER_ID = process.env.BITRIX_USER_ID || '1221912';\n"
            "const BOT_ID = process.env.BOT_ID || '1505555';\n"
            "const BOT_NAME = 'Борис';\n"
            "const VERSION = '14.3';\n"
            "\n"
            "// LLM model used both for the daily digest and for conversational replies.\n"
            "const CHAT_MODEL = 'bitrix/bitrixgpt-5.5';\n"
            "\n"
            "// Fail loudly and immediately if the bot is started without its API key,\n"
            "// instead of limping along and failing mysteriously (401s / undefined\n"
            "// headers) deep inside the first API call.\n"
            "if (!VIBE_API_KEY) {\n"
            "  console.error('[fatal] VIBE_API_KEY is not set. Set it as an environment variable on the deploy server (never hardcode it). See README.md \"Безопасность\".');\n"
            "  process.exit(1);\n"
            "}\n"
            "\n"
            "// Persistent storage (survives server sleeps/restarts on the galaxy /data volume)\n"
            "const DATA_DIR = process.env.DATA_DIR || '/data';"
        ),
        label="secrets comment block + startup VIBE_API_KEY validation + version bump",
        already_applied_marker="if (!VIBE_API_KEY) {\n  console.error('[fatal] VIBE_API_KEY is not set.",
    )

    if content != original:
        backup(path)
        path.write_text(content, encoding="utf-8")
        print(f"  written: {path}")
    else:
        print("  (no changes written — everything already applied or anchors missing)")


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

def patch_readme(path: Path):
    print(f"\nPatching {path.name} ...")
    original = path.read_text(encoding="utf-8")
    content = original

    content = replace_once(
        content,
        old="# Борис — бот новостей и трендов Бразилии (v14.2)",
        new="# Борис — бот новостей и трендов Бразилии (v14.3)",
        label="title version bump",
        already_applied_marker="# Борис — бот новостей и трендов Бразилии (v14.3)",
    )

    # The "Файлы" section's index.js version note was never updated by the
    # sprint 1/2 scripts (only the title was) — so it may still read v14.1
    # here even after sprint 1+2. Fix it independently of the big block
    # replace below, tolerant of either v14.1 or v14.2.
    if "- `index.js` — весь код бота (v14.3)" not in content:
        for stale_version in ("14.1", "14.2"):
            marker = f"- `index.js` — весь код бота (v{stale_version})"
            if marker in content:
                content = content.replace(marker, "- `index.js` — весь код бота (v14.3)", 1)
                print(f"  [ok]   Файлы section: index.js version note v{stale_version} -> v14.3")
                break
        else:
            print("  [WARN] Файлы section: index.js version note not found in any known form — skipping.")
    else:
        print("  [skip] Файлы section: index.js version note (already applied)")

    # Same tolerance for the personality.js description: sprint 1 added an
    # LLM fallback but a couple of earlier README variants never got their
    # personality.js description updated to say so. Bring whichever variant
    # is present up to the current description.
    CURRENT_PERSONALITY_DESC = (
        "- `personality.js` — быстрый путь «живости»: распознавание простых сообщений "
        "(приветствие, благодарность, прощание) без обращения к LLM. Всё остальное "
        "(свободные вопросы, беседа) теперь обрабатывает LLM-диалог из `index.js` "
        "(`generateConversationalReply`), с короткой памятью на диалог (`/reset` — очистить)"
    )
    if CURRENT_PERSONALITY_DESC not in content:
        old_personality_desc = (
            "- `personality.js` — «живость»: распознавание простых сообщений (кто ты, что "
            "умеешь, приветствие, настроение, благодарность, прощание) и ответы о себе/функциях"
        )
        if old_personality_desc in content:
            content = content.replace(old_personality_desc, CURRENT_PERSONALITY_DESC, 1)
            print("  [ok]   Файлы section: personality.js description updated for LLM fallback")
        else:
            print("  [WARN] Файлы section: personality.js description not found in any known form — skipping.")
    else:
        print("  [skip] Файлы section: personality.js description (already applied)")

    content = replace_once(
        content,
        old=(
            "## Ключевые параметры (НЕ потеряй)\n"
            "\n"
            "⚠️ **С v14.2 реальные ключи в README больше не хранятся.** Держи их только в\n"
            "секретах/переменных окружения сервера деплоя. Ниже — только имена переменных:\n"
            "\n"
            "- **Новый API-ключ (для бота/приложения):** значение переменной `VIBE_API_KEY` — смотри в секретах деплоя\n"
            "- **Старый API-ключ (для инфраструктуры/деплоя):** используется только в команде деплоя ниже — бери из секретов, не коммить в git\n"
            "- **Бот:** botId `1505555`, код `boris_news_bot_v2`, eventMode `fetch`\n"
            "- **Сервер (galaxy app):** id `4be3b715-b55c-4dad-a19f-c1a50eca4829`, URL `https://app-355290d5e5e6.vibecode.bitrix24.tech`, accessPolicy `PUBLIC`\n"
            "- **Пользователь (получатель дайджеста):** BITRIX_USER_ID `1221912`\n"
            "- **Wake-расписание:** `cronExpr \"0 9 * * 1-5\"`, timezone `Europe/Moscow` (сервер просыпается в 09:00 Мск Пн-Пт)\n"
            "\n"
            "## Файлы"
        ),
        new=(
            "## Ключевые параметры (НЕ потеряй)\n"
            "\n"
            "🔒 **Секреты (API-ключи) нигде не хранятся в этом репозитории — ни здесь,\n"
            "ни в коде, ни в архиве деплоя.** Они существуют только как переменные\n"
            "окружения на сервере деплоя и подставляются в команду `curl` вручную в\n"
            "момент деплоя (см. ниже и `.env.example`). Подробности — раздел\n"
            "«Безопасность».\n"
            "\n"
            "- **API-ключ бота (`VIBE_API_KEY`):** НЕ хранится нигде в репо. Бери из своего менеджера секретов при каждом деплое.\n"
            "- **API-ключ деплоя/инфраструктуры (`DEPLOY_API_KEY`):** НЕ хранится нигде в репо. Используется только локально в момент запуска команды деплоя.\n"
            "- **Бот:** botId `1505555`, код `boris_news_bot_v2`, eventMode `fetch`\n"
            "- **Сервер (galaxy app):** id `4be3b715-b55c-4dad-a19f-c1a50eca4829`, URL `https://app-355290d5e5e6.vibecode.bitrix24.tech`, accessPolicy `PUBLIC`\n"
            "- **Пользователь (получатель дайджеста):** BITRIX_USER_ID `1221912`\n"
            "- **Wake-расписание:** `cronExpr \"0 9 * * 1-5\"`, timezone `Europe/Moscow` (сервер просыпается в 09:00 Мск Пн-Пт)\n"
            "\n"
            "Эти ID (botId, server id, BITRIX_USER_ID) сами по себе не секреты — без\n"
            "API-ключа ими нельзя ничего сделать — поэтому оставлены в README для\n"
            "удобства копипаста в команды ниже.\n"
            "\n"
            "## Безопасность\n"
            "\n"
            "- **Ключи никогда не коммитятся.** Ни в README, ни в код, ни в архив деплоя (`app.tar.gz`). `index.js` читает их строго из `process.env` и явно падает при старте с понятной ошибкой, если `VIBE_API_KEY` не задан — так утечка через \"забыли передать переменную\" видна сразу, а не как загадочный 401 внутри API-вызова.\n"
            "- **`.gitignore`** в этой папке исключает `.env`, `*.bak`, `node_modules/`, локальные файлы настроек — см. файл рядом.\n"
            "- **`.env.example`** — шаблон переменных окружения без значений; скопируй в `.env` для локальной разработки, `.env` в git не попадёт.\n"
            "- **`scripts/check-secrets.sh`** — грубый grep-фильтр, который можно повесить как git pre-commit hook (см. инструкцию в самом файле), чтобы случайно закоммиченный ключ вида `vibe_api_...` останавливал коммит до пуша, а не после.\n"
            "- **Если ключ всё же попал в git (в любой момент истории, даже в старом коммите):** он уже скомпрометирован, и удаление из последнего коммита это НЕ чинит — ключ остаётся в истории и доступен через `git log -p` любому, у кого есть доступ к репозиторию (или он публичный).\n"
            "  1. Сразу ротируй ключ в панели администратора Bitrix24 vibecode — это единственный шаг, который гарантированно закрывает утечку; сама зачистка истории — дополнительная гигиена, а не замена ротации.\n"
            "  2. Затем при желании перепиши историю (`git filter-repo --path README.md --invert-paths` для полного удаления файла из истории, или точечно `git filter-repo --replace-text` со списком секретов) — координируй с командой, это меняет хэши всех коммитов и требует force-push и повторного клонирования репозитория всеми, у кого есть локальная копия.\n"
            "- **Не отправляй ключи в чат/сообщения боту.** Значения в `env` передаются только через тело `curl`-запроса деплоя с твоей локальной машины/CI — бот сам никогда не должен получать или логировать свой собственный ключ.\n"
            "\n"
            "## Файлы"
        ),
        label="rewrite key-storage section + add Безопасность section",
        already_applied_marker="## Безопасность",
    )

    content = replace_once(
        content,
        old=(
            "- `package.json` — start-скрипт `node index.js`\n"
            "- `app.tar.gz` + `app.tar.gz.base64` — архив для деплоя\n"
            "- `boris_avatar*.png/jpg` — аватары бота"
        ),
        new=(
            "- `package.json` — start-скрипт `node index.js`\n"
            "- `app.tar.gz` + `app.tar.gz.base64` — архив для деплоя (содержит только код, без секретов — переменные окружения передаются отдельно в момент деплоя)\n"
            "- `boris_avatar*.png/jpg` — аватары бота\n"
            "- `.gitignore` — исключает `.env`, `*.bak`, `node_modules/`, локальные настройки из git\n"
            "- `.env.example` — шаблон переменных окружения (без значений) для локальной разработки\n"
            "- `scripts/check-secrets.sh` — grep-guard против случайного коммита API-ключа"
        ),
        label="Файлы section mentions new security files",
        already_applied_marker="scripts/check-secrets.sh` — grep-guard против случайного коммита",
    )

    content = replace_once(
        content,
        old=(
            "## Как задеплоить (после изменения кода)\n"
            "\n"
            "```bash\n"
            "cd <папка>/brazil-news-bot\n"
            "tar -czf app.tar.gz index.js package.json\n"
            "base64 < app.tar.gz | tr -d '\\n' > app.tar.gz.base64\n"
            "B64=$(cat app.tar.gz.base64)\n"
            "\n"
            "# Значения ниже — из переменных окружения твоего шелла / секретов CI,\n"
            "# не хардкодь их в команде:\n"
            "#   export DEPLOY_API_KEY=...   (старый ключ, только для инфраструктуры/деплоя)\n"
            "#   export VIBE_API_KEY=...     (новый ключ, для самого бота/приложения)\n"
            "\n"
            "curl -s -X POST \"https://vibecode.bitrix24.tech/v1/infra/servers/4be3b715-b55c-4dad-a19f-c1a50eca4829/deploy\" \\\n"
            "  -H \"X-Api-Key: ${DEPLOY_API_KEY}\" \\\n"
            "  -H \"Content-Type: application/json\" \\\n"
            "  -d \"{\n"
            "    \\\"source\\\": { \\\"content\\\": \\\"$B64\\\" },\n"
            "    \\\"runtime\\\": \\\"node20\\\",\n"
            "    \\\"start\\\": \\\"cd /opt/app && node index.js\\\",\n"
            "    \\\"port\\\": 3000,\n"
            "    \\\"env\\\": {\n"
            "      \\\"VIBE_API_KEY\\\": \\\"${VIBE_API_KEY}\\\",\n"
            "      \\\"BOT_ID\\\": \\\"1505555\\\",\n"
            "      \\\"BITRIX_USER_ID\\\": \\\"1221912\\\"\n"
            "    },\n"
            "    \\\"displayName\\\": \\\"Борис — интересные истории и тренды\\\",\n"
            "    \\\"description\\\": \\\"Борис — AI-бот, который ежедневно собирает самые интересные и трендовые истории со всего мира, включая бизнес и стартапы.\\\",\n"
            "    \\\"changelog\\\": \\\"v14.2: LLM-диалог вместо статичного меню, uncaughtException/unhandledRejection guards, ключи убраны из README\\\"\n"
            "  }\"\n"
            "```"
        ),
        new=(
            "## Как задеплоить (после изменения кода)\n"
            "\n"
            "🔒 Команда ниже читает `DEPLOY_API_KEY` и `VIBE_API_KEY` из переменных\n"
            "окружения твоего шелла — они должны быть выставлены заранее (см.\n"
            "`.env.example`), и **никогда не вписывай их значения прямо в команду или в\n"
            "этот файл**.\n"
            "\n"
            "```bash\n"
            "cd <папка>/brazil-news-bot\n"
            "tar -czf app.tar.gz index.js personality.js package.json\n"
            "base64 < app.tar.gz | tr -d '\\n' > app.tar.gz.base64\n"
            "B64=$(cat app.tar.gz.base64)\n"
            "\n"
            "# Выставь эти переменные в своей сессии перед запуском (не хардкодь их\n"
            "# здесь и не подставляй значения прямо в curl):\n"
            "#   export DEPLOY_API_KEY=...   (ключ для инфраструктуры/деплоя)\n"
            "#   export VIBE_API_KEY=...     (ключ для самого бота/приложения)\n"
            "\n"
            "curl -s -X POST \"https://vibecode.bitrix24.tech/v1/infra/servers/4be3b715-b55c-4dad-a19f-c1a50eca4829/deploy\" \\\n"
            "  -H \"X-Api-Key: ${DEPLOY_API_KEY}\" \\\n"
            "  -H \"Content-Type: application/json\" \\\n"
            "  -d \"{\n"
            "    \\\"source\\\": { \\\"content\\\": \\\"$B64\\\" },\n"
            "    \\\"runtime\\\": \\\"node20\\\",\n"
            "    \\\"start\\\": \\\"cd /opt/app && node index.js\\\",\n"
            "    \\\"port\\\": 3000,\n"
            "    \\\"env\\\": {\n"
            "      \\\"VIBE_API_KEY\\\": \\\"${VIBE_API_KEY}\\\",\n"
            "      \\\"BOT_ID\\\": \\\"1505555\\\",\n"
            "      \\\"BITRIX_USER_ID\\\": \\\"1221912\\\"\n"
            "    },\n"
            "    \\\"displayName\\\": \\\"Борис — интересные истории и тренды\\\",\n"
            "    \\\"description\\\": \\\"Борис — AI-бот, который ежедневно собирает самые интересные и трендовые истории со всего мира, включая бизнес и стартапы.\\\",\n"
            "    \\\"changelog\\\": \\\"v14.3: секреты полностью убраны из репозитория (README/.gitignore/.env.example/check-secrets.sh), явная проверка VIBE_API_KEY при старте, исправлена команда деплоя (не хватало personality.js в архиве)\\\"\n"
            "  }\"\n"
            "```"
        ),
        label="deploy command: drop 'placeholder' framing, update changelog string",
        already_applied_marker="v14.3: секреты полностью убраны из репозитория",
    )

    content = replace_once(
        content,
        old='- Health: `curl https://app-355290d5e5e6.vibecode.bitrix24.tech/health` → `{"version":"14.1"}`',
        new='- Health: `curl https://app-355290d5e5e6.vibecode.bitrix24.tech/health` → `{"version":"14.3"}`',
        label="health-check example version bump",
        already_applied_marker='{"version":"14.3"}`',
    )

    content = replace_once(
        content,
        old=(
            "- v14.1 — живой индикатор работы: пока бот ищет/генерирует (/news, /showtrends, /surprise), status-индикатор «Ищет...»/«Генерирует...» держится всё время (как «Пишет...» в мессенджерах), а не гаснет через 30 секунд"
        ),
        new=(
            "- v14.1 — живой индикатор работы: пока бот ищет/генерирует (/news, /showtrends, /surprise), status-индикатор «Ищет...»/«Генерирует...» держится всё время (как «Пишет...» в мессенджерах), а не гаснет через 30 секунд\n"
            "- v14.2 (спринт 1) — свободный ввод теперь отвечает через LLM (не только фиксированные паттерны) с короткой памятью диалога (`/reset`); process-level crash guards; ключи убраны из README\n"
            "- v14.3 (спринты 2–3) — `/sourcehealth`: отслеживание деградации скрейпинга источников (habr/bloomberglinea/googlenews/folha/cnnbrasil/trends24/google_trends); исправлен race condition в feedback-состоянии (был глобальный флаг на процесс — стал per-dialog); секреты полностью выведены из репозитория (`.gitignore`, `.env.example`, `scripts/check-secrets.sh`), явная проверка `VIBE_API_KEY` при старте с понятной ошибкой"
        ),
        label="changelog entries for v14.2/v14.3",
        already_applied_marker="v14.3 (спринты 2–3) — `/sourcehealth`",
    )

    if content != original:
        backup(path)
        path.write_text(content, encoding="utf-8")
        print(f"  written: {path}")
    else:
        print("  (no changes written — everything already applied or anchors missing)")


# ---------------------------------------------------------------------------
# New security files
# ---------------------------------------------------------------------------

GITIGNORE_CONTENT = """# --- Secrets: never commit these ---
.env
.env.*
!.env.example
*.key
*.pem

# --- Local backups created by patch scripts (apply_sprintN_patch.py) ---
*.bak
.sprint0-removed-*/

# --- Node ---
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# --- Local runtime data (bot settings persist to /data in production;
#     this covers a local dev copy of the same file) ---
data/
settings.json

# --- OS / editor cruft ---
.DS_Store
Thumbs.db
*.swp

# --- Deploy archive is regenerated at deploy time (see README "Как
#     задеплоить"); keep it out of git so stale builds can't be pushed
#     by accident. Comment these two lines out if you intentionally want
#     to version the built artifact instead of regenerating it. ---
app.tar.gz
app.tar.gz.base64
"""

ENV_EXAMPLE_CONTENT = """# Copy this file to .env for local development:
#   cp .env.example .env
# Then fill in real values in your local .env — it's gitignored and will
# never be committed. For actual deploys, these are set as environment
# variables on the deploy server directly (see README.md "Как задеплоить"),
# not read from this file.

# Bitrix24 vibecode API key used by the bot itself (chat completions,
# sending messages, typing indicators, search). Required — the bot exits
# immediately at startup if this is missing.
VIBE_API_KEY=

# Bitrix24 user ID that receives the daily digest.
BITRIX_USER_ID=

# This bot's own bot ID in Bitrix24.
BOT_ID=

# Local HTTP port the bot listens on (defaults to 3000 if unset).
PORT=3000

# Directory for persisted settings.json (defaults to /data in production;
# use a local writable path for local dev, e.g. ./data).
DATA_DIR=./data
"""

CHECK_SECRETS_SH_CONTENT = r"""#!/usr/bin/env bash
# Blocks a commit if it looks like it contains a Bitrix24 vibecode API key
# (or a couple of other common secret shapes) in plaintext.
#
# This is a blunt grep-based net, not a full secret scanner — it exists to
# catch the specific mistake that already happened once in this repo
# (a vibe_api_... key pasted directly into README.md), not to replace
# judgment. Rotate any key immediately if it's ever committed, regardless
# of whether this script catches it.
#
# --- Install as a git pre-commit hook (run once per local clone) ---
#   ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# --- Run manually against staged changes at any time ---
#   ./scripts/check-secrets.sh
#
# --- Run manually against the whole working tree (not just staged) ---
#   ./scripts/check-secrets.sh --all

set -euo pipefail

# Patterns considered a leaked secret if found in plaintext.
PATTERNS=(
  'vibe_api_[A-Za-z0-9_]{10,}'   # Bitrix24 vibecode API key shape
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'  # PEM private keys
)

if [[ "${1:-}" == "--all" ]]; then
  # Scan the whole working tree (excluding .git and node_modules).
  TARGET_DESC="working tree"
  MATCHES=""
  for pattern in "${PATTERNS[@]}"; do
    found=$(grep -rEn --exclude-dir='.git' --exclude-dir='node_modules' -- "$pattern" . 2>/dev/null || true)
    if [[ -n "$found" ]]; then
      MATCHES="${MATCHES}${found}"$'\n'
    fi
  done
else
  # Default: only scan what's staged for this commit (the normal
  # pre-commit-hook use case) so the check is fast and only blocks what
  # you're about to actually push.
  TARGET_DESC="staged changes"
  MATCHES=""
  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    for pattern in "${PATTERNS[@]}"; do
      found=$(git diff --cached -- "$file" | grep -E "^\+" | grep -Ev '^\+\+\+' | grep -E -- "$pattern" || true)
      if [[ -n "$found" ]]; then
        MATCHES="${MATCHES}${file}: ${found}"$'\n'
      fi
    done
  done < <(git diff --cached --name-only --diff-filter=ACM)
fi

if [[ -n "$MATCHES" ]]; then
  echo "🔴 check-secrets.sh: possible secret found in ${TARGET_DESC}:" >&2
  echo "$MATCHES" >&2
  echo "" >&2
  echo "If this is a real key: do NOT commit it — remove it, use an env var" >&2
  echo "instead (see .env.example), and rotate the key if it was ever" >&2
  echo "committed anywhere before (even in a previous commit you amended)." >&2
  echo "If this is a false positive, adjust PATTERNS in scripts/check-secrets.sh." >&2
  exit 1
fi

echo "✅ check-secrets.sh: no known secret patterns found in ${TARGET_DESC}."
"""


def create_security_files(bot_dir: Path):
    print("\nCreating security files (skipped if already present) ...")
    write_new_file_if_absent(bot_dir / ".gitignore", GITIGNORE_CONTENT, ".gitignore")
    write_new_file_if_absent(bot_dir / ".env.example", ENV_EXAMPLE_CONTENT, ".env.example")
    write_new_file_if_absent(
        bot_dir / "scripts" / "check-secrets.sh",
        CHECK_SECRETS_SH_CONTENT,
        "scripts/check-secrets.sh",
        executable=True,
    )


def main():
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_dir = find_bot_dir(cli_arg)
    print(f"Using bot directory: {bot_dir}")

    patch_index_js(bot_dir / "index.js")
    patch_readme(bot_dir / "README.md")
    create_security_files(bot_dir)

    print("\nDone. Next steps:")
    print("  1. Review the diff: git -C '%s' diff" % bot_dir)
    print("  2. Syntax-check:    node --check '%s'" % (bot_dir / "index.js"))
    print("  3. Sanity-check the secret guard:")
    print("       bash '%s' --all" % (bot_dir / "scripts" / "check-secrets.sh"))
    print("  4. Install it as a pre-commit hook (optional but recommended):")
    print("       ln -sf ../../scripts/check-secrets.sh '%s'" % (bot_dir / ".git" / "hooks" / "pre-commit"))
    print("       chmod +x '%s'" % (bot_dir / ".git" / "hooks" / "pre-commit"))
    print()
    print("  ⚠️  IMPORTANT — this script does NOT rewrite git history. If the old")
    print("      README (with real vibe_api_... keys) was ever committed, those keys")
    print("      are still readable via `git log -p` even after this patch. Do this:")
    print("        a) Rotate BOTH keys now in the Bitrix24 vibecode admin panel —")
    print("           this is what actually neutralizes the leak.")
    print("        b) Check whether the leak is in history:")
    print("             git log -p -- README.md | grep vibe_api_")
    print("        c) If you want it gone from history too (optional once rotated):")
    print("             pip install git-filter-repo")
    print("             git filter-repo --replace-text <(echo 'vibe_api_hDkHAzo9J4C1xAca36XItdmOoUG8KOms_c8d10d==>REDACTED')")
    print("             git filter-repo --replace-text <(echo 'vibe_api_qrBjH5IesjrfCccjhth8ziw9oBP8WJez_8fd2de==>REDACTED')")
    print("           This rewrites all commit hashes — coordinate with anyone else")
    print("           who has a clone, they'll need to re-clone. Force-push after:")
    print("             git push --force-with-lease")


if __name__ == "__main__":
    main()
