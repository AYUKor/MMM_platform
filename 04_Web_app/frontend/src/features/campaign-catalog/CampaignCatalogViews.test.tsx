import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import fixture from "../../test/fixtures/campaign_catalog_v1_synthetic.json";
import { parseCampaignCatalogV1 } from "../../shared/api/campaign-catalog-client";
import type { CampaignCardV1 } from "../../shared/api/generated/campaign-card-v1";
import { CampaignCardView } from "./CampaignCardView";
import { CampaignCatalogUnpublished, CampaignCatalogView } from "./CampaignCatalogView";
import { CampaignCatalogPageState } from "./CampaignCatalogPageState";
import { DEFAULT_FILTERS, type CatalogFilters } from "./campaignCatalogModel";
import {
  CampaignCatalogUnavailableError,
  CampaignNotFoundError,
} from "../../shared/api/campaign-catalog-client";

const NBSP = " ";
const catalog = parseCampaignCatalogV1(structuredClone(fixture));

function cardFor(number: number): CampaignCardV1 {
  const campaign = catalog.campaigns.find((item) => item.number === number);
  if (!campaign) throw new Error(`no campaign ${number}`);
  return {
    contract_name: "campaign_card_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    package_id: catalog.package_id,
    model_version: catalog.model_version as string,
    model_display_name: catalog.model_display_name as string,
    artifact_id: catalog.artifact_id as string,
    catalog_version: catalog.catalog_version as string,
    period_start: catalog.period_start as string,
    period_end: catalog.period_end as string,
    roas_level_label: catalog.roas_level_label as string,
    notes: catalog.notes,
    campaign,
    updated_at_utc: catalog.updated_at_utc as string,
  };
}

function renderCatalog(options: { filters?: Partial<CatalogFilters>; canDownload?: boolean } = {}) {
  const onFiltersChange = vi.fn();
  const onOpen = vi.fn();
  render(
    <MemoryRouter>
      <CampaignCatalogView
        catalog={catalog}
        filters={{ ...DEFAULT_FILTERS, ...options.filters }}
        onFiltersChange={onFiltersChange}
        canDownload={options.canDownload ?? true}
        downloadUrl="http://127.0.0.1:8765/api/v1/campaign-catalog/download"
        cardLink={(number) => `/campaigns/${number}?tab=short`}
        onOpen={onOpen}
      />
    </MemoryRouter>,
  );
  return { onFiltersChange, onOpen };
}

function table() {
  return screen.getByRole("table");
}

