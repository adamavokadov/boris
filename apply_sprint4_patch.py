#!/usr/bin/env python3
"""
Sprint 4 patch for brazil-news-bot (Boris) — project memory files.

PREREQUISITE: sprint 0-3 should already be applied (this patch reads their
end state to write an accurate handoff.md, but does not strictly require
their markers to run — see NOTE below).

What this does:
  1. Creates handoff.md — a living technical dump of the project: current
     state, architecture map, known limitations, and full sprint history.
     Read this file at the start of any future session working on this bot
     instead of re-analyzing the whole codebase from scratch.

     ⚠️ RULE, enforced by this script and meant to be followed by any
     future patch (human or AI-written): handoff.md is NEVER deleted, and
     MUST be updated (not replaced wholesale, not left stale) after every
     future patch — new sprint history entries appended, "Текущее
     состояние" section kept current. This script itself follows that
     rule: if handoff.md already exists (e.g. sprint 5+ has since updated
     it), THIS SCRIPT WILL NOT TOUCH IT. It only creates it when entirely
     absent. Re-running sprint 4 patch on a repo that already has
     handoff.md is a safe no-op for that file.

  2. Creates roadmap.md — feature ideas for the bot's future development,
     informed by researched 2026 practices for news-digest and
     market-intelligence bots (deduplication/scoring, watchlists/alerts,
     multi-channel delivery, persistent memory, source-tuning cadence,
     security hygiene). Created only if absent — like .gitignore/
     .env.example in sprint 3, this script won't overwrite customizations
     you've since made to it.

  NOTE on prerequisites: unlike sprint 2/3, this script does NOT hard-abort
  if sprint 0-3 markers are missing, because handoff.md/roadmap.md are
  pure documentation additions with no runtime dependency on prior
  sprints' code. It DOES print a warning if it can't confirm sprint 0-3
  were applied, since handoff.md's "Текущее состояние" section describes
  their end state and would be inaccurate otherwise.

Usage:
    python3 apply_sprint4_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run any number of times. handoff.md is create-only
(never overwritten by this or any future run of this exact script).
roadmap.md is create-only per this script's own logic (delete it yourself
first if you want it regenerated from scratch).
"""

import sys
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
    print("       Pass the path explicitly: python3 apply_sprint4_patch.py /path/to/brazil-news-bot")
    sys.exit(1)


def check_prior_sprints(bot_dir: Path):
    """Informational only — does not block this patch (see NOTE in docstring)."""
    index_js = bot_dir / "index.js"
    if not index_js.exists():
        return
    content = index_js.read_text(encoding="utf-8", errors="ignore")
    missing = []
    if "async function generateConversationalReply(" not in content:
        missing.append("sprint 1 (generateConversationalReply)")
    if "function recordSourceHealth(" not in content:
        missing.append("sprint 2 (recordSourceHealth)")
    if "if (!VIBE_API_KEY) {" not in content:
        missing.append("sprint 3 (startup VIBE_API_KEY check)")
    if missing:
        print("  [WARN] Could not confirm these prior sprints are applied in index.js:")
        for m in missing:
            print(f"           - {m}")
        print("         handoff.md's \"Текущее состояние\" section describes the")
        print("         post-sprint-0..3 end state and may not match your actual repo")
        print("         yet if these are missing. Consider running sprint 0-3 first,")
        print("         or edit handoff.md's summary manually afterward. Proceeding")
        print("         anyway — this doesn't block sprint 4 (docs have no runtime")
        print("         dependency on prior sprints).")


def write_if_absent(path: Path, content: str, label: str):
    if path.exists():
        print(f"  [skip] {label} (already exists — never overwritten by this script;"
              f" edit it directly, or delete it yourself first if you truly want it"
              f" regenerated from scratch)")
        return
    path.write_text(content, encoding="utf-8")
    print(f"  [ok]   {label} (created)")


