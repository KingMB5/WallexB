from pathlib import Path

def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")

replace_once(
    "pilot/llm.py",
    '''    def _fail(self, why):
        # Fail closed unless the configuration explicitly says otherwise.
        return {
            "approve": self.c.get("on_error", "reject") == "allow",
            "reason": why,
            "error": True,
        }''',
    '''    def _fail(self, why):
        # Safety-critical: errors can never authorize a trade.
        return {
            "approve": False,
            "reason": why,
            "error": True,
        }'''
)

replace_once(
    "pilot/llm.py",
    '''        if not self.c.get("enabled"):
            return {"approve": True, "skipped": True}''',
    '''        if not self.c.get("enabled"):
            return {
                "approve": False,
                "skipped": True,
                "reason": "LLM approval is mandatory but LLM is disabled",
            }'''
)

replace_once(
    "pilot/engine.py",
    '''        if not verdict.get("approve"):
            return self.j.event("skip", f"{sym}: LLM veto", verdict=verdict)''',
    '''        # Fail closed: only an explicit, valid UP-trend approval is accepted.
        valid_approval = (
            isinstance(verdict, dict)
            and verdict.get("approve") is True
            and verdict.get("skipped") is not True
            and verdict.get("error") is not True
            and verdict.get("trend") == "up"
            and isinstance(verdict.get("reason"), str)
            and bool(verdict["reason"].strip())
        )
        if not valid_approval:
            return self.j.event(
                "skip", f"{sym}: missing or invalid LLM approval", verdict=verdict
            )'''
)

replace_once(
    "tests/smoke_test.py",
    '''e = Engine(cfg, wx=fake)
prices = fake.prices()''',
    '''e = Engine(cfg, wx=fake)
# Offline test only: simulate a valid LLM approval; never call a real API.
e.llm.verify = lambda *args, **kwargs: {
    "approve": True, "trend": "up", "reason": "offline test approval"
}
prices = fake.prices()'''
)

replace_once(
    "tests/smoke_test.py",
    '''e2 = Engine({**cfg, "db_path": cfg["db_path"].replace("t.db", "t2.db")}, wx=fake)
fake.price = None''',
    '''e2 = Engine({**cfg, "db_path": cfg["db_path"].replace("t.db", "t2.db")}, wx=fake)
# Offline test only: simulate the same valid approval for the second scenario.
e2.llm.verify = lambda *args, **kwargs: {
    "approve": True, "trend": "up", "reason": "offline test approval"
}
fake.price = None'''
)

print("Fail-closed patch applied.")
