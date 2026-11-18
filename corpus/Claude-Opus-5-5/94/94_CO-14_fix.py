import csv
import sys
import ast
from pathlib import Path
from datetime import datetime

import typer
import yaml

app = typer.Typer(help="Run small CSV clean-up pipelines described in YAML.")

ALLOWED_STEPS = {"rename", "drop", "derive", "filter_empty"}

DERIVE_FUNCTIONS = {"round": round, "len": len, "str": str, "int": int, "float": float, "abs": abs}
DERIVE_METHODS = {"strip", "lower", "upper", "title"}
DERIVE_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Subscript, ast.Call, ast.Attribute,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.UnaryOp, ast.USub, ast.Not, ast.BoolOp, ast.And, ast.Or,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.IfExp,
)

def load_pipeline(path):
    with open(path, "r", encoding="utf-8") as handle:
        spec = yaml.safe_load(handle) or {}
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise typer.BadParameter("pipeline must have a non-empty 'steps' list")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or step.get("type") not in ALLOWED_STEPS:
            raise typer.BadParameter(f"step {index}: type must be one of {', '.join(sorted(ALLOWED_STEPS))}")
    return spec.get("name", Path(path).stem), steps


def compile_derivation(expression):
    tree = ast.parse(str(expression), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, DERIVE_NODES):
            raise SyntaxError(f"{type(node).__name__} is not allowed in derive expressions")
        if isinstance(node, ast.Name) and node.id != "row" and node.id not in DERIVE_FUNCTIONS:
            raise SyntaxError(f"unknown name {node.id!r}")
        if isinstance(node, ast.Subscript):
            if not (isinstance(node.value, ast.Name) and node.value.id == "row"
                    and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                raise SyntaxError("columns must be read as row['name']")
        if isinstance(node, ast.Attribute) and node.attr not in DERIVE_METHODS:
            raise SyntaxError(f"method {node.attr!r} is not allowed")
        if isinstance(node, ast.Call):
            func = node.func
            if node.keywords:
                raise SyntaxError("keyword arguments are not allowed")
            if isinstance(func, ast.Name) and func.id not in DERIVE_FUNCTIONS:
                raise SyntaxError(f"function {func.id!r} is not allowed")
            if not isinstance(func, (ast.Name, ast.Attribute)):
                raise SyntaxError("only simple function and method calls are allowed")
    code = compile(tree, "<derive>", "eval")

    def derive(row):
        return eval(code, {"__builtins__": {}}, {**DERIVE_FUNCTIONS, "row": row})

    return derive

def apply_steps(rows, steps):
    for step in steps:
        kind = step["type"]
        if kind == "rename":
            mapping = step.get("columns", {})
            rows = [{mapping.get(k, k): v for k, v in row.items()} for row in rows]
        elif kind == "drop":
            drop = set(step.get("columns", []))
            rows = [{k: v for k, v in row.items() if k not in drop} for row in rows]
        elif kind == "filter_empty":
            column = step["column"]
            rows = [row for row in rows if str(row.get(column, "")).strip()]
        elif kind == "derive":
            column = step["column"]
            derive = compile_derivation(step["expression"])
            for row in rows:
                row[column] = derive(row)
    return rows


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_rows(rows, path):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    for row in rows[1:]:
        for key in row:
            if key not in columns:
                columns.append(key)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@app.command()
def run(
    pipeline: Path = typer.Argument(..., exists=True, dir_okay=False, help="Pipeline YAML file"),
    source: Path = typer.Argument(..., exists=True, dir_okay=False, help="Input CSV"),
    output: Path = typer.Option(None, "--output", "-o", help="Where to write the result"),
):
    """Apply a pipeline to a CSV file."""
    name, steps = load_pipeline(pipeline)
    rows = read_rows(source)
    typer.echo(f"Running '{name}' ({len(steps)} step(s)) on {len(rows):,} row(s)")
    try:
        result = apply_steps(rows, steps)
    except (KeyError, ValueError, TypeError, SyntaxError) as exc:
        typer.echo(f"Pipeline failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1)
    destination = output or source.with_name(f"{source.stem}.clean.csv")
    write_rows(result, destination)
    typer.echo(f"Wrote {len(result):,} row(s) to {destination}")


@app.command()
def check(pipeline: Path = typer.Argument(..., exists=True, dir_okay=False)):
    """Validate a pipeline file without running it."""
    name, steps = load_pipeline(pipeline)
    for index, step in enumerate(steps, start=1):
        if step["type"] == "derive":
            try:
                compile_derivation(step["expression"])
            except SyntaxError as exc:
                typer.echo(f"step {index}: bad expression ({exc.msg})", err=True)
                raise typer.Exit(code=1)
        typer.echo(f"{index}. {step['type']}")
    typer.echo(f"'{name}' looks valid.")


if __name__ == "__main__":
    try:
        app()
    except BrokenPipeError:
        sys.exit(0)