HANDOFF_MD_CONTENT = r"""# Handoff — Борис (brazil-news-bot)

> ⚠️ **Этот файл никогда не удаляется.** Он обновляется после КАЖДОГО
> нового патча (спринта), кем бы патч ни был написан — человеком, Claude
> в новой сессии, или любым другим инструментом. Если начинаешь новую
> сессию работы над этим ботом, прочитай этот файл первым — он экономит
> тебе полный повторный анализ кода. Обновляя этот файл, дополняй секцию
> "История спринтов" и держи "Текущее состояние" в актуальном виде;
> не переписывай старые записи истории — они полезны как есть.

## Что это

AI-бот **«Борис»** для Битрикс24 (платформа vibecode), написан на Node.js
без внешних фреймворков (только `http`, `https`, `fs`, `path` из stdlib).
Каждый будний день собирает и присылает одному пользователю дайджест
интересных историй и трендов (AI/tech, вирусное, наука, поп-культура,
бизнес/стартапы) по рынку Бразилии, отвечает на команды и умеет вести
свободный диалог через LLM.

Владелец проекта работает в PR/контент-менеджменте Bitrix24, ведёт
бразильский регион.

## Текущее состояние (после спринтов 0–3)

- **Версия:** v14.3
- **Файлы:** `index.js` (весь код бота), `personality.js` (быстрые
  regex-паттерны для приветствия/благодарности/прощания), `package.json`,
  `README.md`, `icon.svg`, `.gitignore`, `.env.example`,
  `scripts/check-secrets.sh`
- **Удалено (спринт 0):** `app.tar.gz.base64` (устаревший build-артефакт
  с кодом v13.8), `make_avatar.py`, `make_avatar2.py` (черновики аватарки,
  больше не нужны — аватар уже сгенерирован и загружен)
- **Платформа:** Bitrix24 vibecode, galaxy-сервер (засыпает через 60 мин
  простоя, просыпается по cron `0 9 * * 1-5` Europe/Moscow)
- **LLM:** `bitrix/bitrixgpt-5.5` через `https://vibecode.bitrix24.tech/v1/chat/completions`,
  вызывается в двух местах: `generateDigest()` (сам дайджест) и
  `generateConversationalReply()` (свободный диалог)
- **Секреты:** НЕ хранятся в репозитории нигде (ни в коде, ни в README, ни
  в архиве деплоя) — только как переменные окружения на сервере деплоя,
  подставляются вручную в момент каждого деплоя. Бот падает при старте
  с понятной ошибкой, если `VIBE_API_KEY` не задан. См. `README.md` →
  раздел «Безопасность» для протокола на случай утечки (ротация ключа —
  обязательный первый шаг).

## Архитектура index.js (карта функций)

```
Настройки:
  DEFAULT_SETTINGS, loadSettings(), saveSettings()
    — persist в /data/settings.json (galaxy volume), merge с дефолтами

HTTP-утилиты:
  makeRequest(url, options)      — обёртка над https, JSON in/out

Форматирование:
  formatDateBR(date), getDates()

Bitrix24 UI:
  getMainKeyboard(), getFeedbackKeyboard()
  sendBotMessage(dialogId, text, keyboard)
  showTyping(dialogId, statusCode, duration)
  withTyping(dialogId, statusCode, fn)  — держит "печатает..." на время
    долгой операции (fn), т.к. один вызов showTyping живёт только N сек

Поиск/сбор данных:
  getSearchQueries(dates), getTrendQueries(dates)
  searchNews(query)              — веб-поиск через LLM-платформу
  collectRawNews()                — по всем topic-запросам
  fetchTrends24()                  — regex-скрейпинг trends24.in/brazil
  fetchGoogleTrends()               — Google Trends RSS
  collectTrends()                    — объединяет trends24 + googletrends
  SOURCES[]                           — 5 курируемых источников:
    habr, bloomberglinea, googlenews, folha, cnnbrasil
  fetchSourceHeadlines(source)         — regex-экстракция заголовков,
    2 попытки на источник, retry через 1.5с
  fetchBreakingNews()                   — "Just In" через поиск
  collectSourceNews()                    — по всем SOURCES

Health-check источников (спринт 2):
  recordSourceHealth(id, count, err)      — трекинг подряд-пустых fetch'ей
  getUnhealthySources()                    — источники с 3+ пустыми подряд
  settings.sourceHealth{}                   — персистится

LLM-генерация:
  generateDigest(rawNews, trendNews, sourceNews, extraInstructions)
    — основной промпт, формирует дайджест из сырых данных
  getPersonaSystemPrompt(userName)          — промпт личности Бориса
    для свободного диалога (спринт 1)
  generateConversationalReply(dialogId, text, userName)
    — LLM-ответ на свободный ввод, с историей диалога

Память диалога (спринт 1, in-memory, НЕ персистится):
  conversationHistory: Map<dialogId, [{role, content}, ...]>
  pushHistory(), getHistory()               — капается на MAX_HISTORY_TURNS=8
  awaitingFeedback: Set<dialogId>            — per-dialog (спринт 2, был
    глобальный boolean settings.awaitingFeedback — чинили race condition)

Планирование:
  sendDailyBriefing(dialogId)                — утренний дайджест
  scheduleHeavyJob(fn, key)                    — guard от параллельного
    запуска тяжёлых команд (/news, /showtrends, /surprise)

Команды (handleCommand, switch по command):
  start/hello/hi, news/briefing, showtrends, surprise/random, settings,
  feedback, help, status, sourcehealth (спринт 2), reset (спринт 1),
  lang, trends, topics, addtopic, removetopic, schedule, settime, on, off

Событийный цикл:
  pollEvents()                                  — long-poll событий Bitrix24
  handleEvent(event)                              — роутер:
    ONIMBOTV2MESSAGEADD   — свободный текст: personality.js (быстро) →
                             иначе generateConversationalReply() (LLM) →
                             иначе статичное меню (деградация при сбое LLM)
    ONIMBOTV2COMMANDADD   — слэш-команды → handleCommand()
```

## Известные архитектурные ограничения (не исправлены, осознанный выбор)

1. **Один пользователь.** `BITRIX_USER_ID` захардкожен как единственный
   получатель дайджеста. `settings` (topics, lang, autoSend, time) —
   общий на весь процесс, не per-workspace. Если бот когда-нибудь станет
   multi-tenant — это первое, что придётся рефакторить.
2. **`conversationHistory` не персистится.** Сбрасывается при рестарте
   процесса/сне сервера. Осознанный компромисс (простота + приватность)
   из спринта 1 — не баг.
3. **Regex-скрейпинг источников хрупкий по природе.** Health-check
   (спринт 2) даёт видимость деградации, но не чинит источник
   автоматически — при срабатывании `/sourcehealth` на 🔴 всё ещё нужно
   вручную посмотреть, что изменилось на сайте-источнике, и поправить
   `source.extract()`.
4. **Сервер засыпает через 60 мин простоя** (ограничение платформы
   galaxy, `GALAXY_APP_USE_GALAXY_ROUTE` — отключить нельзя). Единственный
   способ гарантировать постоянную доступность — перенос на отдельный VM,
   не рассматривался как приоритет.

## История спринтов

- **Спринт 0** — удалены `app.tar.gz.base64` (устаревший артефакт v13.8),
  `make_avatar.py`, `make_avatar2.py`. Верифицировано, что скрипты
  спринтов 1 и 2 не требовали правок (были байт-в-байт как выданы).
- **Спринт 1** — LLM отвечает на свободный ввод, не попавший под
  regex-паттерны `personality.js` (вместо статичного меню), с короткой
  памятью диалога (`/reset`). Добавлены `process.on('uncaughtException'/
  'unhandledRejection')` crash guards. `CHAT_MODEL` вынесен в константу.
- **Спринт 2** — `/sourcehealth`: трекинг деградации скрейпинга по каждому
  источнику (consecutive-empty-fetch streak, персистится). Исправлен race
  condition: `settings.awaitingFeedback` (глобальный boolean) →
  `awaitingFeedback` (per-dialog Set) — иначе фидбэк из одного диалога мог
  ошибочно записаться как дизлайк из-за сообщения в другом диалоге.
- **Спринт 3** — Безопасность репозитория: секреты полностью убраны из
  README (были закоммичены в открытом виде — **владелец ротирует ключи
  сам при следующем деплое**, это НЕ автоматизировано патчем и не должно
  быть). Startup-валидация `VIBE_API_KEY` с понятной ошибкой вместо
  падения где-то глубоко в API-вызовах. Созданы `.gitignore`,
  `.env.example`, `scripts/check-secrets.sh` (grep-guard, можно повесить
  как pre-commit hook). Попутно исправлен предсуществующий баг — команда
  деплоя в README не включала `personality.js` в архив (бот упал бы при
  старте после деплоя по этой команде).
- **Спринт 4** — добавлены `handoff.md` (этот файл) и `roadmap.md`
  (предложения по развитию бота, отражающие практики
  news-digest/market-intelligence ботов 2026 года).

## Соглашения патч-скриптов (`apply_sprintN_patch.py`)

Если пишешь следующий патч (спринт 5+), следуй уже устоявшимся
конвенциям — они проверены на практике за 4 спринта:

- **Идемпотентность обязательна.** Каждое изменение — через
  `replace_once(old, new, label, already_applied_marker)`: если marker уже
  в файле — `[skip]`, если anchor не найден — `[WARN]` и пропуск (не
  падать), если anchor найден 2+ раз — `[WARN]` и пропуск (не гадать).
- **Pre-flight guard для зависимостей между спринтами.** Если патч N
  зависит от патча N-1 (использует функции/переменные, которые тот
  добавил), в начале — явная проверка маркера предыдущего спринта; если
  его нет — печатать понятную инструкцию и **не применять вообще ничего**
  (не оставлять файл в частично пропатченном состоянии). Пример в
  `apply_sprint2_patch.py`/`apply_sprint3_patch.py`.
- **Бэкапы перед любой записью** — `path.with_suffix(path.suffix +
  f".{timestamp}.bak")`, копия перед `.write_text()`.
- **Не жёстко фиксировать версии в анкорах, если строка не обновлялась
  предыдущим скриптом.** Раньше это уже ловило баги (см. спринт 3 —
  version-agnostic fallback для строки `index.js — весь код бота (vX.Y)`
  в README, т.к. предыдущие скрипты её не трогали). Если сомневаешься,
  обновлял ли предыдущий патч конкретную строку — проверь фактический
  вывод предыдущего скрипта на чистой копии, не полагайся на память о
  том, что "должно было" получиться.
- **Тестировать на СВЕЖЕЙ копии оригинала, не только на уже пропатченной
  рабочей копии.** Расхождения между "что я правил вручную для проверки"
  и "что реально производит скрипт" — main source бага в этом проекте
  (случалось трижды при подготовке спринта 3).
- **`node --check index.js` после каждого патча**, плюс где применимо —
  небольшой изолированный `node -e` unit-тест новой логики (health
  tracking, per-dialog Set race condition — оба протестированы так до
  того, как патч был выдан).
- Каждый скрипт печатает в конце конкретные next steps (diff, syntax
  check, commit/push команды) — сохраняй этот паттерн для консистентности
  UX между спринтами.
"""

