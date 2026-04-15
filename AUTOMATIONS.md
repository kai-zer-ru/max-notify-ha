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
> В примерах с **отрицательным** `recipient_id` (групповой чат) это относится к **официальному API**. Для **`notify.a161.ru`** используется только положительный `user_id` одного получателя.

<a id="содержание"></a>

## Содержание

- [Форматы поля buttons](#formats-buttons)
- [max_notify.send_message](#autom-send-message)
  - [Вручную](#autom-send-message-manual)
  - [Из события](#autom-send-message-event)
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

<a id="autom-send-message"></a>

## max_notify.send_message

<a id="autom-send-message-manual"></a>

### Вручную

```yaml
alias: MaxNotify — send_message (manual)
trigger:
  - platform: time_pattern
    minutes: "/30"
action:
  - service: max_notify.send_message
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

<a id="autom-send-message-event"></a>

### Из события

```yaml
alias: MaxNotify — send_message (from event)
trigger:
  - platform: event
    event_type: max_notify_received
action:
  - service: max_notify.send_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      recipient_id: "{{ trigger.event.data.recipient_id }}"
      message: "Получено: {{ trigger.event.data.text | default('') }}"
      buttons:
        - "Ок": "ok"
        - "Повтор": "retry"
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
trigger:
  - platform: state
    entity_id: binary_sensor.door
    to: "on"
action:
  - service: max_notify.send_photo
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
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      command: photo
action:
  - service: max_notify.send_photo
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
trigger:
  - platform: time
    at: "09:00:00"
action:
  - service: max_notify.send_document
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
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      command: report
action:
  - service: max_notify.send_document
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
trigger:
  - platform: state
    entity_id: alarm_control_panel.home_alarm
    to: "triggered"
action:
  - service: max_notify.send_video
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
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      command: video
action:
  - service: max_notify.send_video
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
trigger:
  - platform: event
    event_type: my_custom_event
action:
  - service: max_notify.edit_message
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
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      update_type: message_callback
      callback_data: refresh
action:
  - service: max_notify.edit_message
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

<a id="autom-delete-message-manual"></a>

### Вручную

```yaml
alias: MaxNotify — delete_message (manual)
trigger:
  - platform: event
    event_type: my_cleanup_event
action:
  - service: max_notify.delete_message
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
trigger:
  - platform: event
    event_type: max_notify_received
    event_data:
      update_type: message_callback
      callback_data: delete
action:
  - service: max_notify.delete_message
    data:
      config_entry_id: "{{ trigger.event.data.config_entry_id }}"
      message_id: "{{ trigger.event.data.message_id }}"
mode: single
```

[↑ Наверх](#automations-top)
