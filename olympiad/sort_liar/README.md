# A. Сортировка с обманщиком — симулятор жюри

Изолированный лабораторный стенд для сравнения интерактивных решений C++23. Ничего не меняет в основном функционале `med`. Исходные условия: `2 <= N <= 1000`, `0 <= k <= 30`, `1 <= Q <= 11000`; жюри может отвечать неверно **не более k раз за весь тест**.

Симулятор реализует протокол `? x y` / `YES|NO` / `! p1 ... pN`, контролирует корректность индексов, `x != y`, `t <= Q`, итоговую перестановку, вычисляет **0 при WA**, иначе `1.5 + 0.5 * (Q-t)/Q`. После каждой отправки ответа выполняется немедленная передача в интерактивный stdin программы. В локальном Linux применяется ограничение дочернего процесса: CPU 2 секунды, виртуальная память 256 МБ; 8 секунд wall-time отведены на обмен через Python-посредник.

## GitHub Actions

`.github/workflows/sort-liar-simulation.yml`: запуск автоматически на PR, если изменены файлы этого стенда; после попадания workflow в `main` доступен ручной запуск **Actions → Sort Liar - synthetic interactive judge → Run workflow**, где можно увеличить число повторов до 500 на каждую комбинацию. Три независимых набора: `smoke`, `balanced`, `adversarial`. На PR используется по 2 повтора на комбинацию для экономии CI-минут.

В **Step Summary** публикуются проходы, среднее количество запросов, сумма и средние баллы в разбивке по стратегиям; артефакты: `results.csv`, `results.json`, `summary.md`, а также JSON со всей историей вопросов и ответов для первых 20 неуспешных случаев каждого решения. WA не ломает CI: он является результатом симуляции. Нарушение протокола ломает CI.

## Локальный запуск

```bash
mkdir -p .sort-liar-bin
for f in olympiad/sort_liar/solutions/*.cpp; do
  name="$(basename "${f%.cpp}")"
  g++ -std=c++23 -O2 -pipe "$f" -o ".sort-liar-bin/$name"
done
python3 -m unittest discover -s olympiad/sort_liar/tests -v
python3 olympiad/sort_liar/judge.py \
  --suite adversarial --runs 30 --seed 794 --output sort-liar-report \
  --solver adaptive_v5=.sort-liar-bin/adaptive_v5 \
  --solver greedy_v7=.sort-liar-bin/greedy_v7 \
  --solver sparse_v8=.sort-liar-bin/sparse_v8
```

Воспроизведение ошибки на сохранённой перестановке/seed (включая адаптивную стратегию обмана):

```bash
python3 olympiad/sort_liar/judge.py \
  --replay sort-liar-report/failures/<file>.json \
  --solver sparse_v8=.sort-liar-bin/sparse_v8 \
  --output sort-liar-replay
```

Можно добавить любое новое решение `olympiad/sort_liar/solutions/new_name.cpp`: workflow подхватит его автоматически. При одинаковом `--seed` все решения получают одни и те же перестановки, параметры и правила лжи. Адаптивные решения жюри могут различаться, поскольку последовательности запросов различаются.

## Стратегии жюри

- `honest`, `uniform`, `first`, `last`, `spaced`, `midburst` — отсутствие лжи и разные распределения по времени.
- `first_neighbor`, `middle_neighbor` — концентрация лжи на паре **истинных соседей по значению**. Это особенно трудный сценарий: сравнения с третьими элементами не позволяют отличить переставленную пару.
- `repeat_pair`, `repeat_all` — обман при повторных запросах, чтобы ломать большинство и выявлять необоснованные ремонты порядка.
- `element`, `late_element`, `late` — концентрация лжи на одном элементе и поздних стадиях.

Профили включают `N=1000,k=30,Q=11000` и меньшие значения. Формы перестановок: random, sorted, reversed, nearly_sorted, zigzag, shuffled blocks.

**Ограничение метода:** это *синтетические* тесты, а не опубликованный набор из 50 закрытых тестов. Они позволяют сравнивать алгоритмы и воспроизводить регрессии, но не раскрывают скрытый тест №40. При некоторых `N,k,Q` гарантированное восстановление математически невозможно.


## Replay and paired scoring (v2)

The harness sets `SORT_LIAR_SEED` to the case seed. The three time-seeded C++
reference solvers honor this environment variable **only for simulations**;
without it, the original clock-based seed is used. This makes the recorded
query transcript reproducible without changing the competition protocol.

A failed run saves its entire `trace`: each query, true comparison, reply and
whether the judge lied. By default, `--replay` is now **exact**: the simulator
checks the contestant's next ordered query against the recorded one and gives
the original reply. A changed or nondeterministic query sequence is reported
as `replay_query_diverged`, never silently treated as an equivalent replay.

To compare a different algorithm on the same *permutation and adaptive liar
policy* (not the same answers), use:

```bash
python3 olympiad/sort_liar/judge.py \
  --replay sort-liar-reports/failures/CASE.json \
  --replay-mode strategy \
  --solver candidate=.sort-liar-bin/candidate \
  --output sort-liar-whatif
```

The report now includes **paired score deltas** against `adaptive_v5`,
counts of regressions and fixes, and diagnoses wrong permutations by
the number of reversed true-neighbor pairs and Kendall inversions.
Each stored failure includes the true ranks, indices, number of comparisons,
and lies for its first 20 reversed-neighbor pairs.

The CI runner calls `--verify-failures 2`: it must reproduce the first two
saved failure transcripts per solver **exactly**. This checks that artifacts
are usable. WA itself is still a normal simulation result, not a CI failure.

## Large campaigns and aggregation

For manual GitHub Actions runs with `runs >= 32`, eight independent shards
partition trial numbers, including permutation shapes. Reports are uploaded
separately and then merged by `aggregate.py` into a combined CSV, JSON and
summary with paired scores. On PRs the workflow uses a single shard and two
repetitions per configuration. There is no automatic heavy stress run.

Local two-shard example:

```bash
python3 olympiad/sort_liar/judge.py \
  --suite balanced --runs 20 --shards 2 --shard-index 0 \
  --solver adaptive_v5=.sort-liar-bin/adaptive_v5 \
  --output results/part-0
python3 olympiad/sort_liar/judge.py \
  --suite balanced --runs 20 --shards 2 --shard-index 1 \
  --solver adaptive_v5=.sort-liar-bin/adaptive_v5 \
  --output results/part-1
python3 olympiad/sort_liar/aggregate.py \
  --input results --output results/combined
```

**Caveat:** The simulation uses prescribed strategies; their frequencies
are not estimates of the private judge distribution. Better simulated
aggregate points do not automatically imply improvement on hidden test #40.
