# ParkVision-Saathi — Judge Q&A

Honest, rehearsed answers to the questions a sharp judge will ask. The guiding
rule: **report what was measured, never promise a number.** A weak or aborted
result is a legitimate finding, not a failure to hide.

---

### Q. Is the Congestion Impact Score (CIS) a trained ML model? What's its accuracy?

No — and that distinction is deliberate. The CIS is a **transparent weighted
formula** over five components (lane blockage, intersection impact, traffic
degradation, access blockage, vehicle size). It has no single "accuracy"; instead
we **calibrate its weights to real congestion** and report a **rank correlation
(Spearman ρ) with a bootstrap confidence interval on a held-out test split** of
zones. The RMSE/MAE numbers you may see elsewhere belong to a *different* system —
the next-day violation-count forecast — not the CIS.

### Q. How do you validate a score that has no ground-truth label?

We bring in an **external** signal: the **MapMyIndia travel-time ratio**
(live ETA vs free-flow) measured locally around each zone. That ratio is the
CIS-independent ground truth we correlate the CIS against. We split zones
70/30 (deterministic hash) and report correlation on the **held-out test** zones.

### Q. Isn't that circular? The CIS already contains a traffic term.

It would be — which is exactly why the headline trust metric is the **"honest
CIS"** that uses **only the four violation/road components and explicitly
EXCLUDES `traffic_degradation`**, the one component derived from the measured
ratio. We enforce this with an *airtight* test: perturb `traffic_degradation`
arbitrarily and the honest metric does not move. We *also* display the full-CIS
correlation, but clearly labelled as a **circular upper bound**, never as the
trust number.

### Q. What does the proof actually show?

Two correlations vs the measured ratio on held-out zones: the **honest CIS** and
the **raw violation count** (the "density" baseline). The thesis — *density ≠
impact* — is supported when the honest CIS tracks real congestion better than raw
counts do. The verdict is summarized as a **strength badge**:

- **strong** — the honest CIS's CI lower bound clears the count baseline **and**
  ρ is solidly positive (> 0.3).
- **weak** — a positive but **inconclusive** signal (CIs overlap the baseline, or
  ρ below the strong bar). Reported as-is.
- **aborted** — no usable signal: too few measured zones or near-flat ratios.

### Q. What if the result is weak or aborted? Doesn't that sink the project?

No. We designed for honesty:
- **Weak** → we show the confidence intervals and say it's suggestive, not
  conclusive, at this sample size. The instrument and methodology stand.
- **Aborted** → almost always the **peak-time gotcha**: off-peak, every
  travel-time ratio ≈ 1.0, so there's no variance to calibrate against. Our
  collector **warns** outside peak windows and the calibration **flat-variance
  aborts** rather than fitting noise. The fix is operational (collect at peak),
  not architectural.

We deliberately **do not commit fabricated correlation numbers**. Real numbers
come only from a live peak-time MapMyIndia run; until then the proof panel shows a
graceful "pending" state and the uncalibrated v1 score is served.

### Q. Your sample is small (~150 zones). Why trust anything?

Exactly why we **don't oversell**:
- Every ρ carries a **bootstrap confidence interval**, not a bare point estimate.
- The degradation model is a **strongly-regularized Ridge** evaluated with
  **leave-one-zone-out** CV (leakage-free), not a high-variance model.
- We **explore**: ~40 lower-volume zones are sampled alongside the dense ones, so
  the trust metric isn't measured only where data is thick.

### Q. Why MapMyIndia only? Why not TomTom/HERE for the congestion signal?

Two reasons. Budget: a fixed ₹1000 MapMyIndia allowance, and the collector
**estimates and caps cost before any live call**. And principle: the congestion
ratio is something **MapMyIndia provides directly**, so reaching for a second
traffic API for the same signal is out of scope by design.

### Q. Predictive policing — aren't you just sending police where police already go?

We name this risk explicitly. Violation records are **enforcement locations**, not
ground-truth violations. We mitigate the feedback loop with **ε = 0.10
exploration**: 90% of patrol mass follows risk, 10% goes to under-observed zones
(allocation still sums to 1.0). The forecast is **SHAP-explained** per zone, and
the UI carries an honest-limitations note.

### Q. The throughput / minutes-saved number — is that real?

It's a **modeled estimate under stated assumptions**, labelled as such in the UI,
with **every constant documented**. It's grounded in the calibrated CIS and is
monotonic in team count. We don't claim measured minutes.

### Q. Can you reproduce this? Does the demo need the internet?

Fully reproducible and **offline**: fixed seeds everywhere, deterministic
artifacts, and the demo replays from cached JSON. No live calls, no quota burn.

### Q. Did calibration break the existing product?

No — **additive-shadow**. The calibrated v2 is the default but v1 is one flag/
rename away, the schema only adds fields, and the entire existing test suite stays
green. `/health` exposes the calibration metadata (version, fitted weights, trust
metric, calibrated bucket) so the state is always inspectable.

### Q. What's genuinely novel here?

Turning a heuristic score into a **calibrated, self-validating instrument**: fit
the weights to live traffic, predict the missing component instead of hardcoding
0.5, and **report a real, non-circular trust metric with confidence intervals and
an honest strong/weak/aborted verdict** — including the discipline to say "weak"
or "aborted" when that's what the data shows.
