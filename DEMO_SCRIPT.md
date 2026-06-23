# ParkVision-Saathi — Demo Script

A rehearsed, **fully offline** walkthrough. Everything below replays from cached
JSON artifacts — no live network calls, no API quota burned during the demo. The
calibrated **v2** CIS is the default; the uncalibrated **v1** is one flag away
(`CIS_ARTIFACT_PATH` / file rename) if anything misbehaves.

> One-line thesis: the hackathon theme asks us to **quantify illegal parking's
> impact on traffic flow**. The Congestion Impact Score (CIS) is that
> instrument — and we made it **calibrated, validated, and honest about its own
> trustworthiness**, not a black-box guess.

---

## 0. Before you start (30s setup, off camera)

- Backend running from cached artifacts; frontend dev server up.
- Confirm `/health` shows the data layer and (if a real peak-time collection has
  been calibrated) `calibration.calibrated: true` with a `calibrated_bucket`.
- Decide your **trust branch** from the proof panel's badge: **strong / weak /
  aborted** (see §5). Rehearse the matching sentence — do *not* invent numbers.

---

## 1. The problem (20s)

"Cities can see *where tickets are written*. They can't see *where parking
actually chokes traffic*. Those are not the same place — a busy arterial absorbs
violations; a narrow choke point with a few double-parkers seizes up. We quantify
that difference and make it trustable."

## 2. Density ≠ Impact, on the map (40s)

- Toggle the heatmap between **Violation Density** (raw counts) and **Congestion
  Risk** (CIS). Point out a zone that is hot on one layer and cool on the other.
- "Density and impact rank zones *differently*. Counting tickets is not measuring
  congestion. That's the whole point — and we don't just assert it, we prove it."

## 3. The proof panel — the credibility moment (60s)

Open the **Agent** panel → the **"Density ≠ Impact (validated)"** block.

- Two scatter plots vs **measured MapMyIndia travel-time ratio**:
  - **Honest CIS** (the four violation/road components, **no** traffic signal).
  - **Raw violation count** (the density baseline).
- Each shows **Spearman ρ with a bootstrap confidence interval**, computed on a
  **held-out test split** of zones (70/30, deterministic).
- Lead with the **verdict badge** (strong / weak / aborted) and read the matching
  line from §5.

Key honesty points to say out loud:
- "The trust metric is **non-circular**: the honest predictor *excludes*
  `traffic_degradation`, the one component derived from the measured ratio. So we
  can't accidentally validate the score against itself." (This is enforced by an
  airtight test, not a promise.)
- "We also show the **full CIS** ρ, but only as a *circular upper bound* — it
  contains the measured ratio, so it's labelled as such and is **not** the trust
  metric."

## 4. The calibration loop — self-validating agent (40s)

Same panel, **"Calibration Loop (MapMyIndia)"**:

- Before/after **fitted weights** table + "agreement with reality went ρ_old →
  ρ_new on N real-traffic zones."
- "We fit the four violation/road weights to real congestion by maximizing rank
  correlation. `traffic_degradation` stays fixed at 0.25 — it *is* the measured
  signal, so fitting it to itself would be circular."
- Coherence note: once the weights are calibrated, the agent runs **report-only**
  (it shows the comparison; it does **not** nudge the score a second time against
  the same signal).

## 5. The trust verdict — say the right sentence (pick ONE branch)

The proof badge is computed from the **measured** result (`calibration_strength`):

- **STRONG** — "On held-out zones, the honest CIS's confidence interval clears
  the raw-count baseline and the correlation is solidly positive. Congestion
  impact is measurably more than violation density — proven, with uncertainty
  shown."
- **WEAK** — "On held-out zones the honest CIS points the right way, but the
  confidence intervals overlap the baseline — it's **suggestive, not conclusive**
  at this sample size. We report it honestly and show the CIs rather than
  overselling a point estimate."
- **ABORTED** — "The collection didn't yield a usable signal — either too few
  measured zones or near-flat ratios (an off-peak window makes every ratio ≈ 1).
  That's an honest non-result: we abort the verdict rather than fabricate one,
  and the methodology (peak-time collection, exploration sampling) is the fix."

> Never quote a specific ρ you haven't measured live. The UI shows the real
> number and its CI; let the screen speak.

## 6. From insight to action — throughput simulation (40s)

Open **Simulate**:
- Move the patrol-team slider. Show **modeled** city congestion-index reduction
  vs team count, grounded in the calibrated CIS.
- "Every constant here is documented and the result is labelled a **modeled
  estimate under stated assumptions** — we don't fabricate precise minutes saved."

## 7. Predict + explain, honestly (30s)

Open **Forecast**:
- Next-day hotspot risk per H3 zone; **SHAP** shows *why* a zone is flagged.
- Bias note: "Records are **enforcement locations**, not ground-truth violations.
  We mitigate the feedback loop with **10% exploration** toward under-observed
  zones, and we say so on the panel."

## 8. Close (15s)

"So: a congestion score that's **calibrated to real traffic**, **validated on
held-out zones with confidence intervals**, **honest when the signal is weak**,
and **actionable** through patrol optimization — all replayable offline. That's
how AI-driven parking intelligence quantifies impact on traffic flow and targets
enforcement."

---

## Fallback / safety

- If anything looks off, switch to the **v1** artifact (one flag) — the working
  demo never depends on the calibration being present.
- If `/validation/proof` is **pending** (no live collection yet), the panel shows
  a graceful "pending a live peak-time MapMyIndia run" message — say exactly that;
  the machinery is built and tested, the numbers come from the real run.
- Everything is deterministic and offline; re-running shows identical results.
