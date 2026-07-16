import { describe, expect, it } from "vitest";
import type { CampaignPreview, ValidationIssue, ValidationResult } from "../../entities/lifecycle/types";
import {
  NEW_CALCULATION_SCENARIOS,
  SCENARIO_RECOMMENDATION_RULES,
  buildScenarioInvariantSnapshot,
  checkCampaignFilePolicy,
  getValidationTopStatus,
  groupIssueAffectedEntities,
  guardSingleCampaign,
  resolveNewCalculationStep,
  uploadCanProceedToValidation,
} from "./newCalculationFlow";

const campaign: CampaignPreview = {
  campaign_id: "campaign_111111111111",
  campaign_name: "Тестовая кампания",
  segments: ["Сегмент A"] as CampaignPreview["segments"],
  start_date: "2026-08-01",
  end_date: "2026-08-31",
  active_days: 31,
  channels: ["Канал A", "Канал B"] as CampaignPreview["channels"],
  geographies: ["Гео A", "Гео B"] as CampaignPreview["geographies"],
  creatives: [],
  source_rows_n: 4,
  normalized_rows_n: 4,
  daily_rows_n: 124,
  uploaded_budget_rub: 10_000_000,
  model_input_budget_rub: 10_000_000,
  unmodeled_budget_rub: 0,
  daily_budget_rub: 10_000_000,
};

function validation(overrides: Partial<ValidationResult> = {}): ValidationResult {
  return {
    contract_name: "validation_result_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    validation_id: "validation_222222222222",
    upload_id: "upload_333333333333",
    status: { code: "valid", display_text: "План можно рассчитать" },
    validator_name: "synthetic_validator",
    validator_version: "1.0.0",
    started_at_utc: "2026-08-01T00:00:00Z",
    finished_at_utc: "2026-08-01T00:00:01Z",
    source_payload: {
      artifact_id: "artifact_444444444444",
      kind: "campaign_upload_parsed",
      display_name: "synthetic.csv",
      media_type: "text/csv",
      sha256: "a".repeat(64),
      size_bytes: 100,
      storage_key: "synthetic/parsed.csv",
    },
    model: null,
    normalized_plan: null,
    daily_flighting: null,
    model_validation: null,
    campaigns: [campaign],
    totals: null,
    blocking_errors: [],
    warnings: [],
    job_creation_allowed: true,
    ...overrides,
  };
}

function issue(overrides: Partial<ValidationIssue> = {}): ValidationIssue {
  return {
    code: "LIMITED_CHANNEL_HISTORY",
    severity: "warning",
    display_text: "Synthetic review text",
    scope: "cell",
    recoverable: true,
    source_row_ids: [3],
    affected_cells: [{
      campaign_id: campaign.campaign_id,
      segment: "Сегмент A",
      geo: "Гео A",
      channel: "Канал B",
      target: "turnover_per_user",
    }],
    ...overrides,
  };
}

describe("new calculation file policy", () => {
  it.each(["plan.csv", "PLAN.CSV", "plan.xlsx", "PLAN.XLSX"])("accepts %s", (name) => {
    expect(checkCampaignFilePolicy(name)).toMatchObject({ accepted: true, code: "accepted" });
  });

  it.each(["plan.xls", "plan.tsv", "plan.pdf", "plan"])("rejects unsupported %s", (name) => {
    expect(checkCampaignFilePolicy(name).accepted).toBe(false);
  });

  it.each(["plan.final.csv", "plan.2026.08.xlsx"])("accepts ordinary dotted file name %s", (name) => {
    expect(checkCampaignFilePolicy(name)).toMatchObject({ accepted: true, code: "accepted" });
  });
});

describe("new calculation URL state", () => {
  it("restores upload result, review and scenarios only with matching resource IDs", () => {
    expect(resolveNewCalculationStep("?uploadId=upload_111111111111&step=upload-result").step)
      .toBe("upload-result");
    expect(resolveNewCalculationStep("?validationId=validation_222222222222&step=review").step)
      .toBe("review");
    expect(resolveNewCalculationStep("?validationId=validation_222222222222&step=scenarios").step)
      .toBe("scenarios");
  });

  it("supports the previous validationId-only review URL", () => {
    expect(resolveNewCalculationStep("validationId=validation_222222222222").step).toBe("review");
  });

  it("fails closed for missing or malformed IDs and unknown steps", () => {
    expect(resolveNewCalculationStep("step=scenarios")).toEqual({
      step: "upload",
      uploadId: null,
      validationId: null,
    });
    expect(resolveNewCalculationStep("validationId=RAW_ID&step=review").step).toBe("upload");
    expect(resolveNewCalculationStep("uploadId=upload_111111111111&step=internal").step).toBe("upload");
  });
});

