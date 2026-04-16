# Добавление нового провайдера MaxNotify

Документ в двух частях: **что нужно от владельца/оператора бэкенда** (данные и требования к API) и **что сделать в коде** интеграции.

---

## 1. Для пользователя или владельца сервиса (что предоставить разработчику)

Чтобы подключить новый бэкенд к MaxNotify, нужно формально описать следующее.

### 1.1. Идентификация

| Вопрос | Зачем |
|--------|--------|
| Уникальный **строковый тип** интеграции (например `my_company_max`) | Пишется в `ConfigEntry.data["integration_type"]`, выбирается в мастере настройки. |
| **Человекочитаемое имя** (label) | Ошибки сервисов, плейсхолдер `{provider}` в переводах. |
| **Базовый URL** API (без лишнего слэша в конце, если иначе не оговорено) | Сборка путей `/messages`, `/uploads`, `/updates` и т.д. |
| **Версия API** (`v=` в query), если используется | Как у официального platform-api. |

### 1.2. Аутентификация

- Формат заголовка: сейчас везде **`Authorization: <token>`** (как приходит от Max / прокси).
- Как **проверить токен** при настройке (аналог `GET /me` или «достаточно непустой строки»).
- Срок жизни токена и процедура перевыпуска (для документации пользователю HA).

### 1.3. Исходящие сообщения (обязательный минимум)

Нужна спецификация для **каждой** поддерживаемой операции:

| Операция | Что описать |
|----------|-------------|
| Текст (без клавиатуры) | `POST` URL (query/body), поля JSON (`text`, `format`, …). |
| Текст + inline-клавиатура | Тот же endpoint или другой; формат `attachments` / `inline_keyboard`. |
| Фото / документ / видео | Двухшаговая схема: запрос URL загрузки → `POST` файла → тело сообщения с `token` / вложением. |
| Удаление / редактирование | `DELETE`/`PUT` (или аналог), как передаётся `message_id` (query vs body). |

Важно:

- Как кодируется **получатель**: `user_id`, `chat_id`, отрицательный id группы — и **несовместимости** (как у notify.a161: только ЛС по `user_id`, группы не поддерживаются).
- Максимальный **размер вложения** (если есть) — для проверки до загрузки и ключей перевода `third_party_*`.

### 1.4. Входящие обновления (приём)

Указать, что реально доступно:

| Режим | Требования к API |
|-------|-------------------|
| **Только отправка** | Ничего не нужно. |
| **Long polling** | `GET …/updates` (или ваш путь): параметры, таймаут, поле **marker** для продолжения, формат списка апдейтов. |
| **Очередной polling** | Периодический `GET` без long hold; интервал и лимиты. |
| **Webhook** | Только для совместимости с **официальной** моделью подписок Max, если бэкенд это эмулирует. |

Нужны **примеры JSON** ответа (хотя бы одно сообщение, один callback), чтобы нормализовать их в общий вид события `max_notify_received`.

### 1.5. Возможности (да/нет)

Явно перечислить поддержку:

- групповые чаты (отрицательный `chat_id`);
- `delete_message` / `edit_message`;
- `send_photo`, `send_document`, `send_video`;
- inline-кнопки;
- синхронизация slash-команд с бэкендом (как у официального API).

### 1.6. Ограничения и пулы токенов

- Несколько записей MaxNotify с **одним и тем же токеном** и конфликт режимов приёма (webhook vs polling): для официального API это учитывается через `shares_platform_bot_token_pool` и связанные проверки **внутри провайдера** (`iter_config_entries_sharing_token`, хелперы при отправке форм опций).
- Любые **ограничения мастера настройки** (например «нельзя создать вторую запись с тем же токеном») описываются и проверяются **только в классе провайдера** (методы вроде `config_flow_new_entry_token_error_key`, при необходимости `duplicate_config_entry_for_same_token` / `allow_multiple_config_entries_same_token`), а не в общем `config_flow.py`. Общий код лишь вызывает эти методы.

---

## 2. Для разработчика интеграции (как добавить код)

Ориентир — существующие пакеты `custom_components/max_notify/providers/official/` и `providers/notify_a161/`.

