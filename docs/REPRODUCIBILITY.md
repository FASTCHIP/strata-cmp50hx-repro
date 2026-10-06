# Воспроизведение: информация существующей установки

Здесь описаны зафиксированные параметры и наблюдавшиеся команды, а не протестированная процедура clean install. Новой сборки для публикации не было. Исполняемый файл и веса не распространяются; наличие только этого репозитория недостаточно для запуска модели.

## Источники

[Манифест](../manifests/sources.json) фиксирует:

- Strata `6f32ec070f23ced9f50e704d854d775da52591ab` + [verify.patch](../patches/verify.patch).
- llama.cpp/ggml `3cf03257f219afbe7334045ff7c6a06ac68c627d`: 1376 файлов используемого ggml совпали с upstream Git blob hashes.
- GGUF `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`, revision `ed59f92082b1e93c0e96d60a8b11aab089b52f09`, каталог `Q2_0`. Оба локальных шарда полностью прочитаны; sizes/SHA256 совпали с LFS metadata. [Результат](../manifests/model-verification.json).
- MTP `Qwen/Qwen3.8-Flash-Next`, pinned default fetch-script revision `de4b8e4d43b917e7706784d8bb445c9af86a3540`. Это не независимая полная перепроверка исходных MTP-тензоров. В изученном `tools/mtp_fetch.py` есть fallback на `main` после 404: для строгого воспроизведения его нельзя принимать молча. Следует задавать `STRATA_MTP_REVISION`, проверять inventory revision и выполнять `verify`.

Не использовать upstream `main` вместо указанных revisions и не определять ggml revision через `git rev-parse` в распакованном каталоге без собственного `.git`: он может вернуть HEAD родительского Strata.

## Наблюдавшаяся сборка

Сохранённый бинарник engine 0.1.39 имеет SHA256:

```
7436b64d65319b5b7483c15a43fb45e7c12e510ad7be33f036b2bb963b60c5a1
```

По CMakeCache существующей установки: Release, Ninja, `STRATA_ENABLE_CUDA=ON`, `STRATA_BUILD_TESTS=OFF`, `CMAKE_CUDA_ARCHITECTURES=75`, `STRATA_ISA_FLOOR=avx`, pinned `STRATA_GGML_DIR`, nvcc `/usr/local/cuda-12.8/bin/nvcc`. Наблюдавшийся build target — `strata`, parallel build `-j 4`. Эти сведения не обещают байт-в-байт результат будущей сборки.

Локальный патч освобождает PLE flag и исключает ожидание per-layer doorbells для all-resident batch. Он сохранён как observed local change, не объявляется принятой upstream правкой. Перед применением к другой ревизии обязательна проверка контекста. При публикации `git apply --check` прошёл на исходном pinned файле; компиляция не выполнялась.

## Native pack

Рабочий pack назывался `packs/qwen20`. В подготовительных скриптах существующей установки наблюдались команды:

```bash
python tools/iq_pack.py --gguf <first-shard> --out <packdir>
python tools/iq_pack.py --gguf <first-shard> --out <packdir> --experts-bin
python tools/strata_tokenizer.py --gguf <first-shard> --out <packdir>
```

Здесь `<...>` — обозначения путей, не готовая shell-команда. Эти конвертации при публикации не запускались.

Исходный native experts size: 33973862400 bytes. Рабочий файл: 33975244800 bytes; разница 1382400 bytes соответствует дополнительной blob-записи mmap arena. На хосте около 15 ГиБ RAM: fallback к огромной anonymous arena неприемлем. Не копировать слепой `truncate` из произвольной строки лога: размер/padding должен согласовываться с exact pack metadata и loader pinned версии. Файл `experts.bin.src.json`, dense/index/tokenizer и expert profile — часть зависимостей, а не факультативные файлы.

## MTP runtime

Наблюдавшиеся команды:

```bash
python tools/mtp_fetch.py fetch --out <mtpdir>
python tools/mtp_fetch.py verify --out <mtpdir>
python tools/mtp_pack.py --src <mtpdir> --experts q2_0 --out <mtpdir>/mtp-q2_0.gguf
python tools/mtp_rt.py --gguf <mtpdir>/mtp-q2_0.gguf --out <mtpdir>/rt
```

Runtime `rt`: dense.bin 116099072 bytes; experts.bin 707788800 bytes; draft_vocab.bin 235852 bytes. Доступные hashes перечислены в манифесте. Успешная генерация текущей установки проверена; новая загрузка и конвертация в рамках публикации не проверялись.

## Конфигурация и systemd

[Observed JSON](../configs/strata-qwen.observed.json) сохраняет параметры engine, но нормализует корневые пути: `/opt/strata` и `/srv/models/strata-qwen`. Это не побайтовая копия приватного исходника.

[Пример юнита](../configs/strata-qwen.service.example) нормализует пользователя в `strata` и исправляет Description с «4 GPU» на фактически использованные «3 GPU». Такой пользователь/директории должны существовать при установке. Никакие службы для публикации не менялись.

Порт в `ExecStart` задан явно: `--port 8080`. Поле config.port само по себе не переопределяет argparse default 8095 в изученном launcher. `parallel=2` превращается в engine `--batch 2`; это слоты общего engine, не два engine. `fit_max_tokens=true` уменьшает слишком большой output budget по остаточному контексту, но не обрезает prompt. `reasoning_budget_tokens=0` не означает thinking off.

Observed unit использует `Type=simple` и только `After=network.target`. Mount и существующая CMP unlock/rescan chain не включены в зависимости. Автозапуск после reboot не испытывался; состояние `active` само по себе не означает загруженную модель. Нужны `loaded=true` и успешная генерация.

Loopback-пример отличается только `host=127.0.0.1` и `api_monitor=false`. Он предлагается для ограничения доступа, но не был применён к обследуемому серверу. Дополнительные изменения boot dependencies, auth/TLS и установочные действия здесь не выполняются.

## Что понадобится дополнительно

Для запуска на другой машине нужны совместимое железо, уже подготовленный unlock CMP, подходящий бинарник/библиотеки, модели, native pack, MTP runtime и адаптация путей. В этом репозитории нет этих крупных артефактов и нет автоматического register-write/unlock installer.

Проверка новой сборки, чистой установки, boot-chain и отката остаётся отдельной работой. Результаты существующей установки не выдаются за подтверждение этих этапов.
