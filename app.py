    # Динамическая генерация отчёта OSINT на основе запроса
    clean_query = query.strip()

    if search_type == 'phone':
        # Форматируем номер для ссылок (убираем +, пробелы и скобки)
        phone_digits = ''.join(filter(str.isdigit, clean_query))
        result_data = {
            "ТИП ЗАПРОСА": "Поиск по номеру телефона",
            "ИСХОДНЫЙ НОМЕР": clean_query,
            "ПОИСК В WHATSAPP": f"https://wa.me/{phone_digits}",
            "ПОИСК В TELEGRAM": f"https://t.me/+{phone_digits}",
            "ПОИСК СОВПАДЕНИЙ В GOOGLE": [
                f"https://www.google.com/search?q=%22{phone_digits}%22",
                f"https://www.google.com/search?q=%22{clean_query}%22"
            ],
            "ПРОВЕРКА В ЯНДЕКС": f"https://yandex.ru/search/?text={clean_query}",
            "РЕКОМЕНДАЦИЯ": "Перейдите по ссылкам выше, чтобы проверить привязку мессенджеров и упоминания номера в сети.",
            "СТАТУС": "Данные сформированы"
        }
    elif search_type == 'person':
        result_data = {
            "ТИП ЗАПРОСА": "Поиск физического лица",
            "ФИО / ДАННЫЕ": clean_query,
            "ПОИСК ВКОНТАКТЕ": [
                f"https://vk.com/search?c%5Bq%5D={clean_query}&c%5Bsection%5D=people"
            ],
            "ПОИСК В GOOGLE": [
                f"https://www.google.com/search?q=%22{clean_query}%22"
            ],
            "ПРОВЕРКА В РЕЕСТРАХ НАЛОГОПЛАТЕЛЬЩИКОВ (РК)": [
                f"https://kgd.gov.kz/ru/services/taxpayer_search"
            ],
            "РЕКОМЕНДАЦИЯ": "Используйте открытые источники выше для совпадений по социальным сетям и налоговым базам.",
            "СТАТУС": "Данные сформированы"
        }
    else:
        result_data = {
            "ТИП ЗАПРОСА": f"Общий поиск ({search_type})",
            "ЗАПРОС": clean_query,
            "ПОИСК В GOOGLE": [
                f"https://www.google.com/search?q={clean_query}"
            ],
            "ПОИСК В ЯНДЕКС": [
                f"https://yandex.ru/search/?text={clean_query}"
            ],
            "СТАТУС": "Данные сформированы"
        }
