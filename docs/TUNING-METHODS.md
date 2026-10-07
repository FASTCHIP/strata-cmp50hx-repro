# Методика tuning-кампании Strata

Результаты завершённой кампании: [TUNING-2026-10-07.md](TUNING-2026-10-07.md). Профили: [profiles.json](../results/2026-10-07/profiles.json). Числа относятся к pinned engine 0.1.39 + существующему synchronization patch; не к любому Strata HEAD.

## Проверка опубликованных данных без сервера

Из корня репозитория:

```sh
python3 tools/tuning/aggregate.py
python3 -m unittest discover -s tools/tuning/tests -v
```

Stdlib-only. Первый скрипт проверяет полноту случаев/повторов, SSE DONE, отсутствие reasoning, реальную длину выхода, точный input-token count и отсутствие prefix reuse в измеряемых solo-запросах; затем пересчитывает summary и требует точного совпадения. Warmup может повторять smoke-префикс и исключается из uncached-таблиц. Второй запускает 15 локальных тестов клиента и генератора на mock HTTP/token-counter, без GPU и SSH. Это не проверка модели.

184 опубликованные записи = 162 screening-измерения + 9 warmup + 4 long + 6 concurrent-запросов + 3 concurrent-group. Из оригиналов удалены request bodies, generated text, raw SSE, response/run IDs, внутренние статусы/адреса/UUID. Числовые usage/timings/client wall/TTFT сохранены. Сводка, заново рассчитанная из минимизированных данных, точно совпала с исходной после удаления только run_id. Старый PUBLICATION.json — исторический manifest первоначальной публикации 6 октября; новые файлы и изменённый README учитывает results/2026-10-07/PUBLICATION.json.

## Построение входов на собственной установке

Генератор адаптирован только по путям; логика фактически использовавшегося точного счёта сохранена. Он импортирует `tools.strata_tokenizer` и `serve.server` из вашей pinned Strata checkout, использует pack `packs/qwen20/tokenizer`, effort_end=true и enable_thinking=false. Создаётся `Service(None, ...)`: Engine не запускается. Нужны зависимости исходной Strata установки; это не stdlib-only операция.

```sh
export STRATA_ROOT=/opt/strata
export STRATA_FIXTURES="$PWD/fixtures.json"
export PYTHONPATH="$STRATA_ROOT"
"$STRATA_ROOT/.venv/bin/python" tools/tuning/make_fixtures.py > fixture-generation.json
"$STRATA_ROOT/.venv/bin/python" tools/tuning/make_fixtures.py --verify-only --no-bpe-cache > fixture-verification.json
```

Модель/pack/tokenizer должны соответствовать baseline. Генератор строит три уникальных повторения каждого случая: short code/prose,4096/32768 code/prose,122880/261120 code. Exact fitting — бинарный поиск числа background records и ограниченный поиск padding, затем полный повторный encode экспортированного файла. Содержимое фикстур синтетическое; качество retrieval таким тестом не измеряется.

## Реальный клиентский тест — только с разрешения владельца сервера

Следующие команды дают реальную нагрузку. Они сами не переключают профили, не ставят rescue timer, не проверяют hashes оригинального сервиса. Не выполнять на общей рабочей службе без окна обслуживания. Каждый профиль готовить отдельно по profiles.json; model/packs/GPU/layers/KV/context/env сохранять. Один engine за раз. Выделить защищённый loopback endpoint, убедиться loaded=true/in_flight=0, свежий smoke известного ответа и свободные GPU перед запуском нового профиля. В original campaign использовался отдельный loopback-порт с явным `--port` в launcher; поле port в config не было достаточным.

```sh
python3 tools/tuning/bench.py --base http://127.0.0.1:18080 --out R-screen.jsonl --label R --fixtures fixtures.json --mode screen
python3 tools/tuning/bench.py --base http://127.0.0.1:18080 --out R-long.jsonl --label R --fixtures fixtures.json --mode long
python3 tools/tuning/bench.py --base http://127.0.0.1:18080 --out R-concurrent.jsonl --label R --fixtures fixtures.json --mode concurrent
python3 tools/tuning/bench.py --summarize R-screen.jsonl --labels R --mode screen
```

Отдельный новый файл для каждой попытки; существующие JSONL не дописывать и не смешивать с повторным прогоном. Benchmark сохраняет оригинальные private bodies/text/SSE/status и GPU telemetry — не выкладывайте его raw output без минимизации. Prefix count должен быть0 у измеряемых solo; thinking/token reasoning должны отсутствовать. Локальный max_tokens — потолок, не обещанная длина; EOS записывается фактически. Short output в этой кампании мог завершаться на204/205 токенах вместо256.

Порядок original campaign: R,T8,L,D2,D3,D6,P1,P4,Z. Внутри screening порядок шести случаев вращается, профили не рандомизированы. Из screening выбираются R и кандидаты с геометрическим выигрышем>2% отдельно по decode и prefill; Z не кандидат. Далее long для R/P1; затем concurrent R/P1/Z. Между фазами оригинал восстанавливается с проверкой fingerprint/readiness/реальной генерации. Near-limit261120 оставляет запас под128 output и служебные ограничения.

## Ресурсы, восстановление и интерпретация

Host-specific controller/restore/night scripts намеренно не публикуются как универсальные root-скрипты: они привязаны к конкретным именам unit, путям и immutable baseline. Для собственного runner требуются exclusive lock, independent rollback timer, supervisor с ограничением времени, проверка MainPID=0 и пустых compute apps перед следующим engine, hashes исходного config/unit/exe, актуальный kernel cursor и реальный known-answer smoke при возврате. При OOM/Xid/AER/illegal access остановить нагрузку, сохранить доказательства и вернуть эталон; не повторять циклически. BrokenPipe при intentional stop Python launcher может оставить systemd failed при MainPID0: failed сам по себе не доказывает GPU ошибку.

Телеметрия и текущий kernel-window использовались для контроля; private system logs/UUID в эту публикацию не включены. Факт historical restoration опубликован минимально в completion.json, текущий статус службы он не подтверждает.

Серверные prefill/decode у solo и client wall/TTFT — разные метрики. На двух клиентах считать реальные summed output tokens / wall всей пары; не складывать predicted_per_second из DONE/BDONE при переключениях solo↔batch. Long и concurrency здесь n=1: небольшие отличия требуют повторов. Не интерпретировать Z как full-MTP-off. Не рекламировать screening-выигрыш P1 как long-context улучшение.