describe("past campaigns list", () => {
  it("shows the model, the period and the totals of the catalog", () => {
    renderCatalog();
    expect(screen.getByRole("heading", { level: 1, name: "Кампании прошлых периодов" })).toBeInTheDocument();
    expect(screen.getByText("Модель «Заноза»")).toBeInTheDocument();
    expect(screen.getByText("Данные по 28 июн 2026")).toBeInTheDocument();
    expect(screen.getByText("12 кампаний, оценка есть у 11")).toBeInTheDocument();
    expect(screen.getByText("ROAS всех кампаний 1,62")).toBeInTheDocument();
    expect(screen.getByText("уровень ROAS по отрасли")).toBeInTheDocument();
  });

  it("offers the Excel only to roles that may download reports", () => {
    renderCatalog();
    const link = screen.getByRole("link", { name: /Скачать Excel/ });
    expect(link).toHaveAttribute("href", "http://127.0.0.1:8765/api/v1/campaign-catalog/download");
    expect(link).toHaveAttribute("download", "Каталог_прошлых_кампаний_Заноза_20261105.xlsx");
    expect(link).toHaveTextContent("3 листа");
  });

  it("hides the Excel from viewers", () => {
    renderCatalog({ canDownload: false });
    expect(screen.queryByRole("link", { name: /Скачать Excel/ })).not.toBeInTheDocument();
  });

  it("splits the list into short and long campaigns", () => {
    const { onFiltersChange } = renderCatalog();
    const short = screen.getByRole("tab", { name: /До 120 дней/ });
    const long = screen.getByRole("tab", { name: /Длиннее 120 дней/ });
    expect(short).toHaveAttribute("aria-selected", "true");
    expect(short).toHaveTextContent("9");
    expect(long).toHaveTextContent("3");
    expect(screen.getByRole("status")).toHaveTextContent("Показано 9 из 9");
    expect(within(table()).getAllByRole("row")).toHaveLength(10);

    fireEvent.click(long);
    expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, tab: "long" });
  });

  it("passes search, filters and order up to the page", () => {
    const { onFiltersChange } = renderCatalog();
    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск кампании" }), { target: { value: "Казань" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, search: "Казань" });

    fireEvent.change(screen.getByRole("combobox", { name: "Направление" }), { target: { value: "ТСХ/Онлайн" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, direction: "ТСХ/Онлайн" });

    fireEvent.change(screen.getByRole("combobox", { name: "Канал" }), { target: { value: "Радио" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, channel: "Радио" });

    fireEvent.click(within(screen.getByRole("group", { name: "Надёжность" })).getByRole("button", { name: "0" }));
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, reliability: "0" });

    fireEvent.change(screen.getByRole("combobox", { name: "Порядок" }), { target: { value: "roas" } });
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_FILTERS, sort: "roas" });
  });

  it("shows ranges for computed campaigns and «нет оценки» for the rest", () => {
    renderCatalog();
    const computed = within(table()).getByRole("link", { name: "Тестовая кампания 8" }).closest("tr") as HTMLElement;
    expect(within(computed).getByText("24,7")).toBeInTheDocument();
    expect(within(computed).getByText("2,08")).toBeInTheDocument();

    const missing = within(table()).getByRole("link", { name: "Тестовая кампания 5" }).closest("tr") as HTMLElement;
    expect(within(missing).getAllByText("нет оценки")).toHaveLength(4);
    expect(within(missing).getByTitle("Смотреть с осторожностью")).toHaveTextContent("0");
  });

  it("writes small effects with enough decimals and a basket change under a kopeck in words", () => {
    renderCatalog();
    const small = within(table()).getByRole("link", { name: "Тестовая кампания 11" }).closest("tr") as HTMLElement;
    expect(within(small).getByText("+0,003")).toBeInTheDocument();
    expect(within(small).getByText("+0,002 … +0,005")).toBeInTheDocument();
    expect(within(small).getByText("+0,10")).toBeInTheDocument();
    expect(within(small).getByText("+0,04 … +0,17")).toBeInTheDocument();
    expect(small).toHaveTextContent("География: Москва, Нижегородская область, Республика Татарстан");

    const flat = within(table()).getByRole("link", { name: "Тестовая кампания 10" }).closest("tr") as HTMLElement;
    expect(within(flat).getByText("меньше копейки")).toBeInTheDocument();
    expect(within(flat).getByText("+8,0")).toBeInTheDocument();
  });

  it("highlights a searched city and keeps the rest as a count", () => {
    renderCatalog({ filters: { search: "Самара" } });
    const row = within(table()).getByRole("link", { name: "Тестовая кампания 10" }).closest("tr") as HTMLElement;
    expect(within(row).getByText("Самара").tagName).toBe("MARK");
    expect(row).toHaveTextContent("и ещё 5");
    expect(row).toHaveTextContent("вся страна (Нац. ТВ)");
  });

  it("opens a card from the row and keeps the list filters in the link", () => {
    const { onOpen } = renderCatalog();
    const link = within(table()).getByRole("link", { name: "Тестовая кампания 9" });
    expect(link).toHaveAttribute("href", "/campaigns/9?tab=short");
    fireEvent.click(within(link.closest("tr") as HTMLElement).getByText("61,7"));
    expect(onOpen).toHaveBeenCalledWith(9);
  });

  it("offers a reset when nothing matches and keeps the tab", () => {
    const { onFiltersChange } = renderCatalog({ filters: { tab: "long", search: "Владивосток" } });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULT_FILTERS, tab: "long" });
  });

  it("explains the reliability flag and the overlaps under the list", () => {
    renderCatalog();
    const reliability = catalog.notes.find((note) => note.code === "reliability_flag");
    expect(screen.getByText(reliability?.display_text as string)).toBeInTheDocument();
  });

  it("says plainly when the catalog is not published", () => {
    render(<CampaignCatalogUnpublished displayText="Каталог прошлых кампаний для активной модели пока не опубликован." />);
    expect(screen.getByRole("status")).toHaveTextContent("Каталог пока не опубликован");
  });
});

