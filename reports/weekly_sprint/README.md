# Weekly sprint report artifacts

This directory contains derived report materials for the Clotho sprint weekly report.

Included:

- weekly report markdown;
- PPT outline markdown;
- selected figures;
- derived summary CSV files used to reproduce the report tables and plots.

Not included:

- raw well4 data;
- Gfunction-wells-current.zip;
- stage xlsx/csv raw files;
- full `/tmp` audit directories;
- Excel outputs.

All CSV files here are derived summaries for report traceability. Closure, PKN,
fluid efficiency, and tp outputs remain candidate / diagnostic results, not final
interpretation.

## Directory layout

```text
reports/weekly_sprint/
├── README.md
├── WEEKLY_REPORT_CLOTHO_SPRINT.md
├── PPT_OUTLINE_CLOTHO_SPRINT.md
├── figures/
└── artifacts/
```

`figures/` contains PNG figures generated with Matplotlib for the weekly report.
`artifacts/` contains derived CSV summaries and `artifact_manifest.csv`, which
records each committed artifact's purpose and source `/tmp` path.
