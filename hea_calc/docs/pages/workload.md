# Workload Estimation

Before a batch starts, the calculator counts the compositions it will generate and estimates the calculation time
and the temporary disk space the results will occupy. The count is exact; the time and storage figures are estimates
based on measurements made during development. Single compositions need no estimate.

## Where the estimates appear

* **Composition space** — the **Workload summary** below the composition table shows the number of valid
  compositions, the estimated runtime and the estimated temporary storage. Its information icon explains the
  figures.
* **Large workloads** — from 250,000 compositions the footer shows **Large workload**; its information icon gives
  the estimate. You can still calculate.
* **Too large** — batches of more than 10,000,000 compositions, or batches whose results would not fit on the disk,
  are not started.

## Runtime estimate

The estimated calculation time is

*t* = *N* / (2,250 × *W*) seconds,

where *N* is the number of valid compositions and *W* the number of calculation processes used on this computer (one
fewer than the number of logical processors, at most eight). The rate of 2,250 compositions per second per process
was measured on the development computer for five-element compositions, including storage of the results. It is a
fixed value: it is not measured on your computer and does not account for processor speed, disk speed or the number
of elements per composition. Treat it as an order of magnitude.

During a calculation the header shows the remaining time measured on your computer from the progress so far; this
value replaces the estimate.

## Temporary storage estimate

Results are stored on disk, not in memory, in a temporary database created for this session. The estimated size is

*S* = *N* × 480 bytes,

the largest size per result measured during development, including the database's write-ahead log. Sizes are shown
in decimal units (1 MB = 1,000,000 bytes). A batch starts only if the disk holding the temporary folder has room for
the estimate plus a reserve of 512 MiB used for sorting and filtering.

The database is stored in your temporary folder (`%TEMP%\HEA Calculator\`) and is deleted when the calculator
closes. Export results you want to keep.

| Composition count | Tier | Estimated storage |
|---|---|---|
| fewer than 250,000 | — | below 120 MB |
| 250,000 – 999,999 | Large set | 120 – 480 MB |
| 1,000,000 – 10,000,000 | Very large set (more than one Excel worksheet) | 0.48 – 4.8 GB |
| more than 10,000,000 | Too large — not started | — |

## Execution strategy

Small batches (up to 300 compositions) are calculated directly. Larger batches are generated and calculated in
parallel background processes in groups of 50 to 500 compositions; results are written to the database in order as
they arrive, so the table fills while the calculation runs and the window remains responsive. **Cancel** stops the
calculation; results calculated up to that point are kept.

## Accuracy and limitations

* The composition count is exact.
* The runtime estimate uses one fixed rate measured on a different computer; actual time may differ by a factor of
  several. The remaining time shown during the calculation is measured and more reliable.
* The storage estimate uses the largest measured size per result; actual use is usually lower.
* The largest batch tested end to end is about 1.04 million compositions; storage and table operations were tested
  to 10 million results. The 10,000,000 limit reflects this testing, not a scientific restriction.
