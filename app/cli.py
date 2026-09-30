"""
CLI entry point for the Wayfair template analyser and auto-fill engine.

Usage:
  python -m app.cli analyse-templates --input-dir <dir> --output-dir <dir>
  python -m app.cli analyse-template  --template <file> --output-dir <dir>
  python -m app.cli fill-template     --template <file> --source <file> --profile <file> --output-dir <dir>
  python -m app.cli fill-templates    --template-dir <dir> --source <file> --profile-dir <dir> --output-dir <dir>
"""
from __future__ import annotations
import argparse
import sys
import traceback
from pathlib import Path

from app.analyser.discovery import discover_templates
from app.analyser.inspector import inspect_workbook
from app.analyser.comparator import compare_profiles
from app.analyser.profile_writer import write_profile
from app.analyser.reporter import (
    write_category_summary,
    write_field_comparison,
    write_unmapped_fields,
    write_validation_findings,
    write_markdown_report,
)
from app.analyser.integrity import snapshot_directory, verify_snapshot, sha256_file


def _print_banner(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def run_analyse_templates(input_dir: Path, output_dir: Path) -> int:
    _print_banner(f"Wayfair Template Analyser  |  input: {input_dir}")

    templates = discover_templates(input_dir)
    if not templates:
        print(f"ERROR: No .xlsx/.csv templates found in {input_dir}")
        return 1

    print(f"\nDiscovered {len(templates)} template(s):")
    for t in templates:
        print(f"  {t.name}")

    # --- Integrity snapshot before analysis ---
    print("\n[Integrity] Taking SHA-256 snapshot before analysis …")
    before_hashes = snapshot_directory(input_dir)

    # --- Analyse each workbook ---
    profiles = []
    failures = []
    for tpl in templates:
        print(f"\n[Analysing] {tpl.name} …")
        try:
            profile = inspect_workbook(tpl)
            profiles.append(profile)

            ls = profile.listing_sheet
            print(f"  Status        : {profile.analysis_status}")
            print(f"  Category      : {profile.category_name}")
            print(f"  Sheets        : {len(profile.sheets)}")
            print(f"  Listing sheet : {ls.name if ls else 'NOT DETECTED'}")
            print(f"  Headers       : {len(ls.columns) if ls else 0}")
            print(f"  Warnings      : {len(profile.warnings)}")
            if profile.errors:
                print(f"  ERRORS        : {profile.errors}")
            if profile.analysis_status == "failed":
                failures.append(tpl.name)
        except Exception as exc:
            print(f"  FATAL: {exc}")
            traceback.print_exc()
            failures.append(tpl.name)

    # --- Write per-profile JSON ---
    profile_dir = output_dir.parent / "template_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    for p in profiles:
        out = write_profile(p, profile_dir)
        print(f"  [Profile] {out.name}")

    # --- Cross-category comparison ---
    print("\n[Comparison] Building cross-category field comparison …")
    comparison = compare_profiles(profiles)

    # --- Write reports ---
    output_dir.mkdir(parents=True, exist_ok=True)
    write_category_summary(profiles, output_dir)
    write_field_comparison(profiles, comparison, output_dir)
    write_unmapped_fields(profiles, output_dir)
    write_validation_findings(profiles, output_dir)

    # --- Integrity verify after analysis ---
    print("\n[Integrity] Verifying original files are unchanged …")
    integrity_results = verify_snapshot(before_hashes, input_dir)
    all_ok = all(v == "unchanged" for v in integrity_results.values())
    for fname, status in sorted(integrity_results.items()):
        mark = "OK" if status == "unchanged" else f"!!! {status.upper()} !!!"
        print(f"  {mark:12} {fname}")

    md_path = write_markdown_report(profiles, comparison, integrity_results, output_dir)

    # --- Summary ---
    _print_banner("Processing Summary")
    print(f"  Total workbooks      : {len(templates)}")
    print(f"  Successful           : {len(profiles) - len(failures)}")
    print(f"  Failed               : {len(failures)}")
    if failures:
        for f in failures:
            print(f"    - {f}")
    print(f"  Shared by all cats   : {len(comparison.shared_by_all)}")
    print(f"  Fuzzy suggestions    : {len(comparison.fuzzy_suggestions)}")
    print(f"  File integrity       : {'PASS' if all_ok else 'FAIL'}")
    print(f"\n  Reports in           : {output_dir}")
    print(f"  Profiles in          : {profile_dir}")
    print(f"  Markdown report      : {md_path.name}")

    return 0 if not failures else 2


def run_analyse_template(template: Path, output_dir: Path) -> int:
    _print_banner(f"Wayfair Template Analyser  |  file: {template.name}")

    if not template.exists():
        print(f"ERROR: File not found: {template}")
        return 1

    before = {template.name: sha256_file(template)}
    profile = inspect_workbook(template)

    profile_dir = output_dir.parent / "template_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    out = write_profile(profile, profile_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_category_summary([profile], output_dir)
    write_validation_findings([profile], output_dir)

    integrity = verify_snapshot(before, template.parent)
    status = integrity.get(template.name, "unknown")
    print(f"\n  Integrity: {status}")
    print(f"  Profile : {out}")

    ls = profile.listing_sheet
    print(f"\n  Category      : {profile.category_name}")
    print(f"  Listing sheet : {ls.name if ls else 'NOT DETECTED'}")
    print(f"  Headers       : {len(ls.columns) if ls else 0}")
    print(f"  Warnings      : {len(profile.warnings)}")
    for w in profile.warnings:
        print(f"    - {w}")

    return 0 if profile.analysis_status != "failed" else 1


def run_fill_template(
    template: Path,
    source: Path,
    profile: Path,
    output_dir: Path,
    config_dir: Path,
    write_policy: str = "append",
) -> int:
    from app.autofill.engine import run_fill
    _print_banner(f"Auto-Fill  |  {template.name}  <-  {source.name}")

    report_dir = output_dir.parent / "fill_reports"
    result = run_fill(
        template_path=template,
        source_path=source,
        profile_path=profile,
        output_dir=output_dir,
        report_dir=report_dir,
        config_dir=config_dir,
        write_policy=write_policy,
    )

    if result.error:
        print(f"\n  ERROR: {result.error}")
        return 1

    wr = result.write_result
    errors   = [i for i in result.all_issues if i.severity == "error"]
    warnings = [i for i in result.all_issues if i.severity == "warning"]

    print(f"\n  Output     : {wr.output_path.name}")
    print(f"  Rows written : {wr.rows_written}")
    print(f"  Errors     : {len(errors)}")
    print(f"  Warnings   : {len(warnings)}")

    if errors:
        print("\n  ERRORS (must fix):")
        for e in errors:
            print(f"    [{e.sku}] {e.wayfair_field}: {e.detail}")

    print(f"\n  Reports    : {report_dir}")
    for label, path in result.report_paths.items():
        print(f"    {label}: {path.name}")

    return 0 if not errors else 2


def run_fill_templates(
    template_dir: Path,
    source: Path,
    profile_dir: Path,
    output_dir: Path,
    config_dir: Path,
    write_policy: str = "append",
    registry_path: Path | None = None,
    include_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
    allow_review_required: bool = False,
) -> int:
    from app.autofill.engine import run_fill
    from app.analyser.discovery import discover_templates
    from app.analyser.template_registry import TemplateRegistry
    import json

    _print_banner(f"Batch Auto-Fill  |  source: {source.name}")

    # Load registry for fill-status filtering (optional)
    registry: TemplateRegistry | None = None
    if registry_path and registry_path.exists():
        registry = TemplateRegistry.load(registry_path)
        print(f"\n  Registry loaded: {registry.summary()}")

    templates = discover_templates(template_dir)
    if not templates:
        print(f"ERROR: No templates found in {template_dir}")
        return 1

    report_dir = output_dir.parent / "fill_reports"
    successes, failures, skipped = 0, [], []

    for tpl in templates:
        # Registry-based fill-status check
        if registry is not None:
            from app.analyser.integrity import sha256_file
            try:
                fhash = sha256_file(tpl)
                reg_entry = registry.find_by_hash(fhash)
            except Exception:
                reg_entry = None

            if reg_entry is not None:
                # Filter by explicit include/exclude IDs
                if include_ids and reg_entry.template_id not in include_ids:
                    print(f"\n  [SKIP] {tpl.name} — not in --include-template-id list")
                    skipped.append(tpl.name)
                    continue
                if exclude_ids and reg_entry.template_id in (exclude_ids or []):
                    print(f"\n  [SKIP] {tpl.name} — excluded by --exclude-template-id")
                    skipped.append(tpl.name)
                    continue

                fs = reg_entry.fill_status
                if fs == "not_fillable":
                    print(f"\n  [SKIP] {tpl.name} — fill_status=not_fillable: "
                          f"{'; '.join(reg_entry.blocking_reasons[:2])}")
                    skipped.append(tpl.name)
                    continue
                if fs == "requires_review" and not allow_review_required:
                    print(f"\n  [SKIP] {tpl.name} — fill_status=requires_review "
                          f"(use --allow-review-required to override)")
                    skipped.append(tpl.name)
                    continue

        # Find matching profile
        stem = tpl.stem
        safe = stem.replace(" ", "_").replace(",", "_").replace("&", "_").replace("/", "_")
        candidates = [
            profile_dir / f"{safe}.json",
            profile_dir / f"{safe.replace('__', '_')}.json",
        ]
        profile_path: Path | None = None
        for c in candidates:
            if c.exists():
                profile_path = c
                break
        if not profile_path:
            for pf in sorted(profile_dir.glob("*.json")):
                try:
                    p = json.loads(pf.read_text(encoding="utf-8"))
                    if p.get("source_file", "").strip() == tpl.name.strip():
                        profile_path = pf
                        break
                except Exception:
                    continue

        if not profile_path:
            print(f"\n  [SKIP] {tpl.name} — no matching profile in {profile_dir}")
            failures.append(tpl.name)
            continue

        # Check fill status from profile JSON (even without registry)
        if profile_path:
            try:
                pdata = json.loads(profile_path.read_text(encoding="utf-8"))
                pfs = pdata.get("template_fill_status", "")
                if pfs == "not_fillable":
                    reasons = pdata.get("blocking_reasons", [])[:2]
                    print(f"\n  [SKIP] {tpl.name} — profile fill_status=not_fillable: "
                          f"{'; '.join(str(r) for r in reasons)}")
                    skipped.append(tpl.name)
                    continue
                if pfs == "requires_review" and not allow_review_required:
                    print(f"\n  [SKIP] {tpl.name} — profile fill_status=requires_review "
                          f"(use --allow-review-required to override)")
                    skipped.append(tpl.name)
                    continue
            except Exception:
                pass  # If profile unreadable, attempt fill anyway

        print(f"\n  [Fill] {tpl.name} …")
        result = run_fill(
            template_path=tpl,
            source_path=source,
            profile_path=profile_path,
            output_dir=output_dir,
            report_dir=report_dir,
            config_dir=config_dir,
            write_policy=write_policy,
        )
        if result.error:
            print(f"    ERROR: {result.error}")
            failures.append(tpl.name)
        else:
            wr = result.write_result
            errs = sum(1 for i in result.all_issues if i.severity == "error")
            print(f"    Rows: {wr.rows_written}  Errors: {errs}  -> {wr.output_path.name}")
            successes += 1

    _print_banner("Batch Fill Summary")
    print(f"  Templates processed : {len(templates)}")
    print(f"  Successful          : {successes}")
    print(f"  Skipped (policy)    : {len(skipped)}")
    print(f"  Failed              : {len(failures)}")
    if failures:
        for f in failures:
            print(f"    - {f}")
    print(f"\n  Filled templates : {output_dir}")
    print(f"  Fill reports     : {report_dir}")
    return 0 if not failures else 2


def run_register_template(
    template: Path,
    profile_dir: Path,
    registry_dir: Path,
) -> int:
    from app.analyser.registration_workflow import register_workbook
    from app.analyser.template_registry import TemplateRegistry

    _print_banner(f"Register Template  |  {template.name}")

    registry_json = registry_dir / "template_registry.json"
    registry_csv = registry_dir / "template_registry.csv"
    registry = TemplateRegistry.load(registry_json)

    result = register_workbook(template, profile_dir, registry)

    if result.error:
        print(f"\n  ERROR: {result.error}")

    print(f"\n  Template ID  : {result.template_id}")
    print(f"  File         : {result.filename}")
    print(f"  Purpose      : {result.purpose.purpose if result.purpose else 'N/A'}"
          + (f" ({result.purpose.confidence:.2f})" if result.purpose else ""))
    print(f"  Fill status  : {result.fill_status}")
    print(f"  Category     : {result.profile.category_name if result.profile else 'N/A'}")
    print(f"  Category status : {result.profile.category_resolution_status if result.profile else 'N/A'}")

    listing = result.profile.listing_sheet if result.profile else None
    print(f"  Listing sheet: {listing.name if listing else 'NOT DETECTED'}")
    det = listing.detection if listing else None
    print(f"  Header row   : {det.header_row if det else 'N/A'}")
    print(f"  Columns      : {len(listing.columns) if listing else 0}")
    print(f"  Safe write row: {result.safe_write_start_row}")

    if result.blocking_reasons:
        print(f"\n  BLOCKING:")
        for r in result.blocking_reasons:
            print(f"    - {r}")

    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings[:5]:
            print(f"    - {w}")

    registry.save(registry_json, registry_csv)
    print(f"\n  Registry saved : {registry_json}")

    return 0 if result.fill_status in ("fillable", "fillable_with_warnings") else 2


def run_register_templates(
    input_dir: Path,
    profile_dir: Path,
    registry_dir: Path,
) -> int:
    from app.analyser.registration_workflow import register_bulk
    from app.analyser.discovery import discover_templates

    _print_banner(f"Register Templates  |  input: {input_dir}")

    templates = discover_templates(input_dir)
    if not templates:
        print(f"ERROR: No .xlsx/.csv templates found in {input_dir}")
        return 1

    print(f"\nDiscovered {len(templates)} template(s)")

    results, registry = register_bulk(templates, profile_dir, registry_dir)

    summary = registry.summary()

    # Print preview table
    print(f"\n{'Workbook':<45}  {'Category':<28}  {'Purpose':<22}  "
          f"{'Sheet':<32}  {'HR':>3}  {'Fill Status':<22}  Blocking")
    print("-" * 170)
    for r in results:
        if r.error and not r.profile:
            print(f"  {'ERROR:':} {r.filename}: {r.error}")
            continue
        p = r.profile
        pu = r.purpose
        listing = p.listing_sheet if p else None
        det = listing.detection if listing else None
        cat = p.category_name[:26] if p else "-"
        purpose = pu.purpose[:20] if pu else "N/A"
        sheet = (listing.name[:30] if listing else "NONE")
        hr = str(det.header_row) if det else "-"
        fs = r.fill_status[:20]
        blocking = "; ".join(r.blocking_reasons[:1])[:40] if r.blocking_reasons else ""
        print(f"  {r.filename[:43]:<45}  {cat:<28}  {purpose:<22}  "
              f"{sheet:<32}  {hr:>3}  {fs:<22}  {blocking}")

    print(f"\n{'='*50}")
    print(f"  Analysed             : {len(results)}")
    print(f"  Fillable             : {summary['fillable']}")
    print(f"  Fillable w/ warnings : {summary['fillable_with_warnings']}")
    print(f"  Requires review      : {summary['requires_review']}")
    print(f"  Not fillable         : {summary['not_fillable']}")
    failed_reg = sum(1 for r in results if r.error and not r.registry_entry)
    print(f"  Failed               : {failed_reg}")

    registry_dir.mkdir(parents=True, exist_ok=True)

    # Write preview CSV and MD report
    _write_registration_reports(results, registry_dir)

    return 0


def _write_registration_reports(results: list, registry_dir: Path) -> None:
    """Write template_upload_preview.csv, template_registration_findings.csv, and .md report."""
    import csv as _csv
    from datetime import datetime, timezone as _tz

    preview_rows = []
    finding_rows = []

    for r in results:
        p = r.profile
        pu = r.purpose
        listing = p.listing_sheet if p else None
        det = listing.detection if listing else None
        col_count = len(listing.columns) if listing else 0
        required_count = sum(1 for c in (listing.columns if listing else [])
                             if getattr(c, "required_status", "") == "Required")
        controlled_count = sum(1 for c in (listing.columns if listing else [])
                               if getattr(c, "is_controlled", False))
        rs = r.row_summary or {}

        preview_rows.append({
            "Filename": r.filename,
            "Category": p.category_name if p else "",
            "Category Status": p.category_resolution_status if p else "",
            "Purpose": pu.purpose if pu else "",
            "Purpose Confidence": f"{pu.confidence:.2f}" if pu else "",
            "Listing Sheet": listing.name if listing else "",
            "Header Row": det.header_row if det else "",
            "Header Confidence": f"{det.confidence:.2f}" if det else "",
            "Column Count": col_count,
            "Required Fields": required_count,
            "Controlled Fields": controlled_count,
            "Safe Write Row": r.safe_write_start_row or "",
            "Existing Products": rs.get("existing_product_count", ""),
            "Sample Rows": rs.get("sample_count", ""),
            "Metadata Rows": rs.get("metadata_row_count", ""),
            "Warnings": len(r.warnings),
            "Blocking Issues": len(r.blocking_reasons),
            "Fill Status": r.fill_status,
            "Template ID": r.template_id,
        })

        for b in r.blocking_reasons:
            finding_rows.append({"Filename": r.filename, "Severity": "blocking", "Message": b})
        for w in r.warnings:
            finding_rows.append({"Filename": r.filename, "Severity": "warning", "Message": w})

    preview_csv = registry_dir / "template_upload_preview.csv"
    with open(preview_csv, "w", newline="", encoding="utf-8") as f:
        if preview_rows:
            w = _csv.DictWriter(f, fieldnames=list(preview_rows[0].keys()))
            w.writeheader()
            w.writerows(preview_rows)
    print(f"  Preview CSV      : {preview_csv}")

    findings_csv = registry_dir / "template_registration_findings.csv"
    with open(findings_csv, "w", newline="", encoding="utf-8") as f:
        if finding_rows:
            w = _csv.DictWriter(f, fieldnames=["Filename", "Severity", "Message"])
            w.writeheader()
            w.writerows(finding_rows)
    print(f"  Findings CSV     : {findings_csv}")

    ts = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
    md_lines = [
        "# Template Registration Report",
        f"\n_Generated: {ts}_\n",
        "## Registration Summary\n",
        "| Filename | Purpose | Fill Status | Listing Sheet | Header Row | Safe Write Row | Blocking |",
        "|----------|---------|-------------|---------------|------------|----------------|----------|",
    ]
    for row in preview_rows:
        md_lines.append(
            f"| {row['Filename']} | {row['Purpose']} | {row['Fill Status']} "
            f"| {row['Listing Sheet']} | {row['Header Row']} "
            f"| {row['Safe Write Row']} | {row['Blocking Issues']} |"
        )
    if finding_rows:
        md_lines += ["\n## Findings\n",
                     "| Filename | Severity | Message |",
                     "|----------|----------|---------|"]
        for row in finding_rows:
            md_lines.append(f"| {row['Filename']} | {row['Severity']} | {row['Message']} |")

    md_path = registry_dir / "template_registration_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  MD report        : {md_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Wayfair Template Analyser & Auto-Fill")
    sub = parser.add_subparsers(dest="command")

    # analyse-templates
    p1 = sub.add_parser("analyse-templates")
    p1.add_argument("--input-dir", required=True, type=Path)
    p1.add_argument("--output-dir", required=True, type=Path)

    # analyse-template
    p2 = sub.add_parser("analyse-template")
    p2.add_argument("--template", required=True, type=Path)
    p2.add_argument("--output-dir", required=True, type=Path)

    _wp_choices = ["append", "fill-first-blank", "replace-samples",
                   "replace-all-products", "preview-only"]

    # fill-template
    p3 = sub.add_parser("fill-template")
    p3.add_argument("--template", required=True, type=Path)
    p3.add_argument("--source", required=True, type=Path)
    p3.add_argument("--profile", required=True, type=Path)
    p3.add_argument("--output-dir", required=True, type=Path)
    p3.add_argument("--config-dir", default=Path("config"), type=Path)
    p3.add_argument("--write-policy", default="append", choices=_wp_choices,
                    help="Row write strategy (default: append)")

    # fill-templates (batch)
    p4 = sub.add_parser("fill-templates")
    p4.add_argument("--template-dir", required=True, type=Path)
    p4.add_argument("--source", required=True, type=Path)
    p4.add_argument("--profile-dir", required=True, type=Path)
    p4.add_argument("--output-dir", required=True, type=Path)
    p4.add_argument("--config-dir", default=Path("config"), type=Path)
    p4.add_argument("--write-policy", default="append", choices=_wp_choices,
                    help="Row write strategy (default: append)")
    p4.add_argument("--registry", default=None, type=Path,
                    help="Optional registry JSON path for fill-status filtering")
    p4.add_argument("--include-template-id", nargs="*", dest="include_ids",
                    help="Only fill these template IDs")
    p4.add_argument("--exclude-template-id", nargs="*", dest="exclude_ids",
                    help="Skip these template IDs")
    p4.add_argument("--allow-review-required", action="store_true", default=False,
                    help="Also fill templates with fill_status=requires_review")

    # register-template (single)
    p5 = sub.add_parser("register-template")
    p5.add_argument("--template", required=True, type=Path)
    p5.add_argument("--profile-dir", default=Path("outputs/template_profiles"), type=Path)
    p5.add_argument("--registry-dir", default=Path("outputs/template_registry"), type=Path)

    # register-templates (batch)
    p6 = sub.add_parser("register-templates")
    p6.add_argument("--input-dir", required=True, type=Path)
    p6.add_argument("--profile-dir", default=Path("outputs/template_profiles"), type=Path)
    p6.add_argument("--registry-dir", default=Path("outputs/template_registry"), type=Path)

    args = parser.parse_args(argv)

    if args.command == "analyse-templates":
        return run_analyse_templates(args.input_dir, args.output_dir)
    elif args.command == "analyse-template":
        return run_analyse_template(args.template, args.output_dir)
    elif args.command == "fill-template":
        return run_fill_template(
            args.template, args.source, args.profile,
            args.output_dir, args.config_dir, args.write_policy,
        )
    elif args.command == "fill-templates":
        return run_fill_templates(
            args.template_dir, args.source, args.profile_dir,
            args.output_dir, args.config_dir, args.write_policy,
            registry_path=args.registry,
            include_ids=args.include_ids,
            exclude_ids=args.exclude_ids,
            allow_review_required=args.allow_review_required,
        )
    elif args.command == "register-template":
        return run_register_template(args.template, args.profile_dir, args.registry_dir)
    elif args.command == "register-templates":
        return run_register_templates(args.input_dir, args.profile_dir, args.registry_dir)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
