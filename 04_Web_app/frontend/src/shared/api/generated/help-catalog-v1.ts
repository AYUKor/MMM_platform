/* Generated from ../../contracts/help_catalog_v1.schema.json. Do not edit manually. */

export type ArticleId = string;
export type BodyBlock = Paragraph | Steps | Note;
export type NonEmptyText = string;
export type SafeRoute = "/" | "/calculations" | "/calculations/new" | "/model" | "/help";

export interface HelpCatalogV1 {
  contract_name: "help_catalog_v1";
  schema_version: "1.0.0";
  record_origin: "versioned_help_catalog" | "synthetic_fixture";
  /**
   * @minItems 9
   * @maxItems 9
   */
  sections: [Section, Section, Section, Section, Section, Section, Section, Section, Section];
  updated_at_utc: string;
}
export interface Section {
  section_id:
    | "getting_started"
    | "data_preparation"
    | "scenarios"
    | "result_reading"
    | "reliability"
    | "media_plan"
    | "report"
    | "common_errors"
    | "limitations";
  order: number;
  title: string;
  /**
   * @minItems 1
   */
  articles: [Article, ...Article[]];
}
export interface Article {
  article_id: ArticleId;
  title: string;
  summary: string;
  /**
   * @minItems 1
   */
  body: [BodyBlock, ...BodyBlock[]];
  related_routes: SafeRoute[];
  related_article_ids: ArticleId[];
  /**
   * @minItems 2
   */
  keywords: [string, string, ...string[]];
}
export interface Paragraph {
  block_type: "paragraph";
  text: NonEmptyText;
}
export interface Steps {
  block_type: "steps";
  /**
   * @minItems 1
   */
  items: [string, ...string[]];
}
export interface Note {
  block_type: "note";
  tone: "info" | "warning";
  title: string;
  text: NonEmptyText;
}