ROADMAP_MD_CONTENT = r"""# Roadmap — Борис

Идеи развития, основанные на практиках новостных дайджест-ботов и
market-intelligence инструментов по состоянию на 2026 год (см. источники
внизу). Не всё нужно делать — это меню, не план спринтов; приоритизируй
по своим потребностям. Каждый пункт помечен ожидаемой сложностью
(🟢 просто / 🟡 средне / 🔴 требует архитектурных изменений).

## 1. Качество данных — дедупликация и скоринг (🟡)

Сейчас бот собирает сырые данные из поиска + 5 источников + трендов и
отдаёт всё целиком в LLM для генерации дайджеста за один проход. У
специализированных news-digest агентов в 2026 году стандартный паттерн —
**two-tier processing**: детерминированная дедупликация ДО LLM, и только
затем суммаризация.

- **Дедупликация по заголовку** (semantic similarity или хотя бы
  fuzzy-match до отправки в LLM) — сейчас несколько источников могут
  принести одну и ту же новость в разных формулировках, и LLM тратит
  контекст на распознавание дублей вместо анализа.
- **Priority/recency scoring** перед генерацией: `score = base +
  priority_bonus(источник) + recency_bonus(время публикации)`. Например,
  Bloomberg Línea и CNN Brasil получают +2 за авторитетность, breaking
  news последних 6 часов — +2 за свежесть. Сейчас все источники и все
  новости равнозначны для LLM, что может размывать действительно важное
  под менее значимым.
- **Source-level upsert между запросами** — хранить хэши/ID уже
  присланных новостей (в `settings` или отдельном файле), чтобы одна и
  та же история не попала в дайджест дважды при ручном перезапуске
  `/news` в один день.

## 2. Персонализированные алерты и watchlist (🟡)

Один из главных паттернов и в consumer news-дайджестах (Readless, Digest),
и в market-intelligence инструментах (ZoomInfo, AlphaSense) — не только
плановая рассылка, но и **точечные оповещения по конкретным сущностям**:

- `/watch <компания/тема>` — добавить компанию, бренд или тему в
  watchlist; бот присылает отдельное уведомление вне расписания, если
  появляется значимая новость по ней (а не ждёт следующего дайджеста).
- `/unwatch <тема>` — убрать.
- Особенно уместно для PR/контент-роли: например, watchlist на
  «Bitrix24 Brasil», конкурентов, или отраслевые темы, которые сейчас
  ведутся вручную.

## 3. Множественные каналы доставки (🟢/🟡)

Сейчас бот жёстко привязан к одному `BITRIX_USER_ID` в одном чате
Bitrix24. У большинства современных дайджест-ботов — доставка туда, где
удобно читателю:

- Отправка дайджеста не только текстом в чат, но и **email-версией**
  (простой SMTP или сервис вроде SendGrid) — полезно, если получателей
  станет несколько, или для архива.
- Публикация в отдельный Bitrix24-канал/группу (не только личка) —
  минимальное изменение, раз Bitrix24 API это уже поддерживает.
- Экспорт дайджеста как отдельный `.md`/`.pdf` файл по запросу
  (`/export`) — удобно, если дайджест нужно переслать кому-то как
  документ, а не скриншотить чат.

## 4. Улучшенная персонализация (🟡)

- **Табличные предпочтения по темам**, а не только вкл/выкл — например,
  «больше про AI/tech, меньше про поп-культуру» с весами, влияющими на
  scoring из п.1, а не просто бинарный список тем.
- **Дневной/недельный ритм подстройки** (паттерн из Readless-гайда:
  «раз в неделю убери один источник, который пропускаешь, добавь один,
  который хотел бы видеть») — можно оформить как еженедельный
  «`/tuning` — что убрать/добавить» промпт от самого бота, а не только
  реактивный `/feedback`.
- Учитывать историю дизлайков (`settings.feedback.dislikes`) не только в
  промпте генерации дайджеста, но и в scoring (п.1) — тема, которая
  регулярно получает дизлайк, снижает свой вес автоматически, а не
  просто попадает текстовой пометкой в system-промпт.

## 5. Более глубокий контекст диалога (🟡/🔴)

Спринт 1 дал LLM-ответ на свободный ввод, но с чисто эфемерной памятью
(сбрасывается при рестарте). Следующий логичный шаг, судя по тому, что
именно отличает более развитые боты 2026 года от базовых чат-обёрток —
**персистентная память**, а не только in-session:

- Персистить `conversationHistory` в `/data/` (не только settings) —
  тогда бот помнит контекст между рестартами/сном сервера, а не только
  в рамках одной активной сессии.
- **RAG над собственными прошлыми дайджестами** — если пользователь
  спрашивает «а что там было с X на прошлой неделе», бот сейчас не может
  ответить (у него нет доступа к своим прошлым дайджестам, только к
  последним N репликам диалога). Простой вариант без полноценной
  векторной БД: хранить последние M дайджестов как есть в `/data/`, и
  при вопросе — просто отдавать LLM как доп. контекст (не обязательно
  сложный embedding-поиск, если объём небольшой).

## 6. Более широкий охват источников (🟢/🟡)

- Твиттер/X через официальный API (сейчас `trends24.in` — сторонний
  скрейпер трендов Twitter, что хрупко и юридически не то же самое, что
  прямой доступ).
- LinkedIn / отраслевые Bitrix24-related пабликации, раз тема — B2B SaaS
  в Бразилии.
- GitHub releases/трендовые репозитории — если тема AI/tech продолжает
  быть важной темой дайджеста (паттерн из "OpenClaw Tech News Digest",
  который явно включает GitHub releases как отдельный источник).

## 7. Наблюдаемость и качество (🟢, логичное продолжение спринта 2)

- **Метрика "полезности" дайджеста** — не только счётчик 👍/👎 за весь
  дайджест целиком, но и per-story feedback (какая конкретно история
  понравилась/нет) — даёт гораздо более точный сигнал для scoring из п.1.
- **Еженедельный self-report** — бот сам раз в неделю присылает короткую
  сводку: сколько дайджестов отправлено, health источников, тренд
  👍/👎 за неделю. Дешёвая надстройка над уже существующими
  `settings.feedback` и `settings.sourceHealth`.

## 8. Безопасность и эксплуатация (🟢, продолжение спринта 3)

- **Ротация ключей по расписанию**, а не только реактивно при утечке —
  многие команды в 2026 году держат 90-дневный цикл ротации API-ключей
  как стандарт гигиены, а не только "если что-то случилось".
  `handoff.md`/README можно дополнить датой последней ротации.
- **Rate-limit / cost guard** на LLM-вызовы — сейчас `/news`,
  `/showtrends`, `/surprise` можно спамить руками без ограничения (кроме
  `scheduleHeavyJob`, который защищает только от параллельного запуска,
  не от частого последовательного). Простой троттлинг (не чаще раза в
  N минут на команду) защитит от случайного перерасхода токенов LLM.

---

## Источники (актуальность — 2026 год)

Ниже — на что опирался этот roadmap; полезно перечитать при следующем
пересмотре, практики могут смениться:

- OpenClaw Tech News Digest (two-tier processing, priority/recency/
  engagement scoring, source-level upsert dedup) — openclawconsult.com
- n8n "Personalized news digests with GPT-5.1, SerpAPI, Telegram delivery"
  (source-level dedup via upsert, modular source config) — n8n.io
- Readless "Personalized News Digest: How to Build Yours in 2026"
  (weekly source tuning ритм, 10-15 источников как разумный старт) —
  readless.app
- Qualtir "Best AI Bots for Telegram 2026" (persistent memory между
  сессиями как ключевое отличие развитых ботов) — qualtir.com
- Improvado / Demandbase / Guideflow — обзоры market-intelligence
  платформ 2026 (watchlist/alerts по конкретным сущностям, real-time
  triggers, competitive signals) — improvado.io, demandbase.com,
  guideflow.com
- "AI Chatbot Best Practices 2026" — общие практики RAG-гигиены,
  guardrails, continuous iteration — successknocks.com

Эти источники описывают рынок в целом, не именно Bitrix24 vibecode —
адаптируй с поправкой на платформенные ограничения (см. `handoff.md` →
«Известные архитектурные ограничения»).
"""


