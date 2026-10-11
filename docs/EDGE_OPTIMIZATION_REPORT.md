# Low-memory slag pot inspection: implementation and validation report

**Submitted by:** Umair (`umairrrkhan`)  
**Date:** 11 October 2026  
**Software revision:** `morphology-edge-v2`  
**Scope:** Working non-contact inspection software optimized for small Linux devices, with measured tests and a realistic path to plant deployment.

## 1. Solution and device target

The proposed inspection station uses fixed visible cameras, optional high-temperature radiometric thermal imaging, and local analysis. No sensor is mounted on a pot. A common station can inspect approximately 20 pots, producing ranked crack candidates, annotated evidence, Markdown/JSON reports, and per-pot history.

The provisional target is a Linux single-board computer with 512 MB–1 GB RAM. The current software requires Python, NumPy, SciPy, and Pillow. It uses CPU processing and requires no GPU, cloud inference, or trained model download. The measurements below were made on x86_64 Linux, not on an ARM board; an actual target device remains to be validated. Microcontrollers with tens of megabytes or less cannot run this dependency stack as supplied. They would require a separate native implementation or offloading to a station computer.

## 2. Problems found and fixes delivered

| Issue in the original implementation | Fix in v2 | Effect |
|---|---|---|
| All decoded views remained in RAM until reporting | Analyze and annotate each view, spool to disk, release image/thermal references | Image-buffer use does not grow linearly with view count |
| Morphology created full-frame floating-point temporaries | Use mathematically equivalent uint8 morphology and in-place subtraction/max operations | Lower memory and CPU time without reducing image resolution |
| Thermal processing converted the entire image to float64 and filtered the full frame | Memory-map the Celsius array, validate in strips, calculate float32 thermal neighborhoods only around retained candidates | Avoid full-frame thermal copies and residual buffers |
| Quality statistics and file hashing used large temporary copies | Strip histogram statistics and streaming SHA-256 | Bounded working buffers |
| Tiny components incurred coordinate extraction work | Count component areas before extracting geometry | Less work on small noise responses |
| Clutter or large components could cause excessive work | Explicit component-count and component-extent budgets | Budget exhaustion requests review; no silent success |
| ROI filtering could use pixels outside the pot mask | Use the complete composed filter support when excluding ROI boundaries | Outside-mask pixels cannot contaminate valid interior results |
| A very narrow ROI could have no valid analysis interior | Return uninspectable instead of a misleading no-candidates status | Makes incomplete analysis visible |
| Some malformed manifest fields failed unclearly | Validate required-view list, capture-time type, and ROI dimensions before mask decode | Predictable input rejection |
| Ordinary persistence failures left partial reports | Clean staging automatically and remove the new report directory on failure; database writes remain transactional | Avoids publishing ordinary failed outputs |
| Reports omitted view failure reasons and missing-view details | Include required coverage, per-view status/reason, and quality information | Reviewers can see why analysis was incomplete |

During validation, the original high-resolution noisy demo exposed an overly strict new component limit. The default was adjusted to 16,384, and a regression test now requires both inserted cracks to remain detectable. The workload budget is explicit and still returns uninspectable if exceeded. This is a resource bound, not a universal plant noise threshold.

## 3. Resource limits and acquisition requirements

The default edge profile permits 1,048,576 pixels per view, up to 32 views, up to 16,384 connected components per view, and up to 262,144 pixels in a retained component's bounding box. `--profile standard` permits eight million pixels per view and requires more RAM. Standard mode is not the low-memory default.

Image resolution is preserved. The algorithm does not downsample narrow cracks to meet its memory budget. A larger camera image must be presented as appropriate calibrated acquisition views or tiles; automatic global tile stitching and cross-tile defect reconciliation are not implemented. Components exceeding the extent budget need closer/reframed views or qualified inspection.

The two morphology stages have a composed eight-pixel support margin. The image border and ROI boundary band are excluded and recorded in quality metadata. Overlapping acquisition views must cover that band, with at least 16 pixels of overlap to avoid a gap between analyzed interiors. Declared required-view completeness does not prove physical surface coverage; the station geometry must be surveyed and verified.

Peak memory also depends on component geometry, ROI masks, dependency versions, native library workspaces, file-backed thermal pages, and output encoding. Limits bound workload, not all process memory. Set the native math-library thread count to one on small devices and benchmark it; the evidence tool does this for consistent comparison.

## 4. Measured before/after results

The source baseline was saved before editing. Each benchmark mode ran in a fresh process using the same inputs, dependency versions, and one math-library thread. The synthetic frame is 1024×768 uint8, with one three-pixel horizontal indication and an aligned float32 Celsius thermal array. Both versions retained that candidate; the 20-view inspection retained one candidate per view.

| Measurement | Original v1 | Optimized v2 | Change |
|---|---:|---:|---|
| Detector + thermal median (ms) | 103.35 | 49.84 | 51.8% less time |
| One-view complete inspection (ms) | 372.90 | 284.31 | 23.8% less time |
| 20-view complete inspection (ms) | 6456.58 | 5024.88 | 22.2% less time |
| Detector tracked allocation peak (MiB) | 30.00 | 3.79 | 87.4% lower |
| Detector process peak RSS (MiB) | 82.79 | 55.27 | 33.2% lower |
| 20-view inspection tracked allocation peak (MiB) | 48.08 | 4.64 | 90.4% lower |
| 20-view inspection process peak RSS (MiB) | 102.34 | 61.39 | 40.0% lower |

