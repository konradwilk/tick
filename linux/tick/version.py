"""Derive the displayed version from release tags, or a distribution stamp."""
import argparse
import json
from pathlib import Path
import subprocess


def source_version():
    root = Path(__file__).resolve().parents[2]
    try:
        version = subprocess.run(
            ["git", "describe", "--tags", "--match", "RELEASE_*", "--always"],
            cwd=root, check=True, capture_output=True, text=True,
        ).stdout.strip()
        if version:
            return version.removeprefix("RELEASE_")
    except (OSError, subprocess.CalledProcessError):
        pass
    stamp = Path(__file__).with_name("_version.txt")
    if stamp.is_file():
        return stamp.read_text(encoding="utf-8").strip() or "unknown"
    return "unknown"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "csharp", "swift"), default="text")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    version = source_version()
    literal = json.dumps(version, ensure_ascii=False)
    if args.format == "csharp":
        content = "// Generated file.\nnamespace Tick;\ninternal static class BuildVersion\n{\n    public const string Current = " + literal + ";\n}\n"
    elif args.format == "swift":
        content = "// Generated file.\npublic enum BuildVersion {\n    public static let current = " + literal + "\n}\n"
    else:
        content = version + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != content:
            args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