describe("past campaign card", () => {
  it("shows the four effects with their ranges and reference points", () => {
    render(<MemoryRouter><CampaignCardView card={cardFor(1)} backLink="/campaigns?tab=long" /></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1, name: "Тестовая кампания 1" })).toBeInTheDocument();
    expect(screen.getByText("Кампания № 1")).toBeInTheDocument();
    expect(screen.getByText("18 янв – 30 июн 2026")).toBeInTheDocument();
    expect(screen.getByText("164 дня")).toBeInTheDocument();

    const turnover = screen.getByRole("heading", { name: "Оборот, прирост" }).closest("section") as HTMLElement;
    expect(within(turnover).getByText("81,6")).toBeInTheDocument();
    expect(turnover).toHaveTextContent("от 57,1");
    expect(turnover).toHaveTextContent("до 114,2");

    const orders = screen.getByRole("heading", { name: "Заказы, прирост" }).closest("section") as HTMLElement;
    expect(within(orders).getByText("+1,2")).toBeInTheDocument();
    expect(orders).toHaveTextContent("от +0,9");
    expect(orders).toHaveTextContent("до +1,7");

    const basket = screen.getByRole("heading", { name: "Средний чек, прирост" }).closest("section") as HTMLElement;
    expect(within(basket).getByText("0,00")).toBeInTheDocument();
    expect(basket).toHaveTextContent("меньше копейки в любую сторону");
    expect(basket).not.toHaveTextContent("от ");

    const roas = screen.getByRole("heading", { name: "ROAS" }).closest("section") as HTMLElement;
    expect(within(roas).getByText("2,55")).toBeInTheDocument();
    expect(roas).toHaveTextContent(`оборот ÷ бюджет 32,0 млн ₽`);

    expect(screen.getByText("Оценке можно доверять")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Все кампании" })).toHaveAttribute("href", "/campaigns?tab=long");
  });

  it("explains how to read the estimate with the industry ROAS level", () => {
    render(<MemoryRouter><CampaignCardView card={cardFor(1)} backLink="/campaigns" /></MemoryRouter>);
    const explain = screen.getByRole("heading", { name: /Как читать оценку/ }).closest("section") as HTMLElement;
    expect(explain).toHaveTextContent("уровень ROAS по отрасли");
    expect(within(explain).getAllByRole("listitem")).toHaveLength(3);
    expect(explain).toHaveTextContent("остальные кампании оставить");
  });

  it("splits the budget by channel and marks nationwide channels", () => {
    render(<MemoryRouter><CampaignCardView card={cardFor(10)} backLink="/campaigns" /></MemoryRouter>);
    const channels = screen.getByRole("heading", { name: "Каналы и бюджет" }).closest("section") as HTMLElement;
    const rows = catalog.campaigns.find((item) => item.number === 10)?.channels ?? [];
    for (const row of rows) expect(channels).toHaveTextContent(row.display_name);
    expect(within(channels).getByText("вся страна")).toBeInTheDocument();
    expect(channels).toHaveTextContent("Бюджет кампании60,9");

    const cities = screen.getByRole("heading", { name: "География" }).closest("section") as HTMLElement;
    expect(cities).toHaveTextContent("9 городов и вся страна");
    expect(cities).toHaveTextContent("Вся страна · Нац. ТВ");

    const overlaps = screen.getByRole("heading", { name: "Пересечения" }).closest("section") as HTMLElement;
    expect(overlaps).toHaveTextContent("1кампания того же направления шла в те же дни и города");
  });

  it("counts regions apart from cities and keeps small effects readable", () => {
    render(<MemoryRouter><CampaignCardView card={cardFor(11)} backLink="/campaigns" /></MemoryRouter>);
    const geography = screen.getByRole("heading", { name: "География" }).closest("section") as HTMLElement;
    expect(geography).toHaveTextContent("1 город и 2 региона");
    expect(within(geography).getByText("Нижегородская область")).toBeInTheDocument();

    const orders = screen.getByRole("heading", { name: "Заказы, прирост" }).closest("section") as HTMLElement;
    expect(within(orders).getByText("+0,003")).toBeInTheDocument();
    expect(orders).toHaveTextContent("от +0,002");
    expect(orders).toHaveTextContent("до +0,005");

    const basket = screen.getByRole("heading", { name: "Средний чек, прирост" }).closest("section") as HTMLElement;
    expect(within(basket).getByText("+0,10")).toBeInTheDocument();
    expect(basket).toHaveTextContent("от +0,04");
    expect(basket).toHaveTextContent("до +0,17");
  });

  it("explains a campaign without an estimate instead of showing numbers", () => {
    const card = cardFor(5);
    render(<MemoryRouter><CampaignCardView card={card} backLink="/campaigns" /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Нет оценки эффекта");
    expect(screen.getByRole("status")).toHaveTextContent(card.campaign.status_display_text as string);
    expect(screen.queryByRole("heading", { name: "ROAS" })).not.toBeInTheDocument();
    expect(screen.getByText("Смотреть с осторожностью")).toBeInTheDocument();
    expect(screen.getByText(/других кампаний того же направления/)).toBeInTheDocument();
  });

  it("formats a large budget with Russian digit groups", () => {
    const card = cardFor(7);
    const [first, ...others] = card.campaign.channels;
    const othersBudget = others.reduce((sum, item) => sum + item.budget_rub, 0);
    card.campaign = {
      ...card.campaign,
      budget_rub: 1_234_560_000,
      channels: [{ ...first, budget_rub: 1_234_560_000 - othersBudget }, ...others],
    };
    render(<MemoryRouter><CampaignCardView card={card} backLink="/campaigns" /></MemoryRouter>);
    const total = screen.getByText("Бюджет кампании").nextElementSibling as HTMLElement;
    expect(total.textContent).toBe(`1${NBSP}234,6`);
  });
});

describe("catalog page states", () => {
  it("offers a retry for a temporary outage", () => {
    const onRetry = vi.fn();
    render(<MemoryRouter><CampaignCatalogPageState error={new CampaignCatalogUnavailableError()} onRetry={onRetry} /></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("Каталог временно недоступен");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("sends a missing campaign back to the list without a retry", () => {
    render(<MemoryRouter><CampaignCatalogPageState error={new CampaignNotFoundError()} onRetry={() => undefined} backLink="/campaigns?q=7" /></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("Кампания не найдена");
    expect(screen.queryByRole("button", { name: "Повторить" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Все кампании" })).toHaveAttribute("href", "/campaigns?q=7");
  });
});