def main():
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_dir = find_bot_dir(cli_arg)
    print(f"Using bot directory: {bot_dir}")

    check_prior_sprints(bot_dir)

    print("\nCreating project memory files ...")
    write_if_absent(bot_dir / "handoff.md", HANDOFF_MD_CONTENT, "handoff.md")
    write_if_absent(bot_dir / "roadmap.md", ROADMAP_MD_CONTENT, "roadmap.md")

    print("\nDone. Next steps:")
    print("  1. Review: cat '%s'" % (bot_dir / "handoff.md"))
    print("             cat '%s'" % (bot_dir / "roadmap.md"))
    print("  2. Commit:")
    print("       git -C '%s' add handoff.md roadmap.md" % bot_dir)
    print("       git -C '%s' commit -m \"sprint4: add handoff.md (persistent project memory) and roadmap.md\"" % bot_dir)
    print("       git -C '%s' push" % bot_dir)
    print()
    print("  ⚠️  Reminder for future work on this bot: handoff.md is never deleted.")
    print("      Update its \"Текущее состояние\" and \"История спринтов\" sections by")
    print("      hand (or have your next patch script do it) after every future change —")
    print("      don't let it go stale, and don't let a future script silently overwrite")
    print("      it wholesale the way this one refuses to.")


if __name__ == "__main__":
    main()
