# Reports

Сюда попадают отчеты по качеству и drift для уже собранного model-ready датасета.

Минимальный набор отчетов:

- `data_quality.xlsx` — качество итоговой assembled panel: coverage, missing values, negative/zero checks, active days, budgets, target sanity;
- `old_vs_new_drift.xlsx` — сравнение новой части и старого периода: бюджеты по каналам/гео, target/control distributions, перекосы по регионам;
- optional charts — компактные визуализации для проверки перед refit.

Важно: эти отчеты не заменяют model report. Они отвечают на вопрос `можно ли на этих данных запускать MMM`, а не `какой ROAS получился`.
