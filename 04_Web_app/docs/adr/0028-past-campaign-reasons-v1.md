# ADR 0028: reasons for each past-campaign number

## Status

Accepted on 2026-11-05. The model owner saw a first version on sample cards
and asked to drop general sentences: a reason is shown only when it says
something about the campaign itself, otherwise the card keeps the bar alone.
On five sample campaigns he then asked for short phrases (for example
«Достигнут предел насыщения: весь бюджет в одном месте») and no caption under
the bar, and approved the release.

## Context

The model owner asked to add, to every campaign card and to the downloadable
Excel, typical reasons why the campaign got its number (for example too much
money in the same cities and weeks, or other advertising already saturating
demand). The owner also asked that the wording be a fixed part of the catalog
build, so that a later data drop (the third quarter of 2026 and onwards) is
labelled by the same rules without re-inventing them.

The catalog effect of a campaign (ADR 0027) is a leave-one-out effect of the
active model. It can be split, draw by draw, without changing any number:

- `E_lin`: the campaign's money at the first-ruble return, no saturation;
- `E_alone`: only the campaign's money, with its own adstock and saturation;
- `E_loo`: the catalog effect (all other advertising stays).

`E_loo <= E_alone <= E_lin`, so the shares
`kept = E_loo / E_lin`, `own = (E_lin - E_alone) / E_lin` and
`overlap = (E_alone - E_loo) / E_lin` add up to one.

## Decision

1. `02_Code/01_PyMC/14_weekly_joint_campaign_reasons.py` computes the three
   shares and the other model factors (return of the campaign's cities and
   weeks against the average for the same channels, money outside the model,
   effect counted by the forecast tail) for every campaign of a catalog run,
   on the same draws and the same panel. It checks that `E_loo` equals the
   catalog turnover median and fails otherwise.
2. The same step reads facts about the campaign's money from the ledger
   (`mmm_core.campaign_reasons.ledger_facts`): the share of the budget in the
   largest place (places only from money bought for a named place, not from
   agency rows spread over places by a template),
   money per place and week (per week for national channels), the largest
   share of the budget spent in two weeks in a row, and the campaign of the
   same direction with the most money in the same weeks and places.
3. The wording lives in a versioned rule file,
   `02_Code/01_PyMC/configs/campaign_catalog/reason_rules_v3.json`
   (`campaign_reasons_v3_20261105`). Each reason is one short phrase; the
   shares themselves are on the bar. A reason appears only when it is
   specific to the campaign: its own saturation or other advertising clearly
   above the norm of its main channel (with one ledger fact that shows why, or
   the neighbour campaign), money spread clearly thinner than usual, clearly
   fewer losses than usual (only when nothing else pulls the number down:
   most of the effect kept, no weak cities, no money outside the model), a
   clearly different return of its cities and weeks, money outside the model,
   or effect counted by the forecast after the end of the data. The norm is
   the median of campaigns of the same build with the same main channel; a
   channel with fewer than five campaigns is compared with the whole catalog
   (money density is then not compared). At most three reasons; none is fine.
   Changing a sentence or a threshold means a new rule file version.
4. `--relabel-from <earlier reasons folder>` applies a new rule version to the
   numbers of an earlier green run in seconds (with `--ledger` when that run
   has no ledger facts); it refuses a run that belongs to another catalog or
   has a failed check, and a ledger whose campaigns or budgets differ from
   the catalog run.
5. The order for every new catalog is: `09_weekly_joint_campaign_catalog.py`,
   then `14_weekly_joint_campaign_reasons.py` with the same command line, then
   `mmm_core.campaign_catalog_extension --reasons-dir <14 output>`. The
   extension refuses to build without reasons for the same catalog run.
6. The contract gains `campaign.explanation` (`null` or an object with the
   three shares, the first-ruble effect, zero to three reasons with a code and
   a sentence, and the rule version); `schema_version` becomes `1.1.0`. A
   published `1.0.0` catalog is still served, with `explanation: null`, and the
   card then shows no reasons block.
7. The card shows a three-part bar and the reasons when there are any, with
   no caption below. A share that rounds to 0% but is not zero reads
   «меньше 1%». The Excel sheets gain four columns: the three shares and the
   reasons text (empty when none); the technical sheet says that the shares
   come from the same model as ROAS and that the level of the ruble return is
   set by industry values.

## Consequences

- ROAS, turnover, orders and basket numbers do not change; the reasons only
  explain them;
- the same rule file labels every later catalog, so the owner sees the same
  words for the same situation;
- campaigns that keep almost nothing of their possible effect become visible
  with a stated reason;
- a full reasons run costs one more pass over the draws on the model machine;
  a relabel costs seconds.
