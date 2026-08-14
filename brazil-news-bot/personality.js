// Личность и «живость» Бориса: распознавание простых сообщений и
// ответы о себе и своих функциях. Без внешних зависимостей.

const lower = (s) => (s || '').toLowerCase().trim();
const hasAny = (s, words) => words.some(w => s.includes(w));

function greetingByTime() {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return 'Доброе утро';
  if (h >= 12 && h < 18) return 'Добрый день';
  if (h >= 18 && h < 23) return 'Добрый вечер';
  return 'Доброй ночи';
}

function firstName(fullName) {
  if (!fullName) return '';
  return fullName.trim().split(/\s+/)[0];
}

// Детерминированное распознавание простого свободного ввода.
// Возвращает { text, keyboard } или null, если сообщение не распознано как
// «живой» вопрос (тогда вызывающий покажет стандартное приветствие-меню).
function getCasualReply(text, userName) {
  const t = lower(text);
  const name = firstName(userName);
  const greet = greetingByTime();
  const mention = name ? `, ${name}` : '';

  // --- Кто ты / что умеешь / о себе ---
  if (hasAny(t, ['что ты умеешь', 'что умеешь', 'что ты можешь', 'умеешь', 'что можешь',
                 'твои функции', 'что ты делаешь', 'что такое', 'о себе', 'расскажи о себе',
                 'о чём ты можешь', 'о чем ты можешь', 'о чём можешь', 'о чем можешь',
                 'о чём ты знаешь', 'о чем ты знаешь', 'что интересного знаешь', 'расскажи что',
                 'кто ты', 'ты кто', 'что ты', 'зачем ты', 'для чего ты',
                 'o que você faz', 'o que voce faz', 'o que sabe', 'quem é você', 'quem e voce',
                 'quem é voce', 'para que serve', 'o que você é', 'o que voce e'])) {
    return {
      text:
        `${greet}${mention}! Я Борис ✨ — твой ежедневный куратор самых интересных и трендовых историй со всего мира.\n\n` +
        `Каждый будний день в 09:20 (Мск) я присылаю свежий дайджест с «вау-фактором»: неожиданные новости из мира AI и технологий, вирусное из интернета, наука и космос, поп-культура, любопытное и необычное — плюс тренды и бизнес-идеи.\n\n` +
        `Вот что я умею:\n` +
        `✨ *Интересное сейчас* — подборка самых свежих историй прямо сейчас\n` +
        `🔥 *Тренды* — что сейчас в топе (X/Twitter, Google Trends)\n` +
        `🎲 *Случайная история* — неожиданный факт на удачу\n` +
        `📚 *Темы* — управление темами, которые мне интересно искать\n` +
        `⚙️ *Настройки* — язык, время, автосбор, оценка\n\n` +
        `Я умею говорить на русском и португальском (🇷🇺 / 🇧🇷), запоминаю твои предпочтения и стараюсь не повторяться. Нажми на кнопку ниже — и я покажу, на что способен!`,
      keyboard: [
        { TEXT: '✨ Интересное сейчас', ACTION: 'SEND', ACTION_VALUE: '/news', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
        { TEXT: '🔥 Тренды', ACTION: 'SEND', ACTION_VALUE: '/showtrends', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
        { TEXT: '🎲 Случайная история', ACTION: 'SEND', ACTION_VALUE: '/surprise', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }
      ]
    };
  }

  // --- Приветствие ---
  if (hasAny(t, ['привет', 'здравствуй', 'здравствуйте', 'добрый день', 'доброе утро',
                 'добрый вечер', 'хай', 'hello', 'olá', 'ola', 'oi', 'bom dia', 'boa tarde', 'boa noite'])) {
    const replies = [
      `${greet}${mention}! Рад тебя видеть 😊 Что интересненького сегодня — показать свежие истории или тренды?`,
      `${greet}${mention}! Ты как раз вовремя — у меня есть что рассказать ✨ Хочешь /news или /showtrends?`,
      `Привет${mention}! 😄 Я на связи и полон свежих идей. Запустить дайджест или поискать тренды?`
    ];
    return {
      text: replies[Math.floor(Math.random() * replies.length)],
      keyboard: getQuickActions()
    };
  }

  // --- Как дела / настроение ---
  if (hasAny(t, ['как дела', 'как ты', 'как жизнь', 'как настроение', 'как поживаешь',
                 'como vai', 'como você está', 'como voce esta', 'tudo bem', 'tudo bom'])) {
    return {
      text:
        `У меня всё отлично${mention}! 😄 Только что перерыл интернет в поисках интересного — и, поверь, там есть чем поделиться.\n\n` +
        `Вот, например, могу прямо сейчас собрать тебе свежий дайджест удивительных историй. Запустить?`,
      keyboard: getQuickActions()
    };
  }

  // --- Спасибо / благодарность ---
  if (hasAny(t, ['спасибо', 'благодарю', 'спс', 'круто', 'класс', 'отлично', 'супер', 'молодец',
                 'obrigado', 'obrigada', 'valeu', 'legal', 'ótimo', 'otimo', 'excelente'])) {
    const replies = [
      `Всегда пожалуйста${mention}! 🎉 Рад, что тебе нравится. Если хочешь ещё чего-нибудь интересного — просто скажи.`,
      `Пожалуйста${mention}! 🤗 Для меня это в удовольствие. Могу ещё что-нибудь найти — что скажешь?`,
      `Спасибо тебе${mention}! 🙌 Заходи ещё, у меня каждый раз что-то новенькое.`
    ];
    return {
      text: replies[Math.floor(Math.random() * replies.length)],
      keyboard: getQuickActions()
    };
  }

  // --- Пока / прощание ---
  if (hasAny(t, ['пока', 'до свидания', 'до встречи', 'удачи', 'прощай', 'всё', 'спать',
                 'tchau', 'adeus', 'até logo', 'ate logo', 'boa noite'])) {
    return {
      text: `До встречи${mention}! 👋 Хорошего дня и до скорого. Я буду тут — соберу всё самое интересное к твоему возвращению.`,
      keyboard: getQuickActions()
    };
  }

  return null;
}

function getQuickActions() {
  return [
    { TEXT: '✨ Интересное сейчас', ACTION: 'SEND', ACTION_VALUE: '/news', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '🔥 Тренды', ACTION: 'SEND', ACTION_VALUE: '/showtrends', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' },
    { TEXT: '🔍 Что ты умеешь?', ACTION: 'SEND', ACTION_VALUE: 'Что ты умеешь?', BG_COLOR_TOKEN: 'secondary', DISPLAY: 'LINE' }
  ];
}

module.exports = { getCasualReply };
