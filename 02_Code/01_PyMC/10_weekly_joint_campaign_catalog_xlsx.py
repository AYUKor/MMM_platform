# -*- coding: utf-8 -*-
"""Excel-каталог прошлых кампаний на недельной совместной модели: 3 листа (тех. информация, до 120 дней, 120 дней и больше).

Тот же вид, что у каталога 28.10 (решения Alex): №, название, направление, даты, каналы с бюджетом, города, бюджет,
оборот, заказы на 1000 покупателей, средний чек, ROAS (формулой), пересечения, надёжность 1/0.
Запуск: python -I 10_weekly_joint_campaign_catalog_xlsx.py catalog_results.json OUT.xlsx "подпись модели" "имя запуска"
"""
import sys, json, pickle, hashlib, os
import datetime as dt
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule
from openpyxl.worksheet.properties import PageSetupProperties
CHANNELS = [  # порядок колонок: ключ, название как в портале, короткое имя
    ("dig", "Цифровая реклама", "Цифровая"),
    ("ooh", "Наружная реклама", "Наружная"),
    ("ind", "Indoor", "Indoor"),
    ("rad", "Радио", "Радио"),
    ("ntv", "Национальное ТВ", "Нац. ТВ"),
    ("rtv", "Региональное ТВ", "Рег. ТВ"),
]

RES = sys.argv[1]
OUT = sys.argv[2]
MODEL_LABEL = sys.argv[3] if len(sys.argv) > 3 else 'недельная модель'
RUN_NAME = sys.argv[4] if len(sys.argv) > 4 else ''
R = json.load(open(RES, encoding='utf-8')) if RES.endswith('.json') else pickle.load(open(RES, 'rb'))
res, meta, checks = R['results'], R['meta'], R['checks']
HIDE0 = False


def nn(vals):
    return [None if v is None or v != v else v for v in vals]


def build():
    items = []
    for x in res.values():
        c = x['card']
        items.append(dict(
            id=int(x['id']), name=x['name'], dirs=c['dirs'], start=c['start'], end=c['end'], days=c['days'], long=c['days'] >= 120,
            channels=c['channels'], cities=c['cities'], federal=c['federal'], budget=c['budget'],
            turnover=nn(x['turnover']), orders=nn(x['orders1000']), basket=nn(x['basket']),
            rel=int(x['flag']), overlap=x['overlap'], modeled=bool(x['modeled']), no_model=not x['modeled']))
    items.sort(key=lambda r: r['id'])
    return items


data = build()
short = [x for x in data if not x["long"]]
long_ = [x for x in data if x["long"]]

FONT = "Arial"
f_body = Font(name=FONT, size=10)
f_bold = Font(name=FONT, size=10, bold=True)
f_gray = Font(name=FONT, size=10, color="7F7F7F")
f_head = Font(name=FONT, size=10, bold=True, color="FFFFFF")
f_title = Font(name=FONT, size=14, bold=True)
f_banner = Font(name=FONT, size=10, bold=True, color="C00000")
f_note = Font(name=FONT, size=9, italic=True, color="7F7F7F")
fill_head = PatternFill("solid", fgColor="262626")
fill_head2 = PatternFill("solid", fgColor="3A3A3A")
fill_sect = PatternFill("solid", fgColor="EDEDED")
side_hair = Side(style="hair", color="BFBFBF")
side_mid = Side(style="thin", color="8C8C8C")
side_lime = Side(style="medium", color="C7FD72")

MLN = '#,##0.0'
SIGN1 = '+0.00;-0.00;0.00'
DATEF = 'DD.MM.YYYY'

# колонки: (буква, ширина)
COLS = {
    "A": 5, "B": 44, "C": 24, "D": 11.5, "E": 11.5, "F": 7, "G": 52, "H": 56,
    "I": 12, "J": 12, "K": 10, "L": 10, "M": 15, "N": 15, "O": 12,
    "P": 11, "Q": 9, "R": 9, "S": 11, "T": 9, "U": 9, "V": 11, "W": 9, "X": 9,
    "Y": 9, "Z": 9, "AA": 9, "AB": 15, "AC": 12,
}
CH_COLS = dict(zip([k for k, _, _ in CHANNELS], "IJKLMN"))
GROUP_START = {"I", "P", "S", "V", "Y", "AB", "AC"}


