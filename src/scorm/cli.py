"""
CLI tool for NeuroClips SCORM Course Package building and validation.
Usage:
  python -m src.scorm.cli validate path/to/course.json
  python -m src.scorm.cli build path/to/course.json --output exports/my_course.zip --version 1.2
"""
import sys
import json
import argparse
from pathlib import Path

try:
    from src.scorm.validator import validate_course_document
    from src.scorm.packager import SCORMPackageBuilder
except ImportError:
    from scorm.validator import validate_course_document
    from scorm.packager import SCORMPackageBuilder


def main():
    parser = argparse.ArgumentParser(description="NeuroClips SCORM 1.2 & 2004 Package Builder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Validate command
    val_parser = subparsers.add_parser("validate", help="Validate a course.json document")
    val_parser.add_argument("course_json", type=Path, help="Path to course.json")
    val_parser.add_argument("--assets", type=Path, default=None, help="Path to assets folder")

    # Build command
    build_parser = subparsers.add_parser("build", help="Build a SCORM zip package")
    build_parser.add_argument("course_json", type=Path, help="Path to course.json")
    build_parser.add_argument("--output", "-o", type=Path, required=True, help="Destination .zip path")
    build_parser.add_argument("--version", "-v", choices=["1.2", "2004"], default="1.2", help="SCORM version")
    build_parser.add_argument("--assets", type=Path, default=None, help="Optional asset source directory")

    args = parser.parse_args()

    if not args.course_json.exists():
        print(f"[Error] Course file '{args.course_json}' does not exist.", file=sys.stderr)
        sys.exit(1)

    with open(args.course_json, "r", encoding="utf-8") as f:
        try:
            course_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[Error] Invalid JSON in '{args.course_json}': {e}", file=sys.stderr)
            sys.exit(1)

    report = validate_course_document(course_data, args.assets)

    if args.command == "validate":
        print(json.dumps(report, indent=2))
        sys.exit(0 if report["valid"] else 1)

    elif args.command == "build":
        if not report["valid"]:
            print(f"[Error] Course validation failed:\n" + "\n".join(f" - {err}" for err in report["errors"]), file=sys.stderr)
            sys.exit(1)

        asset_map = {}
        if args.assets and args.assets.exists():
            # rglob + as_posix keep this working on Python < 3.12 (no Path.walk, no
            # backslash inside f-string expressions).
            for full_p in sorted(p for p in args.assets.rglob("*") if p.is_file()):
                rel_p = full_p.relative_to(args.assets)
                asset_map[f"assets/{rel_p.as_posix()}"] = full_p

        builder = SCORMPackageBuilder(
            course_data=course_data,
            scorm_version=args.version,
            asset_files_map=asset_map
        )
        out_zip = builder.build_zip(args.output)
        print(f"[Success] SCORM {args.version} package built successfully at: {out_zip}")
        print(f"Package Size: {round(out_zip.stat().st_size / 1024, 1)} KB")


if __name__ == "__main__":
    main()
