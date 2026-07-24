from pathlib import Path

content = Path("src/greeter.py").read_text(encoding="utf-8")
expected = 'return f"Hello from the developer pipeline, {name}!"'
if expected not in content:
    raise SystemExit("updated greeting was not found")
print("greeting check passed")
