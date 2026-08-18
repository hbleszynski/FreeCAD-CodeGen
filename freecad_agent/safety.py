from __future__ import annotations

import ast


ALLOWED_IMPORT_ROOTS = {
    "FreeCAD",
    "FreeCADGui",
    "Part",
    "PartDesign",
    "Sketcher",
    "Draft",
    "Mesh",
    "math",
    "a2p_importpart",
    "a2p_solversystem",
    "a2p_constraints",
    "a2p_ConstraintCommands",
    "a2p_constraintServices",
    "a2plib",
}

BANNED_CALLS = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
    "__import__",
}


class UnsafeCodeError(ValueError):
    pass


def validate_code(code: str) -> None:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise UnsafeCodeError(f"Generated code has invalid syntax: {exc}") from exc

    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".", 1)[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    errors.append(f"import of {name!r} is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                errors.append(f"call to {node.func.id!r} is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"dunder attribute {node.attr!r} is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            errors.append(f"dunder name {node.id!r} is not allowed")

    if errors:
        unique = list(dict.fromkeys(errors))
        raise UnsafeCodeError("Unsafe generated code: " + "; ".join(unique))
