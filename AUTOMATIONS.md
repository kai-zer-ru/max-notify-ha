<a id="automations-top"></a>

# Примеры автоматизаций для MaxNotify

Ниже примеры для всех сервисов интеграции `max_notify` в двух вариантах:
- с ручным указанием параметров;
- с подстановкой параметров из события `max_notify_received`.

Примеры можно использовать и для записи **Official Max API** (`platform-api.max.ru`), и для **`notify.a161.ru`** — подставьте свои `config_entry_id`, `entity_id` или `recipient_id` из нужной интеграции.

> **Событие `max_notify_received`** в примерах «из события» приходит при **официальном API** (Long Polling или WebHook) и при **`notify.a161.ru`**, если для записи включён **Polling** (опрос очереди прокси), а не режим «Только отправка».
>
> **Inline-кнопки (`buttons`)** и клавиатура из настроек интеграции поддерживаются **в обоих режимах** (официальный API и `notify.a161.ru`) в рамках [возможностей сервиса](https://notify.a161.ru/). Для `notify.a161.ru` при Polling действует **автопереключение на «Только отправка»**: если за выбранный период **1–3 суток** (по умолчанию 3) не было ни входящих обновлений, ни отправки сообщения **с кнопками**, приём отключается — снова включите Polling в настройках записи. Подробнее — [README](README.md#notify-a161).
>
> **Отрицательный** `recipient_id` — **групповой чат** Max. Так работает и **официальный API**, и **`notify.a161.ru`** (отправка и приём в группе — в рамках [возможностей сервиса](https://notify.a161.ru/)).

> Событие `max_notify_received` нормализуется к единому формату независимо от провайдера и содержит стандартные поля (`update_type`, `config_entry_id`, `timestamp`, `recipient_id`, `text`, `command`, `args`, `callback_data`, `message_id`, `event_id`, `raw_update`).
>
> Чтобы **ответить в тот же чат**, откуда пришло сообщение, в `max_notify.send_message` передайте **`config_entry_id`** и **`recipient_id`** именно из **`trigger.event.data`** (оба поля). Значение **`recipient_id`** в событии — это и есть идентификатор того диалога (личного или группового), в который нужно отправить ответ; подбирать `entity_id` сущности `notify` для этого не требуется.

<a id="содержание"></a>

## Содержание

- [Форматы поля buttons](#formats-buttons)
- [Рабочие паттерны](#working-patterns)
  - [Прямое уведомление из автоматизации](#pattern-direct-automation-notify)
  - [Разные сообщения по `trigger.id`](#pattern-trigger-id-choose)
  - [Кнопка → команда → сценарий](#pattern-button-command-script)
  - [Кнопка «Удалить»](#pattern-delete-button)
  - [Временное сообщение «формируется»](#pattern-temporary-message)
  - [Фото/видео с камеры и меню действий](#pattern-camera-menu)
  - [Динамическое фото по URL](#pattern-dynamic-url-photo)
- [max_notify.send_message](#autom-send-message)
  - [Ответ в тот же чат (из события)](#autom-send-message-same-chat)
  - [Вручную](#autom-send-message-manual)
- [max_notify.send_photo](#autom-send-photo)
  - [Вручную](#autom-send-photo-manual)
  - [Из события](#autom-send-photo-event)
- [max_notify.send_document](#autom-send-document)
  - [Вручную](#autom-send-document-manual)
  - [Из события](#autom-send-document-event)
- [max_notify.send_video](#autom-send-video)
  - [Вручную](#autom-send-video-manual)
  - [Из события](#autom-send-video-event)
- [max_notify.edit_message](#autom-edit-message)
  - [Вручную](#autom-edit-message-manual)
  - [Из события](#autom-edit-message-event)
- [max_notify.delete_message](#autom-delete-message)
  - [Вручную](#autom-delete-message-manual)
  - [Из события](#autom-delete-message-event)
- [max_notify.delete_last_outgoing_message](#autom-delete-last-outgoing-message)
  - [Вручную](#autom-delete-last-outgoing-message-manual)

---

<a id="formats-buttons"></a>

## Форматы поля buttons

Поле `buttons` поддерживает несколько форматов (старые форматы сохранены):

- Один ряд, словарь:
  ```yaml
  buttons:
    "Button 1": "button_1"
    "Button 2": "button_2"
  ```
- Один ряд, список объектов:
  ```yaml
  buttons:
    - text: "Button 1"
      payload: "button_1"
    - text: "Button 2"
      payload: "button_2"
  ```
- Несколько рядов, нативный формат:
  ```yaml
  buttons:
    - - text: "Ряд 1 / Кнопка 1"
        payload: "r1_b1"
      - text: "Ряд 1 / Кнопка 2"
        payload: "r1_b2"
    - - text: "Ряд 2 / Кнопка 1"
        payload: "r2_b1"
  ```
- Несколько рядов, упрощенный формат (каждый объект верхнего списка = отдельный ряд):
  ```yaml
  buttons:
    - "Ряд 1 / Кнопка 1": "r1_b1"
      "Ряд 1 / Кнопка 2": "r1_b2"
    - "Ряд 2 / Кнопка 1": "r2_b1"
  ```

[↑ Наверх](#automations-top)

---

<a id="working-patterns"></a>

## Рабочие паттерны

Эти примеры собраны по реальным рабочим автоматизациям. Замените `notify.maxnotify_webhook_chat_123456`, сенсоры `sensor.maxnotify_...` и пути к файлам на свои.

<a id="pattern-direct-automation-notify"></a>

### Прямое уведомление из автоматизации

Самый простой рабочий вариант — вызвать `max_notify.send_message` прямо из `automations.yaml` по событию Home Assistant: запуск системы, состояние датчика, дверной звонок, высокий CO2 и т.п. `entity_id` можно передавать в `data` или через `target`; оба варианта используются в Home Assistant.

```yaml
alias: MaxNotify — запуск Home Assistant
description: Сообщает о старте системы и предлагает удалить уведомление кнопкой.
triggers:
  - trigger: homeassistant
    event: start
conditions: []
actions:
  - action: max_notify.send_message
    data:
      entity_id: notify.maxnotify_webhook_chat_123456
      message: >
        Сервер Home Assistant запущен в {{ utcnow().astimezone().strftime('%H:%M %d.%m.%Y') }}.
        Отчёт о состоянии будет через 1 минуту.
      send_keyboard: true
      buttons:
        - text: "Удалить"
          payload: delete
mode: single
```

```yaml
alias: MaxNotify — дверной звонок
triggers:
  - trigger: device
    domain: mqtt
    device_id: your_device_id
    type: action
    subtype: single
conditions: []
actions:
  - action: max_notify.send_message
    target:
      entity_id: notify.maxnotify_webhook_chat_123456
    data:
      message: "Звонок в дверь"
      send_keyboard: true
mode: single
```

[↑ Наверх](#automations-top)

<a id="pattern-trigger-id-choose"></a>

### Разные сообщения по `trigger.id`

Если одна автоматизация слушает несколько событий, удобно поставить каждому триггеру `id`, а затем выбрать текст через `choose`. Так можно держать связанную логику в одной automation и отправлять разные сообщения в Max.

```yaml
alias: MaxNotify — события двери
triggers:
  - trigger: state
    entity_id: sensor.door_lock_event
    to: "Doorbell is ringing"
    id: doorbell
  - trigger: state
    entity_id: sensor.door_lock_event
    to: "The door is not closed"
    id: opened_from_outside
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: opened_from_outside
        sequence:
          - action: max_notify.send_message
            data:
              entity_id:
                - notify.maxnotify_webhook_chat_123456
              message: >
                Входная дверь открыта снаружи.
                Пользователь: {{ states('sensor.last_door_user') }}
              send_keyboard: true

      - conditions:
          - condition: trigger
            id: doorbell
        sequence:
          - action: max_notify.send_message
            data:
              entity_id:
                - notify.maxnotify_webhook_chat_123456
              message: "Звонок в дверь"
              send_keyboard: true
mode: queued
max: 10
```

[↑ Наверх](#automations-top)

<a id="pattern-button-command-script"></a>

### Кнопка → команда → сценарий

Кнопки с `payload` приходят в событие `max_notify_received` как `command`. Удобно делать одно сообщение с меню и отдельные автоматизации-роутеры для каждой команды.

```yaml
alias: MaxNotify — уведомление с меню
triggers:
  - trigger: state
    entity_id: binary_sensor.washing_machine_done
    to: "on"
conditions: []
actions:
  - action: max_notify.send_message
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      message: "Стирка окончена, вытащи бельё"
      send_keyboard: true
      buttons:
        - - text: "Отчёт"
            payload: report
          - text: "Все ушли из дома"
            payload: away
        - - text: "Удалить"
            payload: delete
mode: single
```

```yaml
alias: MaxNotify — команда report
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: report
conditions: []
actions:
  - action: script.turn_on
    target:
      entity_id: script.system_report
mode: single
```

[↑ Наверх](#automations-top)

<a id="pattern-delete-button"></a>

### Кнопка «Удалить»

Если в сообщении есть кнопка с `payload: delete`, можно удалить именно то сообщение, на котором нажали кнопку. Для этого берите `config_entry_id` и `message_id` из события.

```yaml
alias: MaxNotify — удалить сообщение по кнопке
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: delete
conditions: []
actions:
  - action: max_notify.delete_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      message_id: "{{ trigger.event.data.message_id }}"
mode: single
```

[↑ Наверх](#automations-top)

<a id="pattern-temporary-message"></a>

### Временное сообщение «формируется»

Для долгих операций удобно сначала отправить короткое сообщение, дождаться обновления сенсора последнего исходящего `message_id`, выполнить работу, отправить итог и удалить промежуточное сообщение.

```yaml
alias: MaxNotify — временное сообщение и удаление
triggers:
  - trigger: event
    event_type: my_long_task
conditions: []
actions:
  - alias: "1. Сообщаем, что результат формируется"
    action: max_notify.send_message
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      message: "Фото с камеры формируется"
      send_keyboard: false

  - alias: "2. Ждём ID последнего исходящего сообщения"
    wait_for_trigger:
      - trigger: state
        entity_id:
          - sensor.maxnotify_webhook_last_outgoing_message_id_chat_123456
        for:
          seconds: 1
    timeout: "00:00:10"
    continue_on_timeout: false

  - alias: "3. Сохраняем ID промежуточного сообщения"
    variables:
      message_id_to_delete: "{{ wait.trigger.to_state.state }}"

  - alias: "4. Выполняем долгую операцию"
    delay: "00:00:05"

  - alias: "5. Отправляем итог"
    action: max_notify.send_message
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      message: "Готово"
      send_keyboard: true

  - alias: "6. Удаляем промежуточное сообщение"
    action: max_notify.delete_message
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      message_id: "{{ message_id_to_delete }}"
mode: single
```

[↑ Наверх](#automations-top)

<a id="pattern-camera-menu"></a>

### Фото/видео с камеры и меню действий

Рабочая схема для камер: сделать снимок или запись, отправить медиа и приложить меню с командами для следующих действий. Для локальных файлов используйте путь, доступный Home Assistant, например `/config/www/...`.

```yaml
alias: MaxNotify — фото с камеры
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: photo_cam
conditions: []
actions:
  - alias: "1. Делаем снимок"
    action: camera.snapshot
    target:
      entity_id: camera.front_door
    data:
      filename: /config/www/cam_captures/front_door.jpg

  - alias: "2. Отправляем фото с меню"
    action: max_notify.send_photo
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      file: /config/www/cam_captures/front_door.jpg
      send_keyboard: true
      count_requests: 10
      buttons:
        - - text: "Фото"
            payload: photo_cam
          - text: "Видео"
            payload: video_cam
        - - text: "Фото со всех камер"
            payload: photo_cam_all
          - text: "Видео со всех камер"
            payload: video_cam_all
        - - text: "Удалить"
            payload: delete
mode: single
```

```yaml
alias: MaxNotify — видео с камеры
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: video_cam
conditions: []
actions:
  - alias: "1. Записываем видео"
    action: camera.record
    target:
      entity_id: camera.front_door
    data:
      filename: /config/www/cam_captures/front_door.mp4
      duration: 30
      lookback: 10

  - alias: "2. Отправляем видео"
    action: max_notify.send_video
    data:
      entity_id:
        - notify.maxnotify_webhook_chat_123456
      file: /config/www/cam_captures/front_door.mp4
      send_keyboard: true
      buttons:
        - - text: "Фото"
            payload: photo_cam
          - text: "Видео"
            payload: video_cam
        - - text: "Удалить"
            payload: delete
mode: single
```

[↑ Наверх](#automations-top)

<a id="pattern-dynamic-url-photo"></a>

### Динамическое фото по URL

`file` у `send_photo` может быть не только локальным файлом, но и URL, собранным шаблоном. Это удобно для статических карт, камер и внешних генераторов изображений. Если источник использует самоподписанный или нестандартный SSL, можно указать `disable_ssl: true`.

```yaml
alias: MaxNotify — где все
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: where
conditions: []
actions:
  - repeat:
      for_each: "{{ states.person | map(attribute='entity_id') | list }}"
      sequence:
        - action: max_notify.send_photo
          data:
            config_entry_id: "{{ trigger.event.data.config_entry_id }}"
            recipient_id: "{{ trigger.event.data.recipient_id }}"
            send_keyboard: false
            disable_ssl: true
            file: >
              {% set lat = state_attr(repeat.item, 'latitude') %}
              {% set lon = state_attr(repeat.item, 'longitude') %}
              {% if lat is not none and lon is not none %}
                https://static-maps.example.com/map?lat={{ lat }}&lon={{ lon }}&zoom=17&key=YOUR_API_KEY
              {% else %}
                https://static-maps.example.com/map?lat=0&lon=0&zoom=1&key=YOUR_API_KEY
              {% endif %}
            caption: >
              {% set name = state_attr(repeat.item, 'friendly_name') %}
              {% set lat = state_attr(repeat.item, 'latitude') %}
              {% set lon = state_attr(repeat.item, 'longitude') %}
              {% if lat is not none and lon is not none %}
                {{ name }}: {{ state_translated(repeat.item) }}
              {% else %}
                {{ name }}: нет координат
              {% endif %}
            buttons:
              - - type: link
                  text: "Google"
                  url: >
                    {% set lat = state_attr(repeat.item, 'latitude') %}
                    {% set lon = state_attr(repeat.item, 'longitude') %}
                    {% if lat is not none and lon is not none %}
                      https://www.google.com/maps/search/?api=1&query={{ lat }},{{ lon }}
                    {% endif %}
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-delete-last-outgoing-message"></a>

## max_notify.delete_last_outgoing_message

> Работает только для **групповых чатов** (`recipient_id < 0`) в **Official Max API**.
> Для личных чатов (`recipient_id > 0`) API Max не позволяет читать историю сообщений по `recipient_id`, поэтому сервис вернёт ошибку в UI.

<a id="autom-delete-last-outgoing-message-manual"></a>

### Вручную

```yaml
alias: MaxNotify — delete_last_outgoing_message (manual, group only)
triggers:
  - trigger: event
    event_type: my_cleanup_event
conditions: []
actions:
  - action: max_notify.delete_last_outgoing_message
    target:
      entity_id: notify.maxnotify_long_polling_chat_123456
    data:
      scan_count: 20
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-send-message"></a>

## max_notify.send_message

<a id="autom-send-message-same-chat"></a>
<a id="autom-send-message-event"></a>

### Ответ в тот же чат (из события)

Типовая автоматизация: на любое входящее событие отправить текст **обратно в тот же диалог** (личный или групповой). Обязательно укажите в **`data`** оба поля из триггера — **`config_entry_id`** (запись MaxNotify в Home Assistant) и **`recipient_id`** (чат в Max для этого сообщения). Не задавайте **«Цель»** (`target` / `entity_id`) в редакторе действия: при одной только записи без `recipient_id` служба не может однозначно выбрать чат среди нескольких добавленных в интеграцию.

```yaml
alias: MaxNotify — ответ в тот же чат
description: Отправляет сообщение в тот же чат, откуда пришло max_notify_received.
triggers:
  - trigger: event
    event_type: max_notify_received
conditions: []
actions:
  - action: max_notify.send_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      message: "Получено: {{ trigger.event.data.text | default('') }}"
      buttons:
        - "Ок": "ok"
        - "Повтор": "retry"
mode: single
```

Чтобы реагировать только на команды или ключевые слова, добавьте **условия** или **`event_data`** у триггера (пример — только команда `hello`):

```yaml
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: hello
```

Для фото, видео и документов в разделах ниже действует то же правило: **`config_entry_id`** и **`recipient_id`** из **`trigger.event.data`**, без выбора цели через сущность `notify`, если нужен ответ именно в источник события.

[↑ Наверх](#automations-top)

<a id="autom-send-message-manual"></a>

### Вручную

Фиксированная запись и чат (без привязки к событию):

```yaml
alias: MaxNotify — send_message (manual)
triggers:
  - trigger: time_pattern
    minutes: "/30"
conditions: []
actions:
  - action: max_notify.send_message
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      recipient_id: -70955246010435
      message: "Проверка связи"
      title: "Статус"
      send_keyboard: false
      buttons:
        "Button 1": "button_1"
        "Button 2": "button_2"
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-send-photo"></a>

## max_notify.send_photo

<a id="autom-send-photo-manual"></a>

### Вручную

```yaml
alias: MaxNotify — send_photo (manual)
triggers:
  - trigger: state
    entity_id: binary_sensor.door
    to: "on"
conditions: []
actions:
  - action: max_notify.send_photo
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      recipient_id: -70955246010435
      file: "/config/www/cam/latest.jpg"
      caption: "Дверь открыта"
      count_requests: 6
      buttons:
        "Открыть камеру": "cam_open"
mode: single
```

[↑ Наверх](#automations-top)

<a id="autom-send-photo-event"></a>

### Из события

```yaml
alias: MaxNotify — send_photo (from event)
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: photo
conditions: []
actions:
  - action: max_notify.send_photo
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      file: "/config/www/cam/latest.jpg"
      caption: "Фото по команде /photo"
      buttons:
        - text: "Еще фото"
          payload: "photo"
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-send-document"></a>

## max_notify.send_document

<a id="autom-send-document-manual"></a>

### Вручную

```yaml
alias: MaxNotify — send_document (manual)
triggers:
  - trigger: time
    at: "09:00:00"
conditions: []
actions:
  - action: max_notify.send_document
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      recipient_id: -70955246010435
      file: "/config/reports/daily.pdf"
      caption: "Ежедневный отчет"
      count_requests: 8
      buttons:
        "Подтвердить": "report_ok"
mode: single
```

[↑ Наверх](#automations-top)

<a id="autom-send-document-event"></a>

### Из события

```yaml
alias: MaxNotify — send_document (from event)
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: report
conditions: []
actions:
  - action: max_notify.send_document
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      file: "/config/reports/daily.pdf"
      caption: "Отчет по запросу"
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-send-video"></a>

## max_notify.send_video

<a id="autom-send-video-manual"></a>

### Вручную

```yaml
alias: MaxNotify — send_video (manual)
triggers:
  - trigger: state
    entity_id: alarm_control_panel.home_alarm
    to: "triggered"
conditions: []
actions:
  - action: max_notify.send_video
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      recipient_id: -70955246010435
      file: "/media/security/cam1.mp4"
      caption: "Тревога"
      count_requests: 15
      buttons:
        "Отключить сирену": "alarm_off"
mode: single
```

[↑ Наверх](#automations-top)

<a id="autom-send-video-event"></a>

### Из события

```yaml
alias: MaxNotify — send_video (from event)
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      command: video
conditions: []
actions:
  - action: max_notify.send_video
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      file: "/media/security/last.mp4"
      caption: "Видео по запросу"
      count_requests: 20
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-edit-message"></a>

## max_notify.edit_message

<a id="autom-edit-message-manual"></a>

### Вручную

```yaml
alias: MaxNotify — edit_message (manual)
triggers:
  - trigger: event
    event_type: my_custom_event
conditions: []
actions:
  - action: max_notify.edit_message
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      message_id: "1234567890"
      text: "Обновленный текст"
      buttons:
        "Обновить": "refresh"
        "Закрыть": "close"
      format: text
mode: single
```

[↑ Наверх](#automations-top)

<a id="autom-edit-message-event"></a>

### Из события

```yaml
alias: MaxNotify — edit_message (from event)
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      update_type: message_callback
      callback_data: refresh
conditions: []
actions:
  - action: max_notify.edit_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      message_id: "{{ trigger.event.data.message_id }}"
      text: "Данные обновлены"
      buttons:
        - text: "Повторить"
          payload: "refresh"
        - text: "Готово"
          payload: "done"
mode: single
```

[↑ Наверх](#automations-top)

---

<a id="autom-delete-message"></a>

## max_notify.delete_message

Для удаления сообщений у бота в нужном чате должны быть права **читать** и **удалять** сообщения. В группах и каналах обычно нужно выдать боту роль администратора с соответствующими разрешениями.

<a id="autom-delete-message-manual"></a>

### Вручную

```yaml
alias: MaxNotify — delete_message (manual)
triggers:
  - trigger: event
    event_type: my_cleanup_event
conditions: []
actions:
  - action: max_notify.delete_message
    data:
      config_entry_id: "01KH6B15CHBAT3E3Q4TJRVGBSY"
      message_id: "1234567890"
mode: single
```

[↑ Наверх](#automations-top)

<a id="autom-delete-message-event"></a>

### Из события

```yaml
alias: MaxNotify — delete_message (from event)
triggers:
  - trigger: event
    event_type: max_notify_received
    event_data:
      update_type: message_callback
      callback_data: delete
conditions: []
actions:
  - action: max_notify.delete_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      message_id: "{{ trigger.event.data.message_id }}"
mode: single
```

[↑ Наверх](#automations-top)
