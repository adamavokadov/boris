const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { getCasualReply } = require('./personality');

const PORT = process.env.PORT || 3000;
const VIBE_API_KEY = process.env.VIBE_API_KEY;
const BITRIX_USER_ID = process.env.BITRIX_USER_ID || '1221912';
const BOT_ID = process.env.BOT_ID || '1505555';
const BOT_NAME = 'Борис';
const VERSION = '14.1';

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
  awaitingFeedback: false
};

// Bot settings (loaded from disk, falls back to defaults)
let settings = loadSettings();

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

Формат выдачи:
- 5-7 самых интересных историй + блок свежих трендов
- В конце — «Резюме дня» (1-2 предложения, что сегодня самое интересное)

Формат ответа:
✨ Борис: самое интересное сегодня
📅 {даты}

[тема]: [цепляющий заголовок]
📅 [дата публикации/актуальности]
[суть истории]
[почему это интересно]

🔗 Источник

...

🔥 Тренды (свежие): [что сейчас в тренде]
📅 [дата актуальности тренда]
[краткое описание]

📌 Резюме дня: [1-2 предложения]`
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

Formato de saída:
- 5-7 histórias mais interessantes + bloco de tendências frescas
- No final — «Resumo do dia» (1-2 frases sobre o que é mais interessante hoje)

Formato da resposta:
✨ Boris: o mais interessante hoje
📅 {datas}

[tema]: [título cativante]
📅 [data de publicação/atualidade]
[essência da história]
[por que é interessante]

🔗 Fonte

...

🔥 Tendências (frescas): [o que está em alta agora]
📅 [data de atualidade da tendência]
[breve descrição]

📌 Resumo do dia: [1-2 frases]`;
  
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
      return result.data.choices[0].message.content;
    }
    console.error('AI response error:', result.status, JSON.stringify(result.data).substring(0, 300));
    return null;
  } catch (error) {
    console.error('AI generate failed:', error.message);
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
      return [];
    }
    
    console.log(`Extracted ${unique.length} real trends from trends24.in`);
    return [{
      topic: 'Tendências reais (trends24.in/brazil)',
      raw: 'Tendências reais do X/Twitter no Brasil nas últimas 24 horas:\n' + unique.join(', ')
    }];
  } catch (error) {
    console.error('fetchTrends24 failed:', error.message);
    return [];
  }
}

