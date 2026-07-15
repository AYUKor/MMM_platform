# MMM frontend design handoff

Этот пакет нужно положить в локальную папку проекта, чтобы Codex читал дизайн как обычные project files, а не искал решения в старых чатах.

## Куда положить файлы

```text
04_Web_app/
  docs/
    design/
      MMM_WEBAPP_DESIGN_SPEC_V1.md
      reference/
        mmm_result_overview_mockup.html
        mmm_result_overview_dark.png
        mmm_result_overview_light.png
    frontend/
      MMM_FRONTEND_IMPLEMENTATION_SPEC_V1.md
      CODEX_FRONTEND_PHASE_1_PROMPT.md
```

## Роль файлов

- `MMM_WEBAPP_DESIGN_SPEC_V1.md` — что должно быть в продукте и как должен вести себя интерфейс.
- `mmm_result_overview_mockup.html` — визуальная композиция утвержденной вкладки «Обзор».
- PNG-файлы — быстрые эталоны темной и светлой тем.
- `MMM_FRONTEND_IMPLEMENTATION_SPEC_V1.md` — техническое ТЗ на весь frontend.
- `CODEX_FRONTEND_PHASE_1_PROMPT.md` — первая ограниченная задача Codex.

## Важное правило

HTML-макет содержит демонстрационные числа. Они не являются реальными результатами и не должны попадать в production frontend как константы.

## Как работать

1. Скопировать файлы в проект по структуре выше.
2. В хорошем рабочем чате Codex сообщить, что дизайн утвержден.
3. Дать Codex содержимое `CODEX_FRONTEND_PHASE_1_PROMPT.md`.
4. Сначала принять Phase 1: foundation + result overview.
5. После визуальной проверки переходить к Phase 2: core marketer flow.

Не просить Codex собрать весь frontend одним заданием.