describe("single campaign and validation status guards", () => {
  it("allows exactly one campaign and blocks missing, pending and multiple counts", () => {
    expect(guardSingleCampaign(1)).toMatchObject({ allowed: true, state: "single" });
    expect(guardSingleCampaign(0)).toMatchObject({ allowed: false, state: "missing" });
    expect(guardSingleCampaign(null)).toMatchObject({ allowed: false, state: "pending" });
    expect(guardSingleCampaign(2)).toMatchObject({
      allowed: false,
      state: "multiple",
      title: "В файле обнаружено несколько кампаний",
    });
  });

  it("requests validation only for a parsed one-campaign upload", () => {
    expect(uploadCanProceedToValidation({
      status: { code: "parsed", display_text: "Файл разобран" },
      detected_campaigns_n: 1,
    })).toBe(true);
    expect(uploadCanProceedToValidation({
      status: { code: "parsed", display_text: "Файл разобран" },
      detected_campaigns_n: 2,
    })).toBe(false);
    expect(uploadCanProceedToValidation({
      status: { code: "received", display_text: "Файл получен" },
      detected_campaigns_n: null,
    })).toBe(false);
  });

  it("maps the three approved final statuses and checking state", () => {
    expect(getValidationTopStatus(validation())).toMatchObject({ code: "ready", canContinue: true });
    expect(getValidationTopStatus(validation({ warnings: [issue()] }))).toMatchObject({
      code: "warning",
      canContinue: true,
    });
    expect(getValidationTopStatus(validation({
      status: { code: "invalid", display_text: "Invalid" },
      blocking_errors: [issue({ severity: "blocking" })],
      job_creation_allowed: false,
    }))).toMatchObject({ code: "blocked", canContinue: false });
    expect(getValidationTopStatus(validation({
      status: { code: "running", display_text: "Running" },
      campaigns: [],
      job_creation_allowed: false,
    }))).toMatchObject({ code: "checking", canContinue: false });
  });

  it("fails closed for a contract-inconsistent valid multi-campaign response", () => {
    expect(getValidationTopStatus(validation({ campaigns: [campaign, { ...campaign, campaign_id: "campaign_999999999999" }] })))
      .toMatchObject({ code: "blocked", canContinue: false });
  });

  it("fails closed when a blocking issue is misplaced in warnings", () => {
    expect(getValidationTopStatus(validation({
      warnings: [issue({ severity: "blocking" })],
    }))).toMatchObject({ code: "blocked", canContinue: false });
  });
});

describe("scenario explanation", () => {
  it("defines all six scenarios once and keeps S5/S6 roles distinct", () => {
    expect(NEW_CALCULATION_SCENARIOS).toHaveLength(6);
    expect(new Set(NEW_CALCULATION_SCENARIOS.map((scenario) => scenario.id)).size).toBe(6);
    expect(NEW_CALCULATION_SCENARIOS[4]).toMatchObject({
      id: "S05",
      title: "Самый устойчивый план",
      role: "benchmark",
    });
    expect(NEW_CALCULATION_SCENARIOS[5]).toMatchObject({
      id: "S06",
      title: "Адаптивный поиск",
      role: "adaptive",
    });
    expect(JSON.stringify(NEW_CALCULATION_SCENARIOS[5])).not.toContain("побед");
  });

  it("builds invariants only from campaign contract fields", () => {
    expect(buildScenarioInvariantSnapshot(campaign)).toEqual({
      totalBudgetRub: 10_000_000,
      startDate: "2026-08-01",
      endDate: "2026-08-31",
      channels: ["Канал A", "Канал B"],
      geographies: ["Гео A", "Гео B"],
      existingCellsRule: "Новые каналы, гео и связки гео × канал не добавляются.",
    });
    expect(SCENARIO_RECOMMENDATION_RULES).toHaveLength(5);
  });
});

describe("safe validation issue helpers", () => {
  it("groups affected entities and hides an unknown raw target", () => {
    const rawTarget = "RAW_INTERNAL_TARGET";
    const groups = groupIssueAffectedEntities(
      issue({
        source_row_ids: [7, 3, 7],
        affected_cells: [
          ...issue().affected_cells,
          {
            campaign_id: campaign.campaign_id,
            segment: "Сегмент A",
            geo: "Гео B",
            channel: "Канал A",
            target: rawTarget,
          },
        ],
      }),
      [campaign],
    );

    expect(groups).toMatchObject({
      campaigns: ["Тестовая кампания"],
      segments: ["Сегмент A"],
      channels: ["Канал B", "Канал A"],
      geographies: ["Гео A", "Гео B"],
      geoChannelPairs: ["Гео A × Канал B", "Гео B × Канал A"],
      targets: ["Оборот на пользователя", "Показатель 1 — название не поддерживается"],
      sourceRows: [3, 7],
    });
    expect(JSON.stringify(groups)).not.toContain(rawTarget);
  });
});