// Fetch headlines from curated external sources (habr, bloomberglinea, google news)
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
  const results = [];
  for (const source of SOURCES) {
    const titles = await fetchSourceHeadlines(source);
    if (titles.length > 0) {
      results.push({
        topic: source.name,
        source: source.id,
        raw: `Свежие заголовки из источника «${source.name}»:\n` + titles.map((t, i) => `${i+1}. ${t}`).join('\n')
      });
    }
    await new Promise(resolve => setTimeout(resolve, 800));
  }
  // Add WatcherGuru-style "Just In" breaking news via search
  const breaking = await fetchBreakingNews();
  if (breaking.length > 0) {
    results.push({
      topic: 'WatcherGuru-style «Just In» breaking news',
      source: 'breaking',
      raw: 'Самые свежие «Just In» новости (в стиле WatcherGuru):\n' + breaking.map((h, i) => `${i+1}. ${h}`).join('\n')
    });
  }
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
      return [];
    }
    const html = typeof result.data === 'string' ? result.data : JSON.stringify(result.data);
    const titles = html.match(/<title>(.*?)<\/title>/gs) || [];
    const trends = titles.map(t => {
      const m = t.match(/<title>(.*?)<\/title>/s);
      return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/&amp;/g, '&').trim() : '';
    }).filter(t => t.length > 2 && !/Daily Search Trends|Google/i.test(t)).slice(0, 10);
    if (trends.length === 0) return [];
    console.log(`Extracted ${trends.length} real-time trends from Google Trends`);
    return [{
      topic: 'Google Trends Brasil (realtime)',
      raw: 'Что ищут бразильцы прямо сейчас (Google Trends, последние 4 часа):\n' + trends.join(', ')
    }];
  } catch (error) {
    console.error('fetchGoogleTrends failed:', error.message);
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
  if (!digest) {
    await sendBotMessage(dialogId, '❌ Не удалось сгенерировать дайджест. Попробуй ещё раз.', getMainKeyboard());
    return false;
  }
  
  // Send digest with feedback buttons
  const sent = await sendBotMessage(dialogId, digest, getFeedbackKeyboard());
  console.log(`[${new Date().toISOString()}] Briefing ${sent ? 'sent' : 'failed'} (${rawNews.length} news, ${trendNews.length} trends, ${sourceNews.length} sources)`);
  return sent;
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
        if (trendDigest) {
          await sendBotMessage(dialogId, trendDigest, getFeedbackKeyboard());
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
        if (surpriseDigest) {
          await sendBotMessage(dialogId, surpriseDigest, getFeedbackKeyboard());
        }
      }, 'surprise');
      break;
      
    case 'settings':
      await sendBotMessage(dialogId,
        `⚙️ *Настройки Бориса*\n\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'} (/lang pt|ru)\n` +
        `🔥 Тренды: ${settings.includeTrends ? 'вкл' : 'выкл'} (/trends)\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone}) (/on|/off)\n` +
        `📰 Тем: ${settings.topics.length} (/topics)\n\n` +
        `*Команды:*\n` +
        `• /lang pt|ru — язык\n` +
        `• /trends — вкл/выкл тренды\n` +
        `• /addtopic <тема> — добавить тему\n` +
        `• /removetopic <тема> — убрать тему\n` +
        `• /settime <ЧЧ:ММ> — время\n` +
        `• /on|/off — автосбор\n` +
        `• /feedback good|bad — оценка`,
        getMainKeyboard()
      );
      break;
      
    case 'feedback':
      if (params === 'good') {
        settings.feedback.good++;
        saveSettings();
        await sendBotMessage(dialogId, `👍 Спасибо! Рад, что понравилось. (Всего: ${settings.feedback.good} 👍, ${settings.feedback.bad} 👎)`, getMainKeyboard());
      } else if (params === 'bad') {
        settings.feedback.bad++;
        settings.awaitingFeedback = true;
        saveSettings();
        await sendBotMessage(dialogId, `👎 Спасибо за честность! Что именно вам не понравилось? Напишите, например: "не нравится тема про недвижимость" или "слишком длинные новости". Я учту это.`, getMainKeyboard());
      } else {
        await sendBotMessage(dialogId, 'Используйте кнопки 👍 или 👎 для оценки.', getFeedbackKeyboard());
      }
      break;
      
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
        '• /feedback good|bad — оценка\n\n' +
        '*Темы:*\n' +
        settings.topics.join(', ') + '\n\n' +
        '*Язык:* ' + (settings.lang === 'ru' ? 'Русский' : 'Português'),
        getMainKeyboard()
      );
      break;
      
    case 'status':
      await sendBotMessage(dialogId,
        `📊 *Статус Бориса*\n\n` +
        `✅ Бот активен\n` +
        `📰 Тем: ${settings.topics.length}\n` +
        `🌐 Язык: ${settings.lang === 'ru' ? 'Русский' : 'Português'}\n` +
        `🔥 Тренды (макс 72ч): ${settings.includeTrends ? 'вкл' : 'выкл'}\n` +
        `⏰ Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'} (${settings.time} ${settings.timezone})\n` +
        `👍 Оценки: ${settings.feedback.good} 👍 / ${settings.feedback.bad} 👎\n` +
        `🧠 AI-генерация: включена\n` +
        `🔧 Версия: ${VERSION}`,
        getMainKeyboard()
      );
      break;
      
    case 'lang':
      if (params === 'pt' || params === 'ru') {
        settings.lang = params;
        saveSettings();
        await sendBotMessage(dialogId, `✅ Язык изменен на ${params === 'ru' ? 'Русский' : 'Português'}.`, getMainKeyboard());
      } else {
        await sendBotMessage(dialogId, '❌ Формат: /lang pt или /lang ru', getMainKeyboard());
      }
      break;
      
    case 'trends':
      settings.includeTrends = !settings.includeTrends;
      saveSettings();
      await sendBotMessage(dialogId, `✅ Тренды (макс 72ч): ${settings.includeTrends ? 'включены' : 'выключены'}.`, getMainKeyboard());
      break;
      
    case 'topics':
      await sendBotMessage(dialogId, `📰 *Темы (${settings.topics.length}):*\n\n${settings.topics.map((t,i) => `${i+1}. ${t}`).join('\n')}\n\nДобавить: /addtopic <тема>\nУбрать: /removetopic <тема>`, getMainKeyboard());
      break;
      
    case 'addtopic':
      if (params) {
        settings.topics.push(params);
        saveSettings();
        await sendBotMessage(dialogId, `✅ Тема «${params}» добавлена. Теперь тем: ${settings.topics.length}`, getMainKeyboard());
      } else {
        await sendBotMessage(dialogId, '❌ Укажите тему: /addtopic <тема>', getMainKeyboard());
      }
      break;
      
    case 'removetopic':
      if (params) {
        const idx = settings.topics.findIndex(t => t.toLowerCase() === params.toLowerCase());
        if (idx >= 0) {
          settings.topics.splice(idx, 1);
          saveSettings();
          await sendBotMessage(dialogId, `✅ Тема «${params}» удалена. Осталось: ${settings.topics.length}`, getMainKeyboard());
        } else {
          await sendBotMessage(dialogId, `❌ Тема «${params}» не найдена. /topics — список тем`, getMainKeyboard());
        }
      } else {
        await sendBotMessage(dialogId, '❌ Укажите тему: /removetopic <тема>', getMainKeyboard());
      }
      break;
      
    case 'schedule':
      await sendBotMessage(dialogId,
        `⏰ *Расписание*\n\n` +
        `Автосбор: ${settings.autoSend ? 'вкл' : 'выкл'}\n` +
        `Время: ${settings.time} (${settings.timezone})\n` +
        `Дни: Пн-Пт\n\n` +
        `Изменить время: /settime <ЧЧ:ММ>\n` +
        `Вкл/выкл: /on или /off`,
        getMainKeyboard()
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
        // If we just asked "what didn't you like?", capture the reply as a dislike
        if (settings.awaitingFeedback) {
          settings.awaitingFeedback = false;
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
