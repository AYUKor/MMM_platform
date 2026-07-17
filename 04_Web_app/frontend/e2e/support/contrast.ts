import type { Page } from "@playwright/test";

export interface ContrastTarget {
  name: string;
  selector: string;
}

export interface ContrastSample {
  background: string;
  color: string;
  ratio: number;
  target: string;
  text: string;
}

export async function measureContentContrast(
  page: Page,
  targets: readonly ContrastTarget[],
): Promise<ContrastSample[]> {
  const selector = targets.map((target) => target.selector).join(", ");
  return page.locator(selector).evaluateAll((elements, targetDefinitions) => {
    type Rgba = { r: number; g: number; b: number; a: number };

    const parseColor = (value: string): Rgba => {
      if (value === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
      if (value.startsWith("color(srgb")) {
        const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
        return {
          r: (channels[0] ?? 0) * 255,
          g: (channels[1] ?? 0) * 255,
          b: (channels[2] ?? 0) * 255,
          a: channels[3] ?? 1,
        };
      }
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return {
        r: channels[0] ?? 0,
        g: channels[1] ?? 0,
        b: channels[2] ?? 0,
        a: channels[3] ?? 1,
      };
    };

    const over = (foreground: Rgba, background: Rgba): Rgba => {
      const alpha = foreground.a + background.a * (1 - foreground.a);
      if (alpha === 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (foreground.r * foreground.a + background.r * background.a * (1 - foreground.a)) / alpha,
        g: (foreground.g * foreground.a + background.g * background.a * (1 - foreground.a)) / alpha,
        b: (foreground.b * foreground.a + background.b * background.a * (1 - foreground.a)) / alpha,
        a: alpha,
      };
    };

    const luminance = ({ r, g, b }: Rgba) => {
      const linear = [r, g, b].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    };

    const contrast = (left: Rgba, right: Rgba) => {
      const lighter = Math.max(luminance(left), luminance(right));
      const darker = Math.min(luminance(left), luminance(right));
      return (lighter + 0.05) / (darker + 0.05);
    };

    return elements.flatMap((element) => {
      const htmlElement = element as HTMLElement;
      const rect = htmlElement.getBoundingClientRect();
      const text = htmlElement.innerText.trim();
      if (rect.width === 0 || rect.height === 0 || text.length === 0) return [];

      let background: Rgba = { r: 0, g: 0, b: 0, a: 0 };
      let ancestor: Element | null = htmlElement;
      while (ancestor) {
        background = over(background, parseColor(getComputedStyle(ancestor).backgroundColor));
        ancestor = ancestor.parentElement;
      }
      background = over(background, { r: 255, g: 255, b: 255, a: 1 });
      const colorValue = getComputedStyle(htmlElement).color;
      const foreground = over(parseColor(colorValue), background);

      return targetDefinitions
        .filter((target) => htmlElement.matches(target.selector))
        .map((target) => ({
          background: `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`,
          color: colorValue,
          ratio: contrast(foreground, background),
          target: target.name,
          text: text.slice(0, 80),
        }));
    });
  }, targets);
}
