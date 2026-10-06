# Примеры, а не installer

`strata-qwen.observed.json`: сохранённые настройки benchmark, только пути нормализованы. **0.0.0.0 без API key, api_monitor=true — небезопасный исследовательский профиль.**

`strata-qwen.loopback.example.json`: предлагаемая копия с localhost и monitor off. Не тестировалась в этой кампании; auth/TLS не добавляет.

`strata-qwen.service.example`: observed unit с нормализованными путями/пользователем, Description исправлен на 3 GPU. Не содержит проверенных boot dependencies на mount/unlock и не создаёт пользователя strata.

Корни `/opt/strata`, `/srv/models/strata-qwen` и User=strata — публичные примеры, не требования исходного стенда. Сначала сверить наличие артефактов и права; не копировать юнит и не перезапускать службу вслепую.
