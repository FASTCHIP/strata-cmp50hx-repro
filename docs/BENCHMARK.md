# Проверка результатов и benchmark harness

## Опубликованные данные

Кампания `results/2026-10-06/` содержит 24 workload-записи: warmup 1, short 3, 4K 3, 32K 3, 120K 2, 250K 1, concurrent 6, code 3, prefix-cache control 2. Дополнительно API учёл 5 smoke/protocol/contract запросов; финально requests=29, in_flight=0.

Числовые `usage`, `timings`, клиентские `wall_s`/`ttft_s`, время записи и признак завершения SSE перенесены из исходного аудита. Полные сгенерированные тексты и response IDs исключены; `reasoning_present` вычислен из исходных SSE chunks. Это минимизированные evidence-записи, не полные HTTP-ответы. Телеметрия сохранена только как GPU-числа и `MemAvailable`; её 27 снимков относятся к baseline, а не ко всему followup.

Проверить без GPU и сети:

```bash
python3 tools/aggregate.py
```

Для отдельной копии данных: `python3 tools/aggregate.py <campaign-directory>`. Скрипт пересчитывает и записывает `summary.json` в указанном каталоге. Он проверяет exact count 24, лимиты вывода, SSE completion, отсутствие reasoning и cache_n=0 для solo.

## Повторный запуск — только вручную и на выделенном стенде

Эти команды создают длинные реальные запросы, включая 250K; не запускать на обслуживающем других пользователей сервере без согласования. При подготовке этой публикации они не выполнялись.

```bash
export NO_PROXY='*'
export STRATA_BASE_URL='http://127.0.0.1:8080'
export STRATA_OUTPUT_DIR='run-output'
python3 tools/benchmark.py
```

При необходимости ключ задаётся только через окружение `STRATA_API_KEY`, не через файл репозитория. Клиент явно отключает proxy lookup. Используются Python standard library, seed `1062026 + rep + scale`, 16 технических слов и уникальный начальный nonce; labels задают число слов, не гарантированное число токенов. Сравнивать реальные usage/timings.

Дополнительный code/cache/concurrent ряд требует точного входного файла — в исходной кампании первые 100000 символов сохранённого `serve/server.py` обследованной установки. Исходник в публикацию не включён:

```bash
export STRATA_SOURCE_FILE='/path/to/audited/serve/server.py'
python3 tools/followup.py
```

Followup запускается только после baseline DONE и при заданном STRATA_SOURCE_FILE. Изменённый входной файл даст другой code-case, даже если его имя совпадает. Скрипты перенесены из кампании с заменой hardcoded URL/путей на env и опциональным auth header; новая live-кампания этими публичными версиями не проводилась.

Данные нового запуска содержат полные ответы и НЕ являются готовыми к публикации: требуется отдельное удаление текстов/IDs и проверка секретов. Опубликованный aggregate рассчитан на минимизированный формат кампании; сначала подготовьте этот формат и телеметрию.

## Протоколы и интерпретация

Thinking off:

- Chat Completions: `chat_template_kwargs: {"enable_thinking": false}`.
- Anthropic Messages: `thinking: {"type": "disabled"}`.
- Responses: `reasoning: {"effort": "none"}`; ChatCompletions chat_template_kwargs здесь игнорируется.

Не считать короткий reasoning budget отключением thinking. Probe Responses с неподходящим параметром потратил 32 output tokens на reasoning и дал incomplete; правильный effort дал completed, Canberra, reasoning_tokens=0.

Для solo серверный `predicted_per_second` отражает decode-фазу. Для concurrent при смене режима timings могут описывать только последний сегмент: используйте `sum(completion_tokens) / pair_wall_s` и явно подпишите «включая prefill/admission». Это не чистая скорость concurrent decode. Prefix-cache hit измерять отдельно.
