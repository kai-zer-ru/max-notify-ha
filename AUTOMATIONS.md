# Примеры автоматизаций для Max Notify

Ниже примеры для всех сервисов интеграции `max_notify` в двух вариантах:
- с ручным указанием параметров;
- с подстановкой параметров из события `max_notify_received`.

> Примечание: для примеров "из события" триггер предполагает событие `max_notify_received`.

---

## max_notify.send_message

### Вручную

```yaml
alias: Max Notify — send_message (manual)
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

### Из события

```yaml
alias: Max Notify — send_message (from event)
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
        - text: "Ок"
          payload: "ok"
        - text: "Повтор"
          payload: "retry"
mode: single
```

---

## max_notify.send_photo

### Вручную

```yaml
alias: Max Notify — send_photo (manual)
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

### Из события

```yaml
alias: Max Notify — send_photo (from event)
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

---

## max_notify.send_document

### Вручную

```yaml
alias: Max Notify — send_document (manual)
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

### Из события

```yaml
alias: Max Notify — send_document (from event)
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

---

## max_notify.send_video

### Вручную

```yaml
alias: Max Notify — send_video (manual)
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

### Из события

```yaml
alias: Max Notify — send_video (from event)
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

---

## max_notify.edit_message

### Вручную

```yaml
alias: Max Notify — edit_message (manual)
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

### Из события

```yaml
alias: Max Notify — edit_message (from event)
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

---

## max_notify.delete_message

### Вручную

```yaml
alias: Max Notify — delete_message (manual)
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

### Из события

```yaml
alias: Max Notify — delete_message (from event)
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
