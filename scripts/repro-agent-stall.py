#!/usr/bin/env python3
"""Reproduce the three router behaviours behind the Hermes compression stall.

Runs ON the CT, against the router on localhost and llama-server's /slots.

  disconnect   a client gives up mid-generation (Hermes does it at 300 s);
               does llama-server keep generating for nobody?   (plain + SSE)
  eviction     a side request (a summary) lands while a long conversation is
               cached; how much of the conversation is re-read afterwards?
  agent        the same, shaped like an agent turn (reply without reasoning
               plus a new question), with and without the side request

    python3 scripts/repro-agent-stall.py --model ornith-1.5-9b-q4_k_m
    python3 scripts/repro-agent-stall.py --only disconnect --give-up 8

Prints one JSON line per check.
"""
import argparse
import http.client
import json
import os
import socket
import time
import urllib.request

ROUTER = ("127.0.0.1", 8090)
LLAMA = "http://127.0.0.1:8080"
LONG_ANSWER = ("Write a very long, detailed technical essay about the history of "
               "GPUs, at least 3000 words, with many sections.")


def api_key():
    env = os.environ.get("IA_API_KEY")
    if env:
        return env
    with open("/etc/ia/api-key") as f:
        return f.read().strip()


def busy_slots(key):
    req = urllib.request.Request(f"{LLAMA}/slots", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return [s["id"] for s in json.load(r) if s.get("is_processing")]


def chat(key, model, messages, max_tokens=None, timeout=1800):
    body = {"model": model, "messages": messages, "temperature": 0}
    if max_tokens:
        body["max_tokens"] = max_tokens
    conn = http.client.HTTPConnection(*ROUTER, timeout=timeout)
    t0 = time.monotonic()
    conn.request("POST", "/v1/chat/completions", json.dumps(body),
                 {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    data = json.load(conn.getresponse())
    conn.close()
    return time.monotonic() - t0, data


def check_disconnect(key, model, stream, give_up):
    """Send a long generation, hang up after `give_up` s, time how long the
    server keeps the slot busy afterwards."""
    chat(key, model, [{"role": "user", "content": "hi"}], max_tokens=1)  # model loaded
    body = {"model": model, "temperature": 0, "max_tokens": 3000, "stream": stream,
            "messages": [{"role": "user", "content": LONG_ANSWER}]}
    sock = socket.create_connection(ROUTER)
    payload = json.dumps(body).encode()
    sock.sendall(
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Type: application/json\r\n"
        + f"Authorization: Bearer {key}\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
        + payload)
    time.sleep(give_up)
    sock.close()  # what Hermes does when its stall timer fires
    hung_up = time.monotonic()
    busy_for = None
    while time.monotonic() - hung_up < 600:
        if not busy_slots(key):
            busy_for = time.monotonic() - hung_up
            break
        time.sleep(0.5)
    return {"check": "disconnect", "stream": stream, "gave_up_after_s": give_up,
            "server_busy_after_hangup_s": round(busy_for, 1) if busy_for is not None else ">600"}


def check_eviction(key, model, chars):
    """Cache a long conversation, run a side request, measure the re-read."""
    text = ""
    for path in ("docs/BENCHMARKS.md", "docs/TROUBLESHOOTING.md", "router.py", "setup.sh"):
        with open(path, encoding="utf-8") as f:
            text += f.read()
    while len(text) < chars:
        text += text
    convo = [{"role": "system", "content": "Reference:\n" + text[:chars]},
             {"role": "user", "content": "One sentence: what is this repository?"}]
    _, first = chat(key, model, convo, max_tokens=16)
    side = [{"role": "user", "content": "Summarise this:\n" + text[: chars // 3]}]
    chat(key, model, side, max_tokens=16)
    wall, again = chat(key, model, convo, max_tokens=16)
    t = again.get("timings", {})
    return {"check": "eviction", "conversation_tokens": first.get("usage", {}).get("prompt_tokens"),
            "reread_tokens_after_side_request": t.get("prompt_n"),
            "reread_s": round(t.get("prompt_ms", 0) / 1000, 1), "wall_s": round(wall, 1)}


def check_agent_turn(key, model, chars, side):
    """Like check_eviction, but shaped like an agent turn: the model reasons,
    the next request carries its reply *without* the reasoning plus a new
    question, and (with `side`) a summary request lands in between. A hybrid
    model (ornith is qwen35) can only resume from a saved checkpoint, so this
    is the case an exact-repeat request does not exercise."""
    text = ""
    for path in ("docs/BENCHMARKS.md", "docs/TROUBLESHOOTING.md", "router.py", "setup.sh"):
        with open(path, encoding="utf-8") as f:
            text += f.read()
    while len(text) < chars:
        text += text
    convo = [{"role": "system", "content": "Reference:\n" + text[:chars]},
             {"role": "user", "content": "One sentence: what is this repository?"}]
    _, first = chat(key, model, convo, max_tokens=600)
    reply = first["choices"][0]["message"].get("content") or ""
    if side:
        summary = [{"role": "user", "content": "Summarise this:\n" + text[: chars // 3]}]
        chat(key, model, summary, max_tokens=16)
    convo += [{"role": "assistant", "content": reply},
              {"role": "user", "content": "And which file holds the router?"}]
    wall, again = chat(key, model, convo, max_tokens=16)
    t = again.get("timings", {})
    return {"check": "agent_turn", "side_request": side,
            "conversation_tokens": again.get("usage", {}).get("prompt_tokens"),
            "reread_tokens": t.get("prompt_n"),
            "reread_s": round(t.get("prompt_ms", 0) / 1000, 1), "wall_s": round(wall, 1)}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model", default="ornith-1.5-9b-q4_k_m")
    p.add_argument("--only", choices=["disconnect", "eviction", "agent"])
    p.add_argument("--give-up", type=float, default=8.0,
                   help="seconds before the client hangs up")
    p.add_argument("--chars", type=int, default=64500,
                   help="conversation size for the eviction check (~20k tokens)")
    args = p.parse_args()
    key = api_key()
    if args.only in (None, "disconnect"):
        for stream in (False, True):
            print(json.dumps(check_disconnect(key, args.model, stream, args.give_up)), flush=True)
    if args.only in (None, "eviction"):
        print(json.dumps(check_eviction(key, args.model, args.chars)), flush=True)
    if args.only in (None, "agent"):
        for side in (False, True):
            print(json.dumps(check_agent_turn(key, args.model, args.chars, side)), flush=True)


if __name__ == "__main__":
    main()