### 2.1. Константы типа

1. В `custom_components/max_notify/const.py` добавить, например:  
   `INTEGRATION_TYPE_MY = "my_company_max"`.

### 2.2. Каталог провайдера

Создать пакет `providers/my_company/` (имя на ваше усмотрение), минимально:

| Файл | Назначение |
|------|------------|
| `const.py` | `API_BASE_URL`, `API_VERSION`, `RECEIVE_MODES`, `UPDATE_TYPES_RECEIVE`, при необходимости `TITLE_FALLBACK_SUBSTRINGS` для миграций старых записей по заголовку. |
| `capabilities.py` | Экземпляр `IntegrationCapabilities`: только флаги API и `max_client_upload_bytes`. Префикс переводов — свойство ``translation_prefix`` провайдера (`{integration_type}_`, если задан ``translation_prefix_keys`` в `registry.py`), список ключей — там же. |
| `integration_provider.py` | Класс, наследник `MaxNotifyIntegrationProvider`, с переопределением нужных методов (см. `providers/base.py`). |
| `api.py` | `validate_token`, при необходимости `sync_bot_commands`. |
| `notify.py` (или эквивалент) | Сборка URL для `POST /messages`, `DELETE`/`PUT`, `POST /uploads`, проверка ответа загрузки, сборка JSON тела для медиа/видео, при необходимости pace lock. |
| `updates.py` | `extract_updates_from_payload` — из сырого JSON в список нормализованных update-диктов для `updates.py` интеграции. |
| `config_setup.py` / `options_flow.py` | Шаги мастера и опций; делегирование из `async_config_setup_step` / `async_options_flow_step`. |

Методы провайдера с пустой реализацией в базе, которые чаще всего трогают сторонние API:

- **`config_flow_integration_type_choice_label`** → подпись пункта в **первом шаге мастера** (выбор типа интеграции). По умолчанию совпадает с `label`; переопределите, если в списке нужна другая формулировка, чем в остальном UI.
- **`config_flow_new_entry_token_error_key(hass, token)`** → перед `async_create_entry` в мастере: вернуть **суффикс** ключа ошибки для `prefixed_error_key` (например `duplicate_token_not_allowed`) или `None`, если токен допустим. Вся политика «один токен — одна запись» / «несколько записей разрешены» живёт здесь и в `iter_config_entries_sharing_token`, а не в корневом `config_flow`.
- `shares_platform_bot_token_pool` → `True`, если запись участвует в общем пуле токена платформы Max (конфликты webhook/polling с другими такими же записями).
- `async_resolve_message_post_url` — URL (и при необходимости query/body) для `POST /messages`; по умолчанию через `resolve_simple_message_post_url` без `GET /chats`.
- `options_init_step_id` / `options_use_compact_receive_mode_init_branch` / `should_restore_polling_after_opt_add_button` — различия UI опций между провайдерами.
- `resolve_simple_message_post_url` — если нет отдельного разрешения чата через `GET /chats`.
- `build_delete_message_url` / `build_edit_message_url` / `build_upload_url`.
- `build_media_message_payload` / `build_video_message_payload`.
- `upload_step2_response_ok`.
- `async_run_with_send_pace_lock` — если нужна пауза между отправками.
- `extract_updates_from_poll_json`, `build_updates_poll_params`, `should_persist_updates_marker`, `read_updates_marker_from_poll_response`, `updates_poll_uses_request_pacing`, … — по фактическому режиму приёма.

**Важно:** избегать циклических импортов: тяжёлые модули (config flow) часто импортируются лениво внутри `async_config_setup_step` / `async_options_flow_step`, как у текущих провайдеров.

### 2.3. Реестр

В `providers/registry.py`:

