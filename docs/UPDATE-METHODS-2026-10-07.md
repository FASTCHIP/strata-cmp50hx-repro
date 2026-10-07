# Методы: old/new engine update, 2026-10-07

## Scope

Измерялся HTTP/SSE путь самой Strata, не llama-bench. Engine0.1.39 (исходный runtime с локальным synchronization fix) сравнивался с engine0.1.40.3, upstream `d5ea7133741e67743c0e886bb426c0ce8d69cf6c`; эквивалент synchronization fix уже присутствует upstream. Model/native packs/MTP, GPU split, KV, slots, context, prefill и threshold не менялись. Build: CT200, CUDA12.8, sm75, AVX-only. Это completed update campaign, не новая tuning-матрица.

Плечи запускались в фиксированном порядке old→new; случайного чередования версий нет. Внутри screen порядок cases ротировался между тремя repetitions. Последовательность каждого плеча: smoke, warmup/screen, long, concurrent. После отдельного new test-runtime benchmark установленный штатный unit/profile выбирает новую версию; штатный unit намеренно оставлен OFF и после переключения не smoke-тестировался. Во время публикации никаких повторных аппаратных тестов или изменений GPU-стенда не выполнялось.

## Workloads and gates

ChatCompletions streaming: temperature0, seed42, thinking явно выключен `chat_template_kwargs.enable_thinking=false`, `stream_options.include_usage=true`. Code/prose fixtures: короткий вход139/133 токена, 4096 и32768 токенов; синтетические reference records и финальные code/prose задачи. Long122880 code input tokens, output ceiling128; screen/concurrent ceiling256, smoke/warmup ceiling64. Это тест ресурсов/скорости, не answer-quality или retrieval оценка. Старые серии с output512 не сопоставлять напрямую.

Каждое плечо: smoke1, warmup1, screen6×3, long1, concurrent2 requests плюс одна group запись. Проверены exact cases/repetitions, отсутствие duplicates, ok, DONE, nonempty, actual usage, finish_reason stop/length, отсутствие видимого/hidden reasoning, expected prompt lengths. Для measured solo cache_n=0. Warmup может повторять smoke prefix, сохраняется в raw, но исключается из медиан. Concurrent cache и last-segment timings сохраняются, но не являются uncached solo PP.

Bodies23 paired requests и solo generated text совпали. Concurrent prose generated text отличается при output256/256. Pair validation выполнена по приватным оригиналам; публикация хранит вывод проверки, а не body/text или их идентификаторы. Offline verification не доказывает text equality заново.

## Численные определения

- Client throughput каждой request = actual usage completion_tokens / полный client wall_s. Case summary = median ratios, не ratio median output / median wall. Wall, TTFT и token-window медианы считаются отдельно.
- PP = median timings.prompt_per_second; decode = median timings.predicted_per_second, только mode screen/long. Ключ сравнения включает mode: concurrent повторяет имена p4k cases, но не входит в solo medians.
- Concurrent = sum actual output tokens / group wall_s; не сумма individual throughput или returned predicted_per_second. Switching solo→batch→solo делает returned timings диагностикой последнего сегмента.
- Δ% = (new/old−1)×100. Числа публикуются без округления в JSON; округление только в markdown таблице. Long и concurrent имеют n=1; statistical significance не заявляется.

## Публичная минимизация и проверка

Allowlist включает labels/mode/case/repetition/warmup, expected prompt lengths, original numerical usage/timings, client wall/TTFT/token-window, SSE done/finish reason, actual output counts и group aggregates. Флаги nonempty/reasoning/known-answer вычислены до удаления generated text. Usage вложения ограничены cached_tokens/reasoning_tokens; timings — числовые cache/prompt/predicted/draft поля. Не копируются body/text/raw SSE, run/request IDs, private status/addresses/paths/UUID, credentials или miner arguments.

Публичная COMPARISON отличается от приватной только удалением nonnumerical run_id из concurrent groups (включая summaries). Пересчёт allowlisted rows дал полное object equality со всеми численными полями исходной сводки. Оригиналы не изменены. Artifact hashes названы old_engine/saved_baseline_engine/new_engine без private paths. FINAL-STATE содержит allowlisted checks, semantic aliases unit states, worker/share counts и состояние каждого измеренного плеча; это historical snapshot, не текущий online status.

Из корня репозитория, stdlib-only, без сети/сервера/GPU:

```sh
python3 tools/update/aggregate.py
python3 tools/aggregate.py
python3 tools/tuning/aggregate.py
python3 -m unittest discover -s tools/tuning/tests -v
```

Первая команда проверяет request/SSE/token/cache gates, counts, complete COMPARISON object equality и SHA256 нового publication manifest. Остальные проверяют, что historical evidence series и локальные mock/fixture tests не нарушены. Эти offline/mock проверки не тестируют заново inference, CUDA или численную корректность модели. Existing benchmark/fixture tools в `tools/tuning/` — opt-in live-load инструменты; при данной публикации запускалась только их offline verification/test часть. Hardware tests не повторялись.

Новый `results/2026-10-07-update/PUBLICATION.json` вычислен после завершения форматирования; он покрывает только новый campaign payload и изменённый общий README, исключая сам manifest. Root `PUBLICATION.json` и tuning manifest — historical snapshots своих публикаций, не актуальный полный manifest дерева. Исторические documents/data/configs оставлены без изменений.

## Ограничения

Нет overnight, полного262144-context test новой версии, clean install, reboot-chain, MTP-off A/B, retrieval/vision или общей model correctness проверки. Small fixed-order matrix допускает температурные/временные confounders. Short prose PP и TTFT регрессировали, несмотря на лучший full-client throughput. Build/runtime binaries, weights/packs и archives не распространяются. Observed listener/monitor settings из historical config не являются безопасным production default; требуется защищённый доступ, public exposure не проверялась.
