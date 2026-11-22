"""Test integracji bez API: atrapa LLM zwraca wzorcowy JSON -> pipeline powinien dac F1 ~1."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core.llm as llm
from eval import evaluate as ev

GOLD = {}
def fake_chat(self, messages, schema=None, model=None, max_tokens=None, tag="extract"):
    text = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else ""
    for pdf_text, gold in GOLD.items():
        if pdf_text in text:
            return {"content": json.dumps(gold, ensure_ascii=False), "tokens_in": 1, "tokens_out": 1, "finish": "stop"}
    return {"content": "{}", "tokens_in": 1, "tokens_out": 1, "finish": "stop"}
llm.LLM.chat = fake_chat
llm.LLM.available = property(lambda self: True)

from core import pdf
from core.pipeline import Extractor
data = Path(sys.argv[1])
items = [i for i in ev.build_index(data, "all") if "skany" not in str(i[0])]
for p, gold, t in items:
    if t:
        GOLD[pdf.load(str(p)).text[:300]] = gold
ex = Extractor()
from collections import Counter, defaultdict
st = {"tp": Counter(), "fp": Counter(), "fn": Counter(), "examples": defaultdict(list)}
for p, gold, t in items:
    r = ex.process(p)["result"]
    if gold and r:
        ev.compare(gold, r, "", st)
for k in sorted(set(st["fp"]) | set(st["fn"])):
    print(k, st["fp"][k], st["fn"][k], st["examples"][k][:2])
print("F1:", ev.f1(sum(st["tp"].values()), sum(st["fp"].values()), sum(st["fn"].values())))