1. Импортировать новый провайдер и константы.
2. Создать экземпляр `MyIntegrationProvider(...)` с заполнением полей конструктора `MaxNotifyIntegrationProvider` (`integration_type`, `label`, `api_base_url`, `api_version`, `receive_modes`, `update_types_receive`, `title_fallback_substrings`, лимиты polling, `shares_platform_bot_token_pool`, `access_token_length`, `is_add_chat_available`, при необходимости `translation_prefix_keys` — тогда префикс переводов будет ``{integration_type}_`` только для перечисленных шагов/ключей ошибок).
3. Добавить тип в кортеж **`INTEGRATION_TYPES`** (порядок = порядок в UI).
4. Зарегистрировать в **`_BY_INTEGRATION_TYPE`** и **`_CAPABILITIES`** (и при необходимости в **`_PROVIDER_LABELS`**).
5. **`get_provider`**: сейчас первым проверяется `NOTIFY_A161_PROVIDER.matches_entry`. Для нового стороннего провайдера с **эвристикой по заголовку** добавьте аналогичную проверку **до** общего `entry.data["integration_type"]`, либо полагайтесь только на явный `integration_type` в `data` (предпочтительно для новых записей).

### 2.4. Мастер настройки и переводы

1. **Первый шаг (тип интеграции):** подписи пунктов списка берутся из **`config_flow_integration_type_choice_label()`** провайдера (по умолчанию — поле `label` в `registry.py`). В `config_flow.py` нет веток `if integration_type == …` для подписей; при добавлении третьего провайдера достаточно зарегистрировать его и при необходимости переопределить этот метод.
2. **Плейсхолдеры форм** (`{provider_label}`, `{provider_site_url}` и т.д.): общий модуль `translations.py` — `provider_step_placeholders` / `merge_description_placeholders`; значения приходят из полей провайдера (`label`, `api_base_url`).
3. В `translations/en.json`, `translations/ru.json` и при необходимости `strings.json`: строки для **своих** шагов `config.step.<префикс>_*` / `options.step.<префикс>_*` (если задан `translation_prefix_keys` в реестре — префикс `{integration_type}_`). Обновите описание шага `integration_type`, если нужен другой общий текст подсказки (без перечисления имён провайдеров вручную).
4. Мастер в корне вызывает только **`async_config_setup_step`** / **`async_options_flow_step`** у выбранного провайдера; сценарии шагов — в `config_setup.py` / `options_flow.py` пакета провайдера.

### 2.5. Официальный провайдер и чужие записи

`OfficialIntegrationProvider.iter_config_entries_sharing_token` пропускает записи, совпадающие с `entry_matches_notify_a161`. При новом стороннем типе с тем же механизмом токена убедитесь, что такие записи **не попадают** в пул «официального» токена (добавьте проверку `matches_stored_type_only` / `get_provider(e).shares_platform_bot_token_pool` там, где считаются конфликты webhook/polling).

### 2.6. Тесты

- Юнит-тесты на нормализацию `updates` (как `tests/providers/notify_a161/`).
- При необходимости — на разбор `message_id` из ответов API отправки.

### 2.7. Расширение без правки реестра (эксперименты)

В коде есть хуки:

- `register_capabilities(integration_type, caps)`
- `register_provider_label(integration_type, label)`

Они **не** подставляют полноценный провайдер в `get_provider` / мастер настройки. Для полной поддержки нового типа правки **`registry.py`** и **`INTEGRATION_TYPES`** всё равно необходимы.

---

## 3. Краткий чеклист разработчика

- [ ] `const.py`: `INTEGRATION_TYPE_*`
- [ ] `providers/<id>/`: capabilities, integration_provider, api, notify, updates, config/options flows
- [ ] `registry.py`: экземпляр (`label`, …), `INTEGRATION_TYPES`, `_BY_INTEGRATION_TYPE`, `_CAPABILITIES`
- [ ] `get_provider`: при необходимости отдельная ветка до общего словаря
- [ ] Ограничения мастера и токена: `config_flow_new_entry_token_error_key` / `iter_config_entries_sharing_token` в провайдере, без дублирования в `config_flow.py`
- [ ] Переводы: общий шаг `integration_type` + свои шаги с префиксом типа; плейсхолдеры `{provider_label}` / URL из провайдера
- [ ] Исключить смешение токенов с official в `iter_config_entries_sharing_token` / helpers
- [ ] `pytest`

После этого пользователи смогут выбрать новый тип в первом шаге настройки MaxNotify и пройти ваш сценарий мастера.
