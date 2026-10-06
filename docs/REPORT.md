# Публичная копия отчёта

Внутренний адрес заменён на BENCHMARK_HOST; пути нормализованы. Упомянутые исходные журналы, архивы и полные ответы хранятся в частном аудите и не все входят в этот репозиторий. Публичные числовые доказательства: ../results/2026-10-06/. Снимок не является проверенным установщиком.

# Обследование Strata на BENCHMARK_HOST

Дата: 6 октября 2026, MSK. Запросы benchmark: 23:30:49–23:40:27. Основание: живой сервер, его исходники/конфигурация, сырые HTTP-ответы, журналы и телеметрия. Это не сравнение с llama.cpp и не clean-room установка.

## Состояние и запуск

`strata-qwen.service` работает, включён в автозапуск. Финальная проверка: `active/running`, MainPID693395, NRestarts0, API loadedtrue/in_flight0. Engine0.1.39. OpenAI `/v1/chat/completions`, Anthropic `/v1/messages` и OpenAI `/v1/responses` ответили «Canberra» на известный вопрос с корректным отключением thinking. SSE завершался `[DONE]`. В проверенном интервале журнал ядра не содержал новых записей (Xid/OOM/AER не обнаружены).

Запуск в журнале: systemd23:26:05, начало загрузки23:26:07, готовность23:29:34 — 3мин29с от старта юнита. Это наблюдение одного запуска на существующих файлах и неизвестном состоянии дискового кеша, не гарантированное время холодного старта. Type=simple считает юнит started до загрузки модели; readiness нужно проверять отдельно.

Узел: Ubuntu24.04.4, Python3.12.3, XeonE5-2620v0 (6C/12T, AVX, безAVX2/FMA/F16C), около15GiB RAM. Driver610.43.03; бинарник связан с libcudart/cuBLAS CUDA12.8. GPU0–2: CMP50HX по20480MiB, Gen2x8; GPU3:10240MiB, Gen2x4 и не используется этой моделью.

## Фактический профиль

- Strata Git HEAD `6f32ec070f23ced9f50e704d854d775da52591ab` + локальный `patches/verify.patch`.
- Engine SHA256 `7436b64d65319b5b7483c15a43fb45e7c12e510ad7be33f036b2bb963b60c5a1`.
- Модель `Qwen3.8-Flash-Next-GSQ-RCO-Q2_0`, два GGUF, native-пакет `packs/qwen20`, второй шард указан через `--ple-gguf`.
- GPU[0,1,2], границы layer_split16,32: по16 из48 слоёв. Description юнита говорит4GPU, но реальность3GPU.
- Контекст262144, KVint8, prefill2048, parallel2. Python добавляет engine `--batch 2`; это два слота общего движка.
- expert_cacheauto, pcie_frac0, vram_reserve600MiB, trim_stage_weights. INFO:24576 expert slots,32400MiB expert cache; batch-журнал сообщает CPU experts0 и PCIe0 на выполненных decode-окнах.
- MTP `--spec 4`, spec_min_p0.5, `data/mtp/rt`; INFO отдельно показывает spec6,mtp_max4,lookup3. Не путать эти поля.
- Env: STRATA_ARENA_MMAP1, STRATA_BF16_TC1, STRATA_STAGE_TRIM1; LimitMEMLOCKinfinity/LimitNOFILE65536.
- API8080/0.0.0.0, ключ отсутствует, api_monitortrue, visionfalse. Алиасы strata,coder,qwen3-coder.
- Обычно temperature0.7/top_p0.9/top_k32/min_p0.02; reasoning_budget8192. Соседнего shared-settings файла не найдено. В тестах temperature0, thinking выключен явно.

## Методика и результаты

24 сохранённых нагрузочных ответа: warmup1, short3,4K3,32K3,120K2,250K1, три пары concurrent(6), source-code3, prefix-cache control2. Дополнительно три успешные финальные протокольные проверки, одна проба Responses с неподходящим thinking-параметром и одна первоначальная smoke-проверка; финальный activity.requests29 совпал с этим числом. Все нагрузочные запросы успешны; основной ряд и concurrent выдали ровно512 токенов. Один source-code запрос завершился естественно на401, остальные на512 — это отражено в ../results/2026-10-06/summary.json.

Вход основного ряда — детерминированная случайная последовательность из16 технических слов; уникальный начальный nonce исключает prefix reuse. Для всех solo-замеров таблицы проверено cache_n0. Это тест длины контекста/производительности, не доказательство качества long-context retrieval. Дополнительный code-case использует100000 символов публичного server.py. Disable thinking проверен по отсутствию reasoning_content. PP и decode ниже — серверные фазы, TTFT — реальная клиентская задержка до первого текстового фрагмента.

| Реальные входные токены | Повторы | Выход | PP ток/с, медиана | Decode ток/с, медиана | TTFT с, медиана |
|---|---:|---:|---:|---:|---:|
|241–247|3|512|262.0|72.9|0.97|
|4119–4121|3|512|1156.6|71.5|3.68|
|32116–32121|3|512|1949.6|68.9|17.21|
|120120–120121|2|512|2107.0|69.0|59.64|
|250121|1|512|1928.5|59.7|135.06|
|24862–24863, исходный код|3|401–512|1774.3|76.9|14.38|

Диапазоны decode: short69.8–73.9;4K70.1–73.7;32K66.6–68.9;120K66.6–71.4; code73.7–80.3. 250K — один прогон, 143.62с полный ответ. На длинном запросе использовано250121 входных токенов, не весь262144 лимит.

### Два одновременных клиента

