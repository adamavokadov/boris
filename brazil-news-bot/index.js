const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { getCasualReply } = require('./personality');

const PORT = process.env.PORT || 3000;

// --- Secrets -----------------------------------------------------------
// SECURITY: real values are never hardcoded here or in git. They are set
// as environment variables on the deploy server (galaxy) and injected into
// the `env` block of the deploy request at deploy time — see README.md
// "Как задеплоить". Rotate a key (Bitrix24 vibecode admin panel) any time
// it may have leaked; a rotated key stops working the moment the old one
// is committed, so a leak in git history costs nothing once rotated.
const VIBE_API_KEY = process.env.VIBE_API_KEY;
const BITRIX_USER_ID = process.env.BITRIX_USER_ID || '1221912';
const BOT_ID = process.env.BOT_ID || '1505555';
const BOT_NAME = 'Борис';
const VERSION = '14.3';

// LLM model used both for the daily digest and for conversational replies.
const CHAT_MODEL = 'bitrix/bitrixgpt-5.5';

// Fail loudly and immediately if the bot is started without its API key,
// instead of limping along and failing mysteriously (401s / undefined
// headers) deep inside the first API call.
if (!VIBE_API_KEY) {
  console.error('[fatal] VIBE_API_KEY is not set. Set it as an environment variable on the deploy server (never hardcode it). See README.md "Безопасность".');
  process.exit(1);
}

// Persistent storage (survives server sleeps/restarts on the galaxy /data volume)
const DATA_DIR = process.env.DATA_DIR || '/data';
const SETTINGS_FILE = path.join(DATA_DIR, 'settings.json');

// Default bot settings
const DEFAULT_SETTINGS = {
  topics: [
    'AI & Tech',
    'Viral & Internet',
    'Ciência & Espaço',
    'Cultura Pop',
    'Lifestyle & Bem-estar',
    'Curiosidades & Mundo',
    'Viagens & Experiências',
    'Negócios & Startups',
    'Inovação & Empreendedorismo'
  ],
  autoSend: true,
  time: '09:20',
  timezone: 'Europe/Moscow',
  lang: 'pt',
  includeTrends: true,
  maxTrendAgeHours: 72,
  feedback: {
    good: 0,
    bad: 0,
    dislikes: []
  },
  // Per-source scrape health: lets /status and /sourcehealth surface silent
  // degradation (e.g. a site changes its HTML and our regex extractor
  // starts returning 0 headlines) instead of failing invisibly forever.
  sourceHealth: {},
  // Cross-run dedup (sprint 6): normalized-headline -> ISO timestamp of the
  // last time it was actually included in a sent digest. Pruned to the last
  // SENT_HISTORY_DAYS days on every save so this can't grow unbounded.
  recentlySentHeadlines: {},
  // Per-story feedback (sprint 7): 👍/👎 attached to each individual story
  // in a digest, not just one rating for the whole digest. topicCounts is
  // the aggregate signal ("which topics keep getting thumbed down") that
  // roadmap.md's scoring/personalization sprints (6, 9) can eventually use;
  // recentReactions keeps the last STORY_FEEDBACK_HISTORY_LIMIT individual
  // reactions for /status visibility, most recent first.
  storyFeedback: {
    topicCounts: {},
    recentReactions: []
  }
};

// Bot settings (loaded from disk, falls back to defaults)
let settings = loadSettings();

// Short-term memory for free-form (non-command) conversation, so replies
// can refer back to what was just said instead of being stateless.
const MAX_HISTORY_TURNS = 8; // user+assistant pairs kept per dialog
const conversationHistory = new Map(); // dialogId -> [{role, content}, ...]

// Was `settings.awaitingFeedback` (a single global boolean) — that meant a
// 👎 in one dialog, followed by an unrelated message in a *different*
// dialog, would wrongly record that unrelated message as a dislike, and
// leave the original dialog stuck waiting forever. Track it per-dialog
// instead, same pattern as conversationHistory.
const awaitingFeedback = new Set(); // dialogIds currently waiting for a "what didn't you like?" reply
const awaitingTopic = new Set(); // dialogIds currently waiting for a new topic name (via the "➕ Добавить тему" button)

function loadSettings() {
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      const raw = fs.readFileSync(SETTINGS_FILE, 'utf8');
      const saved = JSON.parse(raw);
      // Merge with defaults so new fields appear after updates
      const merged = { ...JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), ...saved };
      // Merge topics: union of default + saved, so new default topics are added
      // while preserving user's custom topics.
      const defaultTopics = DEFAULT_SETTINGS.topics;
      const savedTopics = Array.isArray(saved.topics) ? saved.topics : [];
      const seen = new Set();
      merged.topics = [...defaultTopics, ...savedTopics].filter(t => {
        if (seen.has(t)) return false;
        seen.add(t);
        return true;
      });
      return merged;
    }
  } catch (err) {
    console.error(`[settings] load failed: ${err.message}`);
  }
  return JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
}

function saveSettings() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2), 'utf8');
  } catch (err) {
    console.error(`[settings] save failed: ${err.message}`);
  }
}

function makeRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.request(url, {
      method: options.method || 'GET',
      headers: options.headers || {},
      timeout: 120000
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          resolve({ status: res.statusCode, data: parsed });
        } catch (e) {
          resolve({ status: res.statusCode, data: data });
        }
      });
    });
    req.on('error', (err) => reject(err));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });
    if (options.body) {
      req.write(JSON.stringify(options.body));
    }
    req.end();
  });
}

function formatDateBR(date) {
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function getDates() {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const twoDaysAgo = new Date(today);
  twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);
  const threeDaysAgo = new Date(today);
  threeDaysAgo.setDate(threeDaysAgo.getDate() - 3);
  return {
    today: formatDateBR(today),
    yesterday: formatDateBR(yesterday),
    twoDaysAgo: formatDateBR(twoDaysAgo),
    threeDaysAgo: formatDateBR(threeDaysAgo),
    todayISO: today.toISOString().split('T')[0],
    yesterdayISO: yesterday.toISOString().split('T')[0],
    twoDaysAgoISO: twoDaysAgo.toISOString().split('T')[0],
    threeDaysAgoISO: threeDaysAgo.toISOString().split('T')[0]
  };
}

// Main keyboard buttons
function getMainKeyboard() {
  return [
    { TEXT: '✨ Интересное сейчас', ACTION: 'SEND', ACTION_VALUE: '/news', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '🔥 Тренды', ACTION: 'SEND', ACTION_VALUE: '/showtrends', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '🎲 Случайная история', ACTION: 'SEND', ACTION_VALUE: '/surprise', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '📚 Темы', ACTION: 'SEND', ACTION_VALUE: '/topics', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '⚙️ Настройки', ACTION: 'SEND', ACTION_VALUE: '/settings', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }
  ];
}