The detector timing uses ten warmed runs. Complete inspections are single runs and include image loading, hashing, thermal validation, annotations, JSON/Markdown, SQLite, and filesystem writes. Their reported time is not a p95 throughput estimate. Tracemalloc is enabled during complete-inspection measurements, so those times include instrumentation overhead. Detector timing is measured separately from allocation tracing.

Tracked allocation peak is measured during the call; it is not total RAM. Process peak RSS includes interpreter, imports, inputs, native allocations, and resident memory-mapped pages. It is the high-water mark for each fresh process. Raw evidence and environment details are in [edge-benchmark.json](validation/edge-benchmark.json).

The earlier v1 report's 115 ms result was a different detector-only benchmark without thermal support. Use this controlled table for before/after comparisons. The results do not establish a hard real-time guarantee or ARM performance.

## 5. Tests and functional validation

**31 automated tests passed in 6.174 seconds.** The final noisy demo detected both inserted candidates, and the edge-profile CLI generated a `review_required` report. Its separate grayscale demo benchmark measured 61.82 ms median and 64.26 ms p95 over 20 runs. Raw test output is in [edge-tests.txt](validation/edge-tests.txt).

Tests cover dark/bright and horizontal/vertical/oblique candidates, physical projected estimates, noise/blob negatives, ROI exclusion, optional thermal support, recurring locations, invalid calibration/data/configuration, missing and bad views, duplicate/path identifiers, timestamp handling, annotated images, Markdown/JSON round trips, and history records.

New regressions exercise integer workload budgets, clutter and large-component rejection, ROI without valid filter interior, byte-morphology equivalence to the previous floating-point calculation, local thermal equivalence to full-frame means, malformed manifests, invalid ROI dimensions, injected disk failure cleanup, memory-mapped thermal input, and streaming 20 views. A dedicated memory regression requires a 20-view workload to stay below 12 MiB of tracked allocations, with margin for dependency variation; the old implementation used approximately 48 MiB on the measured workload.

The original noisy 1024×768 demo must detect both inserted indications. The CLI smoke test must create reports with review-required status. These checks establish software behavior; they do not establish actual slag-pot detection accuracy.

Reproduce:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
PYTHONPATH=. python tools/demo.py work/demo
python -m slag_inspect.cli work/demo/manifest.json --output work/reports --profile edge
python tools/benchmark.py --output work/edge-benchmark.json
```

For a controlled comparison, supply `--baseline-root` pointing to a checkout of the original version containing `slag_inspect`. The baseline measured here corresponds to merged PR #1 (`1dff374ec9743d10a985bee72903fe755b4c64a1`); later documentation did not change its detector. No baseline dependency or input files are needed to run the optimized software.

## 6. Gaps reduced and gaps still requiring plant evidence

The software now closes practical low-memory deployment gaps: bounded image processing, no frame accumulation, reduced thermal overhead, explicit resource failure states, stronger input checks, failed-output cleanup, and reproducible tests/benchmarks. It supplies a usable demonstration of non-contact analysis and automatic record generation.

Reliable inspection at 500–700°C still requires rated camera protection, standoff and heat-load design, validated illumination/filtering, calibrated thermal acquisition, pose registration, and full-surface coverage. No hot-pot dataset or target-device hardware was supplied. The baseline can confuse seams/shadows with cracks and miss branched, curved, broad, faint, subpixel, or occluded indications. Depth and remaining strength are not measured, and failure prediction is not implemented.

Next, collect plant images with qualified ground truth and train/evaluate a compact segmentation model against this baseline. Evaluate minimum detectable opening, defect recall by size/location/temperature, false candidates per complete pot inspection, geometry error, coverage, unusable rate, full-cycle latency, RSS, storage, and thermal stability on the actual board. Split validation by pot and time to avoid repeated defects leaking across datasets.

For a minimum 0.5 mm opening, a preliminary three-pixel sampling requirement means at most 0.167 mm/pixel. A one-metre field needs roughly 6,000 horizontal pixels, so small native-resolution views are preferable to destructive global downsampling. Camera choice and inference model size must follow that requirement.

Proposed acceptance targets remain at least 95% recall for agreed reportable defects with uncertainty stated, at most one false candidate per complete inspection, verified critical-area coverage, and p95 reporting within five seconds after the final valid frame. These are pilot goals, not achieved claims. A 20-view timing sample is not the plant pot-return rate and does not establish this latency target.

## 7. Deployment and submission position

Start with a protected shared station, edge profile, reliable local storage, and operations-approved acquisition. Monitor workload failures and queue delays; reacquire or review incomplete inspections. Preserve raw evidence and add backup, reviewer audit, cross-cycle defect IDs, and CMMS integration. Ordinary exception cleanup is implemented, but files and SQLite are not one crash-atomic transaction; hard-kill/power-loss recovery remains production work.

The submission can credibly demonstrate an optimized, tested prototype and a concrete industrial deployment plan. It cannot claim certified hot-pot reliability or autonomous serviceability decisions. The detailed station design is in [SOLUTION_REPORT.md](SOLUTION_REPORT.md), and the main challenge narrative is in [CHALLENGE_SUBMISSION.md](CHALLENGE_SUBMISSION.md).
