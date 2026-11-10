"""Read the production mutex default without constructing a native Windows handle."""
import ast
from pathlib import Path

source = ast.parse((Path(__file__).resolve().parents[1] / 'instance.py').read_text(encoding='utf-8'))
instance = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'WindowsInstance')
constructor = next(node for node in instance.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
NAME = ast.literal_eval(next(value for arg, value in zip(constructor.args.kwonlyargs, constructor.args.kw_defaults) if arg.arg == 'name'))
