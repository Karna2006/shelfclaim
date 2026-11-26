# Evaluation — `sw_20261126_225839_2007`

The S06–S10 replay completed and the packet validation gate passed. Detection was restricted to the three reviewed shelf frames (57, 62, and 90), so the 11 book rows are not a full-sweep coverage claim. Four were identified and 7 remain unidentified. This is a pipeline result, not an accuracy result: the available ground-truth count file has no measured `true_count` rows, so identity and count accuracy cannot be calculated.

## Evaluation bars

| Metric | Pass bar | Result | Evidence |
|---|---:|---|---|
| Book count error | ≤ 5% | NOT MEASURED | `eval/ground_truth/count_gt.csv` has no measured `true_count` rows |
| Title ID accuracy | ≥ 70% | NOT MEASURED | No matched title ground truth |
| Confidently wrong | ≤ 3% | NOT MEASURED | No matched title ground truth |
| Spine dimensions | 17/20 within 15% | NOT MEASURED | Reviewed frames had no ArUco markers; dimensions remain null |
| Book prices | 12/15 within 25%; median ≤ 25% | NOT MEASURED | No checked-price ground truth |
| Non-book items | ≥ 80% correct category | NOT MEASURED | No labelled item ground truth |
| Floor area | ≤ 10% | NOT MEASURED | Room reconstruction is disabled |
| Wall area | ≤ 15% | NOT MEASURED | Room reconstruction is disabled |
| Time to packet | < 5 min | 96.118319 s | S06–S10 replay telemetry; earlier stages are excluded |

## Identification and price output

| Book | Catalogue result | Confidence | New offer | Used offer |
|---|---|---:|---|---|
| `b_0003` | *The Everyday Hero Manifesto* — Robin Sharma | 1.0 | Not found | ₹732.897, [eBay UK](https://www.ebay.co.uk/itm/298735946906), converted |
| `b_0004` | *The Almanack of Naval Ravikant* — Eric Jorgenson | 1.0 | Not found | ₹1,165.3668, [eBay UK](https://www.ebay.co.uk/itm/277529913307), converted |
| `b_0005` | *Leaders Eat Last* — Simon Sinek | 1.0 | Not found | ₹725.6286, [eBay UK](https://www.ebay.co.uk/itm/142087741059), converted |
| `b_0009` | *Heal Your Mind Heal Your Life* — Monica DuBay | 1.0 | Not found | ₹609.3342, [eBay UK](https://www.ebay.co.uk/itm/306780643589), converted |

The replay used 8 SerpApi searches. The four used offers have per-line source URLs and FX evidence in the saved price artifacts. Google Books sale prices are not used. No price accuracy is claimed without checked-price labels.

## Telemetry

These stage durations are from the S06–S10 replay only:

| Stage | Duration |
|---|---:|
| S06 identification | 65.652798 s |
| S07 book pricing | 30.327691 s |
| S08 items | 0.024337 s |
| S09 room fields | 0.003086 s |
| S10 packet and report | 0.091901 s |

Cost per sweep: **TODO: fill when provider rates are set and cost telemetry is available**. Full capture-to-packet latency and S01–S05 durations: **TODO: fill from a full-run telemetry record**. `config/pricing_rates.yaml` still has TODO rates.
