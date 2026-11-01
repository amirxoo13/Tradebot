from ..config import Config
from ..state import State
from .base import Intent, Strategy


def load(name: str, cfg: Config, state: State) -> Strategy:
    if name == "momentum":
        from .momentum import build
        return build(cfg, state)
    if name == "none":
        return Strategy(cfg, state)
    raise ValueError(f"Unknown strategy: {name!r}. Available: momentum, none")