def fmt_dirs(x):
    return ", ".join(x["dirs"])


def fmt_cities(x):
    s = ", ".join(x["cities"])
    if x["federal"]:
        tail = "вся страна (" + ", ".join(x["federal"]) + ")"
        s = (s + " + " + tail) if s else tail
    return s


def sheet_campaigns(ws, title, rows, first_sheet_name):
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    ws["A1"] = title
    ws["A1"].font = f_title
    ws["A2"] = f"ЧЕРНОВИК: {len(data)} кампаний, цифры модели: {MODEL_LABEL}. В рабочем файле этой строки не будет."
    ws["A2"].font = f_banner
    ws.row_dimensions[1].height = 24

    # шапка: строка 4 — группы, строка 5 — колонки
    for col in COLS:
        for r in (4, 5):
            cell = ws[f"{col}{r}"]
            cell.fill = fill_head if r == 4 else fill_head2
            cell.font = f_head
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    groups = [("I4:O4", "Бюджет, млн ₽"), ("P4:R4", "Оборот, прирост, млн ₽"),
              ("S4:U4", "Заказы, прирост на 1000 покупателей"),
              ("V4:X4", "Средний чек, прирост, ₽"), ("Y4:AA4", "ROAS")]
    for rng, label in groups:
        ws.merge_cells(rng)
        ws[rng.split(":")[0]] = label
    heads = {
        "A": "№", "B": "Кампания", "C": "Направление", "D": "Старт", "E": "Окончание", "F": "Дней",
        "G": "Каналы", "H": "Города",
        "O": "Всего",
        "P": "оценка", "Q": "от", "R": "до", "S": "оценка", "T": "от", "U": "до",
        "V": "оценка", "W": "от", "X": "до", "Y": "оценка", "Z": "от", "AA": "до",
        "AB": "Пересечения (кампаний)", "AC": "Надёжность",
    }
    for k, (_, name, _) in zip("IJKLMN", CHANNELS):
        heads[k] = name
    for col, text in heads.items():
        ws[f"{col}5"] = text
    ws.row_dimensions[4].height = 30
    ws.row_dimensions[5].height = 32
    for col, w in COLS.items():
        ws.column_dimensions[col].width = w

    r0 = 6
    for i, x in enumerate(rows):
        r = r0 + i
        ws.row_dimensions[r].height = 20
        ws[f"A{r}"] = x["id"]
        ws[f"B{r}"] = x["name"]
        ws[f"C{r}"] = fmt_dirs(x)
        ws[f"D{r}"] = date.fromisoformat(x["start"])
        ws[f"E{r}"] = date.fromisoformat(x["end"])
        ws[f"F{r}"] = f"=E{r}-D{r}+1"
        ws[f"G{r}"] = ", ".join(c["name"] for c in x["channels"])
        ws[f"H{r}"] = fmt_cities(x)
        for c in x["channels"]:
            ws[f"{CH_COLS[c['key']]}{r}"] = round(c["budget"] / 1e6, 6)
        ws[f"O{r}"] = f"=SUM(I{r}:N{r})"
        if x["modeled"]:
            for col, vals in (("P", x["turnover"]), ("S", x["orders"]), ("V", x["basket"])):
                lo, mid, hi = vals
                if col == "P":
                    lo, mid, hi = (round(v / 1e6, 6) for v in vals)
                c0 = ws[f"{col}{r}"].column
                ws.cell(row=r, column=c0, value=mid)
                ws.cell(row=r, column=c0 + 1, value=lo)
                ws.cell(row=r, column=c0 + 2, value=hi)
        for col, src in (("Y", "P"), ("Z", "Q"), ("AA", "R")):
            ws[f"{col}{r}"] = f'=IF(OR($O{r}=0,{src}{r}=""),"",{src}{r}/$O{r})'
        ws[f"AB{r}"] = x["overlap"]
        ws[f"AC{r}"] = x["rel"]

        # оформление строки
        for col in COLS:
            cell = ws[f"{col}{r}"]
            cell.font = f_body
            cell.border = Border(bottom=side_hair, left=side_mid if col in GROUP_START else None)
            cell.alignment = Alignment(vertical="center")
        ws[f"A{r}"].alignment = Alignment(horizontal="center", vertical="center")
        ws[f"B{r}"].font = f_bold
        for col in ("D", "E"):
            ws[f"{col}{r}"].number_format = DATEF
            ws[f"{col}{r}"].alignment = Alignment(horizontal="center", vertical="center")
        ws[f"F{r}"].number_format = "0"
        ws[f"F{r}"].alignment = Alignment(horizontal="center", vertical="center")
        for col in "IJKLMNO":
            ws[f"{col}{r}"].number_format = MLN
        ws[f"O{r}"].font = f_bold
        for col in ("P", "Q", "R"):
            ws[f"{col}{r}"].number_format = MLN
        for col in ("S", "T", "U", "V", "W", "X"):
            ws[f"{col}{r}"].number_format = SIGN1
        for col in ("Y", "Z", "AA"):
            ws[f"{col}{r}"].number_format = "0.00"
        for col in ("P", "S", "V", "Y"):
            ws[f"{col}{r}"].font = f_bold
        for col in ("Q", "R", "T", "U", "W", "X", "Z", "AA"):
            ws[f"{col}{r}"].font = f_gray
        ws[f"AB{r}"].number_format = "0"
        ws[f"AB{r}"].alignment = Alignment(horizontal="center", vertical="center")
        ws[f"AC{r}"].number_format = "0"
        ws[f"AC{r}"].font = f_bold
        ws[f"AC{r}"].alignment = Alignment(horizontal="center", vertical="center")

    last = r0 + len(rows) - 1
    # цветовая отметка флага 1/0
    green = PatternFill("solid", bgColor="E2F0D9", fgColor="E2F0D9")
    amber = PatternFill("solid", bgColor="FCE4D6", fgColor="FCE4D6")
    ws.conditional_formatting.add(f"AC{r0}:AC{last}",
                                  CellIsRule(operator="equal", formula=["1"], fill=green,
                                             font=Font(name=FONT, bold=True, color="375623")))
    ws.conditional_formatting.add(f"AC{r0}:AC{last}",
                                  CellIsRule(operator="equal", formula=["0"], fill=amber,
                                             font=Font(name=FONT, bold=True, color="843C0C")))
    ws.auto_filter.ref = f"A5:AC{last}"
    ws.freeze_panes = "C6"
    # короткие пояснения под таблицей
    n1 = last + 2
    ws[f"A{n1}"] = ("Надёжность: 1 — оценке можно доверять (не меньше половины бюджета кампании в каналах, где расчёт модели сошёлся и данных достаточно); "
                    "0 — смотреть с осторожностью.")
    ws[f"A{n1+1}"] = "Пересечения: сколько других кампаний того же направления шли в те же дни и города."
    ws[f"A{n1+2}"] = ("Уровень отдачи каналов задан отраслевыми значениями для каждой сети и направления; данные распределяют его по городам и неделям. "
                      "Средний чек модель почти не даёт рекламе менять (так задумано), эффект идёт в основном через заказы.")
    ws[f"A{n1+3}"] = "Пустые ячейки: деньги кампании пришлись на города или недели, которых нет в модели, оценки нет."
    for rr in (n1, n1 + 1, n1 + 2, n1 + 3):
        ws[f"A{rr}"].font = f_note
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    return r0, last


