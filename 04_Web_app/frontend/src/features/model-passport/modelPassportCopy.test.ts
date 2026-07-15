import { describe, expect, it } from "vitest";
import {
  getAllowedUseCopy,
  getCalculationCopy,
  getDeploymentProfileCopy,
  getEvidenceCopy,
  getRecordOriginCopy,
  getTargetLabel,
} from "./modelPassportCopy";

describe("Model Passport browser copy", () => {
  it("translates stable policy and validation enums", () => {
    expect(getAllowedUseCopy("primary").label).toBe("Основное применение");
    expect(getAllowedUseCopy("diagnostic").description).toContain("не может управлять");
    expect(getEvidenceCopy("unavailable").label).toBe("Нет данных");
    expect(getEvidenceCopy("failed").tone).toBe("danger");
  });

  it("keeps research and production claims separate", () => {
    expect(getDeploymentProfileCopy("research_pilot").label).toContain("Исследовательский");
    expect(getCalculationCopy(true).description).toContain("research-контуре");
    expect(getCalculationCopy(true).description).not.toContain("Проверенный пакет");
    expect(getRecordOriginCopy("synthetic_fixture").label).toBe("Демонстрационные данные");
  });

  it("does not echo an unknown target identifier", () => {
    const label = getTargetLabel("RAW_INTERNAL_TARGET");
    expect(label).toBe("Показатель без пользовательского названия");
    expect(label).not.toContain("RAW_INTERNAL_TARGET");
  });

  it("keeps multiple unknown targets distinguishable without raw identifiers", () => {
    const first = getTargetLabel("RAW_TARGET_A", 1);
    const second = getTargetLabel("RAW_TARGET_B", 2);
    expect(first).not.toBe(second);
    expect(`${first} ${second}`).not.toContain("RAW_TARGET");
  });
});
