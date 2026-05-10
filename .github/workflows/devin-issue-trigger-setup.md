# Настройка триггера Devin из GitHub Issues

## Как это работает

Когда кто-то пишет `@devin-bot` в комментарии к issue, GitHub Action автоматически создаёт сессию Devin через API с контекстом issue (заголовок, описание, комментарий).

## Шаг 1: Создать Service User в Devin

1. Зайди на [Settings > Service users](https://app.devin.ai/settings/service-users)
2. Нажми **Create service user**
3. Имя: например, `GitHub Issue Trigger`
4. Роль: **Member** (достаточно для создания сессий)
5. Нажми **Generate API key** и скопируй ключ (`cog_...`)
6. Запомни **Org ID** — он виден на той же странице (формат `org-...`)

## Шаг 2: Добавить секреты в GitHub-репозиторий

1. Зайди в репозиторий `hleserg/atman` → **Settings** → **Secrets and variables** → **Actions**
2. Добавь два секрета:
   - `DEVIN_API_KEY` — API ключ сервисного пользователя (`cog_...`)
   - `DEVIN_ORG_ID` — ID организации (`org-...`)

## Шаг 3: Добавить workflow файл

GitHub не позволяет Devin пушить workflow-файлы (нужен `workflow` scope). Добавь файл вручную:

1. В репозитории `hleserg/atman` создай файл:
   `.github/workflows/devin-issue-trigger.yml`
2. Вставь содержимое из приложенного файла

## Шаг 4: Проверить

1. Открой любой issue в `hleserg/atman`
2. Напиши комментарий: `@devin-bot Пожалуйста, посмотри этот issue`
3. Зайди в **Actions** → увидишь запуск workflow
4. Зайди в [Devin](https://app.devin.ai) → увидишь новую сессию с контекстом issue

## Настройка

- **Ключевое слово**: по умолчанию `@devin-bot`. Можно изменить в строке `contains(github.event.comment.body, '@devin-bot')` в workflow
- **PR-комментарии**: workflow срабатывает только на issue-комментарии, PR-комментарии пропускаются (строка `!github.event.issue.pull_request`)
