# Сторонние компоненты и лицензии

Прототип **«Фотопринт · AI-ассистент руководителя»**, хакатон Track 3.
Документ закрывает требование **ОТ-08**: перечислены внешние библиотеки,
модели, датасеты, API и заимствованные компоненты с лицензиями.

> Это практическая сводка для хакатона, а не юридическое заключение.
> Точные тексты лицензий лежат в самих пакетах (`*.dist-info`, `node_modules/*/LICENSE`).

## 1. Ключевые компоненты

| Компонент | Версия / поставка | Лицензия | Назначение |
|---|---|---|---|
| Python | 3.11+ (в демо 3.15) | PSF-2.0 | Язык и runtime |
| FastAPI | 0.162 | MIT | HTTP API |
| Starlette | 1.10 | BSD-3-Clause | ASGI-основа FastAPI |
| Uvicorn | 0.54 | BSD-3-Clause | ASGI-сервер |
| Pydantic | 2.14 | MIT | Валидация схем API |
| httpx | 0.28 | BSD-3-Clause | HTTP-клиент к DeepSeek |
| itsdangerous | 2.2 | BSD-3-Clause | Подпись сессионной cookie |
| python-dotenv | 1.2 | BSD-3-Clause | Загрузка .env |
| qrcode | 8.2 | BSD-3-Clause | Генерация QR |
| Pillow | 13.0 | MIT-CMU | Отрисовка QR-карточки |
| pypdf | 6.21 | BSD-3-Clause | Разбор PDF |
| python-multipart | 0.0.33 | Apache-2.0 | Загрузка файлов |
| brotli | 1.2 | MIT | Сжатие HTML |
| Vosk | 0.3.45 | Apache-2.0 | Локальное распознавание речи |
| Vosk model small-ru-0.22 | локальная модель | Apache-2.0 | Русская STT-модель |
| imageio-ffmpeg | 0.8.1 | BSD-2-Clause | Поставка ffmpeg для конвертации аудио |
| FFmpeg (binary) | сборка imageio-ffmpeg | LGPL-2.1+ | Конвертация webm/m4a → WAV |
| Tunnelmole | 2.4.0 | MIT | Публичный HTTPS-туннель |
| Node.js | LTS | MIT | Runtime для Tunnelmole |
| DeepSeek API | deepseek-chat | Коммерческие условия | Внешняя LLM; данные — КНР |
| Material Design Icons | встроенные SVG-пути | Apache-2.0 | Иконки интерфейса |
| Синтетические документы | 21 + 8 образцов | Созданы командой | Демо-данные |
| PDF ТЗ заказчика | 2 файла | Материалы заказчика | Документация хакатона |

### Данные, модели и API

- **Синтетические документы и расшифровки** созданы командой для хакатона;
  реальные персональные данные не используются.
- **8 образцов** в `sample_docs/` созданы командой; внешние датасеты не заимствовались.
- **Vosk-модель** `vosk-model-small-ru-0.22` — Apache-2.0 (проект Vosk).
- **DeepSeek API** — коммерческие условия провайдера; модель `deepseek-chat`,
  обработка в КНР; наружу уходит только маскированный текст.
- **PDF ТЗ** — материалы заказчика (ООО «Фотопринт»), используются как документация
  хакатона, не входят в runtime приложения.
- **Иконки** — встроенные SVG-пути; набор соответствует Material Design Icons (Apache-2.0).
- **Шрифты** — системные; внешние Google Fonts в текущей сборке не подключены.

## 2. Python-зависимости

Всего: **40** пакетов (включая транзитивные и dev/test).

| Пакет | Версия | Лицензия |
|---|---|---|
| annotated-doc | 0.0.6 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| brotli | 1.2.1 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.1 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| fastapi | 0.162.4 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| imageio-ffmpeg | 0.8.1 | BSD-2-Clause |
| iniconfig | 2.3.1 | MIT |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| Pillow | 13.0.0 | MIT-CMU |
| pluggy | 1.7.0 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| pydantic_core | 2.50.4 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pypdf | 6.21.2 | BSD-3-Clause |
| pytest | 9.2.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.33 | Apache-2.0 |
| qrcode | 8.2 | BSD-3-Clause |
| requests | 2.34.2 | Apache-2.0 |
| srt | 3.5.3 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing-inspection | 0.4.5 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| vosk | 0.3.45 | Apache-2.0 |
| websockets | 17.4 | BSD-3-Clause |

## 3. Node.js / Tunnelmole

Всего: **165** npm-пакетов в клиенте Tunnelmole.
Сам Tunnelmole — MIT. Большинство транзитивных пакетов — MIT; ниже полный список.

