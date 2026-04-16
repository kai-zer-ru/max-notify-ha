<p align="center">
  <img src=".images/logo.png" alt="MaxNotify" width="480">
</p>

<a id="readme-top"></a>

# MaxNotify — интеграция с мессенджером Max для Home Assistant

Отправка и приём сообщений в мессенджере **Max** через официальный API (platform-api.max.ru).

<a id="содержание"></a>

## Содержание

- [Присоединяйтесь к сообществу](#community)
- [Важная информация](#important)
  - [Поддержка `notify.a161.ru`](#notify-a161)
- [Возможности](#features)
- [Требования](#requirements)
- [Установка](#install)
  - [Через HACS](#install-hacs)
  - [Вручную (без HACS)](#install-manual)
- [Настройка](#configure)
  - [Официальный API](#configure-official)
  - [Сервис `notify.a161.ru`](#configure-a161)
- [Приём сообщений](#receiving)
  - [WebHook и HTTPS](#webhook-https)
  - [Данные события](#event-data)
  - [Групповые чаты](#group-chats)
  - [Пример: ответ в тот же чат](#example-reply)
  - [Пример: нажатие кнопки](#example-button)
- [Кнопки клавиатуры](#keyboard)
- [Сервисы](#services)
  - [`max_notify.send_message`](#service-send-message)
  - [`max_notify.send_photo`](#service-send-photo)
  - [`max_notify.send_document`](#service-send-document)
  - [`max_notify.send_video`](#service-send-video)
  - [`max_notify.delete_message`](#service-delete-message)
  - [`max_notify.edit_message`](#service-edit-message)
- [Включение режима отладки](#debug)
- [Документация для разработчиков: новый провайдер](docs/PROVIDERS.md)
- [Токен и ID](#token-ids)
- [Ссылки](#links)


[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub](https://img.shields.io/badge/GitHub-kai--zer--ru%2Fmax--notify--ha-blue?logo=github)](https://github.com/kai-zer-ru/max-notify-ha)
[![Donate](https://img.shields.io/badge/donate-Tinkoff-FFDD2D.svg)](https://www.tbank.ru/rm/r_wKLcbFgjYa.ncgWMwrHSA/vyQvd5941/)
---

<a id="community"></a>

# 📣 Присоединяйтесь к сообществу

Следите за новостями, обновлениями и получайте помощь:

- **Канал в Telegram** — [@kai_zer_ru_ha](https://t.me/kai_zer_ru_ha)  
  
- **Канал в Max** — [kai_zer_ru_ha](https://max.ru/id251603503331_biz)

- **Канал в Dzen** - [kai_zer_ru](https://dzen.ru/kai_zer_ru)

[↑ Наверх](#readme-top)

---

<a id="important"></a>

# ⚠️ Важная информация

В данный момент регистрация на платформе разработчиков MAX доступна только индивидуальным предпринимателям и организациям. То есть юридическим лицам. Это ограничение самой платформы. К интеграции это отношения не имеет. Надеемся, что в ближайшем будущем эту процедуру упростят.

[↑ Наверх](#readme-top)

---

<a id="notify-a161"></a>

### 🔗 Поддержка `notify.a161.ru` (важно)

Интеграция поддерживает режим через прокси **`https://notify.a161.ru/`** и бота `https://max.ru/id6162049515_1_bot` — отправка и (опционально) приём в Home Assistant теми же сущностями и сервисами, что и для официального API, с учётом ограничений ниже.

**Дисклеймер:**
- Автор этой интеграции **не несёт ответственности** за работу сервиса `notify.a161.ru` и бота `@id6162049515_1_bot`.
- Подключение и использование этого режима выполняется **на ваш страх и риск**.

**Технические особенности режима `notify.a161.ru`:**
- Доступны **те же сценарии**, что и для официального API, в рамках [возможностей прокси](https://notify.a161.ru/): текст (`send_message`), вложения (`send_photo`, `send_document`, `send_video`), **inline-кнопки** (`send_keyboard`, `buttons`, клавиатура в настройках), **удаление и правка** (`delete_message`, `edit_message`). Ограничения и ответы API определяет сторона сервиса.
- На стороне интеграции перед загрузкой проверяется размер файлов: **до 10 МБ** для фото, документов и видео (при превышении в HA будет ошибка).
- `user_id` привязан к токену и задаётся **один раз** при первой настройке записи (другой получатель — отдельная интеграция MaxNotify).
- **Приём сообщений** — только режим **опроса (Polling)** очереди `notify.a161.ru` (событие **`max_notify_received`**, как у Long Polling у официального API). Режима **WebHook** у этого прокси нет.
- **Политика сервиса (автопереключение на «Только отправка»):** если выбран Polling, интеграция хранит выбранный период **1–3 суток** (по умолчанию **3**). Если за этот период **не было ни входящих обновлений, ни успешной отправки сообщения с кнопками**, режим приёма переключается на **«Только отправка»** (уведомление в HA). Чтобы снова получать события, включите Polling в настройках записи.
- При успешных исходящих запросах к одной записи выдерживается пауза **1 с** между отправками.
- Ответ сервиса иногда приходит **пустым телом** HTTP (без JSON и без `message_id`) — это нормально для части вызовов.
- При включённом приёме (не «Только отправка») создаётся сенсор **идентификатора последнего входящего сообщения** так же, как у официального API.

[↑ Наверх](#readme-top)

---

<a id="features"></a>

## ✨ Возможности

- **Отправка:** текст, фото, документы, видео в чаты Max (сервисы и сущности `notify`).
- **Приём:** входящие сообщения и нажатия inline-кнопок → событие `max_notify_received` для автоматизаций.
- **Кнопки:** настройка клавиатуры в интеграции, отправка сообщений с кнопками, реакция на нажатия по `callback_data`.
- Настройка через UI, без правки YAML (кроме автоматизаций).

Для `notify.a161.ru` доступны **те же сервисы и приём через Polling**, что и в общем списке, с ограничениями прокси и **автопереключением на «Только отправка»** при длительной неактивности (см. [блок про `notify.a161.ru`](#notify-a161)). Отличия официального API: групповые чаты, WebHook, Long Polling к `platform-api.max.ru` — только у записи с токеном Max для разработчиков.

[↑ Наверх](#readme-top)

---

<a id="requirements"></a>

## 📋 Требования

- Home Assistant (актуальная версия).
- Бот в Max и **токен** из раздела [Интеграция](https://business.max.ru/self/#/chat-bots) платформы Max для разработчиков, либо `user_id` и токен, выданные сервисным ботом `@id6162049515_1_bot` для режима `notify.a161.ru`.

[↑ Наверх](#readme-top)

---

<a id="install"></a>

## 🔧 Установка

<a id="install-hacs"></a>

### Через HACS

[![Открыть в Home Assistant и установить MaxNotify через HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kai-zer-ru&repository=max-notify-ha&category=integration)

Если кнопка не открывается (не настроен [My Home Assistant](https://www.home-assistant.io/integrations/my/) и т.п.): **HACS** → **Интеграции** → ⋮ → **Добавить репозиторий** → вставьте `https://github.com/kai-zer-ru/max-notify-ha`, категория **Интеграция**. Установите **MaxNotify** и перезапустите Home Assistant.

<a id="install-manual"></a>

### Вручную (без HACS)

Скопируйте папку `custom_components/max_notify` в `config/custom_components/` и перезапустите HA.

После установки добавьте интеграцию: **Настройки** → **Устройства и службы** → **Добавить интеграцию** → **MaxNotify**.

[↑ Наверх](#readme-top)

---

<a id="configure"></a>

## ⚙️ Настройка

<a id="configure-official"></a>

### 1) 🌐 Официальный API (`platform-api.max.ru`)

1. **Тип интеграции** — выберите «Official Max API (platform-api.max.ru)».
2. **Токен** — вставьте токен доступа бота (раздел «Интеграция» на [business.max.ru](https://business.max.ru/)). Интеграция проверит его через API.
3. **Формат сообщений** — Текст, Markdown или HTML (параметр `format` в [API сообщений](https://dev.max.ru/docs-api/methods/POST/messages)).
4. **Режим приёма** — только отправка, Long Polling или WebHook (см. раздел «Приём сообщений» ниже).
5. При Polling/WebHook: при необходимости укажите **секрет WebHook**, затем настройте **кнопки клавиатуры** (добавить/редактировать/удалить).
6. **Добавить чат** — один ID получателя: **положительный** = личный чат (User ID), **отрицательный** = группа (Chat ID).

Дополнительные чаты: страница интеграции → ⋮ → **Добавить чат**. Изменить токен или формат: **шестерёнка** или ⋮ → **Перенастроить** (токен можно оставить пустым).

После сохранения появятся сущности `notify.max_...` и сервисы `max_notify.send_message`, `send_photo`, `send_document`, `send_video`.

[↑ Наверх](#readme-top)

<a id="configure-a161"></a>

### 2) 🚪 Сервис `notify.a161.ru`

1. **Тип интеграции** — пункт с прокси `notify.a161.ru` в мастере добавления.
2. Перейдите на [notify.a161.ru](https://notify.a161.ru/) и получите у бота **`user_id`** и **токен** (`36` символов).
3. Введите токен, **формат сообщений** (текст / Markdown / HTML) и **режим приёма**: «Только отправка» или **Polling** (опрос очереди входящих обновлений прокси).
4. Если выбран **Polling:** задайте **интервал опроса** `/updates` (секунды), затем **период неактивности 1–3 суток** (по умолчанию 3): по истечении этого срока без **входящих** сообщений и без **исходящих с кнопками** интеграция переключит приём на «Только отправка» — см. [важный блок выше](#notify-a161). Далее настройте **кнопки клавиатуры** (по желанию).
5. Укажите **положительный** `recipient_id` (`user_id`). Он привязан к токену и **не меняется** через настройки; другой получатель — новая запись MaxNotify.

**Шестерёнка / настройки** записи: формат сообщений, режим приёма, при Polling — интервал опроса, период неактивности и клавиатура. Токен можно сменить через **Перенастроить** (⋮). Чтобы сменить `user_id`, удалите запись и создайте заново.

Сервисы Home Assistant те же, что для официального API: `send_message`, `send_photo`, `send_document`, `send_video`, `delete_message`, `edit_message` — в границах [сервиса](https://notify.a161.ru/) и с учётом лимитов интеграции (см. [выше](#notify-a161)).

[↑ Наверх](#readme-top)

---

<a id="receiving"></a>

## 📥 Приём сообщений

Интеграция генерирует событие **`max_notify_received`** при включённом приёме (не режим «Только отправка»).

- **Официальный API** (`platform-api.max.ru`): приём через **Long Polling** или **WebHook** — см. ниже.
- **`notify.a161.ru`:** приём только через **Polling** очереди прокси (то же событие `max_notify_received`). WebHook для этой записи не используется. Подробности и правило автопереключения на «Только отправка» — в [блоке про `notify.a161.ru`](#notify-a161).

### Официальный API: режимы приёма

При режиме **Long Polling** или **WebHook** интеграция получает обновления от Max и публикует **`max_notify_received`**.

**Режимы:**
- **Только отправка** — приём отключён.
- **Long Polling** — опрос API Max, доступ из интернета к HA не нужен.
- **WebHook** — Max шлёт запросы на URL вашего Home Assistant по **HTTPS**. Нужен **внешний** URL инстанса (не локальный `http://192.168…`), иначе регистрация вебхука в Max не выполнится. Задайте его в **Настройки → Система → Сеть** — см. [официальную документацию Home Assistant про URL инстанса](https://www.home-assistant.io/docs/configuration/basic/). Подойдут Nabu Casa, reverse proxy с TLS или другой публичный HTTPS-адрес. В карточке интеграции показывается итоговый URL вебхука; опционально задаётся секрет (заголовок `X-Max-Bot-Api-Secret`).

[↑ Наверх](#readme-top)

<a id="webhook-https"></a>

#### WebHook и HTTPS: как это устроено

- **Почему важен именно внешний адрес.** Серверы Max должны достучаться до вашего Home Assistant из интернета. Одного «локального» HTTPS в поле **Внутренний URL** недостаточно: интеграция ориентируется на то, можно ли собрать **внешний** HTTPS-адрес для вебхука (как при регистрации в Max). Если вы отключили HTTPS на reverse proxy или сменили схему доступа, **обновите и поля в разделе «Сеть»** — иначе в конфиге может остаться старый `https://…`, и Home Assistant будет считать, что всё в порядке.

- **Что происходит, если HTTPS для вебхука больше недоступен** (например убрали сертификат, сменили URL, не задан внешний HTTPS): при **каждой загрузке** интеграции интеграция проверяет, удаётся ли собрать рабочий HTTPS-URL вебхука. Если **нет** — она **снимает подписки WebHook в Max** (через API Max: по известному URL или по списку подписок), чтобы старые URL не оставались «висячими» у бота. Если в настройках всё ещё был выбран режим **WebHook**, режим принудительно переключается на **«Только отправка»**, секрет вебхука очищается, **название записи** в списке интеграций обновляется (как при ручной смене режима — например на «MaxNotify (Только отправка)» / `Send only` в зависимости от языка), в Home Assistant создаётся **запись о проблеме** (repair) с подсказкой проверить сеть и настройки.

- **Журнал.** В обычном журнале (уровень INFO) при загрузке официальной записи интеграции пишется одна строка: доступен ли HTTPS для вебхука, какой URL получился, совпадает ли с правилами «внешний HTTPS», и какие **внешний/внутренний URL** заданы в Home Assistant. Это удобно для диагностики без включения debug-логов.

По [документации Max](https://dev.max.ru/docs-api/methods/POST/subscriptions), пока для бота активна **подписка WebHook** (POST `/subscriptions`), **Long Polling не работает**. В настройках интеграции пункт Long Polling **скрыт**, пока выбран режим WebHook (сначала переключитесь на «Только отправка», чтобы снять регистрацию WebHook). При выборе Long Polling интеграция запрашивает список подписок в Max и **снимает** их через API, чтобы опрос мог работать.

Если в Home Assistant добавлено **несколько** интеграций MaxNotify с **одним и тем же** токеном бота, одновременно нельзя настроить **Long Polling** в одной записи и **WebHook** в другой: при добавлении новой интеграции конфликтующий режим скрыт в мастере, а при сохранении настроек показывается ошибка. **В той же записи** режим по-прежнему можно сменить (например с Long Polling на WebHook или наоборот) — текущая запись при проверке исключается.

[↑ Наверх](#readme-top)

<a id="event-data"></a>

### 📦 Данные события

В `event.data` доступны:

| Поле | Описание |
|------|----------|
| `update_type` | `message_created` (новое сообщение) или `message_callback` (нажатие кнопки) |
| `config_entry_id` | ID записи интеграции |
| `user_id`, `chat_id` | Отправитель и чат (у группы `chat_id` отрицательный) |
| `recipient_id` | Универсальный ID получателя: **> 0** — личный чат (User ID), **< 0** — группа (Chat ID) |
| `text` | Текст сообщения; при `message_callback` — текст сообщения с кнопками |
| `command` | Команда без `/`, если текст начинается с `/` (напр. `/start` → `start`), либо payload нажатой кнопки |
| `args` | Остаток текста после команды |
| `callback_data` | Payload нажатой кнопки (при `message_callback`) |
| `event_id` | Уникальный идентификатор нажатия (для дедупликации в автоматизациях) |

Для автоматизаций рекомендуется использовать **`recipient_id`** (и в триггерах, и в сервисах) — это тот же ID, который вы указываете в «Добавить чат». Поля `chat_id` и `user_id` оставлены для совместимости и низкоуровневых сценариев, но будут удалены в версии **1.5.0**.

[↑ Наверх](#readme-top)

<a id="group-chats"></a>

### 🧩 Групповые чаты

Чтобы получать сообщения из **группы**:
1. Добавьте бота в группу в Max.
2. Назначьте бота **администратором** группы ([документация Max](https://dev.max.ru/docs-api/objects/Update)).
3. Добавьте чат в интеграции с **отрицательным** ID (как в событии).

Личный чат и группа различаются по `recipient_id`: **отрицательный** — группа (Chat ID), **положительный** — личный чат (User ID).

В режиме **`notify.a161.ru`** доступен только один личный **`user_id` > 0`**; групповые чаты через этот прокси не настраиваются.

[↑ Наверх](#readme-top)

<a id="example-reply"></a>

### 💬 Пример: ответ в тот же чат на команду

```yaml
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      command: start

action:
  - service: max_notify.send_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      message: "Привет!"
      send_keyboard: true
```

[↑ Наверх](#readme-top)

<a id="example-button"></a>

### 🔘 Пример: реакция на нажатие кнопки

```yaml
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      update_type: message_callback
      callback_data: light_on
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room
  - service: max_notify.send_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      message: "Свет включён"
```

В автоматизациях используйте триггер «Событие» с типом `max_notify_received` и при необходимости фильтр по `command`, `callback_data`, `chat_id` или `config_entry_id`. Отладка: Инструменты разработчика → События → подписка на `max_notify_received`.

[↑ Наверх](#readme-top)

---

<a id="keyboard"></a>

## 🎛️ Кнопки клавиатуры

**В настройках интеграции:** для **официального API** клавиатура настраивается при режиме **Long Polling** или **WebHook**; для **`notify.a161.ru`** — при выборе **Polling** (после интервала опроса и периода неактивности), в том же мастере добавления/редактирования кнопок.

Добавляются, редактируются и удаляются кнопки (ряд, тип callback/message/**link**, подпись, payload или URL для link). Они по умолчанию прикрепляются к каждому отправляемому сообщению (параметр `send_keyboard` сервиса).

**Payload** кнопки типа callback при нажатии приходит в событии в поле `callback_data` — используйте его в триггерах автоматизаций (например `light_on`, `light_off`).

**Кнопка link** открывает сайт в браузере; в поле URL допускаются только адреса с протоколом **http** или **https** (как в API Max). Иначе сервис в Home Assistant вернёт понятную ошибку до запроса к API.

**В сервисе** `max_notify.send_message` можно передать параметр **`buttons`** — сообщение уйдёт с указанной клавиатурой. Формат: список рядов, каждый ряд — список кнопок `{type: "callback"|"message"|"link", text: "Подпись", payload?: "..."}` или для link `{type: "link", text: "...", url: "https://..."}`. Нужны `config_entry_id` и `chat_id` или `user_id` (не `entity_id`).

Пример отправки с кнопками:

```yaml
service: max_notify.send_message
data:
  config_entry_id: "{{ trigger.event.data.config_entry_id }}"
  user_id: "{{ trigger.event.data.user_id }}"
  message: "Управление:"
  buttons:
    - - type: callback
        text: "Включить"
        payload: light_on
      - type: callback
        text: "Выключить"
        payload: light_off
      - type: link
        text: "Откройте сайт"
        url: "https://example.com"
```

[↑ Наверх](#readme-top)

---

<a id="services"></a>

## 🛠️ Сервисы

Полный набор готовых YAML-примеров для всех сервисов (вручную и из `max_notify_received`) вынесен в отдельный файл:  
[`AUTOMATIONS.md` (содержание)](AUTOMATIONS.md#содержание)

<a id="service-send-message"></a>

### 📨 max_notify.send_message

| Параметр | Описание |
|----------|----------|
| `message` | Текст (обязательно) |
| `title` | Заголовок |
| `entity_id` | Сущности notify MaxNotify (или в «Дополнительно»: `config_entry_id` + `recipient_id`) |
| `recipient_id` | Универсальный ID получателя: положительный — User ID (личный), отрицательный — Chat ID (группа) |
| `send_keyboard` | При `true` (по умолчанию) к сообщению прикрепляется клавиатура из настроек интеграции |
| `buttons` | Дополнительные inline-кнопки (список рядов). Объединяются с настроенной клавиатурой при `send_keyboard=true`; можно указывать вместе с `entity_id` или `config_entry_id` + `recipient_id` |

> Для **`notify.a161.ru`** параметры `send_keyboard` и `buttons` работают так же, как для официального API, если это поддерживает прокси; при ошибке API смотрите ответ в логах.

```yaml
service: max_notify.send_message
data:
  entity_id: notify.max_user_123
  message: "Текст"
  title: "Заголовок"
```

[↑ Наверх](#readme-top)

<a id="service-send-photo"></a>

### 🖼️ max_notify.send_photo

Работает и для **официального API** (`platform-api.max.ru`), и для **`notify.a161.ru`** (с лимитом размера по правилам сервиса).

| Параметр | Описание |
|----------|----------|
| `file` | Путь (`/config/...`, `/media/...`) или URL изображения |
| `url_auth_type` | Тип авторизации для URL медиа: `basic`, `digest`, `bearer` |
| `url_auth_login` | Логин для `basic`/`digest` |
| `url_auth_password` | Пароль для `basic`/`digest` |
| `url_auth_token` | Токен для `bearer` |
| `url_basic_auth` | **Устарело**: формат `логин:пароль` (совместимость, только для `url_auth_type: basic`), будет удалено в версии **1.5.0** |
| `caption` | Подпись |
| `entity_id` / доп. | Как у send_message |
| `count_requests` | Число попыток POST при ожидании обработки вложения (`attachment.not.ready`). Увеличьте для больших файлов. По умолчанию — несколько попыток с паузами (и для официального API, и для `notify.a161.ru`: фото, документ, видео). |

> Если в URL есть `http://логин:пароль@host/...` или переданы параметры авторизации (`url_auth_login/url_auth_password`, `url_auth_token`, `url_basic_auth`) — обязательно укажите `url_auth_type`, иначе сервис вернёт ошибку валидации.

[↑ Наверх](#readme-top)

<a id="service-send-document"></a>

### 📎 max_notify.send_document

Работает и для **официального API**, и для **`notify.a161.ru`** (с лимитом размера по правилам сервиса).

Файл по пути или URL отправляется как документ. Параметры: `file`, поля URL-авторизации как у `send_photo` (`url_auth_type`, `url_auth_login`, `url_auth_password`, `url_auth_token`, `url_basic_auth` — устарело), `caption`, `entity_id` (или config_entry_id + chat_id/user_id), **`count_requests`** — см. описание у `send_photo`.

[↑ Наверх](#readme-top)

<a id="service-send-video"></a>

### 🎥 max_notify.send_video

Работает и для **официального API**, и для **`notify.a161.ru`** (с лимитом размера по правилам сервиса).

Форматы: mp4, mov, webm, mkv. Параметры: `file`, поля URL-авторизации как у `send_photo` (`url_auth_type`, `url_auth_login`, `url_auth_password`, `url_auth_token`, `url_basic_auth` — устарело), `caption`, `entity_id` (или доп.), **`count_requests`** — число попыток при ожидании обработки вложения (для больших видео; для `notify.a161.ru` при необходимости увеличьте, если сервер ещё обрабатывает ролик).

Отправка через сущность: в сценариях и автоматизациях — действие **Уведомление** → выбор сущности MaxNotify.

[↑ Наверх](#readme-top)

<a id="service-delete-message"></a>

### 🗑️ max_notify.delete_message

Работает и для **официального API**, и для **`notify.a161.ru`** (если поддерживается на стороне сервиса).

Удаляет сообщение по ID (у официального API — обычно только сообщения младше 24 часов). `message_id` для автоматизаций с официальным API удобно брать из события `max_notify_received`.

| Параметр | Описание |
|----------|----------|
| `message_id` | ID сообщения (обязательно), напр. `{{ trigger.event.data.message_id }}` |
| `config_entry_id` | Интеграция (если несколько) |

[↑ Наверх](#readme-top)

<a id="service-edit-message"></a>

### ✏️ max_notify.edit_message

Работает и для **официального API**, и для **`notify.a161.ru`** (если поддерживается на стороне сервиса).

Редактирует текст и/или кнопки сообщения (у официального API — обычно только младше 24 часов). Для **`notify.a161.ru`** те же поля уходят в API прокси; фактические ограничения и сроки хранения сообщений задаёт сервис.

| Параметр | Описание |
|----------|----------|
| `message_id` | ID сообщения (обязательно) |
| `text` | Новый текст (опционально) |
| `buttons` | Inline-клавиатура: список рядов `{type, text, payload?}`; заменяет текущие кнопки |
| `remove_buttons` | Удалить все кнопки |
| `format` | Формат текста: text, markdown, html |
| `config_entry_id` | Интеграция (если несколько) |

```yaml
# Удалить сообщение
service: max_notify.delete_message
data:
  message_id: "{{ trigger.event.data.message_id }}"

# Редактировать текст
service: max_notify.edit_message
data:
  message_id: "{{ trigger.event.data.message_id }}"
  text: "Обновлённый текст"
```

[↑ Наверх](#readme-top)

---

<a id="debug"></a>

## 🐞 Включение режима отладки

Для того, что бы в логи начала отправляться отладочная информация нужно в файл `configuration.yaml` добавить строки:

```
logger:
  default: warning
  logs:
    custom_components.max_notify: debug
```
Затем нужно перезагрузить HomeAssistant и перейтии в раздел **Настройки -> Система -> Журнал сервера ->** справа сверху нажать троеточие и выбрать "Показать исходный журнал"

[↑ Наверх](#readme-top)

---

<a id="token-ids"></a>

## 🔑 Токен и ID

**Токен:** [Max для разработчиков](https://dev.max.ru/) → бот → **Интеграция** → получить токен.

**User ID и Chat ID:** бот [CHECK ID](https://max.ru/id222312277810_1_bot) в Max возвращает ID по пересланному сообщению. Либо через API: `GET https://platform-api.max.ru/chats` с заголовком `Authorization: <токен>` ([документация API Max](https://dev.max.ru/docs-api)).

[↑ Наверх](#readme-top)

---

<a id="links"></a>

## 🔗 Ссылки

- [Репозиторий](https://github.com/kai-zer-ru/max-notify-ha)
- [Документация API Max](https://dev.max.ru/docs-api)
- [Max для разработчиков](https://dev.max.ru/)
- [Канал в Telegram](https://t.me/kai_zer_ru_ha)
- [Канал в Max](https://max.ru/id251603503331_biz)

[↑ Наверх](#readme-top)
