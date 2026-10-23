"""Run an approach over many postings through the Message Batches API (half price),
saving every response under data/runs/ so a crash or a re-score never pays twice.

Postings go through the same functions as a direct call (extract.pipeline_verdict,
direct.direct_verdict). A Replay stands in for client.messages.create: it hands back
saved responses in order, and when it runs out it records the request needed next.
Those requests become the next round's batch; round 2 holds the pipeline's retries.
"""

import json
import os
from pathlib import Path

from anthropic.types import Message

RUNS_DIR = Path("data/runs")
MAX_ROUNDS = 3  # the pipeline needs at most 2; more means something is looping


class Pending(Exception):
    """A posting needs a response that hasn't been fetched yet."""

    def __init__(self, params):
        super().__init__("response not fetched yet")
        self.params = params


class Replay:
    """A `call` that returns saved responses in order, then raises Pending with the next request."""

    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, **params):
        if not self.responses:
            raise Pending(params)
        return self.responses.pop(0)


class Failed:
    """An errored, expired, or canceled batch request. Parsing it fails like a bad
    response does, so the pipeline retries it and the direct prompt flags it."""

    content = ()

    def __init__(self, kind):
        self.stop_reason = f"batch request {kind}"


def step(postings, solve, saved):
    """Replay every posting. Returns (results for finished postings, {id: params still needed}).
    `solve(text, call)` answers one posting; `saved` maps id -> responses so far."""
    done, needed = {}, {}
    for pid, text in postings.items():
        try:
            done[pid] = solve(text, Replay(saved.get(pid, [])))
        except Pending as p:
            needed[pid] = p.params
    return done, needed


def load_saved(run_dir):
    """({id: [responses in round order]}, number of rounds collected)."""
    saved, rounds = {}, 0
    while (path := Path(run_dir) / f"round{rounds + 1}.jsonl").exists():
        rounds += 1
        for line in path.read_text().splitlines():
            row = json.loads(line)
            response = Message.model_validate(row["message"]) if row["type"] == "succeeded" else Failed(row["type"])
            saved.setdefault(row["custom_id"], []).append(response)
    return saved, rounds


def write_atomic(path, text):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def advance(client, run_dir, postings, solve, log=print):
    """Move a run as far as it can go without waiting. Returns {id: result} once every
    posting is finished, else None: run it again later and it picks up where it stopped."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    while True:
        saved, rounds = load_saved(run_dir)
        done, needed = step(postings, solve, saved)
        if not needed:
            return done
        k = rounds + 1
        if k > MAX_ROUNDS:
            raise RuntimeError(f"{run_dir}: still needs requests after {MAX_ROUNDS} rounds")
        submitted = run_dir / f"round{k}.batch.json"
        if not submitted.exists():
            batch = client.messages.batches.create(
                requests=[{"custom_id": pid, "params": params} for pid, params in needed.items()]
            )
            write_atomic(submitted, json.dumps({"batch_id": batch.id, "custom_ids": sorted(needed)}))
            log(f"{run_dir.name}: submitted round {k}, {len(needed)} requests (batch {batch.id})")
            return None
        info = json.loads(submitted.read_text())
        if set(info["custom_ids"]) != set(needed):
            raise RuntimeError(f"{run_dir}: round {k} was submitted for other postings; use a new run name")
        batch = client.messages.batches.retrieve(info["batch_id"])
        if batch.processing_status != "ended":
            log(f"{run_dir.name}: round {k} still {batch.processing_status}")
            return None
        rows = []
        for r in client.messages.batches.results(info["batch_id"]):
            message = r.result.message.model_dump(mode="json") if r.result.type == "succeeded" else None
            rows.append(json.dumps({"custom_id": r.custom_id, "type": r.result.type, "message": message}))
        write_atomic(run_dir / f"round{k}.jsonl", "\n".join(rows) + "\n")
        log(f"{run_dir.name}: collected round {k}, {len(rows)} results")


def token_totals(run_dir):
    """Summed usage over every saved response, for checking what a run cost."""
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    saved, _ = load_saved(run_dir)
    for responses in saved.values():
        for m in responses:
            if isinstance(m, Message):
                for key in totals:
                    totals[key] += getattr(m.usage, key) or 0
    return totals
