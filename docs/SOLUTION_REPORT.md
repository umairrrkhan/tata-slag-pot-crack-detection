# Automated non-contact crack inspection of slag pots

Date: 11 October 2026. Repository: `umairrrkhan/tata-slag-pot-crack-detection`.

## Revision status

The delivered software is now `morphology-edge-v2`. Read [the low-memory report](EDGE_OPTIMIZATION_REPORT.md) for current tests, measured resource use, streaming, and fixes. The v1 timings below are historical; current measurements include a controlled before/after comparison. Production imaging and validation requirements remain applicable.

## Recommendation

Install a fixed inspection station on the empty-pot return route, using high-resolution visible cameras as the primary crack sensing modality, with a high-temperature radiometric thermal camera as supporting evidence. Use existing handling equipment to present repeatable views. All instruments remain on the station, with no sensor mounted on a pot. Process images locally and automatically create a ranked defect report and a digital inspection history for each of approximately 20 pots.

Use a trained lightweight pixel segmentation model for production once plant data is available. This repository supplies a working, fast, deterministic CPU morphology baseline for testing acquisition, reporting, ranking, and recordkeeping before model training. It is not a trained or certified crack detector. No plant data, pot CAD, minimum detectable crack dimensions, approved severity limits, or camera specifications were supplied; these must be established during the pilot.

## Station and acquisition

1. Place the station away from pouring and active slag handling. Inspect an empty, stationary pot at an operationally suitable hold point. Use plant safety interlocks and verify the required mechanical presentation with operations.
2. Survey the pot geometry, recurring crack positions, permitted viewing angles, and available dwell time. Provide side, rim/lip, lower-body, base, and accessible interior views. The pot and existing carrier can occlude areas; add cameras or controlled repositioning to meet coverage. Missing coverage must produce an incomplete inspection.
3. Mount industrial global-shutter visible cameras with lenses selected for the minimum crack opening and field of view. Use strobed blue/green illumination and matched optical filters to reduce hot-body glow. Verify exposure, reflection rejection, optical signal, and motion blur on real hot, scaled surfaces.
4. Protect station cameras with rated cooled or air-purged enclosures, radiant heat shielding, sacrificial windows, and remote electronics. Calculate standoff and housing heat load from actual geometry, exposure duration, and surrounding equipment; a 700°C surface does not imply an ordinary camera can operate nearby.
5. Add a radiometric thermal camera with a documented measurement range extending beyond 700°C and suitable optics/filter options. Record emissivity assumptions, reflected temperature, distance, atmospheric conditions, and calibration. A high-temperature MWIR system is a candidate; final spectral band and detector choice require a vendor demonstration. Do not assume consumer thermal cameras are suitable.
6. Identify the pot using the existing PLC/carrier mapping or an externally visible identifier that survives service. Confirm ID consistency across all views and record cycle count when available. No new mounted sensing device is required.
7. Trigger short bursts after motion settles. Production software selects sharp, unclipped frames, checks dust/steam/occlusion and pose, requests reacquisition when needed, and registers images to a canonical pot coordinate system. Log capture time and sensor settings.

The software baseline implements contrast/clipping quality gates and declared view completeness. Hardware triggering, identity integration, motion/blur and occlusion classifiers, pose registration, automatic frame selection, and PLC interlocks are production integration work, not implemented capabilities.

## Optical resolution

Design from a specified minimum crack opening, not a camera megapixel count. As a preliminary sampling rule, require at least three image pixels across that opening; engineering validation must establish actual detectability under scale, dust, heat shimmer, and oblique views.

For a 0.5 mm opening, target object sampling at or below 0.167 mm/pixel. Across a 1 m view that requires roughly 6,000 horizontal pixels; smaller views or multiple cameras may be necessary. At the demo's 0.5 mm/pixel calibration, a three-pixel line represents 1.5 mm. Its synthetic success does not demonstrate 0.5 mm crack detection. The baseline uses a nine-pixel morphology window and should be tuned to a validated range of apparent widths.

Physical dimensions require calibrated local geometry. A single global scale is acceptable only for a rectified, approximately planar patch at the calibrated pose. Curved walls and steep viewing angles need local mapping from CAD, stereo, or surveyed calibration. The prototype reports projected line extent and average pixel area/extent width; it does not measure true crack path length, maximum opening, depth, wall penetration, or remaining strength.

