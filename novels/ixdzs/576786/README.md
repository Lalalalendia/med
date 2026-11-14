# IXDZS 576786 — полный китайский оригинал

- Название: 一个老父亲在漫威的悠闲生活
- Автор: 暮沉
- Источник: https://ixdzs8.com/read/576786/
- Разрешение на воспроизведение: подтверждено заказчиком 2026-11-14.
- Диапазон: главы 1–242, 242/242 проверено.
- Метод: официальный ZIP-архив источника, без обхода ограничений.
- Верификация: целостность ZIP, номера глав 1–242, непустой китайский текст, отсутствие одинаковых глав, SHA-256 всех TXT и combined.txt.
- Результат: SUCCESS, GitHub Actions run #43584833965 (2026-11-14).

## Скачать текст

[GitHub Actions artifact: ixdzs-576786-chapters-001-242-authorized-cn](https://github.com/Lalalalendia/med/actions/runs/43584833965/artifacts/14110300605)

Это ZIP-артефакт GitHub Actions (хранение 30 дней), внутри которого лежит
`ixdzs-576786-1-242-cn.zip`. Внутренний архив содержит:

- `chapters/0001.txt` … `chapters/0242.txt`
- `combined.txt` — весь китайский текст в порядке глав
- `manifest.json` — метаданные, размеры и SHA-256 каждой главы

### Контрольные суммы

- Архив `ixdzs-576786-1-242-cn.zip` SHA-256:
  `026b369060058d2fb137052bfbf0935f4951d4cb4ed165c934ff580098ecf2c0`
- `combined.txt` SHA-256:
  `60a6c0df443f817c8bd62d93d65abb023a15f95fcee58990ed2e788ddf417a79`
- Размер внутреннего архива: 1 500 014 байт.

### Воспроизвести выгрузку

```bash
python -m pip install requests beautifulsoup4
python tools/novel-ingest/ixdzs_576786_export.py --selftest
python tools/novel-ingest/ixdzs_576786_export.py --rights-confirmed --out out/authorized-ixdzs-576786
```

Экспорт требует подтверждения прав. Выгрузка полного художественного текста
не добавляется в публичную историю Git; она хранится только как результат
GitHub Actions и в локальном игнорируемом каталоге `out/`.
