#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
"""

import os
import sys
import json
import logging
from datetime import datetime
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
CONFIG = {
    'target_user_id': os.getenv('TARGET_USER_ID', '1221912'),
    'api_key': os.getenv('VIBE_API_KEY'),
    'portal': os.getenv('BITRIX_PORTAL_DOMAIN', 'bitrix24.team'),
    'cron_schedule': '20 9 * * 1-5',  # 9:20, пн-пт
    'timezone': 'Europe/Moscow'
}

# Исключенные ключевые слова (португальский + английский)
EXCLUDED_KEYWORDS = [
    'futebol', 'football', 'soccer', 'esporte', 'sport', 'esportes',
    'política', 'eleição', 'eleições', 'crime', 'morte', 'acidente',
    'catástrofe', 'guerra', 'conflito', 'baleado', 'assassinato',
    'morto', 'morreu', 'assalto', 'roubo', 'policial', 'polícia',
    'prisão', 'preso', 'detido', 'tragédia', 'desastre'
]

# Темы для поиска
SEARCH_QUERIES = [
    'economia Brasil real inflação Banco Central investimentos',
    'agronegócio Brasil soja milho preços commodities',
    'tecnologia Brasil startups IA SaaS regulamentação big tech',
    'tendências sociais Brasil transporte greves consumo',
    'legislação Brasil negócios regulamentação eleições 2026'
]

def check_config():
    """Проверка конфигурации"""
    if not CONFIG['api_key']:
        logger.error("❌ ОШИБКА: VIBE_API_KEY не установлен")
        return False
    return True

def search_brazil_news():
    """Поиск новостей через VibeCode Search API"""
    all_results = []
    
    headers = {
        'X-Api-Key': CONFIG['api_key'],
        'Content-Type': 'application/json'
    }
    
    for query in SEARCH_QUERIES:
        try:
            logger.info(f"🔍 Поиск: {query}")
            response = requests.post(
                'https://vibecode.bitrix24.tech/v1/search',
                json={
                    'query': query,
                    'provider': 'brave',
                    'filters': {
                        'language': 'pt',
                        'region': 'BR'
                    }
                },
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'results' in data:
                    all_results.extend(data['results'])
                    logger.info(f"✅ Найдено: {len(data['results'])} результатов")
            else:
                logger.warning(f"⚠️ Ошибка поиска: {response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске '{query}': {e}")
    
    return all_results

def filter_news(news_items):
    """Фильтрация новостей по исключениям"""
    filtered = []
    
    for item in news_items:
        text = f"{item.get('title', '')} {item.get('description', '')} {item.get('snippet', '')}".lower()
        
        # Проверяем исключения
        if any(keyword in text for keyword in EXCLUDED_KEYWORDS):
            continue
        
        filtered.append(item)
    
    return filtered

def format_digest(news_items):
    """Форматирование дайджеста"""
    if not news_items:
        return (
            "🇧🇷 Дайджест новостей из Бразилии\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y')}\n"
            "═" * 40 + "\n\n"
            "К сожалению, сегодня не удалось получить новости.\n"
            "Попробуйте позже или проверьте источники вручную.\n\n"
            "═" * 40 + "\n"
            "Дайджест для Amado 🚀"
        )
    
    # Берем максимум 5 новостей
    top_news = news_items[:5]
    
    digest_lines = [
        "🇧🇷 Дайджест новостей из Бразилии",
        f"📅 {datetime.now().strftime('%d.%m.%Y')}",
        "═" * 40,
        ""
    ]
    
    for i, item in enumerate(top_news, 1):
        title = item.get('title', 'Без заголовка')
        description = item.get('description', item.get('snippet', 'Нет описания'))
        source = item.get('url', item.get('source', 'Неизвестно'))
        
        digest_lines.extend([
            f"{i}. {title}",
            f"   {description}",
            f"   Источник: {source}",
            ""
        ])
    
    digest_lines.extend([
        "═" * 40,
        "Дайджест подготовлен для Amado 🚀"
    ])
    
    return "\n".join(digest_lines)

def send_notification(message):
    """Отправка уведомления в Битрикс24"""
    try:
        headers = {
            'X-Api-Key': CONFIG['api_key'],
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            'https://vibecode.bitrix24.tech/v1/notifications',
            json={
                'userId': CONFIG['target_user_id'],
                'message': message,
                'type': 'personal',
                'tag': 'brazil-news-digest'
            },
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info("✅ Дайджест отправлен")
            return True
        else:
            logger.error(f"❌ Ошибка отправки: {response.status_code}")
            logger.error(f"Ответ: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке: {e}")
        return False

def collect_and_send_digest():
    """Основная функция: сбор и отправка дайджеста"""
    logger.info("🔄 Начинаю сбор дайджеста...")
    logger.info(f"⏰ {datetime.now().isoformat()}")
    
    try:
        # Сбор новостей
        news = search_brazil_news()
        logger.info(f"📰 Всего найдено: {len(news)}")
        
        # Фильтрация
        filtered_news = filter_news(news)
        logger.info(f"📰 После фильтрации: {len(filtered_news)}")
        
        # Форматирование
        digest = format_digest(filtered_news)
        
        # Отправка
        sent = send_notification(digest)
        
        if sent:
            logger.info("✅ Дайджест успешно отправлен")
        else:
            logger.error("❌ Не удалось отправить дайджест")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в процессе: {e}")

# Flask routes
@app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'service': 'Brazil News Digest for Amado',
        'schedule': CONFIG['cron_schedule'],
        'timezone': CONFIG['timezone'],
        'next_run': 'Завтра в 9:20 (если будний день)'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/trigger', methods=['POST'])
def trigger():
    """Ручной запуск дайджеста"""
    logger.info("🚀 Ручной запуск дайджеста")
    collect_and_send_digest()
    return jsonify({'status': 'triggered', 'message': 'Дайджест отправлен'})

def main():
    """Основная функция запуска"""
    logger.info("═" * 50)
    logger.info("🇧🇷 Brazil News Digest Service")
    logger.info("🚀 Для продукта Amado")
    logger.info("═" * 50)
    
    if not check_config():
        logger.error("❌ Ошибка конфигурации. Завершение.")
        sys.exit(1)
    
    # Настройка планировщика
    scheduler = BackgroundScheduler(timezone=CONFIG['timezone'])
    scheduler.add_job(
        collect_and_send_digest,
        'cron',
        hour=9,
        minute=20,
        day_of_week='mon-fri',
        id='brazil_digest',
        name='Brazil News Digest'
    )
    scheduler.start()
    
    logger.info("✅ Планировщик настроен")
    logger.info(f"📅 Расписание: {CONFIG['cron_schedule']} (пн-пт, 9:20)")
    logger.info(f"🌍 Часовой пояс: {CONFIG['timezone']}")
    logger.info("═" * 50)
    
    # Запуск Flask
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
