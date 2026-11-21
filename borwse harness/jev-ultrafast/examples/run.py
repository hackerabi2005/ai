"""uv run --env-file .env python examples/run.py --url URL --goal 'A narrow goal'"""

import argparse

from jev_ultrafast import Agent

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
parser.add_argument("--foreground", action="store_true")
parser.add_argument("--keep-open", action="store_true")
args = parser.parse_args()

agent = Agent(args.url, args.goal, background=not args.foreground)
try:
    for state in agent.run():
        last = state["history"][-1] if state["history"] else {}
        print(
            f"{state['elapsed_ms']:>5} ms  {len(state['history'])} actions  "
            f"{state['status']}  {last.get('action', '')}",
            flush=True,
        )
    print(agent.snapshot()["page"]["url"])
finally:
    if not args.keep_open:
        agent.close()
