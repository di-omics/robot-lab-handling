"""Command line: python -m handoff_study <sheet|score> ...   (run from the project folder)

  sheet   write the planned trials.csv and header-only verdicts.csv and setup_time.csv; refuses to overwrite a
          sheet that holds results. --check writes nothing and compares the design columns with design.py.
  score   check the 3 sheets, then print the report as Markdown (--json: as data). --write also saves results.md
          and results.json. Exit 1, with every problem listed by row, when a sheet is invalid.

DIR defaults to this package's folder. No clock, no random, no network.
"""

import argparse
import sys
from pathlib import Path

from . import design, score

HERE = Path(__file__).resolve().parent


def planned_files():
    """Return {file name: text} for the 3 sheets as `sheet` writes them."""
    return {"trials.csv": design.csv_text(design.TRIAL_COLUMNS, design.trials()),
            "verdicts.csv": design.csv_text(design.VERDICT_COLUMNS, []),
            "setup_time.csv": design.csv_text(design.SETUP_COLUMNS, [])}


def check_sheet(folder):
    """Compare the design columns of folder/trials.csv with design.py, writing nothing. @return the exit code."""
    header, rows, problems = score.read_csv(Path(folder) / "trials.csv")
    if header is not None:
        problems += score.design_problems(header, rows) if header else ["trials.csv: the file is empty"]
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} difference(s) from design.py")
        return 1
    print(f"trials.csv matches design.py: {len(rows)} trials, design {design.design_id()}")
    return 0


def write_sheet(folder):
    """Write the planned sheets into folder, unless a sheet there holds results. @return the exit code."""
    folder = Path(folder)
    for key, name in score.FILES.items():
        if not (folder / name).exists():
            continue
        header, rows, problems = score.read_csv(folder / name)
        number = score.holds_results(key, rows)
        if header is None or problems or number is not None:
            where = f"row {number}" if number is not None else "it cannot be read cleanly"
            print(f"{name} holds results ({where}): nothing written")
            return 1
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in planned_files().items():
        (folder / name).write_text(text, encoding="ascii", newline="")
    print(f"wrote trials.csv ({len(design.trials())} trials, all planned, design {design.design_id()}), "
        "verdicts.csv and setup_time.csv (header only)")
    return 0


def run_score(folder, write=False, as_json=False):
    """Check the 3 sheets in folder, then print the report (or its data) and, with write, save both.
    Problems go to stderr. @return the exit code: 0 scored, 1 when a sheet is invalid."""
    folder = Path(folder)
    sheets, problems = score.load(folder)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{len(problems)} problem(s): nothing scored", file=sys.stderr)
        return 1
    data = score.score(sheets["trials"], sheets["verdicts"], sheets["setup"])
    markdown, text = score.render(data), score.as_json(data)
    if write:
        (folder / "results.md").write_text(markdown, encoding="ascii", newline="")
        (folder / "results.json").write_text(text, encoding="ascii", newline="")
        print("wrote results.md and results.json", file=sys.stderr)
    print(text if as_json else markdown, end="")
    return 0


def main(argv=None):
    """Run the command line. @return the exit code."""
    parser = argparse.ArgumentParser(prog="python -m handoff_study", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("sheet", help="write the planned sheets, or --check them against design.py")
    p.add_argument("--dir", type=Path, default=HERE, help="folder of the sheets (default: this package)")
    p.add_argument("--check", action="store_true", help="write nothing; exit 1 when the design columns differ")
    p = commands.add_parser("score", help="check the sheets and print the report")
    p.add_argument("--dir", type=Path, default=HERE, help="folder of the sheets (default: this package)")
    p.add_argument("--write", action="store_true", help="also write results.md and results.json in DIR")
    p.add_argument("--json", action="store_true", help="print the report as data instead of Markdown")
    args = parser.parse_args(argv)
    if args.command == "sheet":
        return check_sheet(args.dir) if args.check else write_sheet(args.dir)
    return run_score(args.dir, write=args.write, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
