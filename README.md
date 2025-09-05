# Аукционный бот: автодеплой в Yandex Cloud (шаг за шагом)

Этот репозиторий уже готов к автодеплою: Docker + Yandex Cloud Serverless Containers + GitHub Actions.

## Что потребуется
1) Аккаунт в Telegram и токен бота от @BotFather.  
2) Аккаунт в Yandex Cloud (бесплатный тариф подходит).  
3) Аккаунт на GitHub.

---

## 1. Создаём бота в Telegram
- Откройте @BotFather → `/newbot` → придумайте имя и получите **BOT_TOKEN** (что-то вроде `123456:ABC...`).

## 2. Заливаем этот код в GitHub
- Создайте новый репозиторий на GitHub (кнопка **New**).
- Загрузите все файлы отсюда (или просто перетащите архив и распакуйте).
- Убедитесь, что есть файлы: `bot.py`, `bot_webhook.py`, `requirements.txt`, `Dockerfile`, `.github/workflows/deploy.yml`.

## 3. Готовим доступ к Yandex Cloud
### Вариант A: через **Cloud Shell** (без установки на компьютер)
- Зайдите в [Yandex Cloud Console](https://console.cloud.yandex.ru/) → запустите **Cloud Shell** (значок терминала).
- Выполните команды по очереди:

```bash
# Папка по умолчанию уже выбрана, но на всякий случай:
yc config list

FOLDER_ID=$(yc config get folder-id)
CLOUD_ID=$(yc config get cloud-id)

# Создаём сервисный аккаунт:
yc iam service-account create --name auction-bot-sa
SA_ID=$(yc iam service-account get --name auction-bot-sa --format json | jq -r .id)

# Выдаём роли:
yc resource-manager folder add-access-binding --id $FOLDER_ID \
  --role container-registry.admin --service-account-id $SA_ID
yc resource-manager folder add-access-binding --id $FOLDER_ID \
  --role serverless.containers.editor --service-account-id $SA_ID
yc resource-manager folder add-access-binding --id $FOLDER_ID \
  --role viewer --service-account-id $SA_ID

# Создаём ключ сервисного аккаунта и выводим в файл
yc iam key create --service-account-id $SA_ID --output key.json

# Посмотреть значения (скопируйте для GitHub Secrets):
echo "CLOUD_ID=$CLOUD_ID"
echo "FOLDER_ID=$FOLDER_ID"
echo "----- key.json (скопируйте всё содержимое) -----"
cat key.json
```

### Вариант B: установить `yc` локально
- Установите CLI:  
  `curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash && yc init`  
- Дальше те же команды, что в варианте A.

## 4. Добавляем секреты в GitHub
В вашем репозитории: **Settings → Secrets and variables → Actions → New repository secret**. Добавьте:
- `YC_SA_JSON` — **всё** содержимое файла `key.json`.
- `YC_CLOUD_ID` — значение из команды выше.
- `YC_FOLDER_ID` — значение из команды выше.
- `BOT_TOKEN` — токен из @BotFather.
- `WEBHOOK_SECRET` — любое слово, например `auction-secret-123`.

## 5. Запускаем автодеплой
- Сделайте любой коммит/пуш в ветку `main` (например, отредактируйте README и нажмите **Commit**).
- Вкладка **Actions** в GitHub: запустится задача **Deploy to Yandex Cloud**. 
- По завершении задача сама:
  - соберёт Docker-образ,
  - развернёт **Serverless Container**,
  - зарегистрирует **Webhook** в Telegram.

## 6. Проверяем бота
- Откройте ваш бот в Telegram (ссылка от BotFather) и напишите `/newgame`.
- В группе добавляйте ботa, пишите `/join`, можно `/addbot`, затем `/start`.

---

## Полезно
- Логи контейнера:
```
yc logs read --container-name auction-bot --follow
```
- Переменные окружения (секреты) меняются в GitHub → Secrets.  
- Состояние игры хранится в памяти контейнера. Нужна персистентность — добавьте базу (Redis/SQLite) и передайте настройки через `--env` в шаге деплоя.
