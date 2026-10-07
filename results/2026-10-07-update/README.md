# Engine update campaign — 2026-10-07

Отдельно от sibling tuning `../2026-10-07/` и аудита `../2026-10-06/`.

Восемь allowlisted JSONL: old/new × smoke/screen/long/concurrent. На плечо1/19/1/3 строки; concurrent включает две request rows и одну group row. Числа usage/timings/client wall/TTFT/token-window сохранены; diagnostic cache/actual output lengths не округлены. Nonempty/reasoning/known-answer — флаги, вычисленные до удаления текста.

COMPARISON.json воспроизводится полностью офлайн, включая все summaries; из оригинальной COMPARISON удалены только nonnumerical run IDs. PAIR-VALIDATION — отдельная проверка приватных оригиналов, не утверждение о независимо воспроизводимой публичной text equality.

PUBLICATION.json покрывает новые campaign-файлы, новый offline verifier, новые документы и обновлённый общий README; исключает сам себя. Ранее опубликованные manifest остаются историческими снимками и не описывают новую редакцию общего README.

```sh
python3 tools/update/aggregate.py
```

Команду запускать из корня репозитория. Network/GPU не нужны.
