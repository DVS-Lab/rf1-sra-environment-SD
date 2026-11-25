# Katie's baseline imaging denominator

For this secondary analysis, start the participant flow at **151 adults aged 55
or older in the baseline imaging roster**. The Linux2 comparison of IDs in the
current age-filtered BIDS table and the frozen roster returned no differences in
either direction. Neither table is a recruitment register.

| Stage | Change from the preceding stage | Remaining |
| --- | --- | ---: |
| Baseline imaging roster, age 55+ | Starting denominator | 151 |
| Usable Social Doors run | 9 without a documented baseline acquisition, 2 partial, 1 with no recorded choices | 139 |
| Social Doors imaging pool | 2 below 95% reference-mask coverage | 137 |
| Linked analysis workbook | 2 without a screener match, 24 with incomplete required fields, 1 without a numeric ADI rank; no further loss for PM2.5 | 110 |
| Final paired analytic sample | 11 above the task/session mean FD fence on either or both runs; 2 below 95% coverage on the monetary run; no additional exclusions for low tSNR | **97** |

The 137 are **not** the final paired-QC pool: both the Social Doors and monetary
Doors runs must pass for the final analysis. The last step reproduces the
[frozen cohort reconciliation](katie-cohort.md).

## Why the flow does not begin at 164

A conference abstract described 164 older adults as completing both tasks;
an archived Methods draft described 164 as recruited. Neither identifies the
participants counted. The historical recruitment tracker examined also does not
identify a group of 164 under either definition. Subtracting 151 from 164
therefore does **not** establish that 13 people were excluded, withdrew, or
failed to complete scanning. Describe recruitment procedures separately from
the verified baseline imaging denominator.

## Reproducibility

From the analysis checkout on Linux2, the following is optional, read-only and
noninteractive. It verifies the frozen imaging counts and reports any live age
roster differences; it does not search for files, require a recruitment export,
or alter eligibility.

```bash
python3 code/audit_katie_recruitment.py
```

If a dated primary roster for the historical count independently becomes
available, the separate `--roster` / `--source-note` mode compares unique
IDs in both directions and writes only to ignored `work/`. Its inputs are
a CSV or TSV with an `rf1_id` column and a description of the report, cutoff,
and age rule. Optional columns `documented_disposition` and `evidence_ref`
must be supplied together. Do not publish the roster or individual discrepancies.
Such a comparison is not required to reproduce the imaging study sample.
