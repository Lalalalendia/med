# Источник для перевода: 見切りから始める我流剣術 (n8001hc)

**Это японский оригинал, НЕ 40 переведённых глав Rulate.**

- Автор: 氷純.
- Narō: https://ncode.syosetu.com/n8001hc/
- Глава 1: https://ncode.syosetu.com/n8001hc/1/
- Глава 166: https://ncode.syosetu.com/n8001hc/166/
- [Исследование и реестр в Notion](https://app.notion.com/p/3f432a84beec8139b608fd73565d4762) фиксируют 166/166 доступных исходных тел по проверке от 10.10.2026; в октябрьском отчёте сохранялись метаданные, **а не тексты**.

## Сбор через med

Используется существующий `tools/novel-ingest/narou_ingest.py`. Он читает две страницы оглавления и 166 исходных эпизодов, сохраняет UTF-8 текст отдельно в `raw/001.txt` ... `raw/166.txt`, названия, исходные URL, длину и SHA-256 каждого текста. Никаких авторизованных страниц, обходов доступа, паролей, переводов или сохранений в Notion автоматически не выполняет.

Для воспроизводимости:

```bash
python -m pip install requests beautifulsoup4
python -m unittest discover -s tools/novel-ingest -p test_narou_ingest.py -v
python -m unittest discover -s tools/novel-ingest -p test_n8001hc_package.py -v
python tools/novel-ingest/narou_ingest.py --ncode n8001hc --expected 166 --min-chars 120 --delay 1.5 --out-dir out/narou-n8001hc
python tools/novel-ingest/n8001hc_package.py --source out/narou-n8001hc --output out/narou-n8001hc-japanese-original-001-166.zip
```

**GitHub Actions**: [.github/workflows/narou-n8001hc-source-166.yml](../../.github/workflows/narou-n8001hc-source-166.yml). Запускается на ветке `research/narou-n8001hc-source-166-20261023`. Архив создаётся только при полном PASS 166/166: внутри `chapters/001.txt` ... `chapters/166.txt`, `combined.txt` и `manifest.json`. Архив является временным артефактом GitHub Actions с хранением до 7 дней; **в Git-историю тексты не записываются**. Отдельный метаданный отчёт сохраняется и при ошибке.

После получения корпуса литературный перевод начинается **с №1**. Текущие 40 русских глав на Rulate не являются исходной базой нового перевода. Для внутреннего перевода права на использование оригинала пользователь сообщил как имеющиеся; автоматически права на публикацию или распространение не подтверждены.

Статус корпуса: см. **точный** результат GitHub Actions; наличие скрипта не доказывает, что тексты извлечены.