// Feedback keyboard
function getFeedbackKeyboard() {
  return [
    { TEXT: '👍 Полезно', ACTION: 'SEND', ACTION_VALUE: '/feedback good', BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' },
    { TEXT: '👎 Не понравилось', ACTION: 'SEND', ACTION_VALUE: '/feedback bad', BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' }
  ];
}

// Bitrix24 has no text-input keyboard button, so any settings screen that
// needs free-form text (adding a topic, a custom time) still falls back to
// asking for a typed reply — same pattern as the /feedback bad flow.
const MAX_TOPIC_BUTTONS = 15; // above this, a per-topic keyboard gets unwieldy

// Settings hub: one-tap toggles + links into the Topics/Schedule sub-screens.
function getSettingsKeyboard() {
  return [
    { TEXT: settings.lang === 'ru' ? '🌐 Язык: RU → PT' : '🌐 Idioma: PT → RU', ACTION: 'SEND', ACTION_VALUE: settings.lang === 'ru' ? '/lang pt' : '/lang ru', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: settings.includeTrends ? '🔥 Тренды: выкл' : '🔥 Тренды: вкл', ACTION: 'SEND', ACTION_VALUE: '/trends', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: settings.autoSend ? '⏰ Автосбор: выкл' : '⏰ Автосбор: вкл', ACTION: 'SEND', ACTION_VALUE: settings.autoSend ? '/off' : '/on', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '📚 Темы', ACTION: 'SEND', ACTION_VALUE: '/topics', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '⏱ Расписание', ACTION: 'SEND', ACTION_VALUE: '/schedule', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/menu', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }
  ];
}

// One ❌ button per topic (removes it with a single tap, no retyping the
// exact topic string) + add/back. Falls back to no per-topic buttons if the
// list has grown past MAX_TOPIC_BUTTONS, to keep the keyboard usable.
function getTopicsKeyboard() {
  const buttons = [];
  if (settings.topics.length <= MAX_TOPIC_BUTTONS) {
    for (const t of settings.topics) {
      buttons.push({ TEXT: `❌ ${t}`, ACTION: 'SEND', ACTION_VALUE: `/removetopic ${t}`, BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' });
    }
  }
  buttons.push({ TEXT: '➕ Добавить тему', ACTION: 'SEND', ACTION_VALUE: '/addtopic', BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' });
  buttons.push({ TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/settings', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });
  return buttons;
}

// Common send-time presets as one-tap buttons; /settime <HH:MM> still works
// for anything not in this list.
const SCHEDULE_TIME_PRESETS = ['08:00', '09:00', '09:20', '10:00'];
function getScheduleKeyboard() {
  const buttons = SCHEDULE_TIME_PRESETS.map(t => ({
    TEXT: t === settings.time ? `✅ ${t}` : t,
    ACTION: 'SEND',
    ACTION_VALUE: `/settime ${t}`,
    BG_COLOR_TOKEN: t === settings.time ? 'primary' : 'secondary',
    DISPLAY: 'LINE'
  }));
  buttons.push({ TEXT: settings.autoSend ? '⏸ Выключить автосбор' : '▶️ Включить автосбор', ACTION: 'SEND', ACTION_VALUE: settings.autoSend ? '/off' : '/on', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });
  buttons.push({ TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/settings', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' });
  return buttons;
}

function getSourceHealthKeyboard() {
  return [
    { TEXT: '🔄 Обновить', ACTION: 'SEND', ACTION_VALUE: '/sourcehealth', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '⬅️ Назад', ACTION: 'SEND', ACTION_VALUE: '/menu', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }
  ];
}

// Build search queries
function getSearchQueries(dates) {
  const langSuffix = settings.lang === 'ru' ? 'новости' : 'notícias';
  const topicQueries = {
    'AI & Tech': `IA inteligência artificial tecnologia novidade viral ${dates.yesterday} ${dates.today} história curiosa ferramenta nova ${langSuffix}`,
    'Viral & Internet': `viral internet redes sociais TikTok X trend desafio ${dates.yesterday} ${dates.today} o que está bombando ${langSuffix}`,
    'Ciência & Espaço': `ciência espaço descoberta pesquisa curiosa ${dates.yesterday} ${dates.today} estudo surpreendente ${langSuffix}`,
    'Cultura Pop': `cultura pop cinema música streaming série celebridade ${dates.yesterday} ${dates.today} lançamento ${langSuffix}`,
    'Lifestyle & Bem-estar': `lifestyle bem-estar tendência hábito alimentação saúde mental ${dates.yesterday} ${dates.today} novidade ${langSuffix}`,
    'Curiosidades & Mundo': `curiosidade história inusitada recorde mundo fato surpreendente ${dates.yesterday} ${dates.today} ${langSuffix}`,
    'Viagens & Experiências': `viagem turismo destino experiência interessante ${dates.yesterday} ${dates.today} dica ${langSuffix}`,
    'Negócios & Startups': `negócios startups tendência empreendedorismo oportunidade nova ${dates.yesterday} ${dates.today} mercado inovação ${langSuffix}`,
    'Inovação & Empreendedorismo': `inovação empreendedorismo startup oportunidade negócio novo ${dates.yesterday} ${dates.today} tendência moderna ${langSuffix}`
  };
  
  return settings.topics.map(topic => ({
    topic,
    query: topicQueries[topic] || `${topic} ${dates.yesterday} ${dates.today} ${langSuffix}`
  }));
}

function getTrendQueries(dates) {
  const langSuffix = settings.lang === 'ru' ? 'тренды поиска' : 'tendências de busca';
  return [
    { topic: 'Tendências hoje', query: `o que está em alta agora viral trending ${dates.today} assunto mais comentado ${langSuffix}` },
    { topic: 'Tendências 24h', query: `tendência viral últimas 24 horas ${dates.yesterday} ${dates.today} o que todo mundo está falando ${langSuffix}` },
    { topic: 'Tendências 48h', query: `assunto em alta viral ${dates.twoDaysAgo} ${dates.today} história interessante ${langSuffix}` }
  ];
}

async function searchNews(query) {
  try {
    const result = await makeRequest('https://vibecode.bitrix24.tech/v1/search', {
      method: 'POST',
      headers: {
        'X-Api-Key': VIBE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: {
        query: query,
        search_depth: 'advanced',
        max_results: 5,
        lang: settings.lang === 'ru' ? 'ru' : 'auto',
        time_range: 'day'
      }
    });
    return result.status === 200 ? result.data : null;
  } catch (error) {
    console.error(`Search failed: ${error.message}`);
    return null;
  }
}

// Show a "typing / thinking" indicator in the chat while the bot works
async function showTyping(dialogId, statusMessageCode = 'IMBOT_AGENT_ACTION_THINKING', duration = 30) {
  try {
    await makeRequest(`https://vibecode.bitrix24.tech/v1/bots/${BOT_ID}/typing`, {
      method: 'POST',
      headers: {
        'X-Api-Key': VIBE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: { dialogId, statusMessageCode, duration }
    });
  } catch (err) {
    // Non-fatal — typing indicator is cosmetic
  }
}

// Keep a "typing / searching / generating" indicator alive for the whole
// duration of a long operation, like a messenger "Пишет..." bubble. The bot's
// work (collecting news, trends, generating) takes minutes, while a single
// typing call lives only `duration` seconds — so we re-send it periodically
// until the operation finishes.
async function withTyping(dialogId, statusMessageCode, fn) {
  let finished = false;
  let timer;
  const kick = async () => {
    if (finished) return;
    try {
      await makeRequest(`https://vibecode.bitrix24.tech/v1/bots/${BOT_ID}/typing`, {
        method: 'POST',
        headers: {
          'X-Api-Key': VIBE_API_KEY,
          'Content-Type': 'application/json'
        },
        body: { dialogId, statusMessageCode, duration: 25 }
      });
    } catch (err) {
      // typing indicator is cosmetic; keep trying
    }
    if (!finished) timer = setTimeout(kick, 15000);
  };
  timer = setTimeout(kick, 0);
  try {
    return await fn();
  } finally {
    finished = true;
    if (timer) clearTimeout(timer);
  }
}

// Send message as bot Boris with optional keyboard
async function sendBotMessage(dialogId, text, keyboard = null) {
  try {
    const body = {
      dialogId: dialogId,
      fields: { message: text }
    };
    if (keyboard) {
      body.fields.keyboard = keyboard;
    }
    const result = await makeRequest(`https://vibecode.bitrix24.tech/v1/bots/${BOT_ID}/messages`, {
      method: 'POST',
      headers: {
        'X-Api-Key': VIBE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: body
    });
    const ok = result.status === 200;
    console.log(`[send] dialogId=${dialogId} status=${result.status} ok=${ok} resp=${JSON.stringify(result.data).substring(0,200)}`);
    return ok;
  } catch (error) {
    console.error(`[send] Send failed dialogId=${dialogId}: ${error.message}`);
    return false;
  }
}

// Generate digest using AI (LLM)
async function generateDigest(rawNews, trendNews, sourceNews = [], extraInstructions = '') {
  const dates = getDates();
  const lang = settings.lang;
  
  // Build feedback-based instructions
  let feedbackInstructions = '';
  if (settings.feedback.dislikes.length > 0) {
    feedbackInstructions = `\n\n⚠️ ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ (учитывай их):\nПользователь отметил, что ему НЕ нравится:\n- ${settings.feedback.dislikes.join('\n- ')}\nСтарайся избегать этих тем/форматов.`;
  }
  
  const systemPrompt = lang === 'ru'
    ? `Ты — Борис, AI-куратор интересных и трендовых историй. Каждый день ты собираешь САМЫЕ интересные, неожиданные и вирусные новости со всего мира — то, о чём люди реально говорят и что хочется переслать другу.

Твоя главная цель — «вау-фактор»: истории, которые удивляют, развлекают и дают тему для разговора. Пример отличной истории: «В Австралии ИИ Claude взломал сайт, чтобы записать своего владельца на тренировку». Вот такие истории и нужны.

⚠️ ЖЁСТКОЕ ТРЕБОВАНИЕ ПО СВЕЖЕСТИ:
- Сегодняшняя дата: ${dates.todayISO}
- Собирай ТОЛЬКО свежие истории за последние 72 часа (не старше ${dates.threeDaysAgoISO})
- ЛЮБАЯ история старше 72 часов — ОТБРОСЬ, даже если она кажется важной
- Если история про событие, которое было давно (недели/месяцы назад) — это устаревшее, НЕ включай

Что ПОЛНОСТЬЮ исключаем (скучно и неинтересно):
- Политика, скандалы, выборы, личные выпады
- Процентные ставки, ключевые ставки, макроэкономика, сухие финансовые сводки
- Войны и дипломатические кризисы
- Биржевые котировки, курсы валют, инвестиционные обзоры
- Корпоративные отчёты, IPO, квартальные результаты
- Логистика, инфраструктура, грузоперевозки
- Любые «сухие» новости без человеческого интереса

Что включаем (интересно и трендово):
1. AI и технологии — забавные и неожиданные истории про ИИ, новые крутые инструменты, вирусные техно-события
2. Вирусное и интернет — что бомбит в соцсетях, тренды TikTok/X, вирусные челленджи и мемы
3. Наука и космос — удивительные открытия, забавные исследования, космические новости
4. Поп-культура — кино, музыка, стриминг, сериалы, интересные события
5. Лайфстайл и благополучие — новые тренды, привычки, еда, здоровье
6. Любопытное и мир — необычные истории, рекорды, удивительные факты
7. Путешествия и впечатления — интересные места, лайфхаки, необычный опыт
8. Бизнес и стартапы — новые тренды в бизнесе, свежие возможности для стартапов, современные бизнес-модели, инновации
9. Предпринимательство и инновации — новые ниши, трендовые направления для запуска своего дела

Структура каждой истории (строго):
1. Заголовок — цепляющий, интригующий
2. 📅 ДАТА — ОБЯЗАТЕЛЬНО укажи дату публикации/актуальности истории (например «10/08/2026» или «сегодня»). Без даты история не принимается.
3. Суть (2-3 предложения): что произошло, где, когда
4. Почему это интересно/забавно/удивительно
5. Ссылка на первоисточник

Для трендов: ОБЯЗАТЕЛЬНО укажи дату актуальности тренда (например «10/08/2026»). Объясни, почему тема стала трендом ПРЯМО СЕЙЧАС и почему она интересна. Если тренд устаревший (старше 72 часов) — НЕ включай.

Принципы:
- Отбирай истории с «вау-фактором» — необычные, забавные, удивительные
- Проверяй факты из нескольких источников
- Пиши живо и увлекательно, как хороший сторителлинг
- НЕ давай сухой перечень — превращай в интересный рассказ
- ОБЯЗАТЕЛЬНО показывай дату у каждой истории и каждого тренда — это критично, чтобы пользователь видел свежесть
${feedbackInstructions}

Формат выдачи — строго JSON, без markdown-разметки вокруг, без текста до или после JSON. Схема:
{
  "summary": "1-2 предложения — что сегодня самое интересное",
  "stories": [
    {
      "topic": "категория из списка выше",
      "title": "цепляющий заголовок",
      "date": "дата публикации/актуальности, например 10/08/2026 или сегодня",
      "body": "суть истории, 2-3 предложения: что произошло, где, когда",
      "why": "почему это интересно/забавно/удивительно",
      "source": "ссылка на первоисточник или название источника, если ссылки нет"
    }
  ],
  "trends": [
    {
      "topic": "название тренда",
      "date": "дата актуальности тренда",
      "body": "почему тема в тренде прямо сейчас и почему это интересно"
    }
  ]
}
5-7 историй в "stories". "trends" может быть пустым массивом, если трендов не было в исходных данных. Каждая история и каждый тренд ОБЯЗАТЕЛЬНО должны иметь непустое поле "date" — без даты запись не принимается.`
    : `Você é o Boris, um curador de histórias interessantes e em alta. Todos os dias você reúne as notícias MAIS interessantes, inesperadas e virais do mundo — aquelas que as pessoas realmente comentam e querem encaminhar para um amigo.

Seu principal objetivo é o "fator uau": histórias que surpreendem, divertem e dão assunto para conversa. Exemplo de ótima história: "Na Austrália, a IA Claude hackeou um site para inscrever seu dono na academia". É esse tipo de história que precisamos.

⚠️ REQUISITO RÍGIDO DE FRESCURA:
- Data de hoje: ${dates.todayISO}
- Cole APENAS histórias frescas das últimas 72 horas (não mais antigas que ${dates.threeDaysAgoISO})
- QUALQUER história mais antiga que 72 horas — DESCARTE, mesmo que pareça importante
- Se a história é sobre um evento antigo (semanas/meses atrás) — está desatualizada, NÃO inclua

O que fica TOTALMENTE excluído (chato e sem graça):
- Política, escândalos, eleições, ataques pessoais
- Taxas de juros, taxa básica, macroeconomia, resumos financeiros secos
- Guerras e crises diplomáticas
- Cotações de bolsa, câmbio, análises de investimento
- Relatórios corporativos, IPO, resultados trimestrais
- Logística, infraestrutura, transporte de cargas
- Qualquer notícia "seca" sem interesse humano

O que incluir (interessante e em alta):
1. IA e tecnologia — histórias engraçadas e inesperadas sobre IA, ferramentas novas e legais, eventos virais de tech
2. Viral e internet — o que está bombando nas redes, trends do TikTok/X, desafios e memes virais
3. Ciência e espaço — descobertas surpreendentes, pesquisas curiosas, notícias espaciais
4. Cultura pop — cinema, música, streaming, séries, eventos interessantes
5. Lifestyle e bem-estar — novas tendências, hábitos, comida, saúde
6. Curiosidades e mundo — histórias incomuns, recordes, fatos surpreendentes
7. Viagens e experiências — lugares interessantes, dicas, experiências diferentes
8. Negócios e startups — novas tendências de negócios, oportunidades frescas para startups, modelos de negócio modernos, inovação
9. Empreendedorismo e inovação — novos nichos, áreas em alta para começar o próprio negócio

Estrutura de cada história (estritamente):
1. Título — cativante, intrigante
2. 📅 DATA — OBRIGATÓRIO: indique a data de publicação/atualidade da história (ex.: «10/08/2026» ou «hoje»). Sem data, a história não é aceita.
3. Essência (2-3 frases): o que aconteceu, onde, quando
4. Por que é interessante/engraçado/surpreendente
5. Link para a fonte original

Para tendências: OBRIGATÓRIO indicar a data de atualidade da tendência (ex.: «10/08/2026»). Explique por que o tema virou tendência AGORA e por que é interessante. Se a tendência estiver desatualizada (mais de 72 horas) — NÃO inclua.

Princípios:
- Selecione histórias com "fator uau" — incomuns, engraçadas, surpreendentes
- Verifique os fatos em mais de uma fonte
- Escreva de forma viva e envolvente, como um bom storytelling
- NÃO dê lista seca — transforme em uma narrativa interessante
- OBRIGATÓRIO mostrar a data em cada história e cada tendência — é crítico para o usuário ver a frescura
${feedbackInstructions}

Formato de saída — estritamente JSON, sem markdown ao redor, sem texto antes ou depois do JSON. Esquema:
{
  "summary": "1-2 frases — o que é mais interessante hoje",
  "stories": [
    {
      "topic": "categoria da lista acima",
      "title": "título cativante",
      "date": "data de publicação/atualidade, ex.: 10/08/2026 ou hoje",
      "body": "essência da história, 2-3 frases: o que aconteceu, onde, quando",
      "why": "por que é interessante/engraçado/surpreendente",
      "source": "link para a fonte original ou nome da fonte, se não houver link"
    }
  ],
  "trends": [
    {
      "topic": "nome da tendência",
      "date": "data de atualidade da tendência",
      "body": "por que o tema virou tendência agora e por que é interessante"
    }
  ]
}
5-7 histórias em "stories". "trends" pode ser um array vazio se não havia tendências nos dados brutos. Cada história e cada tendência DEVEM ter o campo "date" preenchido — sem data, o item não é aceito.`;
  
  let userContent = `Datas: ${dates.twoDaysAgo} a ${dates.today} (hoje: ${dates.todayISO})\n\n`;
  userContent += `⚠️ IMPORTANTE: Cole APENAS histórias e tendências das últimas 72 horas. Descarte qualquer coisa mais antiga. Priorize histórias com "fator uau" — interessantes, engraçadas, surpreendentes e virais.\n\n`;
  userContent += `⚠️ OBRIGATÓRIO: mostre a DATA de cada história e de cada tendência (ex.: «10/08/2026»). Без даты ответ не принимается.\n\n`;
  userContent += `Aqui estão os dados brutos de busca. Selecione as 5-7 histórias MAIS INTERESSANTES e FRESCAS, estruture conforme o modelo e produza o resumo final:\n\n`;
  
  userContent += `=== HISTÓRIAS ===\n\n`;
  rawNews.forEach((n, i) => {
    userContent += `--- HISTÓRIA ${i+1} (categoria: ${n.topic}) ---\n`;
    userContent += `${n.raw}\n\n`;
  });
  
  if (trendNews && trendNews.length > 0) {
    userContent += `=== TENDÊNCIAS (24-72 HORAS) ===\n\n`;
    trendNews.forEach((t, i) => {
      userContent += `--- TENDÊNCIA ${i+1} (${t.topic}) ---\n`;
      userContent += `${t.raw}\n\n`;
    });
  }
  
  if (sourceNews && sourceNews.length > 0) {
    userContent += `=== СВЕЖИЕ ЗАГОЛОВКИ ИЗ КУРИРУЕМЫХ ИСТОЧНИКОВ ===\n\n`;
    userContent += `Это реальные свежие заголовки из проверенных источников. Используй их как дополнительный материал — выбирай самые интересные и трендовые, проверяй свежесть (не старше 72 часов):\n\n`;
    sourceNews.forEach((s, i) => {
      userContent += `--- ИСТОЧНИК ${i+1} (${s.topic}) ---\n`;
      userContent += `${s.raw}\n\n`;
    });
  }
  
  try {
    const result = await makeRequest('https://vibecode.bitrix24.tech/v1/chat/completions', {
      method: 'POST',
      headers: {
        'X-Api-Key': VIBE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: {
        model: 'bitrix/bitrixgpt-5.5',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userContent }
        ],
        temperature: 0.3,
        max_tokens: 4000
      }
    });
    
    if (result.status === 200 && result.data && result.data.choices && result.data.choices[0]) {
      const raw = result.data.choices[0].message.content;
      return parseDigestJSON(raw);
    }
    console.error('AI response error:', result.status, JSON.stringify(result.data).substring(0, 300));
    return null;
  } catch (error) {
    console.error('AI generate failed:', error.message);
    return null;
  }
}

// Parses generateDigest()'s LLM response into { summary, stories, trends }.
// The prompt asks for strict JSON, but models sometimes wrap it in a
// ```json fence anyway despite instructions not to — stripped defensively
// before parsing. Returns null (not a partial/malformed object) on any
// parse failure or missing "stories" array, so callers can fall back to
// "couldn't generate a digest right now" instead of sending broken output.
function parseDigestJSON(raw) {
  if (!raw) return null;
  let text = raw.trim();
  const fenceMatch = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/);
  if (fenceMatch) text = fenceMatch[1].trim();
  try {
    const parsed = JSON.parse(text);
    if (!parsed || !Array.isArray(parsed.stories)) {
      console.error('Digest JSON missing "stories" array:', text.substring(0, 300));
      return null;
    }
    return {
      summary: typeof parsed.summary === 'string' ? parsed.summary : '',
      stories: parsed.stories.filter(s => s && s.title),
      trends: Array.isArray(parsed.trends) ? parsed.trends.filter(t => t && t.topic) : []
    };
  } catch (error) {
    console.error('Digest JSON parse failed:', error.message, '| raw (truncated):', text.substring(0, 300));
    return null;
  }
}

// Free-form conversational reply via LLM, used when personality.js's
// regex patterns don't recognize the input. Keeps a short per-dialog
// history so the bot can hold a real back-and-forth instead of answering
// each message in isolation. Returns null on any failure so the caller
// can fall back to the static menu instead of showing a broken reply.
async function generateConversationalReply(dialogId, text, userName) {
  const lang = settings.lang;
  const name = (userName || '').trim().split(/\s+/)[0];
  const systemPrompt = lang === 'ru'
    ? `Ты — Борис, дружелюбный AI-куратор интересных и трендовых новостей. ` +
      `Ты уже поздоровался и объяснил, что умеешь, если это было нужно — сейчас просто ` +
      `отвечай на сообщение пользователя живо, тепло и по делу, 1-3 предложения. ` +
      `Если уместно, предложи посмотреть свежие истории (/news), тренды (/showtrends) ` +
      `или случайную историю (/surprise). Не повторяй списки команд без необходимости.` +
      (name ? ` Имя пользователя: ${name}.` : '')
    : `Você é o Boris, um curador de notícias e tendências simpático e direto. ` +
      `Responda à mensagem do usuário de forma calorosa e objetiva, em 1-3 frases. ` +
      `Se fizer sentido, sugira ver histórias recentes (/news), tendências (/showtrends) ` +
      `ou uma história aleatória (/surprise). Não repita listas de comandos sem necessidade.` +
      (name ? ` Nome do usuário: ${name}.` : '');

  const history = conversationHistory.get(dialogId) || [];
  const messages = [
    { role: 'system', content: systemPrompt },
    ...history,
    { role: 'user', content: text }
  ];

  try {
    const result = await makeRequest('https://vibecode.bitrix24.tech/v1/chat/completions', {
      method: 'POST',
      headers: {
        'X-Api-Key': VIBE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: {
        model: CHAT_MODEL,
        messages: messages,
        temperature: 0.6,
        max_tokens: 400
      }
    });

    if (result.status === 200 && result.data && result.data.choices && result.data.choices[0]) {
      const reply = result.data.choices[0].message.content;
      const updated = [...history, { role: 'user', content: text }, { role: 'assistant', content: reply }];
      // Keep only the last MAX_HISTORY_TURNS turns (each turn = 1 user + 1 assistant message)
      conversationHistory.set(dialogId, updated.slice(-MAX_HISTORY_TURNS * 2));
      return reply;
    }
    console.error('Conversational AI error:', result.status, JSON.stringify(result.data).substring(0, 300));
    return null;
  } catch (error) {
    console.error('Conversational AI failed:', error.message);
    return null;
  }
}

async function collectRawNews() {
  const dates = getDates();
  const queries = getSearchQueries(dates);
  let rawNews = [];
  
  for (const q of queries) {
    console.log(`Searching [${q.topic}]: ${q.query}`);
    const news = await searchNews(q.query);
    if (news && news.answer) {
      rawNews.push({ topic: q.topic, raw: news.answer });
    }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  return rawNews;
}

// Fetch real trends directly from trends24.in/brazil (X/Twitter trending topics)
async function fetchTrends24() {
  try {
    console.log('Fetching real trends from trends24.in/brazil...');
    const result = await makeRequest('https://trends24.in/brazil/', {
      method: 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml'
      }
    });
    
    if (result.status !== 200) {
      console.error('trends24 fetch error:', result.status);
      return [];
    }
    
    const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);
    
    // Extract trending topics - they appear as text in the timeline
    // Look for the "Trending Topic Statistics" section and extract trends
    // Simpler: extract all capitalized words/phrases that look like trends
    
    // Find the timeline section
    const timelineMatch = html.match(/Twitter Trends Timeline for last 24 hours([\s\S]*?)View all 50 trends/);
    let timelineText = '';
    if (timelineMatch) {
      timelineText = timelineMatch[1];
    } else {
      timelineText = html;
    }
    
    // Extract trend names - they are in the timeline as text between timestamps
    // Remove HTML tags
    const cleanText = timelineText
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<style[\s\S]*?<\/style>/gi, '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&nbsp;/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    
    // Extract the most recent trends (first timestamp block)
    // Split by timestamps like "Thu Aug 06 2026 13:21:29"
    const blocks = cleanText.split(/[A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{4} \d{2}:\d{2}:\d{2}/);
    
    // The first block after the first timestamp contains the latest trends
    let latestTrends = [];
    if (blocks.length > 1) {
      // Take the first few blocks (most recent)
      for (let i = 1; i < Math.min(blocks.length, 4); i++) {
        const words = blocks[i].split(' ').filter(w => w.length > 1 && w.length < 40);
        latestTrends = latestTrends.concat(words);
      }
    }
    
    // Deduplicate and limit
    const unique = [...new Set(latestTrends)].slice(0, 30);
    
    if (unique.length === 0) {
      console.log('No trends extracted from trends24');
      recordSourceHealth('trends24', 0, 'extractor returned 0 items');
      return [];
    }
    
    console.log(`Extracted ${unique.length} real trends from trends24.in`);
    recordSourceHealth('trends24', unique.length, null);
    return [{
      topic: 'Tendências reais (trends24.in/brazil)',
      raw: 'Tendências reais do X/Twitter no Brasil nas últimas 24 horas:\n' + unique.join(', ')
    }];
  } catch (error) {
    console.error('fetchTrends24 failed:', error.message);
    recordSourceHealth('trends24', 0, error.message);
    return [];
  }
}

// Fetch headlines from curated external sources (habr, bloomberglinea, google news)
// --- Pre-LLM deduplication and scoring (sprint 6) --------------------
// Cheap, dependency-free near-duplicate detection over headline strings.
// No embeddings/external calls — this runs synchronously over every
// headline in a collection run and needs to stay fast and free.
const DEDUP_SIMILARITY_THRESHOLD = 0.45; // Jaccard word-overlap, 0-1 — tuned against
// a sample of realistic PT-BR near-duplicate headline pairs (paraphrased by
// different outlets), which scored 0.50-0.71, vs genuinely distinct stories
// (including ones sharing a common subject word like "Brasil"), which scored
// 0.00-0.10. 0.45 sits in the gap between those two clusters.
const SENT_HISTORY_DAYS = 3; // how long a sent headline blocks a repeat

// Authority bonus per source id. Deliberately additive-only (no negative
// entries): a source absent from this map just gets +0, never demoted, so
// this can't silently bury a source nobody got around to rating.
const SOURCE_PRIORITY = {
  bloomberglinea: 2,
  cnnbrasil: 2
};

function normalizeForDedup(title) {
  return (title || '')
    .toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // strip accents
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function titleSimilarity(a, b) {
  const wordsA = new Set(normalizeForDedup(a).split(' ').filter(w => w.length > 2));
  const wordsB = new Set(normalizeForDedup(b).split(' ').filter(w => w.length > 2));
  if (wordsA.size === 0 || wordsB.size === 0) return 0;
  let intersection = 0;
  for (const w of wordsA) { if (wordsB.has(w)) intersection++; }
  const union = wordsA.size + wordsB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// Prune recentlySentHeadlines older than SENT_HISTORY_DAYS. Called before
// every filter/record pass so the map never grows unbounded.
function pruneSentHistory() {
  if (!settings.recentlySentHeadlines) { settings.recentlySentHeadlines = {}; return; }
  const cutoff = Date.now() - SENT_HISTORY_DAYS * 24 * 60 * 60 * 1000;
  for (const [key, iso] of Object.entries(settings.recentlySentHeadlines)) {
    if (new Date(iso).getTime() < cutoff) delete settings.recentlySentHeadlines[key];
  }
}

function wasRecentlySent(title) {
  pruneSentHistory();
  return Object.prototype.hasOwnProperty.call(settings.recentlySentHeadlines, normalizeForDedup(title));
}

function recordSentHeadlines(titles) {
  pruneSentHistory();
  const now = new Date().toISOString();
  for (const t of titles) {
    settings.recentlySentHeadlines[normalizeForDedup(t)] = now;
  }
  saveSettings();
}

// Tracks how many near-duplicates the last collection run collapsed, for
// /status visibility. Reset at the start of each dedupeAndScoreHeadlines() call.
let lastDedupStats = { input: 0, output: 0, collapsed: 0, blockedRepeats: 0 };

// items: [{ title, sourceId, sourceName, position }], position = index in
// its own source's listing (0 = first/most prominent on that page/feed).
// Returns items deduped (near-duplicates collapsed to their
// highest-scored representative) and sorted by score descending.
function dedupeAndScoreHeadlines(items) {
  const filtered = items.filter(it => !wasRecentlySent(it.title));
  const blockedRepeats = items.length - filtered.length;

  const scored = filtered.map(it => {
    const priorityBonus = SOURCE_PRIORITY[it.sourceId] || 0;
    const recencyBonus = Math.max(0, 3 - Math.floor(it.position / 3)); // earlier in listing = fresher, tapers off
    return { ...it, score: priorityBonus + recencyBonus, seenInSources: new Set([it.sourceId]) };
  });

  // Group near-duplicates. O(n^2) over headlines from one collection run
  // (tens, not thousands) — fine at this scale, revisit if SOURCES grows a lot.
  const groups = [];
  for (const item of scored) {
    let placed = false;
    for (const group of groups) {
      if (titleSimilarity(item.title, group.best.title) >= DEDUP_SIMILARITY_THRESHOLD) {
        group.best.seenInSources.add(item.sourceId);
        // A story independently picked up by more than one source is more
        // likely to actually matter — small bonus, captured before the
        // duplicate itself is dropped below.
        if (group.best.seenInSources.size > 1) {
          group.best.score += 1;
        }
        if (item.score > group.best.score) {
          const mergedSources = group.best.seenInSources;
          group.best = item;
          group.best.seenInSources = mergedSources;
        }
        placed = true;
        break;
      }
    }
    if (!placed) groups.push({ best: item });
  }

  const result = groups.map(g => g.best).sort((a, b) => b.score - a.score);
  lastDedupStats = {
    input: items.length,
    output: result.length,
    collapsed: filtered.length - result.length,
    blockedRepeats
  };
  return result;
}

// --- Per-story feedback and digest delivery (sprint 7) -------------------
// A short, stable, deterministic id for a story, derived from its
// normalized title. Needs to survive a round trip through a keyboard
// button's ACTION_VALUE (short string, no spaces/newlines) and stay the
// same for the "same" story across re-runs, so djb2-style string hash to
// base36 rather than anything random or position-dependent.
function hashStory(title) {
  const normalized = normalizeForDedup(title);
  let hash = 5381;
  for (let i = 0; i < normalized.length; i++) {
    hash = ((hash * 33) ^ normalized.charCodeAt(i)) >>> 0;
  }
  return hash.toString(36);
}

const STORY_FEEDBACK_HISTORY_LIMIT = 50; // most recent per-story reactions kept for /status

// In-memory lookup from story hash -> { topic, title }, populated whenever
// sendDigestAsMessages() actually sends a story, so a later 👍/👎 tap can
// resolve which topic to credit/blame. Deliberately NOT persisted to disk:
// it's a short-lived index over "stories currently sitting in someone's
// chat with live buttons", not a feedback record — settings.storyFeedback
// is the actual persisted log. A restart between sending a digest and
// someone tapping its buttons is an acceptably rare edge case (falls back
// to the "Без темы" bucket in recordStoryFeedback, same as an unknown/old
// hash) rather than something worth the complexity of persisting this too.
// Capped so a long-running process can't leak memory across many digests.
const STORY_LOOKUP_CACHE_LIMIT = 500;
const storyLookupCache = new Map(); // hash -> { topic, title }

function rememberStoryForFeedback(hash, topic, title) {
  storyLookupCache.set(hash, { topic, title });
  if (storyLookupCache.size > STORY_LOOKUP_CACHE_LIMIT) {
    const oldestKey = storyLookupCache.keys().next().value;
    storyLookupCache.delete(oldestKey);
  }
}

function getStoryFeedbackKeyboard(storyHash) {
  return [
    { TEXT: '👍', ACTION: 'SEND', ACTION_VALUE: `/storyfeedback ${storyHash} good`, BG_COLOR_TOKEN: 'primary', DISPLAY: 'LINE' },
    { TEXT: '👎', ACTION: 'SEND', ACTION_VALUE: `/storyfeedback ${storyHash} bad`, BG_COLOR_TOKEN: 'alert', DISPLAY: 'LINE' }
  ];
}

// Records a single story-level reaction. Deliberately one tap, no follow-up
// question (unlike digest-level /feedback bad, which asks what was wrong) —
// asking for a written reason on every individual story would make the
// per-story keyboard annoying to use, defeating the point of it being
// lower-friction than the whole-digest feedback.
function recordStoryFeedback(storyHash, topic, title, reaction) {
  if (!settings.storyFeedback) settings.storyFeedback = { topicCounts: {}, recentReactions: [] };
  const safeTopic = topic || 'Без темы';
  if (!settings.storyFeedback.topicCounts[safeTopic]) {
    settings.storyFeedback.topicCounts[safeTopic] = { good: 0, bad: 0 };
  }
  settings.storyFeedback.topicCounts[safeTopic][reaction]++;
  settings.storyFeedback.recentReactions.unshift({
    hash: storyHash,
    topic: safeTopic,
    title: title || '',
    reaction,
    ts: new Date().toISOString()
  });
  settings.storyFeedback.recentReactions = settings.storyFeedback.recentReactions.slice(0, STORY_FEEDBACK_HISTORY_LIMIT);
  saveSettings();
}

// One-line /status summary: total per-story reactions + the single
// most-disliked topic if any topic has at least MIN_REACTIONS_FOR_SIGNAL
// reactions against it (avoids calling out a topic off just 1 stray tap).
const MIN_REACTIONS_FOR_SIGNAL = 3;
function formatStoryFeedbackSummary() {
  const counts = (settings.storyFeedback && settings.storyFeedback.topicCounts) || {};
  const topics = Object.entries(counts);
  if (topics.length === 0) return `📝 Оценки историй: пока нет данных\n`;

  let totalGood = 0, totalBad = 0;
  let worstTopic = null, worstBad = 0;
  for (const [topic, c] of topics) {
    totalGood += c.good;
    totalBad += c.bad;
    const total = c.good + c.bad;
    if (total >= MIN_REACTIONS_FOR_SIGNAL && c.bad > worstBad) {
      worstBad = c.bad;
      worstTopic = topic;
    }
  }
  const worstNote = worstTopic ? `, чаще всего 👎 — «${worstTopic}»` : '';
  return `📝 Оценки историй: ${totalGood} 👍 / ${totalBad} 👎${worstNote}\n`;
}

// Sends a digest (the { summary, stories, trends } shape parseDigestJSON()
// returns) as one message per story instead of one giant block of text —
// each story gets its own 👍/👎 keyboard via getStoryFeedbackKeyboard().
// `introText` is the header line shown before the first story (kept
// caller-supplied since the daily briefing, /showtrends, and /surprise each
// want different wording here). `kind` is only used for a fallback title if
// a story is somehow missing a topic. Records every sent story into
// recentlySentHeadlines (sprint 6) so a manual re-run doesn't repeat them.
async function sendDigestAsMessages(dialogId, digest, introText) {
  const lines = [introText];
  if (digest.summary) lines.push(`📌 ${digest.summary}`);
  await sendBotMessage(dialogId, lines.join('\n\n'), getMainKeyboard());

  for (const story of digest.stories) {
    const parts = [];
    parts.push(`*${story.topic || 'Интересное'}: ${story.title}*`);
    if (story.date) parts.push(`📅 ${story.date}`);
    if (story.body) parts.push(story.body);
    if (story.why) parts.push(story.why);
    if (story.source) parts.push(`🔗 ${story.source}`);
    const storyHash = hashStory(story.title);
    rememberStoryForFeedback(storyHash, story.topic || null, story.title || null);
    await sendBotMessage(dialogId, parts.join('\n'), getStoryFeedbackKeyboard(storyHash));
    await new Promise(resolve => setTimeout(resolve, 400)); // avoid hammering the API with a burst of sends
  }

  if (digest.trends && digest.trends.length > 0) {
    const trendLines = ['🔥 *Тренды (свежие)*'];
    for (const t of digest.trends) {
      trendLines.push('');
      trendLines.push(`*${t.topic}*`);
      if (t.date) trendLines.push(`📅 ${t.date}`);
      if (t.body) trendLines.push(t.body);
    }
    await sendBotMessage(dialogId, trendLines.join('\n'), getFeedbackKeyboard());
  } else {
    await sendBotMessage(dialogId, 'Оцени дайджест в целом:', getFeedbackKeyboard());
  }

  const sentTitles = digest.stories.map(s => s.title).filter(Boolean);
  if (sentTitles.length > 0) recordSentHeadlines(sentTitles);
}

const SOURCES = [
  {
    id: 'habr',
    name: 'Habr (tech/IT)',
    url: 'https://habr.com/ru/articles/top/daily/',
    lang: 'ru',
    extract: (html) => {
      const titles = html.match(/class="tm-title__link"[^>]*>(.*?)<\/a>/gs) || [];
      return titles.map(t => {
        const m = t.match(/>(.*?)<\/a>/s);
        return m ? m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').trim() : '';
      }).filter(t => t.length > 10).slice(0, 15);
    }
  },
  {
    id: 'bloomberglinea',
    name: 'Bloomberg Línea Brasil (business)',
    url: 'https://www.bloomberglinea.com.br/',
    lang: 'pt',
    extract: (html) => {
      const titles = html.match(/<h[23][^>]*>(.*?)<\/h[23]>/gs) || [];
      return titles.map(t => {
        const m = t.match(/>(.*?)<\/h[23]>/s);
        return m ? m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').trim() : '';
      }).filter(t => t.length > 15).slice(0, 15);
    }
  },
  {
    id: 'googlenews',
    name: 'Google News Brasil (trending)',
    url: 'https://news.google.com/rss/topics/CAAqLAgKIiZDQkFTRmdvSkwyMHZNR1ptZHpWbUVnVndkQzFDVWhvQ1FsSW9BQVAB?hl=pt-BR&gl=BR&ceid=BR:pt-419',
    lang: 'pt',
    extract: (html) => {
      const titles = html.match(/<title>(.*?)<\/title>/gs) || [];
      return titles.map(t => {
        const m = t.match(/<title>(.*?)<\/title>/s);
        return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&amp;/g, '&').trim() : '';
      }).filter(t => t.length > 15 && !/Google Notícias|Google News/i.test(t)).slice(0, 20);
    }
  },
  {
    id: 'folha',
    name: 'Folha de S.Paulo (lifestyle)',
    url: 'https://feeds.folha.uol.com.br/comida/rss091.xml',
    lang: 'pt',
    extract: (html) => {
      const titles = html.match(/<title>(.*?)<\/title>/gs) || [];
      return titles.map(t => {
        const m = t.match(/<title>(.*?)<\/title>/s);
        return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&amp;/g, '&').trim() : '';
      }).filter(t => t.length > 15 && !/Folha de S\.Paulo/i.test(t)).slice(0, 15);
    }
  },
  {
    id: 'cnnbrasil',
    name: 'CNN Brasil',
    url: 'https://www.cnnbrasil.com.br/feed/',
    lang: 'pt',
    extract: (html) => {
      const titles = html.match(/<title>(.*?)<\/title>/gs) || [];
      return titles.map(t => {
        const m = t.match(/<title>(.*?)<\/title>/s);
        return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&amp;/g, '&').trim() : '';
      }).filter(t => t.length > 15 && !/CNN Brasil/i.test(t)).slice(0, 15);
    }
  }
];

// --- Source scrape health tracking -----------------------------------------
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
}

// Fetch "Just In" breaking news (WatcherGuru-style) via web search.
// X/Threads/watcher.guru are blocked for direct scraping (Cloudflare/JS),
// so we surface the same breaking-news content through the search API.
async function fetchBreakingNews() {
  const queries = [
    'JUST IN breaking news today technology science world',
    'breaking news today latest headlines tech AI science'
  ];
  // Exclude crypto/markets/finance-heavy breaking news (user doesn't want dry finance)
  const EXCLUDE = /crypto|bitcoin|ethereum|btc|eth|altcoin|token|blockchain|defi|nft|market cap|price surge|price drop|stock market|shares (rise|fall)|ipo|earnings report|wall street|dow jones|nasdaq|s&p 500|fx rate|forex|interest rate|fed|central bank/i;
  const headlines = [];
  for (const query of queries) {
    try {
      const result = await makeRequest('https://vibecode.bitrix24.tech/v1/search', {
        method: 'POST',
        headers: {
          'X-Api-Key': VIBE_API_KEY,
          'Content-Type': 'application/json'
        },
        body: {
          query,
          search_depth: 'advanced',
          max_results: 5,
          lang: 'en',
          time_range: 'day'
        }
      });
      if (result.status === 200 && result.data) {
        const answer = result.data.answer;
        if (answer && !EXCLUDE.test(answer)) headlines.push(answer);
        for (const r of (result.data.results || [])) {
          if (r.title && /JUST IN|breaking|just in/i.test(r.title) && !EXCLUDE.test(r.title)) {
            headlines.push(r.title);
          }
        }
      }
    } catch (error) {
      console.error(`[breaking] search failed: ${error.message}`);
    }
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
  // Deduplicate and limit
  const seen = new Set();
  const unique = headlines.filter(h => {
    const k = h.toLowerCase().slice(0, 60);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).slice(0, 15);
  console.log(`[breaking] collected ${unique.length} breaking-news headlines`);
  return unique;
}

async function collectSourceNews() {
  // Flatten every source's headlines into one list FIRST, so dedup can
  // catch the same story picked up by two different sources — that was
  // previously impossible because each source's headlines were joined into
  // prose before the next source was even fetched.
  const flat = [];
  const sourceMeta = {}; // sourceId -> { name }
  for (const source of SOURCES) {
    const titles = await fetchSourceHeadlines(source);
    sourceMeta[source.id] = { name: source.name };
    titles.forEach((title, position) => {
      flat.push({ title, sourceId: source.id, sourceName: source.name, position });
    });
    await new Promise(resolve => setTimeout(resolve, 800));
  }
  // Add WatcherGuru-style "Just In" breaking news via search
  const breaking = await fetchBreakingNews();
  sourceMeta.breaking = { name: 'WatcherGuru-style «Just In» breaking news' };
  breaking.forEach((title, position) => {
    flat.push({ title, sourceId: 'breaking', sourceName: sourceMeta.breaking.name, position });
  });

  const deduped = dedupeAndScoreHeadlines(flat);
  console.log(`[dedup] ${lastDedupStats.input} headlines in, ${lastDedupStats.collapsed} near-duplicates collapsed, ${lastDedupStats.blockedRepeats} already-sent repeats blocked, ${lastDedupStats.output} out`);

  // Regroup by source for the digest prompt, preserving the existing
  // per-source `raw` text format so generateDigest()'s prompt is unchanged —
  // only which headlines make it in, and their order (highest-scored first
  // within each source), is different.
  const bySource = {};
  for (const item of deduped) {
    if (!bySource[item.sourceId]) bySource[item.sourceId] = [];
    bySource[item.sourceId].push(item.title);
  }

  const results = [];
  for (const [sourceId, titles] of Object.entries(bySource)) {
    const name = sourceMeta[sourceId] ? sourceMeta[sourceId].name : sourceId;
    if (sourceId === 'breaking') {
      results.push({
        topic: name,
        source: sourceId,
        raw: 'Самые свежие «Just In» новости (в стиле WatcherGuru):\n' + titles.map((t, i) => `${i+1}. ${t}`).join('\n')
      });
    } else {
      results.push({
        topic: name,
        source: sourceId,
        raw: `Свежие заголовки из источника «${name}»:\n` + titles.map((t, i) => `${i+1}. ${t}`).join('\n')
      });
    }
  }
  // Record what actually made it into this collection run so a same-day
  // re-run of /news won't repeat these headlines verbatim. Recorded here
  // (collection time) rather than only after a successful send, since a
  // failed digest generation shouldn't leave the same near-duplicates
  // eligible again on an immediate retry either.
  recordSentHeadlines(deduped.map(d => d.title));
  return results;
}

// Fetch real-time trending topics from Google Trends RSS (Brazil)
async function fetchGoogleTrends() {
  try {
    const result = await makeRequest('https://trends.google.com/trending/rss?geo=BR&hours=4', {
      method: 'GET',
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    if (result.status !== 200) {
      console.error('google trends fetch error:', result.status);
      recordSourceHealth('google_trends', 0, `HTTP ${result.status}`);
      return [];
    }
    const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);
    const titles = html.match(/<title>(.*?)<\/title>/gs) || [];
    const trends = titles.map(t => {
      const m = t.match(/<title>(.*?)<\/title>/s);
      return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&amp;/g, '&').trim() : '';
    }).filter(t => t.length > 2 && !/Daily Search Trends|Google/i.test(t)).slice(0, 10);
    if (trends.length === 0) {
      recordSourceHealth('google_trends', 0, 'extractor returned 0 items');
      return [];
    }
    console.log(`Extracted ${trends.length} real-time trends from Google Trends`);
    recordSourceHealth('google_trends', trends.length, null);
    return [{
      topic: 'Google Trends Brasil (realtime)',
      raw: 'Что ищут бразильцы прямо сейчас (Google Trends, последние 4 часа):\n' + trends.join(', ')
    }];
  } catch (error) {
    console.error('fetchGoogleTrends failed:', error.message);
    recordSourceHealth('google_trends', 0, error.message);
    return [];
  }
}

async function collectTrends() {
  if (!settings.includeTrends) return [];
  
  // Collect real trends from trends24.in (X/Twitter Brazil)
  const realTrends = await fetchTrends24();
  // Collect real-time trends from Google Trends RSS
  const googleTrends = await fetchGoogleTrends();
  
  // Also collect search-based trends (Google Trends style) for richer coverage
  const dates = getDates();
  const trendQueries = getTrendQueries(dates);
  let trendNews = [];
  
  for (const q of trendQueries) {
    console.log(`Searching trends [${q.topic}]: ${q.query}`);
    const news = await searchNews(q.query);
    if (news && news.answer) {
      trendNews.push({ topic: q.topic, raw: news.answer });
    }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  
  // Combine all sources (deduplicate by topic)
  const combined = [...realTrends, ...googleTrends, ...trendNews];
  const seen = new Set();
  return combined.filter(t => {
    if (seen.has(t.topic)) return false;
    seen.add(t.topic);
    return true;
  });
}

async function sendDailyBriefing(dialogId) {
  console.log(`[${new Date().toISOString()}] Starting daily briefing...`);
  
  // Keep the "searching" indicator alive during the (long) collection phase.
  const { raw: rawNews, trends: trendNews, sources: sourceNews } = await withTyping(
    dialogId,
    'IMBOT_AGENT_ACTION_SEARCHING',
    async () => {
      const r = await collectRawNews();
      const t = await collectTrends();
      const s = await collectSourceNews();
      return { raw: r, trends: t, sources: s };
    }
  );
  
  if (rawNews.length === 0 && trendNews.length === 0 && sourceNews.length === 0) {
    await sendBotMessage(dialogId, '❌ Не удалось собрать истории сегодня. Попробую снова завтра.', getMainKeyboard());
    return false;
  }
  
  const digest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () =>
    generateDigest(rawNews, trendNews, sourceNews)
  );
  if (!digest || digest.stories.length === 0) {
    await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест. Попробуй ещё раз.', getMainKeyboard());
    return false;
  }
  
  // Send digest as one message per story (sprint 7), each with its own
  // 👍/👎 keyboard, instead of one giant block of text.
  const introText = settings.lang === 'ru'
    ? `✨ *Борис: самое интересное сегодня*\n📅 ${formatDateBR(new Date())}`
    : `✨ *Boris: o mais interessante hoje*\n📅 ${formatDateBR(new Date())}`;
  await sendDigestAsMessages(dialogId, digest, introText);
  console.log(`[${new Date().toISOString()}] Briefing sent (${rawNews.length} news, ${trendNews.length} trends, ${sourceNews.length} sources, ${digest.stories.length} stories delivered)`);
  return true;
}

// Guard: prevent the same heavy job type from running twice in parallel.
// Heavy jobs (digest/trends/surprise) take minutes, and running them in the
// event-poll loop would block processing of all subsequent events. We instead
// schedule them to run in the background so the bot keeps answering instantly.
const heavyJobs = {};
function scheduleHeavyJob(fn, key) {
  if (heavyJobs[key]) {
    console.log(`[heavy:${key}] already running, skipping duplicate`);
    return;
  }
  heavyJobs[key] = (async () => {
    try {
      await fn();
    } catch (err) {
      console.error(`[heavy:${key}] failed: ${err.message}`);
    } finally {
      delete heavyJobs[key];
    }
  })();
}

// Command handlers
async function handleCommand(command, params, dialogId) {
  switch (command) {
    case 'start':
    case 'hello':
    case 'hi':
      await sendBotMessage(dialogId,
        `Привет! Я Борис ✨ — твой ежедневный дайджест самых интересных и трендовых историй со всего мира.\n\n` +
        `Каждый будний день в 09:20 (Мск) присылаю свежие истории с «вау-фактором»: AI и технологии, вирусное из интернета, наука, поп-культура, любопытное и необычное.\n\n` +
        `Используй кнопки или команды:\n` +
        `• ✨ Интересное сейчас — /news\n` +
        `• 🔥 Тренды — /showtrends\n` +
        `• 🎲 Случайная история — /surprise\n` +
        `• 📚 Темы — /topics\n` +
        `• ⚙️ Настройки — /settings\n` +
        `• /help — все команды`,
        getMainKeyboard()
      );
      break;

    case 'news':
    case 'briefing':
      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);
      await sendBotMessage(dialogId, '⏳ Ищу самые интересные и свежие истории...', getMainKeyboard());
      scheduleHeavyJob(() => sendDailyBriefing(dialogId), 'news');
      break;
      
    case 'showtrends':
      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);
      await sendBotMessage(dialogId, '⏳ Ищу свежие тренды (последние 72 часа)...', getMainKeyboard());
      scheduleHeavyJob(async () => {
        const trendNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectTrends());
        if (trendNews.length === 0) {
          await sendBotMessage(dialogId, '❌ Не удалось собрать тренды сейчас. Попробуй позже.', getMainKeyboard());
          return;
        }
        const trendDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([], trendNews));
        if (trendDigest && trendDigest.stories.length > 0) {
          const introText = settings.lang === 'ru' ? '🔥 *Свежие тренды*' : '🔥 *Tendências frescas*';
          await sendDigestAsMessages(dialogId, trendDigest, introText);
        } else {
          await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест трендов. Попробуй ещё раз.', getMainKeyboard());
        }
      }, 'trends');
      break;

    case 'surprise':
    case 'random':
      await showTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', 30);
      await sendBotMessage(dialogId, '🎲 Ищу случайную интересную историю...', getMainKeyboard());
      scheduleHeavyJob(async () => {
        const surpriseNews = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_SEARCHING', () => collectRawNews());
        if (surpriseNews.length === 0) {
          await sendBotMessage(dialogId, '❌ Не удалось найти историю. Попробуй позже.', getMainKeyboard());
          return;
        }
        const pick = surpriseNews[Math.floor(Math.random() * surpriseNews.length)];
        const surpriseDigest = await withTyping(dialogId, 'IMBOT_AGENT_ACTION_GENERATING', () => generateDigest([pick], []));
        if (surpriseDigest && surpriseDigest.stories.length > 0) {
          const introText = settings.lang === 'ru' ? '🎲 *Случайная история*' : '🎲 *História aleatória*';
          await sendDigestAsMessages(dialogId, surpriseDigest, introText);
        } else {
          await sendBotMessage(dialogId, '❌ Не удалось сгенерировать историю. Попробуй ещё раз.', getMainKeyboard());
        }
      }, 'surprise');
      break;
      
    case 'settings':
      await sendBotMessage(dialogId,
        `⚙️ *Настройки Бориса*\n\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\n` +
        `🔥 Тренды: ${settings.includeTrends ? 'вкл' : 'выкл'}\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\n` +
        `📰 Тем: ${settings.topics.length}\n\n` +
        `Нажми кнопку, чтобы изменить — или используй команды из /help.`,
        getSettingsKeyboard()
      );
      break;
      
    case 'feedback':
      if (params === 'good') {
        settings.feedback.good++;
        saveSettings();
        await sendBotMessage(dialogId, `👍 Спасибо! Рад, что понравилось. (Всего: ${settings.feedback.good} 👍, ${settings.feedback.bad} 👎)`, getMainKeyboard());
      } else if (params === 'bad') {
        settings.feedback.bad++;
        awaitingFeedback.add(dialogId);
        saveSettings();
        await sendBotMessage(dialogId, `👎 Спасибо за честность! Что именно вам не понравилось? Напишите, например: "не нравится тема про недвижимость" или "слишком длинные новости". Я учту это.`, getMainKeyboard());
      } else {
        await sendBotMessage(dialogId, 'Используйте кнопки 👍 или 👎 для оценки.', getFeedbackKeyboard());
      }
      break;

    case 'storyfeedback': {
      // Triggered by the 👍/👎 buttons under an individual story
      // (sprint 7) — ACTION_VALUE is "/storyfeedback <hash> good|bad".
      // Deliberately no follow-up question here (unlike /feedback bad
      // above) — see recordStoryFeedback()'s comment for why.
      const [storyHash, reaction] = params.split(' ');
      if (!storyHash || (reaction !== 'good' && reaction !== 'bad')) {
        await sendBotMessage(dialogId, '❌ Не удалось разобрать оценку истории.', getMainKeyboard());
        break;
      }
      // Resolve topic/title from the in-memory send-time cache. Falls back
      // to "Без темы" (inside recordStoryFeedback) if the process restarted
      // since this story was sent, or the cache evicted it — the reaction
      // itself is still recorded either way, just without topic attribution.
      const cached = storyLookupCache.get(storyHash);
      const topic = cached ? cached.topic : null;
      const title = cached ? cached.title : null;
      recordStoryFeedback(storyHash, topic, title, reaction);
      await sendBotMessage(dialogId, reaction === 'good' ? '👍 Учтено!' : '👎 Учтено, буду показывать поменьше такого.', null);
      break;
    }

    case 'help':
      await sendBotMessage(dialogId,
        '🤖 *Борис — помощь*\n\n' +
        '*Кнопки:*\n' +
        '• ✨ Интересное сейчас\n' +
        '• 🔥 Тренды\n' +
        '• 🎲 Случайная история\n' +
        '• 📚 Темы\n' +
        '• ⚙️ Настройки\n\n' +
        '*Команды:*\n' +
        '• /news — интересное сейчас\n' +
        '• /showtrends — тренды\n' +
        '• /surprise — случайная история\n' +
        '• /settings — настройки\n' +
        '• /lang <pt|ru> — язык\n' +
        '• /topics — список тем\n' +
        '• /addtopic <тема> — добавить тему\n' +
        '• /removetopic <тема> — убрать тему\n' +
        '• /trends — вкл/выкл тренды\n' +
        '• /schedule — расписание\n' +
        '• /settime <ЧЧ:ММ> — время\n' +
        '• /on|/off — автосбор\n' +
        '• /feedback good|bad — оценка дайджеста целиком (по историям — кнопки 👍/👎 под каждой)\n' +
        '• /reset — очистить память диалога\n' +
        '• /sourcehealth — состояние источников новостей\n' +
        '• /menu — открыть меню с кнопками\n\n' +
        '*Темы:*\n' +
        settings.topics.join(', ') + '\n\n' +
        '*Язык:* ' + (settings.lang === 'ru' ? 'Русский' : 'Português'),
        getMainKeyboard()
      );
      break;
      
    case 'status':
      const unhealthy = getUnhealthySources();
      const healthLine = unhealthy.length > 0
        ? `⚠️ Проблемные источники (0 результатов ${SOURCE_HEALTH_ALERT_THRESHOLD}+ раз подряд): ${unhealthy.map(h => h.id).join(', ')} — см. /sourcehealth\n`
        : `✅ Все источники в норме\n`;
      const storyFeedbackLine = formatStoryFeedbackSummary();
      await sendBotMessage(dialogId,
        `📊 *Статус Бориса*\n\n` +
        `✅ Бот активен\n` +
        `📰 Тем: ${settings.topics.length}\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\n` +
        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\n` +
        `👍 Оценки дайджеста: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\n` +
        storyFeedbackLine +
        `🧠 AI-генерация дайджеста: включена\n` +
        `💬 Свободный диалог через LLM: включен (память ${MAX_HISTORY_TURNS} реплик, /reset — очистить)\n` +
        `🧹 Дедуп (посл. сбор): ${lastDedupStats.input} → ${lastDedupStats.output} (склеено ${lastDedupStats.collapsed}, повторов заблокировано ${lastDedupStats.blockedRepeats})\n` +
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
        `🩺 *Здоровье источников*\n\n${lines.join('\n')}\n\n` +
        `🔴 = вероятно сломан экстрактор/сайт изменился (${SOURCE_HEALTH_ALERT_THRESHOLD}+ пустых подряд)\n` +
        `🟡 = недавно были пустые ответы, но не критично\n` +
        `🟢 = работает нормально`,
        getSourceHealthKeyboard()
      );
      break;

    case 'reset':
      conversationHistory.delete(dialogId);
      await sendBotMessage(dialogId, '🧹 Память этого диалога очищена. Начинаем с чистого листа!', getMainKeyboard());
      break;
      
    case 'lang':
      if (params === 'pt' || params === 'ru') {
        settings.lang = params;
        saveSettings();
        await sendBotMessage(dialogId, `✅ Язык изменен на ${params === 'ru' ? 'Русский' : 'Português'}.`, getSettingsKeyboard());
      } else {
        await sendBotMessage(dialogId, '❌ Формат: /lang pt или /lang ru', getSettingsKeyboard());
      }
      break;
      
    case 'trends':
      settings.includeTrends = !settings.includeTrends;
      saveSettings();
      await sendBotMessage(dialogId, `✅ Тренды (макс 72ч): ${settings.includeTrends ? 'включены' : 'выключены'}.`, getSettingsKeyboard());
      break;
      
    case 'topics':
      await sendBotMessage(dialogId,
        `📰 *Темы (${settings.topics.length}):*\n\n${settings.topics.map((t,i) => `${i+1}. ${t}`).join('\n')}\n\n` +
        (settings.topics.length <= MAX_TOPIC_BUTTONS
          ? `Нажми ❌ на теме, чтобы убрать её, или добавь новую.`
          : `Тем многовато для кнопок — убрать: /removetopic <тема>`),
        getTopicsKeyboard()
      );
      break;
      
    case 'addtopic':
      if (params) {
        settings.topics.push(params);
        saveSettings();
        await sendBotMessage(dialogId, `✅ Тема «${params}» добавлена. Теперь тем: ${settings.topics.length}`, getTopicsKeyboard());
      } else {
        awaitingTopic.add(dialogId);
        await sendBotMessage(dialogId, '✏️ Напиши название новой темы одним сообщением.', getMainKeyboard());
      }
      break;
      
    case 'removetopic':
      if (params) {
        const idx = settings.topics.findIndex(t => t.toLowerCase() === params.toLowerCase());
        if (idx >= 0) {
          settings.topics.splice(idx, 1);
          saveSettings();
          await sendBotMessage(dialogId, `✅ Тема «${params}» удалена. Осталось: ${settings.topics.length}`, getTopicsKeyboard());
        } else {
          await sendBotMessage(dialogId, `❌ Тема «${params}» не найдена. /topics — список тем`, getTopicsKeyboard());
        }
      } else {
        await sendBotMessage(dialogId, '❌ Укажите тему: /removetopic <тема>', getTopicsKeyboard());
      }
      break;
      
    case 'schedule':
      await sendBotMessage(dialogId,
        `⏰ *Расписание*\n\n` +
        `Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'}\n` +
        `Время: ${settings.time} (${settings.timezone})\n` +
        `Дни: Пн-Пт\n\n` +
        `Выбери время кнопкой ниже, или укажи своё: /settime <ЧЧ:ММ>`,
        getScheduleKeyboard()
      );
      break;
      
    case 'settime':
      if (params && /^\d{2}:\d{2}$/.test(params)) {
        settings.time = params;
        saveSettings();
        await sendBotMessage(dialogId, `✅ Время автосбора изменено на ${params} (${settings.timezone})`, getMainKeyboard());
      } else {
        await sendBotMessage(dialogId, '❌ Формат: /settime 09:20', getMainKeyboard());
      }
      break;
      
    case 'on':
      settings.autoSend = true;
      saveSettings();
      await sendBotMessage(dialogId, '✅ Автосбор включен.', getMainKeyboard());
      break;
      
    case 'off':
      settings.autoSend = false;
      saveSettings();
      await sendBotMessage(dialogId, '⏸ Автосбор выключен. Используйте /news для ручного запроса.', getMainKeyboard());
      break;
      
    case 'menu':
      await sendBotMessage(dialogId,
        `Меню Бориса ✨ — выбери, с чего начать:`,
        getMainKeyboard()
      );
      break;

    default:
      await sendBotMessage(dialogId, `❌ Неизвестная команда: /${command}. /help — список команд`, getMainKeyboard());
  }
}

// Poll events from bot
async function pollEvents() {
  let offset;
  console.log('Starting event polling...');
  
  while (true) {
    try {
      let url = `https://vibecode.bitrix24.tech/v1/bots/${BOT_ID}/events?limit=50`;
      if (offset !== undefined) url += `&offset=${offset}`;
      
      const result = await makeRequest(url, {
        headers: { 'X-Api-Key': VIBE_API_KEY }
      });
      
      if (result.status === 200 && result.data && result.data.data) {
        const { events, nextOffset } = result.data.data;
        
        for (const event of events || []) {
          await handleEvent(event);
        }
        
        if (nextOffset !== undefined) offset = nextOffset;
      }
    } catch (err) {
      console.error('Poll error:', err.message);
    }
    
    await new Promise(r => setTimeout(r, 3000));
  }
}

async function handleEvent(event) {
  const data = event.data || {};
  console.log(`[event] type=${event.type} data=${JSON.stringify(data).substring(0,500)}`);
  
  switch (event.type) {
    case 'ONIMBOTV2MESSAGEADD':
      const dialogId = data.chat?.dialogId || data.dialogId;
      const text = data.message?.text || '';
      // Skip system messages and the bot's own messages
      if (data.message?.isSystem) return;
      if (data.message?.authorId === data.bot?.id) return;
      console.log(`Message from ${data.user?.name}: ${text}`);
      
      if (text.startsWith('/')) {
        const parts = text.split(' ');
        const command = parts[0].replace('/', '').toLowerCase();
        const params = parts.slice(1).join(' ');
        await handleCommand(command, params, dialogId);
      } else {
        // If we just asked "what didn't you like?" *in this dialog*, capture
        // the reply as a dislike. Per-dialog (not global) so an unrelated
        // message in another dialog can't be mistaken for feedback.
        if (awaitingTopic.has(dialogId)) {
          awaitingTopic.delete(dialogId);
          const newTopic = text.trim();
          settings.topics.push(newTopic);
          saveSettings();
          await sendBotMessage(dialogId, `✅ Тема «${newTopic}» добавлена. Теперь тем: ${settings.topics.length}`, getTopicsKeyboard());
        } else if (awaitingFeedback.has(dialogId)) {
          awaitingFeedback.delete(dialogId);
          settings.feedback.dislikes.push(text.trim());
          saveSettings();
          await sendBotMessage(dialogId, `👌 Понял, учту: «${text.trim()}». Спасибо за обратную связь!`, getMainKeyboard());
        } else {
          // "Живой" ответ: распознаём простые вопросы (что умеешь, кто ты,
          // приветствие, настроение и т.д.). Если не распознали — показываем
          // интерактивное приветствие-меню.
          const casual = getCasualReply(text, data.user?.name);
          if (casual) {
            await sendBotMessage(dialogId, casual.text, casual.keyboard || getMainKeyboard());
          } else {
            // Not a recognized regex pattern — hand off to the LLM for a real
            // conversational reply instead of always showing the static menu.
            await showTyping(dialogId, 'IMBOT_AGENT_ACTION_THINKING', 20);
            const aiReply = await generateConversationalReply(dialogId, text, data.user?.name);
            if (aiReply) {
              await sendBotMessage(dialogId, aiReply, getMainKeyboard());
            } else {
              const h = new Date().getHours();
              const greet = h >= 5 && h < 12 ? 'Доброе утро' : (h >= 12 && h < 18 ? 'Добрый день' : 'Добрый вечер');
              const who = (data.user?.name || '').trim().split(/\s+/)[0];
              await sendBotMessage(dialogId,
                `${greet}${who ? ', ' + who : ''}! Я Борис ✨ — твой куратор интересных историй.\n\n` +
                `Могу показать свежие истории, тренды или рассказать о себе. С чего начнём?\n\n` +
                `• ✨ Интересное сейчас — /news\n` +
                `• 🔥 Тренды — /showtrends\n` +
                `• 🎲 Случайная история — /surprise\n` +
                `• 💬 «Что ты умеешь?» — о моих возможностях`,
                getMainKeyboard());
            }
          }
        }
      }
      break;
      
    case 'ONIMBOTV2COMMANDADD':
      const cmdDialogId = data.chat?.dialogId || data.dialogId;
      const cmd = data.command?.command || '';
      const cmdParams = data.command?.params || '';
      console.log(`Command from ${data.user?.name}: /${cmd} ${cmdParams}`);
      await handleCommand(cmd, cmdParams, cmdDialogId);
      break;
  }
}

// HTTP server
const server = http.createServer(async (req, res) => {
  console.log(`${req.method} ${req.url}`);
  
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', bot: BOT_NAME, time: new Date().toISOString(), version: VERSION }));
    return;
  }
  
  if (req.url === '/trigger' && req.method === 'POST') {
    res.writeHead(202, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'started' }));
    sendDailyBriefing(BITRIX_USER_ID).catch(console.error);
    return;
  }
  
  res.writeHead(404);
  res.end('Not Found');
});

// Keep the long-lived server process alive through unexpected errors —
// one bad event/message should not take the whole bot down until the
// next scheduled wake-up.
process.on('uncaughtException', (err) => {
  console.error('[fatal-ish] uncaughtException:', err && err.stack || err);
});
process.on('unhandledRejection', (reason) => {
  console.error('[fatal-ish] unhandledRejection:', reason);
});

server.listen(PORT, () => {
  console.log(`🚀 ${BOT_NAME} v${VERSION} running on port ${PORT}`);
  console.log(`Bot ID: ${BOT_ID}`);
  console.log(`Health: http://localhost:${PORT}/health`);
  console.log(`Trigger: POST http://localhost:${PORT}/trigger`);
  console.log(`Settings file: ${SETTINGS_FILE}`);
  
  pollEvents().catch(err => console.error('Polling crashed:', err));
  
  // The server only wakes on schedule (09:00 Moscow, Mon-Fri), so on startup
  // in a weekday we should just send the digest. The old isWeekdayMorning()
  // checked a narrow 09:00-09:40 window and could miss if the container
  // started late (e.g. "Not a weekday morning - skipping scheduled digest").
  const moscowDay = new Date(new Date().toLocaleString('en-US', { timeZone: 'Europe/Moscow' })).getDay();
  if (moscowDay >= 1 && moscowDay <= 5) {
    console.log('Weekday detected - sending morning digest');
    sendDailyBriefing(BITRIX_USER_ID).catch(console.error);
  } else {
    console.log('Weekend - skipping scheduled digest');
  }
});
