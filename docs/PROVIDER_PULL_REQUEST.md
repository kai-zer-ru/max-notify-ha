# Внедрение провайдера: руководство для Pull Request

Целевая аудитория: разработчик, который добавляет поддержку нового бэкенда в репозиторий [MaxNotify](https://github.com/kai-zer-ru/max-notify-ha).

Перед кодом убедитесь, что оператор API заполнил [спецификацию данных и контракт](PROVIDER_SPEC.md).

---

## 1. Ориентиры в кодовой базе

Изучите два встроенных провайдера:

- `custom_components/max_notify/providers/official/` — платформенный API Max;
- `custom_components/max_notify/providers/notify_a161/` — сторонний API с отличиями (polling, длина токена, свои шаги мастера).

Общий контракт класса: `custom_components/max_notify/providers/base.py` (`MaxNotifyIntegrationProvider`).

Реестр и порядок в UI: `custom_components/max_notify/providers/registry.py`.

---

## 2. Минимальный набор изменений

1. **`const.py`** — константа `INTEGRATION_TYPE_*` (строка совпадает с тем, что хранится в `ConfigEntry`).
2. **Каталог** `custom_components/max_notify/providers/<id>/` — изолированный пакет (провайдеры **не импортируют друг друга**).
3. **`registry.py`** — экземпляр провайдера, кортеж `INTEGRATION_TYPES`, словари `_BY_INTEGRATION_TYPE`, `_CAPABILITIES`, при необходимости `_PROVIDER_LABELS`.
4. **`get_provider`** — для новых записей предпочтителен явный `integration_type` в `data`. Отдельная ветка с эвристикой по `title` (как у notify_a161) допустима только для миграций и должна быть узко ограничена.
5. **Переводы** — `translations/en.json`, `translations/ru.json` (и при необходимости `strings.json`): шаги `config.step.*` / `options.step.*` с префиксом `{integration_type}_`, если задан `translation_prefix_keys` в реестре.
6. **Тесты** — см. раздел 5.

Мастер настройки в корне вызывает только `async_config_setup_step` / `async_options_flow_step` у выбранного провайдера; сценарии шагов живут в `config_setup.py` и `options_flow.py` пакета провайдера.

---

## 3. Структура пакета провайдера

| Файл | Назначение |
|------|------------|
| `const.py` | `API_BASE_URL`, `API_VERSION`, режимы приёма, типы апдейтов, при необходимости `TITLE_FALLBACK_SUBSTRINGS` для старых записей. |
| `capabilities.py` | Frozen-экземпляр `IntegrationCapabilities` из `providers/capabilities.py`. |
| `integration_provider.py` | Подкласс `MaxNotifyIntegrationProvider` с переопределёнными методами. |
| `api.py` | `async_validate_access_token`, при необходимости синхронизация команд бота. |
| Модули отправки / загрузок | Сборка URL и тел для `POST /messages`, `POST /uploads`, `DELETE`/`PUT` — по аналогии с `official/notify.py` или notify_a161. |
| `updates.py` (или аналог) | Нормализация сырого JSON в список dict для общего слоя приёма. |
| `config_setup.py`, `options_flow.py` | Шаги мастера и опций; тяжёлые импорты — лениво внутри методов, чтобы избежать циклов. |

Методы с пустой реализацией в базе переопределяются по необходимости: разрешение URL отправки (`async_resolve_message_post_url` / `resolve_simple_message_post_url`), параметры polling, обработка webhook, `extract_updates_from_poll_json`, лимиты вложений, `async_run_with_send_pace_lock` и т.д.

Политика **один токен — одна запись** и прочие ограничения мастера задаются в провайдере (`config_flow_new_entry_token_error_key`, `duplicate_config_entry_for_same_token`, `allow_multiple_config_entries_same_token`, `iter_config_entries_sharing_token`), а не дублируются в общем `config_flow.py`.

Если провайдер участвует в общем пуле токена платформы Max (`shares_platform_bot_token_pool=True`), аккуратно реализуйте `iter_config_entries_sharing_token` и исключите чужие типы интеграции из конфликтов webhook/polling (см. официальный провайдер).

---

## 4. Регистрация в `registry.py`

- Импорт констант и класса провайдера.
- Создание экземпляра со всеми полями конструктора: `integration_type`, `label`, `api_base_url`, `api_version`, `receive_modes`, `update_types_receive`, флаги приёма и групп, `access_token_length`, `translation_prefix_keys`, лимиты polling, `shares_platform_bot_token_pool`, `is_add_chat_available`, `allow_multiple_config_entries_same_token`, `max_attachments_per_message_limit` и т.д.
- Добавление типа в **`INTEGRATION_TYPES`** (порядок = порядок пунктов в первом шаге мастера).
- Запись в **`_BY_INTEGRATION_TYPE`** и **`_CAPABILITIES`**.

Подпись пункта выбора типа в мастере берётся из `config_flow_integration_type_choice_label()` (по умолчанию совпадает с `label`).

Экспериментальные хуки `register_capabilities` / `register_provider_label` **не** подключают полноценный провайдер к мастеру и `get_provider`; для нового типа правка реестра обязательна.

---

## 5. Тесты

- Юнит-тесты на `IntegrationCapabilities` и маршрутизацию (см. `tests/providers/notify_a161/test_capabilities.py`, `tests/test_config_flow_provider_routing.py`).
- Разбор входящих updates и граничные случаи `recipient_id` (в т.ч. группы при `supports_group_chats=False`).
- При сложной отправке — проверки извлечения `message_id` из ответа API, если это используется в сценариях.

Запуск: из корня репозитория `pytest` (при необходимости с тем же интерпретатором, что и для проекта).

---

## 6. Когда PR можно принять (критерии для ревью)

**Смысл раздела:** это чеклист для человека, который **проверяет ваш pull request**. Если все пункты выполнены, изменения обычно считают **готовыми к слиянию** в основную ветку.

- Новый тип интеграции добавлен в `const.py` и в реестр; в мастере настройки он появляется **автоматически** через реестр, без отдельных «специальных» правок в общем `config_flow` под одно имя провайдера (кроме уже существующих общих шагов мастера).
- Все заявленные возможности бэкенда перечислены в `IntegrationCapabilities`; общий код не должен вызывать функции, которые ваш API не поддерживает, **без предварительной проверки** capability.
- Нет зацикливания импортов; код вашего провайдера **не подключает** модули другого провайдера.
- Есть строки интерфейса на **английском и русском** для новых шагов и сообщений об ошибках; при необходимости согласованы подсказки с плейсхолдерами (`{provider_label}`, URL и т.п.) в `translations.py`.
- Написаны тесты, **`pytest` проходит без ошибок**.
- В описании PR кратко указано: что это за сервис, есть ли публичная документация API, какие есть ограничения (токен, группы, вложения). Язык описания — русский или английский.

---

## 7. Чеклист перед отправкой PR

- [ ] Заполнена [спецификация для оператора API](PROVIDER_SPEC.md) и приложена к PR или вынесена в документацию сервиса.
- [ ] `INTEGRATION_TYPE_*` + пакет `providers/<id>/` + `registry.py`.
- [ ] `capabilities.py` + регистрация в `_CAPABILITIES`.
- [ ] Валидация токена и ограничения мастера в классе провайдера.
- [ ] `translations/en.json`, `translations/ru.json` (и при необходимости `strings.json`).
- [ ] Тесты: capabilities, routing, updates при наличии приёма.
- [ ] `pytest` зелёный.

Спасибо за вклад в MaxNotify.