## Analysis and classification

Production processing should segment the pot surface, verify coverage, normalize lighting, and perform full-surface crack segmentation. Use recurring locations to prioritize additional high-resolution passes and review, while retaining full-surface inspection for new locations. Distinguish crack patterns from casting seams, scratches, oxide, adhered slag, repairs, and shadows using plant annotations.

Train a compact segmentation network with patch processing and overlapping context. Label isolated, branched, network, and uncertain surface indications if there are enough samples for those classes. Export to ONNX and benchmark FP16 or validated INT8 inference on the chosen edge device. Optimize only after confirming small-crack recall. Retain a frozen validation set when tuning thresholds.

The implemented baseline:

- Applies grayscale closing/opening to detect narrow dark and bright indications; both polarities matter under changing illumination.
- Labels 8-connected components and uses principal-axis geometry to reject small, broad, and roughly round responses.
- Labels retained candidates as horizontal, vertical, or oblique, in image coordinates. These are orientation categories, not metallurgical failure modes.
- Examines the complete supplied ROI and adds a ranking bonus for recurring-location overlap.
- Optionally corroborates a visible candidate with local thermal contrast. Absence of thermal contrast never removes a visible candidate. Thermal anomalies alone are not reported as cracks by this baseline.
- Ranks review priority with an explicit heuristic from projected size, hotspot overlap, and thermal support. This score is not model confidence, severity, or failure probability.

Thermal imaging alone is insufficient: emissivity changes, oxide and slag deposits, reflected radiation, and cooling gradients can mimic cracks; a crack can have little resolvable thermal contrast. Optional 3D imaging can improve registration and verify geometric openings where optical conditions permit, but hot-surface glare and resolution still require testing. Depth and subsurface damage require suitable qualified NDT after cooling or other separately validated methods. A hidden crack cannot be inferred reliably from a clean visible surface.

## Speed and scale

The CPU baseline uses compiled NumPy/SciPy operations. Filters and component labeling operate over pixels; geometry is computed only within component bounding boxes. For fixed filter sizes, expected processing work is approximately linear in pixel count, with memory proportional to image size. Pathological image texture can increase component overhead. The default 1,048,576-pixel edge limit (eight million in the optional standard profile) bounds input size, not a certified memory ceiling.

At the scale of 20 pots, one shared station with local processing is preferable to instrumenting every pot. Pipeline acquisition and processing in production and cap queues so stale inspections are visible. Derive scheduling from the actual return rate and station dwell time; 20 pots alone does not determine throughput.

Proposed pilot target: results within five seconds of the final valid frame for the agreed complete view set, with reacquisition time reported separately. This is an engineering target, not a demonstrated production measurement. Measure p50/p95/p99 end-to-end timing on the selected hardware, including registration, thermal mapping, storage, and PLC exchanges.

## Digital records and actions

The prototype writes a UUID-scoped Markdown and JSON report and annotated PNG for each view. SQLite records pot ID, UTC capture time, status, report path, report hash, and complete JSON; an index supports per-pot history queries. Provenance includes algorithm version, thresholds, manifest, and SHA-256 input hashes. Filenames use constrained identifiers to prevent output path traversal. NumPy thermal loading disables pickles.

An incomplete or uninspectable result must trigger reacquisition or manual inspection under plant procedure. An urgent candidate requests prompt qualified review; authorized personnel decide quarantine, NDT, repair, or serviceability using established engineering limits. No software result in this repository releases a pot automatically.

Production records should add calibrated pot coordinates, defect IDs matched across views/cycles, reviewer decisions, repair history, audit events, immutable original camera captures, model artifact hashes, retention policy, access control, backup, and MES/CMMS integration. Prototype history is append-only through the application, but SQLite is not tamper-proof. Report files and database writes are not one atomic transaction; a process crash can leave an unindexed directory. Ordinary persistence exceptions now remove partial directories and staging is cleaned automatically. Recovery and reconciliation are needed before unattended deployment. Missing thermal data is explicitly visible in provenance and candidate fields, but camera dropout recovery is not implemented.

## Predictive monitoring

Start with registered defect growth trends, cycle counts, thermal exposure, repair history, and inspector outcomes. Assign persistent defect IDs and compare measurements only when view pose and calibration are comparable. Use uncertainty bands and trigger inspection escalation for validated growth limits. A later survival or hazard model could combine these signals with real failure/censoring records. With approximately 20 assets and no supplied failure history, a defensible remaining-life model cannot be trained here; failure prediction is deliberately not claimed.

