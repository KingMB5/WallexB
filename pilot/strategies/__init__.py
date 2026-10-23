import importlib
import pkgutil

from .base import Strategy


def load_strategies(cfgs):
    for m in pkgutil.iter_modules(__path__):
        if m.name != "base":
            importlib.import_module(f"{__name__}.{m.name}")
    registry = {cls.name: cls for cls in Strategy.__subclasses__()}
    out = []
    for c in cfgs:
        if not c.get("enabled", True):
            continue
        if c["name"] not in registry:
            raise SystemExit(f"strategy '{c['name']}' not found. available: {sorted(registry)}")
        out.append(registry[c["name"]](c.get("params", {})))
    return out
