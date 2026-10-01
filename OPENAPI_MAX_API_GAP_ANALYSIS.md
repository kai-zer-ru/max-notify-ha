# Анализ OpenAPI Max Bot API vs MaxNotify

Дата: 2026-09-29  
Источник: [max-messenger/api-schema](https://github.com/max-messenger/api-schema) (`schema.yaml`, `info.version: 0.0.33`)  
Документация рядом: [dev.max.ru/docs-api](https://dev.max.ru/docs-api), README репозитория схемы  

Статус: **только анализ**, правок кода нет. Файл локальный — **не коммитить**.

Область сравнения: в первую очередь провайдер **official** (`platform-api2.max.ru`). Провайдер **notify.a161** — отдельный HTTP/WS-бэкенд; совпадения путей (`/messages`, `/uploads`) не означают полное совпадение контракта со схемой Max.

---

## Краткий вердикт

Интеграция уже закрывает ядро сценария HA: отправка/правка/удаление сообщений, фото/документ/видео, inline-кнопки (callback/message/link), webhook и long polling, slash-команды бота (`PATCH /me/commands`), приём `message_created` / `message_callback`.

Расхождения с официальной OpenAPI:

1. **Устаревшие или внесхемные детали** (query `v=…`, диапазон `from`/`to` вместо `after`/`before`, узкий набор `update_types`).
2. **Неиспользуемые возможности API**, полезные для HA (ответ на callback, reply/forward, действия «печатает», pin, комментарии к постам, доп. типы кнопок и вложений, события жизненного цикла бота/чата).
3. **Риски контракта** (файл + клавиатура в одном сообщении; `format: text` у нас локальный — в схему не уходит, это ок).

---

## Что у нас уже совпадает со схемой

| Область | Схема | У нас |
|--------|--------|--------|
| Базовый хост | `https://platform-api2.max.ru/` | `API_BASE_URL = https://platform-api2.max.ru` |
| Авторизация | заголовок `Authorization: <token>` без `Bearer` | так и есть |
| `GET /me` | информация о боте | проверка токена |
| `PATCH /me/commands` | до 32 команд | sync из options |
| `POST/PUT/DELETE /messages` | send / edit / delete | сервисы send/edit/delete |
| Получатель | `user_id` или `chat_id` в query | `recipient_id > 0` → user, `< 0` → chat |
| Тело сообщения | `text`, `attachments`, `notify`, `format` | собираем в `message_payload_builders` / outbound |
| `format` в API | только `markdown` \| `html` | при «plain text» поле не шлём |
| Inline keyboard | attachment `type: inline_keyboard` | да |
| Кнопки | `callback`, `message`, `link` (+ ещё типы) | эти три в UI и сервисах |
| `POST /uploads?type=` | `image`, `video`, `audio`, `file` | image / video / file |
| Webhook | `POST/GET/DELETE /subscriptions`, secret `X-Max-Bot-Api-Secret` | official webhook_api |
| Long poll | `GET /updates` (`limit`, `timeout`, `marker`, `types`) | updates_service |
| Список чатов | **нет** `GET /chats` (только `/chats/{chatId}/…`) | код уже не опирается на список чатов (с июня 2026) |

---

## 1. Что не так / устарело / рискованно относительно схемы

### 1.1. Query-параметр `v=1.2.5` отсутствует в OpenAPI

Мы добавляем `v={API_VERSION}` почти ко всем URL official (`/me`, `/me/commands`, `/messages`, `/uploads`, GET сообщений).

В `schema.yaml` **нет** параметра `v` ни у одного метода. Версия схемы — `info.version: 0.0.33`, не `1.2.5`.

**Вывод:** либо сервер ещё принимает `v` для совместимости (игнорирует), либо это наследие старых доков. Нужна проверка на живом API; при отсутствии эффекта — убрать из URL, чтобы не путать с версией OpenAPI.

### 1.2. `GET /messages`: deprecated `from`/`to` вместо `after`/`before`

**Статус (2026-09-29): исправлено.** `list_message_ids_in_period` шлёт `after` / `before` в хронологическом порядке (`after=ts_from`, `before=ts_to`), без reverse-swap deprecated `from`/`to`.

Схема:

- `from`, `to` — **deprecated**, в описании прямо: use `after` / `before`;
- для старых `from`/`to`: сообщения в обратном порядке, при обоих параметрах **`to` должен быть меньше `from`**;
- актуальные: `after`, `before`, `count` (1–100, default 50).

### 1.3. Подписка на обновления слишком узкая

Official подписывается только на:

```text
message_created, message_callback
```

В схеме `Update.update_type` также:

| Тип | Смысл (кратко) |
|-----|----------------|
| `message_edited` | сообщение изменено |
| `message_removed` | сообщение удалено |
| `bot_started` / `bot_stopped` | Start / остановка диалога (+ deep-link `payload` у started) |
| `bot_added` / `bot_removed` | бота добавили/удалили из чата |
| `user_added` / `user_removed` | участник (нужны права админа) |
| `chat_title_changed` | сменили название |
| `dialog_cleared` / `dialog_removed` / `dialog_muted` / `dialog_unmuted` | диалог |
| `comment_created` / `comment_edited` / `comment_removed` | комментарии к посту |
| `bot_admin_permissions_changed` | права бота-админа |

Сейчас эти события **не заказываются** ни в webhook (`update_types`), ни (по умолчанию) в long poll `types` — даже если платформа когда-то шлёт лишнее, интеграция их почти не нормализует в `max_notify_received` (логика заточена под created/callback + локальный `slash_command`).

### 1.4. `slash_command` — не тип API

`UPDATE_SLASH_COMMAND = "slash_command"` — **наша** переразметка `message_created` с текстом `/…` для автоматизаций HA. В OpenAPI такого `update_type` нет. Это не баг API, но важно не путать с контрактом Max при документации и отладке.

### 1.5. Документ (`type: file`) + клавиатура в одном сообщении

**Статус (2026-09-29): исправлено.** `send_document` отклоняет непустую inline-клавиатуру (`service_send_document_no_inline_keyboard`); по умолчанию `send_keyboard: false`.

Схема: `FileAttachmentRequest` — **«MUST be the only attachment in message»**.  
То же для `audio`, `sticker`, `contact` (для них проверки ещё нет).

### 1.6. `disable_link_preview` не используем + странное описание в схеме

`POST /messages` и `POST /answers` имеют query `disable_link_preview`.

- У `/answers` текст логичный: *If **true**, server will not generate preview…*
- У `/messages` в схеме написано: *If **false**, server will not generate…* при `default: false` — похоже на **ошибку в OpenAPI**, а не на реальное поведение.

Мы параметр нигде не передаём → превью ссылок всегда по умолчанию сервера.

### 1.7. Long polling vs рекомендация платформы

README схемы и описание `GET /updates`: long polling **не для production**, для продакшена — webhook; одновременно webhook и long poll нельзя.

У нас long polling остаётся опцией режима приёма. Для HA это осознанный компромисс (нет публичного HTTPS), но расходится с официальной рекомендацией. Также: **с 25 мая 2026** — отказ от webhook по HTTP и самоподписных сертификатов (мы уже требуем `https://` при регистрации).

### 1.8. Лимиты upload из схемы vs наш единый потолок

Схема (multipart):

| type | Лимит (из описания `/uploads`) |
|------|--------------------------------|
| image | до 50 MB и ≤ 7680×7680; форматы JPG/PNG/GIF/TIFF/BMP/HEIC |
| video | до 250 MB; MP4/MOV/MKV/WEBM |
| audio | до 256 MB **или** ≤ 60 мин |
| file | до 4 GB |

У official `OFFICIAL_MAX_UPLOAD_BYTES = 4 GiB` на всё — ближе к лимиту **file**, чем к image/video. Клиентская проверка может пропускать файлы, которые сервер отклонит раньше (50/250 MB).

`type=photo` в схеме помечен как больше не поддерживаемый → `type=image`. У нас уже `image` — ок.

### 1.9. Мелочи UI / валидации vs схема

| Тема | Схема | У нас |
|------|--------|--------|
| Текст кнопки | 1–128 символов | не жёстко валидируем длину |
| Callback payload | max 1024, required | payload опционален в UI (пустой callback может уйти) |
| Link URL | string ≤ 2048 | только `http`/`https` (строже схемы — ок для HA) |
| Текст сообщения | maxLength 4000 | `MAX_MESSAGE_LENGTH = 4000` — ок |
| Команды бота | name 1–64, description ≤ 128, max 32 | лимит 32 есть; длины name/description стоит сверить |

### 1.10. Что выглядит согласованным (не баг)

- Порядок получателя user_id / chat_id.
- Токен без Bearer.
- `notify: false` в теле.
- Отсутствие `GET /chats` (списка) — схема подтверждает.
- Нормализация `message.body.mid` / sender для удаления последнего исходящего в группах.

---

## 2. Что можно ещё использовать (не реализовано)

Приоритет с точки зрения сценариев Home Assistant (субъективно).

### Высокий приоритет для HA

#### 2.1. `POST /answers` — ответ на нажатие callback

Сейчас при `message_callback` мы только шлём событие HA. Схема требует/ожидает ответ бота:

- query: `callback_id` (из `update.callback.callback_id`);
- body: `CallbackAnswer` — либо `notification` (тост пользователю), либо `message` (`NewMessageBody` — правка текущего сообщения), либо оба.

**Зачем:** закрыть «крутилку» у кнопки, показать «Принято», заменить клавиатуру/текст сообщения без отдельного `edit_message` с ручным `message_id`.

Сервис вида `max_notify.answer_callback` с полями `callback_id`, `notification`, опционально новый текст/кнопки.

#### 2.2. Поле `link` в `NewMessageBody` — reply / forward

```json
"link": { "type": "reply" | "forward", "mid": "<message_id>" }
```

**Зачем:** автоответы в тред ответа на входящее `message_id` из `max_notify_received`; пересылка уведомлений.

#### 2.3. `POST /chats/{chatId}/actions` — typing / mark_seen / sending_*

`SenderAction`: `typing_on`, `sending_photo`, `sending_video`, `sending_audio`, `sending_file`, `mark_seen`.

**Зачем:** перед долгой выгрузкой видео/фото показать «бот печатает / отправляет файл»; `mark_seen` для диалогов.

#### 2.4. Расширить принимаемые `update_types`

Минимум полезного для автоматизаций:

- `bot_started` (+ deep-link `payload`) — онбординг, привязка пользователя;
- `message_edited` / `message_removed` — синхронизация состояния;
- `bot_added` / `bot_removed` / `bot_stopped` — жизненный цикл чата;
- `chat_title_changed` — обновить friendly name в HA.

Нужна доработка нормализации в `updates_service` и подписки webhook/long poll.

#### 2.5. Типы кнопок из схемы, которых нет в UI

| type | Назначение |
|------|------------|
| `request_contact` | запрос контакта пользователя |
| `request_geo_location` | геолокация (`quick`: без подтверждения) |
| `open_app` | мини-приложение (`web_app`, опц. `contact_id` / `payload`) |
| `clipboard` | копировать `payload` в буфер |

В коде уже есть намёк: `_INLINE_KEYBOARD_SPECIAL_ROW_TYPES` включает `open_app`, `request_geo_location`, `request_contact` для лимита кнопок в ряду, но мастер опций и `_normalize_buttons_for_api` пропускают только callback/message/link (остальное схлопывается в callback).

### Средний приоритет

#### 2.6. Фото по URL без своей загрузки

`PhotoAttachmentRequestPayload`: взаимоисключающие `url` | `token` | `photos`.

Сейчас URL мы скачиваем сами и грузим через `/uploads`. Можно слать `{"type":"image","payload":{"url":"https://…"}}` — меньше трафика HA, но зависимость от доступности URL для серверов Max.

#### 2.7. Вложение `share` (превью ссылки)

`ShareAttachmentRequest` / `ShareAttachmentPayload` (`url` или `token`) — явный превью-блок URL, отдельно от текста.

#### 2.8. Вложение `location`

`latitude` + `longitude` на уровне attachment (не только кнопка request_geo).

#### 2.9. Аудио: `POST /uploads?type=audio` + attachment `audio`

Сейчас нет `send_audio`. Лимиты и форматы — в описании uploads. Как и file: **единственное** вложение в сообщении (без keyboard?).

#### 2.10. Стикер: `sticker` + `payload.code`

Нишевый сценарий.

#### 2.11. Pin / unpin / get pin

- `PUT/DELETE/GET /chats/{chatId}/pin`
- тело pin: `message_id`, опц. `notify`

Полезно для каналов/групп «важное объявление».

#### 2.12. `GET /messages/{messageId}`

Одно сообщение по id — проверка существования, разбор вложений, URL публичного поста (`message.url`).

#### 2.13. Комментарии к постам канала

- `GET/POST/PUT/DELETE …/messages/{messageId}/comments`
- `GET …/comments/{commentId}`
- Updates: `comment_*`
- Тело комментария **без attachments** (`NewCommentBody`)

Имеет смысл, если бот — админ канала с нужными правами.

#### 2.14. Управление чатом / участниками

Всё под `/chats/{chatId}/…`:

- `GET` / `PATCH` чата (title, description, icon, pin через patch);
- members: list / add / remove;
- admins: get / post / delete;
- `GET/DELETE …/members/me` (membership / leave).

Для типичного notify-ботa HA — вторично; для «умного» модератора — да.

#### 2.15. `GET /videos/{videoToken}`

Детали видео после upload/отправки (playback URLs). Может помочь диагностике `attachment.not.ready`, но не обязателен для отправки.

### Низкий / инфраструктурный приоритет

#### 2.16. Resumable upload

Схема описывает upload не только multipart, но и resumable через `Content-Range` и GET статуса на upload URL. Для больших file/video через нестабильную сеть — ценность есть; реализация заметно сложнее текущего multipart.

#### 2.17. Синхронизация схемы как артефакта

Имеет смысл периодически (CI или ручной чеклист) сверять `schema.yaml` с:

- списком путей, которые дергает official;
- enum `UploadType`, `TextFormat`, `MessageLinkType`, discriminator `Update` / `Button` / `AttachmentRequest`.

Генерировать клиент из OpenAPI в HA **не** обязательно (и противоречит «пустой requirements»), но схема — хороший контрактный эталон.

---

## 3. Карта покрытия эндпоинтов (official)

| Метод | Путь | Статус у нас |
|-------|------|--------------|
| GET | `/me` | используется |
| PATCH | `/me/commands` | используется |
| GET | `/chats/{chatId}` | нет |
| PATCH | `/chats/{chatId}` | нет |
| POST | `/chats/{chatId}/actions` | нет |
| GET/PUT/DELETE | `/chats/{chatId}/pin` | нет |
| GET/DELETE | `/chats/{chatId}/members/me` | нет |
| GET/POST | `/chats/{chatId}/members/admins` | нет |
| DELETE | `/chats/{chatId}/members/admins/{userId}` | нет |
| GET/POST/DELETE | `/chats/{chatId}/members` | нет |
| GET/POST/DELETE | `/subscriptions` | используется |
| POST | `/uploads` | используется (image/video/file; не audio) |
| GET/POST/PUT/DELETE | `/messages` | используется |
| GET | `/messages/{messageId}` | нет |
| * | `/messages/{messageId}/comments…` | нет |
| GET | `/videos/{videoToken}` | нет |
| POST | `/answers` | нет |
| GET | `/updates` | используется |

---

## 4. Поля исходящего сообщения: покрытие `NewMessageBody`

| Поле | Используем |
|------|------------|
| `text` | да |
| `attachments` (image/video/file + inline_keyboard) | да |
| `attachments` (audio/sticker/contact/location/share) | нет |
| `link` (reply/forward) | нет |
| `notify` | да |
| `format` (`markdown`/`html`) | да (plain = не слать) |

Query при отправке:

| Параметр | Используем |
|----------|------------|
| `user_id` / `chat_id` | да |
| `disable_link_preview` | нет |
| `v` | да, но **вне схемы** |

---

## 5. Рекомендуемый порядок работ (когда решите править код)

Не делается в рамках этого документа; ориентир:

1. Проверить на живом API: поведение `disable_link_preview`; file+keyboard. (`v=` и `after`/`before` для периода — уже поправлены в коде.)
2. `POST /answers` + прокинуть `callback_id` в `max_notify_received` (если ещё не везде удобно брать из raw).
3. `link.reply` / `link.forward` в send/edit.
4. Расширить `update_types` + нормализацию (`bot_started` минимум).
5. `sendAction` (typing) перед тяжёлыми upload.
6. Кнопки `clipboard` / `request_*` / `open_app` по запросу пользователей.
7. Комментарии / pin / audio — по реальному спросу.

---

## 6. Источники

- OpenAPI: https://github.com/max-messenger/api-schema/blob/main/schema.yaml  
- Обзор API / генераторы / auth / base URL: https://github.com/max-messenger/api-schema  
- Человекочитаемые методы: https://dev.max.ru/docs-api  
- Код сверки: `custom_components/max_notify/providers/official/*`, `notify_outbound.py`, `message_payload_builders.py`, `webhook_api.py`, `updates_service.py`, `const.py`

---

*Конец анализа.*