## Validation and acceptance

Collect real hot and cooler inspections across all pots, crack sizes and locations, repair states, surface contamination, lighting, steam, dust, and operational poses. Include confirmed defects and hard negatives. Obtain qualified ground truth using appropriate inspection/NDT procedures; keep label uncertainty explicit.

Split data by pot and capture period to prevent adjacent frames and repeated cracks leaking across train/test sets. Validate on held-out pots or grouped cross-validation, and later on a prospective time period. Report defect-level recall by minimum opening/length, location and temperature band; false alarms per pot; localization error; measurement error; coverage; uninspectable rate; and full-cycle latency. Use confidence intervals and an adequate defect count. For example, zero misses among 100 independent confirmed defects only bounds the one-sided 95% miss rate to roughly 3%; near-identical frames do not supply independent defects.

Proposed acceptance goals, subject to maintenance approval and a defined detectable size: at least 95% defect recall with reported uncertainty, at most one false candidate per complete pot inspection on representative negatives, verified coverage of all critical locations, and p95 reporting latency below five seconds after final frame. These goals are not achieved results. Run in shadow mode alongside existing inspection, investigate every disagreement, and approve operating limits before changing maintenance practice.

### Tests executed in this workspace

Command: `python -m unittest discover -s tests -v`.

**17 tests passed** in 0.287 seconds. Tests cover dark/bright horizontal and vertical candidates, oblique candidates, projected dimensions, random-noise and round-blob negatives, ROI exclusion, clipping/low contrast, optional thermal support, hotspot prioritization without coverage exclusion, invalid calibration/arrays/configuration, missing and unusable views, duplicate IDs, path identifiers, timestamp validation, annotations, Markdown/JSON round trips, and SQLite history with unique inspection records.

Command: `PYTHONPATH=. python tools/demo.py work/demo`.

Two synthetic inserted candidates were detected in a 1024×768 frame. Twenty warmed CPU detector-only runs measured **115.04 ms median** and **125.23 ms p95**. The single demo inspection took **138.79 ms** for input loading, analysis, and provenance, excluding persistence. Environment: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, Linux x86_64. These are workspace measurements, not hardware specifications or plant performance guarantees. The detector-only benchmark excludes thermal processing and reporting. CI is configured to repeat tests and the demo; a GitHub Actions result has not been verified.

Synthetic tests establish software behavior, not reliability in a steel plant. The baseline can confuse seams and narrow shadows with cracks and may miss low-contrast, wide, curved, branched, occluded, or subpixel indications. Quality checks do not detect every form of bad imagery. These limitations motivate plant data, dedicated segmentation, geometry calibration, and qualified review.

## Implementation and procurement sequence

1. Survey pot geometry, minimum defect size, temperature distributions, recurring positions, station space, available dwell time, and existing control interfaces.
2. Demonstrate visible illumination/filtering and radiometric thermal acquisition on hot real pots with an equipment supplier. Confirm enclosure thermal ratings and optical resolution.
3. Use this prototype to exercise manifests, coverage, records, and review workflow; collect labeled pilot captures.
4. Train and compare segmentation against the baseline using the held-out validation protocol. Benchmark production edge hardware and add acquisition/registration/control integrations.
5. Run shadow operation, agree acceptance thresholds, document interventions, and roll out to the fleet after maintenance approval.

Budget requires vendor quotations. Main cost drivers are optical resolution and number of views, rated enclosures/cooling/purge supply, high-temperature radiometric camera, safe mechanical presentation, edge compute, PLC integration, labeling/NDT verification, and maintenance. Keep thermal optional in initial image experiments, but evaluate it before committing to its production cost. Avoid inventing procurement prices without specifications.

## Delivered scope

Working CPU candidate detector, orientation classification, review ranking, optional thermal corroboration, ROI/hotspot support, declared multi-view completeness, annotations, automated Markdown/JSON reports, indexed per-pot records, reproducible demo/benchmark, regression tests, CI configuration, and this engineering report. Camera integration, trained AI, true 3D/depth measurement, cross-cycle defect tracking, unattended recovery, and failure forecasting remain clearly defined production work.