wb = Workbook()
ws_tech = wb.active
ws_tech.title = "Тех. информация"
ws_s = wb.create_sheet("Кампании до 120 дней")
ws_l = wb.create_sheet("Кампании длиннее 120 дней")
s0, s1 = sheet_campaigns(ws_s, "Кампании до 120 дней", short, "short")
l0, l1 = sheet_campaigns(ws_l, "Кампании длиннее 120 дней", long_, "long")

# ---------- тех. лист ----------
ws = ws_tech
ws.sheet_view.showGridLines = False
ws.column_dimensions["A"].width = 34
ws.column_dimensions["B"].width = 96
ws["A1"] = "Тех. информация"
ws["A1"].font = f_title
ws.row_dimensions[1].height = 24
ws["A2"] = "ЧЕРНОВИК. Эти поля заполняются автоматически при каждом пересчёте каталога."
ws["A2"].font = f_banner
ws["A4"], ws["B4"] = "Параметр", "Значение"
for col in "AB":
    ws[f"{col}4"].font = f_head
    ws[f"{col}4"].fill = fill_head
    ws[f"{col}4"].alignment = Alignment(vertical="center")
ws.row_dimensions[4].height = 20

TBD = "будет указано при расчёте"
DN = dt.timezone(dt.timedelta(hours=7))
num = checks.get('numbers', {})
gone = num.get('old_not_found', [])
gone_txt = ("; " + "; ".join(f"№{g['id']} «{g['name']}» вошла в другую кампанию после исправления дат в журнале 02.11.2026" for g in gone)) if gone else ""
secs = int(meta['calc_seconds'])
code_h = hashlib.sha256(''.join(f"{k}:{v}" for k, v in sorted(meta['code_sha256'].items())).encode()).hexdigest()[:12]
T = dict(
    model_version=MODEL_LABEL + (f", запуск {RUN_NAME}" if RUN_NAME else ""),
    model_spec=("Одна модель на 4 направления (ТС5 и ТСХ, магазины и доставка): недельные заказы и средний чек, оборот = заказы × чек; "
                "5 каналов (нац. ТВ, рег. ТВ, радио, наружная реклама вместе с Indoor, цифровая реклама); реклама магазинов действует только "
                "на магазины, доставки только на доставку; в каждом городе реклама действует по своим расходам на жителя; перенос рекламы "
                f"до {meta['adstock_weeks']} недель; обучение 01.01.2025–28.06.2026."),
    level=("Уровень ROAS каждого канала привязан к отраслевым значениям для каждой сети и направления (решение от 03.11.2026); "
           "данные распределяют его по городам и неделям. Уровень — допущение, а не измерение."),
    package=os.path.basename(meta['inputs']['npz']['path']),
    package_hash=meta['inputs']['npz']['sha256'],
    data_period="01.01.2025–30.06.2026 (эффект считается по 28.06.2026, последняя полная неделя)",
    ledger_version="журнал расходов v3 (исправлен 02.11.2026)",
    ledger_hash=meta['inputs']['ledger']['sha256'],
    dictionary_version=("v1: названия, различающиеся регистром, пробелами, знаками и приставкой «РК», считаются одной кампанией; пауза больше "
                        "30 дней — другая кампания; период длиннее года режется по границе года; номера как в справочнике названий" + gone_txt),
    method_version="v2 (черновик): недельная модель; деньги кампании раскладываются по городам модели по тем же правилам, что при обучении",
    code_version=f"{meta['code_version']}, сборка {code_h}",
    calc_time=dt.datetime.strptime(meta['finished_utc'], '%d.%m.%Y %H:%M').replace(tzinfo=dt.timezone.utc).astimezone(DN).strftime('%d.%m.%Y %H:%M') + " (Дананг, UTC+7)",
    calc_duration=f"{secs // 60} мин {secs % 60} с ({meta['n_campaigns']} кампаний, {meta['n_draws']} случайных наборов параметров модели)",
    file_time=dt.datetime.now(DN).strftime('%d.%m.%Y') + " (Дананг)",
)
rows = [
    ("§", "Модель и пакет"),
    ("Версия модели", T["model_version"]),
    ("Спецификация модели", T["model_spec"]),
    ("Уровень отдачи", T["level"]),
    ("Пакет модели", T["package"]),
    ("Хэш пакета (SHA-256)", T["package_hash"]),
    ("§", "Данные"),
    ("Период данных", T["data_period"]),
    ("Версия реестра кампаний", T["ledger_version"]),
    ("Хэш реестра кампаний (SHA-256)", T["ledger_hash"]),
    ("Версия словаря кампаний", T["dictionary_version"]),
    ("§", "Расчёт"),
    ("Метод", f"Оценка строится путем создания контрфактуала. Реклама действует с переносом до {meta['adstock_weeks']} недель."),
    ("Версия метода", T["method_version"]),
    ("Версия кода расчёта", T["code_version"]),
    ("Дата и время расчёта", T["calc_time"]),
    ("Длительность расчёта", T["calc_duration"]),
    ("Диапазон «от» – «до»", "от 10-го до 90-го процентиля результата"),
    ("§", "Правила каталога"),
    ("Деление на листы", "Длительность — от первого до последнего дня кампании. Меньше 120 дней — лист "
                         "«Кампании до 120 дней», 120 дней и больше — лист «Кампании длиннее 120 дней»."),
    ("Пересечения", "Другие кампании того же направления, у которых совпал хотя бы один день и один город. "
                    "Федеральные каналы считаются как все города."),
    ("Города", "Деньги кампании раскладываются по городам модели так же, как при обучении: «РФ» по населению городов, область по её городам и остатку. "
               "Отдача рубля зависит от расходов на жителя: где реклама плотнее (например, Москва), отдача рубля ниже."),
    ("Единицы", "Бюджет и оборот — млн ₽. Заказы — прирост на 1000 покупателей. "
                "Средний чек — прирост в рублях. ROAS = прирост оборота / весь бюджет кампании."),
    ("§", "Файл"),
    ("Файл сформирован", T["file_time"]),
    ("Кампаний до 120 дней", f"=COUNTA('Кампании до 120 дней'!B{s0}:B{s1})"),
    ("Кампаний длиннее 120 дней", f"=COUNTA('Кампании длиннее 120 дней'!B{l0}:B{l1})"),
    ("Кампаний всего", "=B26+B27"),
]
r = 5
start_row_of_total = None
for a, b in rows:
    if a == "§":
        ws[f"A{r}"] = b
        ws[f"A{r}"].font = f_bold
        for col in "AB":
            ws[f"{col}{r}"].fill = fill_sect
        ws.row_dimensions[r].height = 18
    else:
        ws[f"A{r}"] = a
        ws[f"B{r}"] = b
        ws[f"A{r}"].font = f_body
        is_tbd = b == TBD
        ws[f"B{r}"].font = Font(name=FONT, size=10, italic=is_tbd, color="7F7F7F" if is_tbd else "000000")
        ws[f"A{r}"].alignment = Alignment(vertical="top")
        ws[f"B{r}"].alignment = Alignment(vertical="top", wrap_text=True, horizontal="left")
        for col in "AB":
            ws[f"{col}{r}"].border = Border(bottom=side_hair)
        if len(str(b)) > 95:
            ws.row_dimensions[r].height = 28 if len(str(b)) < 190 else 42
    r += 1
# формулы итогов ссылаются на строки по факту
tot_rows = {ws[f"A{i}"].value: i for i in range(5, r)}
ws[f"B{tot_rows['Кампаний всего']}"] = f"=B{tot_rows['Кампаний до 120 дней']}+B{tot_rows['Кампаний длиннее 120 дней']}"
for k in ("Кампаний до 120 дней", "Кампаний длиннее 120 дней", "Кампаний всего"):
    ws[f"B{tot_rows[k]}"].number_format = "0"
    ws[f"B{tot_rows[k]}"].alignment = Alignment(horizontal="left", vertical="top")

ws_tech.sheet_properties.tabColor = "7F7F7F"
ws_s.sheet_properties.tabColor = "C7FD72"
ws_l.sheet_properties.tabColor = "D48A20"
ws_tech.page_setup.orientation = "landscape"
ws_tech.page_setup.fitToHeight = 0
ws_tech.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
# открывать на листе с кампаниями до 120 дней
wb.active = 1
for i, w in enumerate(wb.worksheets):
    w.sheet_view.tabSelected = (i == 1)
wb.save(OUT)
print("saved", OUT, "short rows", s0, s1, "long rows", l0, l1)
