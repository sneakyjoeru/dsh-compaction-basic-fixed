# Набор для компакции dsh — «сжимать на N % окна модели», переживает апгрейды

Три части для **DeepSeek Harness (dsh)** web, снятые с рабочего NAS-деплоя:

| Часть | Что делает |
|---|---|
| `dsh-compaction-basic-fixed/` | Бэкенд компакции. **Стабильный загрузчик**: берёт перенесённую копию под установленную версию `dsh-compaction-basic` (три фикса для длинных сессий), а если её нет — поставочный пакет. Компакция никогда не «умирает» после апгрейда dsh. Накладывает живую настройку порога. |
| `dsh-compaction-threshold/` | Сама настройка: *сжимать при **N %** окна контекста маршрутной модели* — по умолчанию **80**, дробные значения допустимы (75.2), глобально **и для конкретной пары provider/model**. Применяется сразу, без перезапуска. |
| `patches/meter-compaction-percent.py` | Необязательный UI-патч всплывашки счётчика контекста: поле `Compact at [ 80 ] %`, порог в токенах для реально маршрутной модели, галочка `only for <model>`. Кольцо/процент показывают 100 % ровно на пороге. При смещении якорей в новой версии — пропускается с громкой строкой, сборку не ломает. |

## Зачем

- Поставочный `dsh-compaction-basic` держит headroom 65 536 токенов, поэтому на окне 131k сжимает
  на ~47 %, а не на 80 %. Здесь порог = `floor(min(ratio · W, W − O))`, где ratio — из настройки, а
  `W` — окно той модели, которая **реально обслуживает** сессию: это процент, никогда не число токенов.
- В длинных сессиях три поставочных проверки (хвост по routed-токенам, исчерпание обхода плотным
  выводом, сравнение оценки саммари с routed-размером) заставляли суммаризировать на каждом шаге —
  исправлено в копиях.
- Копия поставочного пакета привязана к одной версии dsh; после апгрейда преflight dsh отключал
  строку (зафиксировано 2026-10-23). Загрузчик убирает этот сценарий: `engines.dsh` с открытым
  диапазоном + проверка версии при импорте + откат на поставочный пакет + одна строка в логе.

## Установка — десктоп (нативный dsh)

1. Клонировать в домашний каталог dsh и связать bare-импорты с пакетами самого dsh:

   ```sh
   git clone https://github.com/sneakyjoeru/dsh-compaction-basic-fixed "$DSH_HOME/plugins/dsh-compaction"
   cd "$DSH_HOME/plugins/dsh-compaction"
   DSH_NM="$(dirname "$(node -p 'require.resolve("@deepseek-ai/dsh/package.json")')")/node_modules"
   ln -sfn "$DSH_NM" dsh-compaction-basic-fixed/node_modules
   ln -sfn "$DSH_NM" dsh-compaction-threshold/node_modules
   node dsh-compaction-basic-fixed/verify.mjs      # ALL PASS
   ```

2. `$DSH_HOME/profiles/<profile>/cordis.patch.yml` (абсолютные пути):

   ```yaml
   # хост-план — настройка
   - insert:
       - id: compaction-threshold
         name: /АБС/ПУТЬ/plugins/dsh-compaction/dsh-compaction-threshold/index.mjs
   # план пресета — внутри группы `compaction` вашего агентского пресета
   # (строка compaction-basic на хост-плане — мёртвая конфигурация для стандартного пресета)
   - id: compaction-basic
     name: /АБС/ПУТЬ/plugins/dsh-compaction/dsh-compaction-basic-fixed/index.mjs
     config: { thresholdRatio: 0.8, retainRatio: 0.2, headroomTokens: 0, maxTokens: 4096 }
   ```

3. Необязательный UI во всплывашке: `python3 patches/meter-compaction-percent.py` поверх установленного
   `dsh-client-ui-conversation/lib/client.js` (по умолчанию ищет под `/usr/local/lib`). Повторять
   после каждого апгрейда dsh; если upstream сдвинулся — патч пропускается с громкой строкой.
4. Перезапустить dsh. В логе: `compaction-basic-fixed: fixed copy ...` и нет `entries did not activate`.

## Установка — удалённый сервер (dsh в Docker, например NAS)

1. Клон положить внутрь `$DSH_HOME` контейнера (постоянный том), `node_modules` → симлинк на
   `/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules` (путь одинаков в любом образе).
2. Те же две записи в `profiles/web/cordis.patch.yml`.
3. UI-патч — в **Dockerfile** (`COPY patches/meter-compaction-percent.py /opt/nas-patches/` +
   `RUN python3 /opt/nas-patches/meter-compaction-percent.py`), чтобы переживал пересборки.
4. Пересоздать контейнер (`docker compose up -d --force-recreate dsh-web`); работающий не патчить.
5. Проверка: `docker logs dsh-web 2>&1 | grep -E "compaction-basic-fixed:|did not activate"`; открыть чат,
   нажать на кольцо контекста — во всплывашке появится редактор порога.

## Как пользоваться

- Поле процента: ввести число (например `75.2` или `75,2`), Enter или уход с поля — сохраняет; Esc —
  отменяет. Диапазон 1–100.
- Галочка «only for <model>»: значение сохраняется как правило только для текущей пары
  provider/model; снять галочку — правило удаляется и действует глобальное.
- Подсказка показывает порог в токенах для окна текущей модели (`≈ 90.4K of 113K tokens`).
- То же самое доступно в Settings (dsh сам строит форму для namespace `compaction-threshold`).

## После апгрейда dsh

Для работы компакции делать ничего не нужно. Чтобы вернуть фиксы длинных сессий на новой версии:
скопировать новый поставочный `dsh-compaction-basic` в `dsh-compaction-basic-fixed/versions/<версия>/`,
заново наложить три ханка `LOCAL OVERRIDE`, запустить `verify.mjs`, перезапустить.

MIT. Копии в `versions/*` сохраняют MIT-условия исходного пакета.
