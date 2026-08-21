#!/usr/bin/env python3
"""
Sprint 7 patch for brazil-news-bot (Boris) — observability via per-story
feedback, per roadmap.md section 7.

DECISION: per-story feedback uses buttons under each story (the existing
pattern from getFeedbackKeyboard(), just made granular), not message
reactions -- confirmed with the project owner. Reactions
(imbot.v2.Chat.Message.Reaction.add / ONIMBOTV2REACTIONCHANGE) remain
unused; see the "Инфраструктура Вайбкод" section of README.md for that
option if it's revisited later.

PREREQUISITE: sprint 0-3, 5, and 6 must already be applied (anchors are the
post-sprint-6 shape of index.js: dedupeAndScoreHeadlines/SOURCE_PRIORITY
present, VERSION \'14.3\'). Hard-aborts if that shape isn\'t found.

--- Why this is a bigger change than earlier sprints ---
Per-story buttons require each story to be its own message, which requires
knowing where one story ends and the next begins. generateDigest() used to
return one prose blob written by the LLM (\'✨ Борис: ...\n\n[тема]: [заголовок]\n...\'),
with no structure to split on reliably. This patch changes generateDigest()\'s
output contract from prose to structured JSON: {summary, stories[], trends[]}
where each story is {topic, title, date, body, why, source}. All three call
sites (daily briefing, /showtrends, /surprise) are updated together, since
they all go through the same function and none can be left consuming the old
prose shape.

What this does:
  1. DEFAULT_SETTINGS gains storyFeedback: {topicCounts, recentReactions} --
     topicCounts is the aggregate ("which topics keep getting thumbed
     down") that roadmap.md\'s scoring/personalization sprints (6, 9) can
     eventually read; recentReactions is a capped log for /status.
  2. generateDigest()\'s system prompt (both RU and PT branches) now asks
     for strict JSON matching the {summary, stories[], trends[]} schema,
     replacing the old free-text "Формат ответа" instructions. All the
     surrounding editorial guidance (freshness rules, exclusion list, "wow
     factor" criteria, category list) is untouched -- only the output-format
     instructions at the end of each branch changed.
  3. parseDigestJSON(raw) parses the LLM response, defensively stripping a
     ```json fence if the model adds one despite being told not to, and
     returns null (never a partial/malformed object) on any parse failure
     or a missing "stories" array, so callers fall back to an error message
     instead of sending broken output.
  4. hashStory(title) -- short deterministic id (djb2-style hash, base36) so
     a story\'s identity survives a round trip through a keyboard button\'s
     ACTION_VALUE.
  5. storyLookupCache -- in-memory Map (hash -> {topic, title}), NOT
     persisted to disk, populated whenever sendDigestAsMessages() actually
     sends a story. This is what lets a later 👍/👎 tap resolve which topic
     to credit -- settings.storyFeedback is the persisted feedback log,
     this cache is just a short-lived index over "stories currently sitting
     in someone\'s chat with live buttons". Capped at
     STORY_LOOKUP_CACHE_LIMIT so a long-running process can\'t leak memory.
  6. sendDigestAsMessages(dialogId, digest, introText) -- shared by all
     three call sites. Sends an intro message, then one message per story
     with its own getStoryFeedbackKeyboard() (👍/👎), then a trends block
     (or a "rate the whole digest" prompt if no trends), and records every
     sent story into recentlySentHeadlines (sprint 6) so a manual re-run
     doesn\'t repeat them.
  7. New /storyfeedback <hash> good|bad command, triggered by the per-story
     buttons. Deliberately one tap, no follow-up question (unlike /feedback
     bad, which asks what was wrong) -- asking for a written reason on every
     individual story would defeat the point of this being lower-friction.
  8. /status shows an aggregate story-feedback line via
     formatStoryFeedbackSummary(), which only names a "worst topic" once it
     has at least MIN_REACTIONS_FOR_SIGNAL reactions -- so one stray
     downvote doesn\'t get called out.
  9. /help documents the split between /feedback (whole digest) and the
     per-story buttons.

Usage:
    python3 apply_sprint7_patch.py [path/to/brazil-news-bot]

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
    print("       Pass the path explicitly: python3 apply_sprint7_patch.py /path/to/brazil-news-bot")
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
        print(f"  [WARN] {label}: anchor text not found -- skipping.")
        return content
    if count > 1:
        print(f"  [WARN] {label}: anchor found {count} times (expected 1) -- skipping to avoid a bad patch.")
        return content
    print(f"  [ok]   {label}")
    return content.replace(old, new, 1)

OLD1 = '  recentlySentHeadlines: {}\n};'
NEW1 = '  recentlySentHeadlines: {},\n  // Per-story feedback (sprint 7): 👍/👎 attached to each individual story\n  // in a digest, not just one rating for the whole digest. topicCounts is\n  // the aggregate signal ("which topics keep getting thumbed down") that\n  // roadmap.md\'s scoring/personalization sprints (6, 9) can eventually use;\n  // recentReactions keeps the last STORY_FEEDBACK_HISTORY_LIMIT individual\n  // reactions for /status visibility, most recent first.\n  storyFeedback: {\n    topicCounts: {},\n    recentReactions: []\n  }\n};'

OLD2 = 'Формат выдачи:\n- 5-7 самых интересных историй + блок свежих трендов\n- В конце — «Резюме дня» (1-2 предложения, что сегодня самое интересное)\n\nФормат ответа:\n✨ Борис: самое интересное сегодня\n📅 {даты}\n\n[тема]: [цепляющий заголовок]\n📅 [дата публикации/актуальности]\n[суть истории]\n[почему это интересно]\n\n🔗 Источник\n\n...\n\n🔥 Тренды (свежие): [что сейчас в тренде]\n📅 [дата актуальности тренда]\n[краткое описание]\n\n📌 Резюме дня: [1-2 предложения]`\n    : `Você é o Boris'
NEW2 = 'Формат выдачи — строго JSON, без markdown-разметки вокруг, без текста до или после JSON. Схема:\n{\n  "summary": "1-2 предложения — что сегодня самое интересное",\n  "stories": [\n    {\n      "topic": "категория из списка выше",\n      "title": "цепляющий заголовок",\n      "date": "дата публикации/актуальности, например 10/08/2026 или сегодня",\n      "body": "суть истории, 2-3 предложения: что произошло, где, когда",\n      "why": "почему это интересно/забавно/удивительно",\n      "source": "ссылка на первоисточник или название источника, если ссылки нет"\n    }\n  ],\n  "trends": [\n    {\n      "topic": "название тренда",\n      "date": "дата актуальности тренда",\n      "body": "почему тема в тренде прямо сейчас и почему это интересно"\n    }\n  ]\n}\n5-7 историй в "stories". "trends" может быть пустым массивом, если трендов не было в исходных данных. Каждая история и каждый тренд ОБЯЗАТЕЛЬНО должны иметь непустое поле "date" — без даты запись не принимается.`\n    : `Você é o Boris'

OLD3 = 'Formato de saída:\n- 5-7 histórias mais interessantes + bloco de tendências frescas\n- No final — «Resumo do dia» (1-2 frases sobre o que é mais interessante hoje)\n\nFormato da resposta:\n✨ Boris: o mais interessante hoje\n📅 {datas}\n\n[tema]: [título cativante]\n📅 [data de publicação/atualidade]\n[essência da história]\n[por que é interessante]\n\n🔗 Fonte\n\n...\n\n🔥 Tendências (frescas): [o que está em alta agora]\n📅 [data de atualidade da tendência]\n[breve descrição]\n\n📌 Resumo do dia: [1-2 frases]`;'
NEW3 = 'Formato de saída — estritamente JSON, sem markdown ao redor, sem texto antes ou depois do JSON. Esquema:\n{\n  "summary": "1-2 frases — o que é mais interessante hoje",\n  "stories": [\n    {\n      "topic": "categoria da lista acima",\n      "title": "título cativante",\n      "date": "data de publicação/atualidade, ex.: 10/08/2026 ou hoje",\n      "body": "essência da história, 2-3 frases: o que aconteceu, onde, quando",\n      "why": "por que é interessante/engraçado/surpreendente",\n      "source": "link para a fonte original ou nome da fonte, se não houver link"\n    }\n  ],\n  "trends": [\n    {\n      "topic": "nome da tendência",\n      "date": "data de atualidade da tendência",\n      "body": "por que o tema virou tendência agora e por que é interessante"\n    }\n  ]\n}\n5-7 histórias em "stories". "trends" pode ser um array vazio se não havia tendências nos dados brutos. Cada história e cada tendência DEVEM ter o campo "date" preenchido — sem data, o item não é aceito.`;'

OLD4 = "      method: 'POST',\n      headers: {\n        'X-Api-Key': VIBE_API_KEY,\n        'Content-Type': 'application/json'\n      },\n      body: {\n        model: 'bitrix/bitrixgpt-5.5',\n        messages: [\n          { role: 'system', content: systemPrompt },\n          { role: 'user', content: userContent }\n        ],\n        temperature: 0.3,\n        max_tokens: 4000\n      }\n    });\n    \n    if (result.status === 200 && result.data && result.data.choices && result.data.choices[0]) {\n      return result.data.choices[0].message.content;\n    }\n    console.error('AI response error:', result.status, JSON.stringify(result.data).substring(0, 300));\n    return null;\n  } catch (error) {\n    console.error('AI generate failed:', error.message);\n    return null;\n  }\n}"
NEW4 = '      method: \'POST\',\n      headers: {\n        \'X-Api-Key\': VIBE_API_KEY,\n        \'Content-Type\': \'application/json\'\n      },\n      body: {\n        model: \'bitrix/bitrixgpt-5.5\',\n        messages: [\n          { role: \'system\', content: systemPrompt },\n          { role: \'user\', content: userContent }\n        ],\n        temperature: 0.3,\n        max_tokens: 4000\n      }\n    });\n    \n    if (result.status === 200 && result.data && result.data.choices && result.data.choices[0]) {\n      const raw = result.data.choices[0].message.content;\n      return parseDigestJSON(raw);\n    }\n    console.error(\'AI response error:\', result.status, JSON.stringify(result.data).substring(0, 300));\n    return null;\n  } catch (error) {\n    console.error(\'AI generate failed:\', error.message);\n    return null;\n  }\n}\n\n// Parses generateDigest()\'s LLM response into { summary, stories, trends }.\n// The prompt asks for strict JSON, but models sometimes wrap it in a\n// ```json fence anyway despite instructions not to — stripped defensively\n// before parsing. Returns null (not a partial/malformed object) on any\n// parse failure or missing "stories" array, so callers can fall back to\n// "couldn\'t generate a digest right now" instead of sending broken output.\nfunction parseDigestJSON(raw) {\n  if (!raw) return null;\n  let text = raw.trim();\n  const fenceMatch = text.match(/^```(?:json)?\\s*([\\s\\S]*?)\\s*```$/);\n  if (fenceMatch) text = fenceMatch[1].trim();\n  try {\n    const parsed = JSON.parse(text);\n    if (!parsed || !Array.isArray(parsed.stories)) {\n      console.error(\'Digest JSON missing "stories" array:\', text.substring(0, 300));\n      return null;\n    }\n    return {\n      summary: typeof parsed.summary === \'string\' ? parsed.summary : \'\',\n      stories: parsed.stories.filter(s => s && s.title),\n      trends: Array.isArray(parsed.trends) ? parsed.trends.filter(t => t && t.topic) : []\n    };\n  } catch (error) {\n    console.error(\'Digest JSON parse failed:\', error.message, \'| raw (truncated):\', text.substring(0, 300));\n    return null;\n  }\n}'

OLD5 = '  return result;\n}\n\nconst SOURCES = ['
NEW5 = '  return result;\n}\n\n// --- Per-story feedback and digest delivery (sprint 7) -------------------\n// A short, stable, deterministic id for a story, derived from its\n// normalized title. Needs to survive a round trip through a keyboard\n// button\'s ACTION_VALUE (short string, no spaces/newlines) and stay the\n// same for the "same" story across re-runs, so djb2-style string hash to\n// base36 rather than anything random or position-dependent.\nfunction hashStory(title) {\n  const normalized = normalizeForDedup(title);\n  let hash = 5381;\n  for (let i = 0; i < normalized.length; i++) {\n    hash = ((hash * 33) ^ normalized.charCodeAt(i)) >>> 0;\n  }\n  return hash.toString(36);\n}\n\nconst STORY_FEEDBACK_HISTORY_LIMIT = 50; // most recent per-story reactions kept for /status\n\n// In-memory lookup from story hash -> { topic, title }, populated whenever\n// sendDigestAsMessages() actually sends a story, so a later 👍/👎 tap can\n// resolve which topic to credit/blame. Deliberately NOT persisted to disk:\n// it\'s a short-lived index over "stories currently sitting in someone\'s\n// chat with live buttons", not a feedback record — settings.storyFeedback\n// is the actual persisted log. A restart between sending a digest and\n// someone tapping its buttons is an acceptably rare edge case (falls back\n// to the "Без темы" bucket in recordStoryFeedback, same as an unknown/old\n// hash) rather than something worth the complexity of persisting this too.\n// Capped so a long-running process can\'t leak memory across many digests.\nconst STORY_LOOKUP_CACHE_LIMIT = 500;\nconst storyLookupCache = new Map(); // hash -> { topic, title }\n\nfunction rememberStoryForFeedback(hash, topic, title) {\n  storyLookupCache.set(hash, { topic, title });\n  if (storyLookupCache.size > STORY_LOOKUP_CACHE_LIMIT) {\n    const oldestKey = storyLookupCache.keys().next().value;\n    storyLookupCache.delete(oldestKey);\n  }\n}\n\nfunction getStoryFeedbackKeyboard(storyHash) {\n  return [\n    { TEXT: \'👍\', ACTION: \'SEND\', ACTION_VALUE: `/storyfeedback ${storyHash} good`, BG_COLOR_TOKEN: \'primary\', DISPLAY: \'LINE\' },\n    { TEXT: \'👎\', ACTION: \'SEND\', ACTION_VALUE: `/storyfeedback ${storyHash} bad`, BG_COLOR_TOKEN: \'alert\', DISPLAY: \'LINE\' }\n  ];\n}\n\n// Records a single story-level reaction. Deliberately one tap, no follow-up\n// question (unlike digest-level /feedback bad, which asks what was wrong) —\n// asking for a written reason on every individual story would make the\n// per-story keyboard annoying to use, defeating the point of it being\n// lower-friction than the whole-digest feedback.\nfunction recordStoryFeedback(storyHash, topic, title, reaction) {\n  if (!settings.storyFeedback) settings.storyFeedback = { topicCounts: {}, recentReactions: [] };\n  const safeTopic = topic || \'Без темы\';\n  if (!settings.storyFeedback.topicCounts[safeTopic]) {\n    settings.storyFeedback.topicCounts[safeTopic] = { good: 0, bad: 0 };\n  }\n  settings.storyFeedback.topicCounts[safeTopic][reaction]++;\n  settings.storyFeedback.recentReactions.unshift({\n    hash: storyHash,\n    topic: safeTopic,\n    title: title || \'\',\n    reaction,\n    ts: new Date().toISOString()\n  });\n  settings.storyFeedback.recentReactions = settings.storyFeedback.recentReactions.slice(0, STORY_FEEDBACK_HISTORY_LIMIT);\n  saveSettings();\n}\n\n// One-line /status summary: total per-story reactions + the single\n// most-disliked topic if any topic has at least MIN_REACTIONS_FOR_SIGNAL\n// reactions against it (avoids calling out a topic off just 1 stray tap).\nconst MIN_REACTIONS_FOR_SIGNAL = 3;\nfunction formatStoryFeedbackSummary() {\n  const counts = (settings.storyFeedback && settings.storyFeedback.topicCounts) || {};\n  const topics = Object.entries(counts);\n  if (topics.length === 0) return `📝 Оценки историй: пока нет данных\\n`;\n\n  let totalGood = 0, totalBad = 0;\n  let worstTopic = null, worstBad = 0;\n  for (const [topic, c] of topics) {\n    totalGood += c.good;\n    totalBad += c.bad;\n    const total = c.good + c.bad;\n    if (total >= MIN_REACTIONS_FOR_SIGNAL && c.bad > worstBad) {\n      worstBad = c.bad;\n      worstTopic = topic;\n    }\n  }\n  const worstNote = worstTopic ? `, чаще всего 👎 — «${worstTopic}»` : \'\';\n  return `📝 Оценки историй: ${totalGood} 👍 / ${totalBad} 👎${worstNote}\\n`;\n}\n\n// Sends a digest (the { summary, stories, trends } shape parseDigestJSON()\n// returns) as one message per story instead of one giant block of text —\n// each story gets its own 👍/👎 keyboard via getStoryFeedbackKeyboard().\n// `introText` is the header line shown before the first story (kept\n// caller-supplied since the daily briefing, /showtrends, and /surprise each\n// want different wording here). `kind` is only used for a fallback title if\n// a story is somehow missing a topic. Records every sent story into\n// recentlySentHeadlines (sprint 6) so a manual re-run doesn\'t repeat them.\nasync function sendDigestAsMessages(dialogId, digest, introText) {\n  const lines = [introText];\n  if (digest.summary) lines.push(`📌 ${digest.summary}`);\n  await sendBotMessage(dialogId, lines.join(\'\\n\\n\'), getMainKeyboard());\n\n  for (const story of digest.stories) {\n    const parts = [];\n    parts.push(`*${story.topic || \'Интересное\'}: ${story.title}*`);\n    if (story.date) parts.push(`📅 ${story.date}`);\n    if (story.body) parts.push(story.body);\n    if (story.why) parts.push(story.why);\n    if (story.source) parts.push(`🔗 ${story.source}`);\n    const storyHash = hashStory(story.title);\n    rememberStoryForFeedback(storyHash, story.topic || null, story.title || null);\n    await sendBotMessage(dialogId, parts.join(\'\\n\'), getStoryFeedbackKeyboard(storyHash));\n    await new Promise(resolve => setTimeout(resolve, 400)); // avoid hammering the API with a burst of sends\n  }\n\n  if (digest.trends && digest.trends.length > 0) {\n    const trendLines = [\'🔥 *Тренды (свежие)*\'];\n    for (const t of digest.trends) {\n      trendLines.push(\'\');\n      trendLines.push(`*${t.topic}*`);\n      if (t.date) trendLines.push(`📅 ${t.date}`);\n      if (t.body) trendLines.push(t.body);\n    }\n    await sendBotMessage(dialogId, trendLines.join(\'\\n\'), getFeedbackKeyboard());\n  } else {\n    await sendBotMessage(dialogId, \'Оцени дайджест в целом:\', getFeedbackKeyboard());\n  }\n\n  const sentTitles = digest.stories.map(s => s.title).filter(Boolean);\n  if (sentTitles.length > 0) recordSentHeadlines(sentTitles);\n}\n\nconst SOURCES = ['

OLD6 = "  const digest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () =>\n    generateDigest(rawNews, trendNews, sourceNews)\n  );\n  if (!digest) {\n    await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест. Попробуй ещё раз.', getMainKeyboard());\n    return false;\n  }\n  \n  // Send digest with feedback buttons\n  const sent = await sendBotMessage(dialogId, digest, getFeedbackKeyboard());\n  console.log(`[${new Date().toISOString()}] Briefing ${sent ? 'sent' : 'failed'} (${rawNews.length} news, ${trendNews.length} trends, ${sourceNews.length} sources)`);\n  return sent;\n}"
NEW6 = "  const digest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () =>\n    generateDigest(rawNews, trendNews, sourceNews)\n  );\n  if (!digest || digest.stories.length === 0) {\n    await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест. Попробуй ещё раз.', getMainKeyboard());\n    return false;\n  }\n  \n  // Send digest as one message per story (sprint 7), each with its own\n  // 👍/👎 keyboard, instead of one giant block of text.\n  const introText = settings.lang === 'ru'\n    ? `✨ *Борис: самое интересное сегодня*\\n📅 ${formatDateBR(new Date())}`\n    : `✨ *Boris: o mais interessante hoje*\\n📅 ${formatDateBR(new Date())}`;\n  await sendDigestAsMessages(dialogId, digest, introText);\n  console.log(`[${new Date().toISOString()}] Briefing sent (${rawNews.length} news, ${trendNews.length} trends, ${sourceNews.length} sources, ${digest.stories.length} stories delivered)`);\n  return true;\n}"

OLD7 = "    case 'showtrends':\n      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);\n      await sendBotMessage(dialogId, '⏳ Ищу свежие тренды (последние 72 часа)...', getMainKeyboard());\n      scheduleHeavyJob(async () => {\n        const trendNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectTrends());\n        if (trendNews.length === 0) {\n          await sendBotMessage(dialogId, '❌ Не удалось собрать тренды сейчас. Попробуй позже.', getMainKeyboard());\n          return;\n        }\n        const trendDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([], trendNews));\n        if (trendDigest) {\n          await sendBotMessage(dialogId, trendDigest, getFeedbackKeyboard());\n        }\n      }, 'trends');\n      break;\n\n    case 'surprise':\n    case 'random':\n      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);\n      await sendBotMessage(dialogId, '🎲 Ищу случайную интересную историю...', getMainKeyboard());\n      scheduleHeavyJob(async () => {\n        const surpriseNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectRawNews());\n        if (surpriseNews.length === 0) {\n          await sendBotMessage(dialogId, '❌ Не удалось найти историю. Попробуй позже.', getMainKeyboard());\n          return;\n        }\n        const pick = surpriseNews[Math.floor(Math.random() * surpriseNews.length)];\n        const surpriseDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([pick], []));\n        if (surpriseDigest) {\n          await sendBotMessage(dialogId, surpriseDigest, getFeedbackKeyboard());\n        }\n      }, 'surprise');\n      break;\n      \n"
NEW7 = "    case 'showtrends':\n      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);\n      await sendBotMessage(dialogId, '⏳ Ищу свежие тренды (последние 72 часа)...', getMainKeyboard());\n      scheduleHeavyJob(async () => {\n        const trendNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectTrends());\n        if (trendNews.length === 0) {\n          await sendBotMessage(dialogId, '❌ Не удалось собрать тренды сейчас. Попробуй позже.', getMainKeyboard());\n          return;\n        }\n        const trendDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([], trendNews));\n        if (trendDigest && trendDigest.stories.length > 0) {\n          const introText = settings.lang === 'ru' ? '🔥 *Свежие тренды*' : '🔥 *Tendências frescas*';\n          await sendDigestAsMessages(dialogId, trendDigest, introText);\n        } else {\n          await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест трендов. Попробуй ещё раз.', getMainKeyboard());\n        }\n      }, 'trends');\n      break;\n\n    case 'surprise':\n    case 'random':\n      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);\n      await sendBotMessage(dialogId, '🎲 Ищу случайную интересную историю...', getMainKeyboard());\n      scheduleHeavyJob(async () => {\n        const surpriseNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectRawNews());\n        if (surpriseNews.length === 0) {\n          await sendBotMessage(dialogId, '❌ Не удалось найти историю. Попробуй позже.', getMainKeyboard());\n          return;\n        }\n        const pick = surpriseNews[Math.floor(Math.random() * surpriseNews.length)];\n        const surpriseDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([pick], []));\n        if (surpriseDigest && surpriseDigest.stories.length > 0) {\n          const introText = settings.lang === 'ru' ? '🎲 *Случайная история*' : '🎲 *História aleatória*';\n          await sendDigestAsMessages(dialogId, surpriseDigest, introText);\n        } else {\n          await sendBotMessage(dialogId, '❌ Не удалось сгенерировать историю. Попробуй ещё раз.', getMainKeyboard());\n        }\n      }, 'surprise');\n      break;\n      \n"

OLD8 = '    case \'feedback\':\n      if (params === \'good\') {\n        settings.feedback.good++;\n        saveSettings();\n        await sendBotMessage(dialogId, `👍 Спасибо! Рад, что понравилось. (Всего: ${settings.feedback.good} 👍, ${settings.feedback.bad} 👎)`, getMainKeyboard());\n      } else if (params === \'bad\') {\n        settings.feedback.bad++;\n        awaitingFeedback.add(dialogId);\n        saveSettings();\n        await sendBotMessage(dialogId, `👎 Спасибо за честность! Что именно вам не понравилось? Напишите, например: "не нравится тема про недвижимость" или "слишком длинные новости". Я учту это.`, getMainKeyboard());\n      } else {\n        await sendBotMessage(dialogId, \'Используйте кнопки 👍 или 👎 для оценки.\', getFeedbackKeyboard());\n      }\n      break;\n      \n'
NEW8 = '    case \'feedback\':\n      if (params === \'good\') {\n        settings.feedback.good++;\n        saveSettings();\n        await sendBotMessage(dialogId, `👍 Спасибо! Рад, что понравилось. (Всего: ${settings.feedback.good} 👍, ${settings.feedback.bad} 👎)`, getMainKeyboard());\n      } else if (params === \'bad\') {\n        settings.feedback.bad++;\n        awaitingFeedback.add(dialogId);\n        saveSettings();\n        await sendBotMessage(dialogId, `👎 Спасибо за честность! Что именно вам не понравилось? Напишите, например: "не нравится тема про недвижимость" или "слишком длинные новости". Я учту это.`, getMainKeyboard());\n      } else {\n        await sendBotMessage(dialogId, \'Используйте кнопки 👍 или 👎 для оценки.\', getFeedbackKeyboard());\n      }\n      break;\n\n    case \'storyfeedback\': {\n      // Triggered by the 👍/👎 buttons under an individual story\n      // (sprint 7) — ACTION_VALUE is "/storyfeedback <hash> good|bad".\n      // Deliberately no follow-up question here (unlike /feedback bad\n      // above) — see recordStoryFeedback()\'s comment for why.\n      const [storyHash, reaction] = params.split(\' \');\n      if (!storyHash || (reaction !== \'good\' && reaction !== \'bad\')) {\n        await sendBotMessage(dialogId, \'❌ Не удалось разобрать оценку истории.\', getMainKeyboard());\n        break;\n      }\n      // Resolve topic/title from the in-memory send-time cache. Falls back\n      // to "Без темы" (inside recordStoryFeedback) if the process restarted\n      // since this story was sent, or the cache evicted it — the reaction\n      // itself is still recorded either way, just without topic attribution.\n      const cached = storyLookupCache.get(storyHash);\n      const topic = cached ? cached.topic : null;\n      const title = cached ? cached.title : null;\n      recordStoryFeedback(storyHash, topic, title, reaction);\n      await sendBotMessage(dialogId, reaction === \'good\' ? \'👍 Учтено!\' : \'👎 Учтено, буду показывать поменьше такого.\', null);\n      break;\n    }\n\n'

OLD9 = "        '• /feedback good|bad — оценка\\n' +\n"
NEW9 = "        '• /feedback good|bad — оценка дайджеста целиком (по историям — кнопки 👍/👎 под каждой)\\n' +\n"

OLD10 = "    case 'status':\n      const unhealthy = getUnhealthySources();\n      const healthLine = unhealthy.length > 0\n        ? `⚠️ Проблемные источники (0 результатов ${SOURCE_HEALTH_ALERT_THRESHOLD}+ раз подряд): ${unhealthy.map(h => h.id).join(', ')} — см. /sourcehealth\\n`\n        : `✅ Все источники в норме\\n`;\n      await sendBotMessage(dialogId,\n        `📊 *Статус Бориса*\\n\\n` +\n        `✅ Бот активен\\n` +\n        `📰 Тем: ${settings.topics.length}\\n` +\n        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +\n        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +\n        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +\n        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +\n        `🧠 AI-генерация дайджеста: включена\\n` +\n        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +\n        `🧹 Дедуп (посл. сбор): ${lastDedupStats.input} → ${lastDedupStats.output} (склеено ${lastDedupStats.collapsed}, повторов заблокировано ${lastDedupStats.blockedRepeats})\\n` +\n        healthLine +\n        `🔧 Версия: ${VERSION}`,\n        getMainKeyboard()\n      );\n      break;\n"
NEW10 = "    case 'status':\n      const unhealthy = getUnhealthySources();\n      const healthLine = unhealthy.length > 0\n        ? `⚠️ Проблемные источники (0 результатов ${SOURCE_HEALTH_ALERT_THRESHOLD}+ раз подряд): ${unhealthy.map(h => h.id).join(', ')} — см. /sourcehealth\\n`\n        : `✅ Все источники в норме\\n`;\n      const storyFeedbackLine = formatStoryFeedbackSummary();\n      await sendBotMessage(dialogId,\n        `📊 *Статус Бориса*\\n\\n` +\n        `✅ Бот активен\\n` +\n        `📰 Тем: ${settings.topics.length}\\n` +\n        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\\n` +\n        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\\n` +\n        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\\n` +\n        `👍 Оценки дайджеста: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\\n` +\n        storyFeedbackLine +\n        `🧠 AI-генерация дайджеста: включена\\n` +\n        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\\n` +\n        `🧹 Дедуп (посл. сбор): ${lastDedupStats.input} → ${lastDedupStats.output} (склеено ${lastDedupStats.collapsed}, повторов заблокировано ${lastDedupStats.blockedRepeats})\\n` +\n        healthLine +\n        `🔧 Версия: ${VERSION}`,\n        getMainKeyboard()\n      );\n      break;\n"



def patch_index_js(path: Path):
    print(f"\nPatching {path.name} ...")
    original = path.read_text(encoding="utf-8")
    content = original

    # --- Pre-flight: refuse to run against a pre-sprint-6 file ---
    PREREQ_MARKER = "function dedupeAndScoreHeadlines(items) {"
    if PREREQ_MARKER not in content:
        print("  [ABORT] sprint 6 changes not found in this file (no dedupeAndScoreHeadlines()).")
        print("          Run sprint 0-3, 5, and 6 first. No changes were made.")
        return

    content = replace_once(content, OLD1, NEW1,
        label="DEFAULT_SETTINGS: add storyFeedback",
        already_applied_marker="storyFeedback: {\n    topicCounts: {},")

    content = replace_once(content, OLD2, NEW2,
        label="RU prompt: switch output format to strict JSON schema",
        already_applied_marker="Формат выдачи — строго JSON")

    content = replace_once(content, OLD3, NEW3,
        label="PT prompt: switch output format to strict JSON schema",
        already_applied_marker="Formato de saída — estritamente JSON")

    content = replace_once(content, OLD4, NEW4,
        label="generateDigest(): parse JSON response via parseDigestJSON()",
        already_applied_marker="function parseDigestJSON(raw) {")

    content = replace_once(content, OLD5, NEW5,
        label="add hashStory/storyLookupCache/getStoryFeedbackKeyboard/recordStoryFeedback/sendDigestAsMessages/formatStoryFeedbackSummary",
        already_applied_marker="async function sendDigestAsMessages(dialogId, digest, introText) {")

    content = replace_once(content, OLD6, NEW6,
        label="sendDailyBriefing(): use sendDigestAsMessages()",
        already_applied_marker="await sendDigestAsMessages(dialogId, digest, introText);\n  console.log")

    content = replace_once(content, OLD7, NEW7,
        label="/showtrends and /surprise: use sendDigestAsMessages()",
        already_applied_marker="🎲 *Случайная история*")

    content = replace_once(content, OLD8, NEW8,
        label="add /storyfeedback command (per-story 👍/👎)",
        already_applied_marker="case \'storyfeedback\': {")

    content = replace_once(content, OLD9, NEW9,
        label="/help: clarify /feedback is whole-digest, mention per-story buttons",
        already_applied_marker="оценка дайджеста целиком (по историям")

    content = replace_once(content, OLD10, NEW10,
        label="/status: show per-story feedback summary line",
        already_applied_marker="const storyFeedbackLine = formatStoryFeedbackSummary();")

    if content != original:
        backup(path)
        path.write_text(content, encoding="utf-8")
        print(f"  written: {path}")
    else:
        print("  (no changes written -- everything already applied or anchors missing)")


def main():
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_dir = find_bot_dir(cli_arg)
    print(f"Using bot directory: {bot_dir}")

    patch_index_js(bot_dir / "index.js")

    print("\nDone. Next steps:")
    print("  1. node --check \'%s\'" % (bot_dir / "index.js"))
    print("  2. Review the diff, run /news and confirm each story arrives as its own")
    print("     message with 👍/👎 buttons; tap one and confirm /status shows it.")
    print("  3. Commit & push.")


if __name__ == "__main__":
    main()