Три пары: каждый примерно4.1K входа +512 выхода. Полное время пары23.09/22.63/21.87с. Суммарный выход1024 токена, end-to-end throughput44.34/45.24/46.81 ток/с, медиана45.24. Эта величина ВКЛЮЧАЕТ prefill/admission и не является чистым decode. Первый клиент TTFT3.68–3.91с, второй10.52–10.84с; следовательно prompt admission не мгновенно параллелен.

Сам engine batch log показывает54.2/54.7/55.1 rows/s с включённым admission — и это ещё третья метрика, не1024/clientwall. Чистый сопоставимый concurrent decode rate в этой серии отдельно не измерялся.

Основной вывод: parallel2 работоспособен, но на этой нагрузке не удваивает пропускную способность. Solo после4K полного prefill даёт около47.3 output ток/с end-to-end; две заявки дают45.2 суммарно. Не смешивать с solo decode71.5.

Критичная ловушка измерений: при новом клиенте Strata переводит solo GEN в batch, затем может вернуться в solo. Ответные timings отражают последний DONE/BDONE-сегмент, а не сумму всех фаз. Например после512 выходных токенов timing.predicted_n может описывать лишь110–111 хвостовых токенов; одно поле predicted_per_second достигло106.4, но весь ответ гораздо медленнее. Для concurrent используются usage и клиентский wall-clock, а не сумма этих скоростей.

### Prefix cache и speculation

Повтор точного4K запроса: первый cache_n0/prompt_n4120/prompt_ms3518.7; повтор cache_n4113/prompt_n7/prompt_ms88.1. Decode оба72.2 ток/с. Значит cached TTFT не годится как полный PP-бенчмарк.

Принятие draft-токенов (отношение сумм accepted/offered) около58–67% в основном ряду и72.3% в code-case. В логах есть suffix/lookup drafts. Это подтверждает работу speculation, но её выигрыш относительно spec-off не измерен; отдельного MTP-off A/B и сравнения качества с референсом не было.

## Ресурсы и устойчивость

27 baseline-телеметрических снимков: peak GPU0/1/2=17301/17309/17863MiB, максимум температуры66/61/55°C. GPU3 память0. Минимальный MemAvailable около10.06GiB. Эти пики получены с интервалом опроса и не доказывают абсолютный максимум; continuous followup-телеметрия отдельно не велась. Финальный GPU memory17307/17313/17873MiB, дополнительный небольшой рост после followup.

Финальный MemoryPeak cgroup14382772224 bytes включает учитываемый файловый кеш; это не равнозначно нереклеймируемому RSS. Warning о31.6GB experts против16GB RAM в launcher не означает реальный OOM: здесь включён mmap. Однако режим зависит от native-файла и невозможности fallback в огромную anonymous arena.

## Риски и контракт launcher

1. Нет auth/TLS при listen0.0.0.0; monitor открывает сохранённые промпты/ответы достижимому клиенту, а JSON-management endpoints позволяют менять состояние. Доступ с машины обследования без ключа подтверждён; доступность из Интернета не проверялась. Host/Origin checks не заменяют ACL. Безопасный публичный рецепт должен использовать loopback/VPN/reverse proxy и секрет отдельно. На живом сервере это не изменялось.
2. Unit имеет только After=network.target, без явной зависимости от CMP unlock/rescan и mount. Это потенциальная гонка boot; чистый reboot-тест в обследовании не проводился.
3. `--port 8080` в ExecStart обязателен: config.port в изученном main не переопределяет argparse port (default8095).
4. `fit_max_tokens=true` уменьшает слишком большой лимит ответа до доступного контекста; prompt не обрезает. Лимит включает reasoning. reason_budget0 не отключает thinking.
5. `/slots` — один synthetic compatibility slot, не правдивое число engine batch slots; смотреть metrics.live.slots/status.concurrency.
6. Shutdown не гарантирует drain клиентов; Engine.close делает QUIT, затем terminate/kill с таймаутами. engine_silence_s600 не является общим deadline для всех batch-wait путей.
7. Для `/v1/responses` thinking отключается `reasoning: {"effort":"none"}`, а chat_template_kwargs из ChatCompletions этим endpoint не используется. Проба с32 output tokens и лишь chat_template_kwargs дала incomplete и32 reasoning tokens без финального текста; с правильным reasoning.effort — completed/Canberra, reasoning_tokens0. Это контракт endpoint, не отказ модели.
8. `pipeline_qwen.sh` нельзя публиковать как готовый универсальный installer: readiness проверяется лишь HTTP-доступностью, padding берётся из произвольной строки лога, затрагиваются другие сервисы, меняется enabled-state. Нужен проверяемый идемпотентный шаг с pack metadata и rollback.

## Воспроизведение и границы доказательств

Полный перечень в REPRODUCIBILITY.md. Исходники/юнит/патч и CMake flags сохранены. Реально используемый ggml независимо проверен против pinned upstream3cf03257: все1376 файлов совпали по Git blob hash. Оба GGUF полностью прочитаны и проверены SHA256 после окончания benchmark: они совпали с LFS metadata pinned HF revision ed59f92082b1e93c0e96d60a8b11aab089b52f09. Итоговый источник истины — ../manifests/model-verification.json и лог.

Не проверялись: clean bootstrap на новой машине, новый build/binary, reboot-chain, двухклиентный262K контекст каждому, vision, tool-calling, качество ответов/референсные logits, MTP-off A/B, длительная overnight-устойчивость. Этот отчёт составлен до публикации; здесь опубликована информация существующего обследования, без новой сборки или повторных нагрузочных тестов.
