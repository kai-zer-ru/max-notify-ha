# Сертификаты НУЦ Минцифры для официального API Max

Платформа Max переводит API с **`platform-api.max.ru`** на **`platform-api2.max.ru`**. Новый endpoint использует TLS-сертификаты, выпущенные **Национальным удостоверяющим центром (НУЦ) Минцифры России** («Russian Trusted»). Если эти корневые сертификаты не добавлены в доверенные, Home Assistant не сможет установить HTTPS-соединение с API Max.

Типичная ошибка в журнале:

```text
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```

или при настройке интеграции — «Не удалось подключиться» / `cannot_connect`.

Инструкция ниже актуальна для записи MaxNotify с **официальным API Max**. Режим **notify.a161.ru** использует другой хост и эти шаги обычно не нужны.

## Порядок действий (важно)

1. **Сначала** добавьте сертификаты НУЦ Минцифры в доверенные — через [Additional CA](#способ-a--additional-ca-рекомендуется) (рекомендуется для HAOS, Supervised, Docker) или другой способ ниже.
2. **Перезапустите** Home Assistant и убедитесь, что HTTPS к `platform-api2.max.ru` проходит без ошибки SSL ([проверка](#1-из-контейнера-или-хоста-где-работает-ha)).
3. **Только после этого** обновляйте MaxNotify до версии **2.1.0** и выше (HACS или вручную).

Если обновить MaxNotify раньше, запись с официальным API перестанет подключаться (`CERTIFICATE_VERIFY_FAILED`, `cannot_connect`) до настройки сертификатов.

---

## Содержание

- [Порядок действий](#порядок-действий-важно)
- [Какие файлы скачать](#какие-файлы-скачать)
- [Как понять, какой у вас способ установки](#как-понять-какой-у-вас-способ-установки)
- [Home Assistant OS (HAOS)](#home-assistant-os-haos)
- [Home Assistant Supervised](#home-assistant-supervised)
- [Home Assistant Container (Docker)](#home-assistant-container-docker)
- [Home Assistant Core (venv)](#home-assistant-core-venv)
- [Другие варианты](#другие-варианты)
- [Проверка после установки](#проверка-после-установки)
- [Если ошибка осталась](#если-ошибка-осталась)

---

## Какие файлы скачать

Нужны **оба** сертификата цепочки НУЦ Минцифры (формат PEM, расширение `.crt`):

| Файл | Прямая ссылка |
|------|---------------|
| Корневой CA | https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt |
| Выпускающий (sub) CA | https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt |

Альтернатива: портал [Госуслуг](https://www.gosuslugi.ru/) → раздел про сертификаты для Linux / НУЦ Минцифры.

Сохраните файлы на компьютер, с которого вы управляете Home Assistant. Имена в примерах ниже:

- `russian_trusted_root_ca_pem.crt`
- `russian_trusted_sub_ca_pem.crt`

---

## Как понять, какой у вас способ установки

| Способ | Как узнать |
|--------|------------|
| **HAOS** | **Настройки → Система → О системе** — тип установки «Home Assistant OS» |
| **Supervised** | На хосте установлен пакет Supervisor; в UI может быть «Home Assistant Supervised» |
| **Container** | Home Assistant запущен в Docker / Docker Compose на Linux, macOS или Windows |
| **Core** | Python-окружение (venv) на хосте, без контейнера HA |

Если сомневаетесь — для HAOS, Supervised и Container **рекомендуется** способ через интеграцию [Additional CA](https://github.com/Athozs/hass-additional-ca) (см. ниже): она переживает обновления ядра Home Assistant.

---

## Home Assistant OS (HAOS)

HAOS запускает Home Assistant **внутри Docker-контейнера**. Python в контейнере проверяет SSL через хранилище сертификатов контейнера (не через браузер вашего ПК). Поэтому добавление CA только в Windows/macOS **не поможет** интеграции.

### Способ A — Additional CA (рекомендуется)

Подходит для HAOS, Supervised и Container; изменения сохраняются после обновлений Home Assistant.

**Сначала сертификаты — потом MaxNotify.** Ниже описана только настройка доверия к CA. Обновление MaxNotify до **2.1.0+** (переход на `platform-api2.max.ru`) выполняйте **после** шагов 1–5 и успешной [проверки SSL](#1-из-контейнера-или-хоста-где-работает-ha).

1. Установите интеграцию **[Additional CA](https://github.com/Athozs/hass-additional-ca)** через HACS (категория *Integration*) или вручную в `custom_components/additional_ca`.
2. Скопируйте оба `.crt` в каталог конфигурации Home Assistant, например:
   - `/config/russian_trusted_root_ca_pem.crt`
   - `/config/russian_trusted_sub_ca_pem.crt`  
   (в File editor / Samba / SSH — это одна папка с `configuration.yaml`.)
3. Добавьте в `configuration.yaml`:

```yaml
additional_ca:
  russian_trusted_root: russian_trusted_root_ca_pem.crt
  russian_trusted_sub: russian_trusted_sub_ca_pem.crt
```

4. **Перезапустите** Home Assistant (**Настройки → Система → Перезагрузка**).
5. Убедитесь, что SSL к новому API работает — см. [Проверка после установки → п. 1](#1-из-контейнера-или-хоста-где-работает-ha).
6. **Затем** обновите MaxNotify (HACS или вручную) до версии **2.1.0** и выше и при необходимости перенастройте запись с официальным API.

Документация интеграции Additional CA: https://github.com/Athozs/hass-additional-ca

### Способ B — вручную через SSH (без Additional CA)

Используйте, если не хотите ставить дополнительную интеграцию. **Минус:** после некоторых обновлений Home Assistant шаги могут потребоваться снова.

**Сначала сертификаты — потом MaxNotify** (как в [способе A](#способ-a--additional-ca-рекомендуется)).

1. Включите SSH: дополнение **Terminal & SSH** или [отладочный SSH на порту 22222](https://developers.home-assistant.io/docs/operating-system/debugging/).
2. Подключитесь и выполните `login`, чтобы попасть в shell HAOS.
3. Скопируйте сертификаты в контейнер Home Assistant (если файлы лежат в `/config/` на хосте):

```bash
docker cp /config/russian_trusted_root_ca_pem.crt homeassistant:/usr/local/share/ca-certificates/
docker cp /config/russian_trusted_sub_ca_pem.crt homeassistant:/usr/local/share/ca-certificates/
docker exec homeassistant update-ca-certificates
```

4. Перезапустите Home Assistant: **Настройки → Система → Перезагрузка**.
5. Проверьте SSL — [п. 1](#1-из-контейнера-или-хоста-где-работает-ha), **затем** обновите MaxNotify до **2.1.0+**.

---

## Home Assistant Supervised

Supervisor управляет контейнером `homeassistant` на Linux-хосте (Debian/Ubuntu). Сертификаты нужно доверять **контейнеру**, с которого идут исходящие HTTPS-запросы интеграций.

### Способ A — Additional CA

Те же шаги, что для [HAOS → Способ A](#способ-a--additional-ca-рекомендуется): файлы в `/config/`, блок `additional_ca` в `configuration.yaml`, перезагрузка, проверка SSL, **после этого** — обновление MaxNotify.

### Способ B — вручную в контейнер

На хосте с Supervisor (имя контейнера обычно `homeassistant`):

```bash
sudo cp russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt /usr/local/share/ca-certificates/
# Если сертификаты на хосте — скопируйте их в контейнер:
docker cp russian_trusted_root_ca_pem.crt homeassistant:/usr/local/share/ca-certificates/
docker cp russian_trusted_sub_ca_pem.crt homeassistant:/usr/local/share/ca-certificates/
docker exec homeassistant update-ca-certificates
```

Перезапустите Home Assistant из UI или:

```bash
docker restart homeassistant
```

### Способ C — на хосте Supervisor (дополнительно)

Имеет смысл добавить CA и на **хост** Debian/Ubuntu — для других сервисов на машине:

```bash
sudo cp russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Для работы MaxNotify этого **может быть недостаточно**, если запросы идут из контейнера — всё равно выполните шаги для контейнера или используйте Additional CA.

---

## Home Assistant Container (Docker)

Отдельный Docker или Docker Compose **без** полного HAOS/Supervisor.

### Способ A — Additional CA

1. Смонтируйте каталог конфигурации HA в контейнер (как обычно: `-v /path/to/config:/config`).
2. Положите `.crt` в этот каталог, добавьте `additional_ca` в `configuration.yaml`, перезапустите контейнер.
3. Проверьте SSL к `platform-api2.max.ru`, **затем** обновите MaxNotify до **2.1.0+**.

### Способ B — при старте контейнера

Пример фрагмента `docker-compose.yml` с однократной установкой CA при каждом запуске:

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    volumes:
      - ./config:/config
      - ./certs/russian_trusted_root_ca_pem.crt:/usr/local/share/ca-certificates/russian_trusted_root_ca_pem.crt:ro
      - ./certs/russian_trusted_sub_ca_pem.crt:/usr/local/share/ca-certificates/russian_trusted_sub_ca_pem.crt:ro
    command: >
      /bin/sh -c "update-ca-certificates && python -m homeassistant --config /config"
```

Проверьте актуальный `command`/`entrypoint` образа — в новых версиях HA может отличаться; при сомнении используйте Additional CA.

### Способ C — `docker exec` (разово)

```bash
docker cp russian_trusted_root_ca_pem.crt <имя_контейнера>:/usr/local/share/ca-certificates/
docker cp russian_trusted_sub_ca_pem.crt <имя_контейнера>:/usr/local/share/ca-certificates/
docker exec <имя_контейнера> update-ca-certificates
docker restart <имя_контейнера>
```

---

## Home Assistant Core (venv)

Core установлен **напрямую в ОС** (часто Raspberry Pi OS, Debian, Ubuntu). Достаточно обновить системное хранилище CA на **той же машине**, где запущен Home Assistant.

### Debian / Ubuntu / Raspberry Pi OS

```bash
sudo cp russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Перезапустите службу Home Assistant (systemd):

```bash
sudo systemctl restart home-assistant@<ваш_пользователь>
# или как у вас назван сервис: homeassistant, home-assistant и т.д.
```

Проверьте SSL к `platform-api2.max.ru` ([п. 1](#1-из-контейнера-или-хоста-где-работает-ha) или [п. 3](#3-на-linux-хосте-core)), **затем** обновите MaxNotify до **2.1.0+**.

### Fedora / RHEL / CentOS / AlmaLinux

```bash
sudo cp russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust extract
```

### Arch Linux

```bash
sudo cp russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt /etc/ca-certificates/trust-source/anchors/
sudo trust extract-compat
```

---

## Другие варианты

### Home Assistant в Kubernetes / Helm

Добавьте сертификаты в образ или ConfigMap и смонтируйте в `/usr/local/share/ca-certificates/`, затем `update-ca-certificates` в initContainer или entrypoint. Либо используйте Additional CA в смонтированном `/config`.

### Home Assistant на Windows (Core в WSL или нативно)

- **WSL2 + Core:** установите CA внутри дистрибутива Linux (как в разделе Core для Debian/Ubuntu).
- **Нативный Python на Windows:** импортируйте `.crt` в «Доверенные корневые центры сертификации» (текущий пользователь или локальный компьютер) через `certmgr.msc` или двойной щелчок по файлу. Перезапустите Home Assistant.

### Home Assistant на macOS (Core)

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain russian_trusted_root_ca_pem.crt
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain russian_trusted_sub_ca_pem.crt
```

Перезапустите процесс Home Assistant.

### NixOS и прочие нестандартные установки

Добавьте сертификаты НУЦ в trust store вашей сборки (например, через `security.pki.certificateFiles` или переопределение пакета `certifi`). Универсальной команды нет — ориентируйтесь на документацию дистрибутива.

---

## Проверка после установки

> **Где именно запускать команды на HAOS.** Дополнение **«Терминал»** / **Terminal & SSH** — отдельный контейнер; **Additional CA** кладёт сертификаты в **`homeassistant`**. Поэтому:
>
> | Команда в терминале дополнения | Результат |
> |--------------------------------|-----------|
> | `curl https://platform-api2.max.ru/...` **напрямую** | часто `unable to get local issuer certificate (20)` — это **нормально**, не ошибка MaxNotify |
> | `docker exec homeassistant curl https://platform-api2.max.ru/...` | проверка **там же**, где работает интеграция; если код **200**/**401** без SSL-ошибки — всё настроено |
>
> Если сообщения через MaxNotify уже уходят, с сертификатами всё в порядке; `docker exec` нужен только для явной проверки.

### 1. HAOS / Docker / Supervised — контейнер `homeassistant`

Команду можно выполнить из дополнения **«Терминал»** (если там доступен `docker`), из [отладочного SSH](https://developers.home-assistant.io/docs/operating-system/debugging/) (**22222** → `login`) или с любого хоста, где виден контейнер `homeassistant`:

```bash
docker exec homeassistant curl -sS -o /dev/null -w "%{http_code}\n" \
  "https://platform-api2.max.ru/me?v=1.2.5" \
  -H "Authorization: <ваш_токен>"
```

Ожидается **200** (верный токен) или **401** — главное, **без** ошибки SSL.

Проверка цепочки TLS:

```bash
docker exec homeassistant openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru </dev/null 2>&1 | tail -5
```

Нужно `Verify return code: 0 (ok)`.

Проверить, что CA попали в trust store контейнера:

```bash
docker exec homeassistant grep -i "Russian Trusted" /etc/ssl/certs/ca-certificates.crt
```

**Не путайте две команды:** прямой `curl` в shell дополнения и `docker exec homeassistant curl ...` — это разные окружения; для проверки MaxNotify нужен второй вариант.

**Если `docker exec homeassistant curl` тоже падает с SSL**, а сообщения не уходят — см. [Если ошибка осталась](#если-ошибка-осталась).

### 2. В Home Assistant

1. Если вы ещё **не** обновляли MaxNotify — сначала завершите настройку сертификатов (п. 1 выше), затем обновите интеграцию до **2.1.0** и выше.
2. **Настройки → Устройства и службы → MaxNotify → Перенастроить** — введите токен снова или дождитесь успешной проверки.
3. Отправьте тестовое сообщение через службу `max_notify.send_message`.

### 3. Home Assistant Core (venv на хосте Linux)

```bash
curl -v "https://platform-api2.max.ru/me?v=1.2.5" 2>&1 | grep -E "SSL|subject|issuer|error"
trust list | grep -i russian
```

---

## Если ошибка осталась

1. **Порядок:** если MaxNotify уже на **2.1.0+**, но SSL не настроен — добавьте сертификаты по инструкции выше, перезапустите HA; обновление интеграции откатывать не обязательно. Если ещё на старой версии — **сначала** сертификаты, **потом** обновление до **2.1.0+**.
2. **Оба** сертификата (root и sub) добавлены, после установки был **полный перезапуск** Home Assistant.
3. Для HAOS/Docker проверьте именно **контейнер** `homeassistant`, а не только хост:

```bash
docker exec homeassistant grep -i "Russian Trusted" /etc/ssl/certs/ca-certificates.crt
```

4. Включите отладочный лог MaxNotify (`custom_components.max_notify: debug` в `configuration.yaml`) и посмотрите **Настройки → Система → Журнал**.
5. Режим **notify.a161.ru** не ходит на `platform-api2.max.ru` — если используете его, эта инструкция не применяется.
6. Вопросы по API Max: [чат поддержки business](https://max.ru/business_support_bot), документация: https://dev.max.ru/docs-api

---

## Связанные материалы

- [README MaxNotify](../README.md) — настройка официального API
- [Документация Max API](https://dev.max.ru/docs-api)
- [Additional CA для Home Assistant](https://github.com/Athozs/hass-additional-ca)
- [Отладка HAOS через SSH](https://developers.home-assistant.io/docs/operating-system/debugging/)