<details>
<summary>Полный список npm-пакетов и лицензий</summary>

| Пакет | Версия | Лицензия |
|---|---|---|
| @babel/code-frame | 7.29.7 | MIT |
| @babel/helper-validator-identifier | 7.29.7 | MIT |
| @jest/expect-utils | 29.7.0 | MIT |
| @jest/schemas | 29.6.3 | MIT |
| @jest/types | 29.6.3 | MIT |
| @sinclair/typebox | 0.27.12 | MIT |
| @types/deep-equal | 1.0.4 | MIT |
| @types/is-number | 7.0.5 | MIT |
| @types/istanbul-lib-coverage | 2.0.6 | MIT |
| @types/istanbul-lib-report | 3.0.3 | MIT |
| @types/istanbul-reports | 3.0.4 | MIT |
| @types/jest | 29.5.14 | MIT |
| @types/node | 26.6.6 | MIT |
| @types/node-fetch | 2.6.13 | MIT |
| @types/node-localstorage | 1.3.3 | MIT |
| @types/node-persist | 3.1.8 | MIT |
| @types/source-map-support | 0.5.10 | MIT |
| @types/stack-utils | 2.0.3 | MIT |
| @types/validator | 13.15.10 | MIT |
| @types/ws | 7.4.7 | MIT |
| @types/yargs | 17.0.35 | MIT |
| @types/yargs-parser | 21.0.3 | MIT |
| address | 2.0.3 | MIT |
| agent-base | 6.0.2 | MIT |
| ansi-styles | 4.3.0 | MIT |
| append-field | 1.0.0 | MIT |
| array-buffer-byte-length | 1.0.2 | MIT |
| asynckit | 0.4.0 | MIT |
| available-typed-arrays | 1.0.7 | MIT |
| axios | 1.21.1 | MIT |
| braces | 3.0.3 | MIT |
| buffer-from | 1.1.2 | MIT |
| busboy | 1.6.0 | MIT |
| call-bind | 1.0.9 | MIT |
| call-bind-apply-helpers | 1.0.2 | MIT |
| call-bound | 1.0.4 | MIT |
| chalk | 4.1.2 | MIT |
| ci-info | 3.9.0 | MIT |
| color-convert | 2.0.1 | MIT |
| color-name | 1.1.4 | MIT |
| combined-stream | 1.0.8 | MIT |
| commander | 5.1.0 | MIT |
| concat-stream | 1.6.2 | MIT |
| core-util-is | 1.0.3 | MIT |
| debug | 4.4.3 | MIT |
| deep-equal | 2.2.3 | MIT |
| deepmerge | 4.3.1 | MIT |
| define-data-property | 1.1.4 | MIT |
| define-properties | 1.2.1 | MIT |
| delayed-stream | 1.0.0 | MIT |
| detect-port | 2.1.0 | MIT |
| diff-sequences | 29.6.3 | MIT |
| dunder-proto | 1.0.1 | MIT |
| es-define-property | 1.0.1 | MIT |
| es-errors | 1.3.0 | MIT |
| es-get-iterator | 1.1.3 | MIT |
| es-object-atoms | 1.1.2 | MIT |
| es-set-tostringtag | 2.1.0 | MIT |
| escape-string-regexp | 2.0.0 | MIT |
| expect | 29.7.0 | MIT |
| fill-range | 7.1.1 | MIT |
| follow-redirects | 1.16.3 | MIT |
| for-each | 0.3.5 | MIT |
| form-data | 4.0.6 | MIT |
| function-bind | 1.1.2 | MIT |
| functions-have-names | 1.2.3 | MIT |
| get-intrinsic | 1.3.0 | MIT |
| get-proto | 1.0.1 | MIT |
| gopd | 1.2.0 | MIT |
| graceful-fs | 4.2.11 | ISC |
| has-bigints | 1.1.0 | MIT |
| has-flag | 4.0.0 | MIT |
| has-property-descriptors | 1.0.2 | MIT |
| has-symbols | 1.1.0 | MIT |
| has-tostringtag | 1.0.2 | MIT |
| hasown | 2.0.4 | MIT |
| https-proxy-agent | 5.0.1 | MIT |
| imurmurhash | 0.1.4 | MIT |
| inherits | 2.0.4 | ISC |
| internal-slot | 1.1.0 | MIT |
| is-arguments | 1.2.0 | MIT |
| is-array-buffer | 3.0.5 | MIT |
| is-bigint | 1.1.0 | MIT |
| is-boolean-object | 1.2.2 | MIT |
| is-callable | 1.2.7 | MIT |
| is-date-object | 1.1.0 | MIT |
| is-map | 2.0.3 | MIT |
| is-number | 7.0.0 | MIT |
| is-number-object | 1.1.1 | MIT |
| is-regex | 1.2.1 | MIT |
| is-set | 2.0.3 | MIT |
| is-shared-array-buffer | 1.0.4 | MIT |
| is-string | 1.1.1 | MIT |
| is-symbol | 1.1.1 | MIT |
| is-weakmap | 2.0.2 | MIT |
| is-weakset | 2.0.4 | MIT |
| isarray | 2.0.5 | MIT |
| jest-diff | 29.7.0 | MIT |
| jest-get-type | 29.6.3 | MIT |
| jest-matcher-utils | 29.7.0 | MIT |
| jest-message-util | 29.7.0 | MIT |
| jest-util | 29.7.0 | MIT |
| js-tokens | 4.0.0 | MIT |
| math-intrinsics | 1.1.0 | MIT |
| media-typer | 0.3.0 | MIT |
| micromatch | 4.0.8 | MIT |
| mime-db | 1.52.0 | MIT |
| mime-types | 2.1.35 | MIT |
| minimist | 1.2.8 | MIT |
| mkdirp | 0.5.6 | MIT |
| ms | 2.1.3 | MIT |
| multer | 1.4.5-lts.2 | MIT |
| nanoid | 3.3.20 | MIT |
| node-fetch | 2.7.0 | MIT |
| node-localstorage | 2.2.1 | MIT |
| object-assign | 4.1.1 | MIT |
| object-inspect | 1.13.4 | MIT |
| object-is | 1.1.6 | MIT |
| object-keys | 1.1.1 | MIT |
| object.assign | 4.1.7 | MIT |
| picocolors | 1.1.1 | ISC |
| picomatch | 2.3.2 | MIT |
| possible-typed-array-names | 1.1.0 | MIT |
| pretty-format | 29.7.0 | MIT |
| pretty-format/ansi-styles | 5.2.0 | MIT |
| process-nextick-args | 2.0.1 | MIT |
| proxy-from-env | 2.1.0 | MIT |
| react-is | 18.3.1 | MIT |
| readable-stream | 2.3.8 | MIT |
| readable-stream/isarray | 1.0.0 | MIT |
| regexp.prototype.flags | 1.5.4 | MIT |
| safe-buffer | 5.1.2 | MIT |
| safe-regex-test | 1.1.0 | MIT |
| set-function-length | 1.2.2 | MIT |
| set-function-name | 2.0.2 | MIT |
| side-channel | 1.1.1 | MIT |
| side-channel-list | 1.0.1 | MIT |
| side-channel-map | 1.0.1 | MIT |
| side-channel-weakmap | 1.0.2 | MIT |
| slash | 3.0.0 | MIT |
| slide | 1.1.6 | ISC |
| source-map | 0.6.1 | BSD-3-Clause |
| source-map-support | 0.5.21 | MIT |
| stack-utils | 2.0.6 | MIT |
| stop-iteration-iterator | 1.1.0 | MIT |
| streamsearch | 1.1.0 | MIT |
| string_decoder | 1.1.1 | MIT |
| supports-color | 7.2.0 | MIT |
| to-regex-range | 5.0.1 | MIT |
| toml | 3.0.0 | MIT |
| tr46 | 0.0.3 | MIT |
| tunnelmole | 2.4.0 | MIT |
| type-is | 1.6.18 | MIT |
| typedarray | 0.0.6 | MIT |
| undici-types | 8.9.0 | MIT |
| util-deprecate | 1.0.2 | MIT |
| validator | 13.15.35 | MIT |
| webidl-conversions | 3.0.1 | BSD-2-Clause |
| whatwg-url | 5.0.0 | MIT |
| which-boxed-primitive | 1.1.1 | MIT |
| which-collection | 1.0.2 | MIT |
| which-typed-array | 1.1.24 | MIT |
| write-file-atomic | 1.3.4 | ISC |
| ws | 7.5.13 | MIT |
| xtend | 4.0.2 | MIT |

</details>

## 4. Оговорки

- Лицензии взяты из метаданных Python-пакетов и `package-lock.json`.
- Транзитивные зависимости могут иметь собственные условия; их тексты сохраняются
  в пакетах и `node_modules`.
- FFmpeg поставляется сборкой `imageio-ffmpeg`; точная конфигурация сборки определяет
  LGPL/GPL-условия. Для пилота нужно проверить конкретный бинарник.
- DeepSeek API не является open-source компонентом; действуют условия провайдера.
- При замене дизайна/шрифтов/иконок обновить этот файл.
