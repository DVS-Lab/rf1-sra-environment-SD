# Verify the recruitment denominator

The manuscript's 164 is a recruitment count, not the denominator of the October imaging handoff. The ID list behind 164 must come from the report/export used to count recruitment, with its cutoff and age definition. Do not use an arbitrary 164-row workbook, today's age-filtered BIDS table, the 137 task IDs, the 110 linked participants, the 97 analyzed participants, or the earlier 33-ID screener investigation as a substitute.

On Linux2, from this repository:

```bash
python3 code/audit_katie_recruitment.py
```

This validates the historical 151/139/137 counts, compares the current scanner-age pool to the frozen pool (a date/age check only), and lists candidate filenames in bounded project locations without opening them. It cannot identify a recruitment roster by filename. Add `--search-root /path/to/recruitment/exports` to search another accessible directory. Jacob's pipeline used a private screener export on Windows; the recruitment source may not be on Linux2. If necessary, ask the owner of the 164 count for **the dated RF1-ID list, its inclusion rule, and the date at which age was defined**. If the original count was a typo or included repeat visits, document that finding instead of manufacturing a 164-person list.

Export one row per person from that source to `work/recruitment-input/recruited_164.tsv` with the header `rf1_id` (CSV also supported). Use five-digit IDs with or without the `sub-` prefix. IDs alone are sufficient to identify discrepancies. Optional columns `documented_disposition` and `evidence_ref` carry visit outcomes when known and traceable to a record. A source reference is required for every supplied disposition; do not include names, birth dates, addresses or clinical notes. No automatic deduplication, age re-filtering or participant changes.

```bash
read -r -p "Source report/version, cutoff and age definition: " NOTE
python3 code/audit_katie_recruitment.py \
  --roster work/recruitment-input/recruited_164.tsv --source-note "$NOTE"
```

The comparison writes a new ignored `work/recruitment-flow-*/` directory each time. `counts.json` is aggregate-only; `discrepancies.tsv` has the two directional differences; `provenance.json` records hashes and the source description. Inspect recruitment-only **and** imaging-only IDs. The difference of 13 is not automatically 13 omitted people. Historical age-filter status and the documented October source exclusions can explain technical nonmembership, not necessarily the participant's visit outcome. The October 15 inventory, when available, and current BIDS evidence are follow-up leads, not proof of a missed visit or withdrawal. Resolve other mismatches against dated visit/disposition records, add only supported reasons to the private input, and rerun. Never publish the recruitment list or individual discrepancy report.
