#!/usr/bin/env python3
"""Human or Bot? — a Turing-test game that lives in a GitHub profile README.

Players vote via issue title:  vote|<round_id>|<guess>
The Action updates this file's derived state and rewrites the README section
between the game markers. No server, no database — everything lives in git.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROUNDS_FILE = ROOT / "rounds.json"
STATE_FILE = ROOT / "state.json"
README = ROOT.parent / "README.md"

BEGIN = "<!--BEGIN TURING-->"
END = "<!--END TURING-->"

VOTES_TO_ADVANCE = 8  # votes before a round closes and the answer is revealed


def load(path: Path, default):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def init_state(rounds: list[dict]) -> dict:
    return {
        "round_index": 0,
        "votes": {},          # round_id -> {"ai": [users], "human": [users]}
        "resolved": {},       # round_id -> {"answer": bool, "ai_correct": int, "total": int}
        "scores": {},         # user -> {"correct": int, "total": int}
        "total_votes": 0,
    }


def round_id(r: dict) -> str:
    return str(r["id"])


def tally(state: dict, rid: str) -> dict:
    v = state["votes"].get(rid, {"ai": [], "human": []})
    return {"ai": len(v.get("ai", [])), "human": len(v.get("human", []))}


def record_vote(state: dict, rid: str, guess: str, user: str) -> bool:
    """Register a vote. Returns True if accepted, False if duplicate/closed."""
    if rid in state["resolved"]:
        return False
    bucket = state["votes"].setdefault(rid, {"ai": [], "human": []})
    guess = "ai" if guess == "ai" else "human"
    if user in bucket["ai"] or user in bucket["human"]:
        return False
    bucket[guess].append(user)
    state["total_votes"] += 1
    return True


def resolve_if_ready(state: dict, rounds: list[dict]) -> dict | None:
    """If the current round has enough votes, resolve it and score players."""
    r = rounds[state["round_index"]]
    rid = round_id(r)
    t = tally(state, rid)
    total = t["ai"] + t["human"]
    if total < VOTES_TO_ADVANCE:
        return None

    answer_is_ai = bool(r["is_ai"])
    bucket = state["votes"][rid]
    correct_users = bucket["ai"] if answer_is_ai else bucket["human"]

    for user in bucket["ai"] + bucket["human"]:
        s = state["scores"].setdefault(user, {"correct": 0, "total": 0})
        s["total"] += 1
        if user in correct_users:
            s["correct"] += 1

    state["resolved"][rid] = {
        "answer_is_ai": answer_is_ai,
        "correct": len(correct_users),
        "total": total,
        "closed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    state["round_index"] += 1
    return state["resolved"][rid]


def accuracy(s: dict) -> str:
    if not s["total"]:
        return "—"
    return f"{100 * s['correct'] // s['total']}%"


def render(state: dict, rounds: list[dict]) -> str:
    resolved = state["resolved"]
    idx = state["round_index"]
    lines: list[str] = []

    head_done = len(resolved)
    lines.append(f"**Rondas resueltas:** {head_done}/{len(rounds)} &nbsp;·&nbsp; "
                 f"**Votos totales:** {state['total_votes']} &nbsp;·&nbsp; "
                 f"**Humanos detectados:** ve el marcador abajo")

    if idx < len(rounds):
        r = rounds[idx]
        rid = round_id(r)
        t = tally(state, rid)
        got = t["ai"] + t["human"]
        lines.append("")
        lines.append(f"### 🔎 Ronda #{rid} — ¿quién escribió esto?")
        lines.append("")
        lines.append(f"> {r['text']}")
        lines.append("")
        lines.append(f"*Votos: {got}/{VOTES_TO_ADVANCE} — "
                     f"🤖 IA: {t['ai']} · 🧑 Humano: {t['human']}*")
        lines.append("")
        lines.append(f"[🤖 Vota: es IA](https://github.com/AnnGeliux/AnnGeliux/issues/new?title=vote%7C{rid}%7Cai&body=Solo+dale+Create.)"
                     f" &nbsp;·&nbsp; "
                     f"[🧑 Vota: es humano](https://github.com/AnnGeliux/AnnGeliux/issues/new?title=vote%7C{rid}%7Chuman&body=Solo+dale+Create.)")
    else:
        lines.append("")
        lines.append("### 🏁 Todas las rondas resueltas — ¡gracias por jugar!")
        lines.append("")

    # Leaderboard
    scores = state["scores"]
    if scores:
        lines.append("")
        lines.append("### 🏆 Marcador global")
        lines.append("")
        lines.append("| Jugador | Aciertos | Votos | Precisión |")
        lines.append("| :--- | :---: | :---: | :---: |")
        ranking = sorted(scores.items(), key=lambda kv: (-kv[1]["correct"], kv[1]["total"]))
        medals = ["🥇", "🥈", "🥉"]
        for i, (user, s) in enumerate(ranking[:10]):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"| {medal} [@{user}](https://github.com/{user}) | {s['correct']} | "
                         f"{s['total']} | {accuracy(s)} |")
        lines.append("")
        lines.append(f"<sub>Se necesitan {VOTES_TO_ADVANCE} votos por ronda para revelar la respuesta. "
                     "Los textos de IA fueron generados con modelos locales (Ollama).</sub>")

    # History
    if resolved:
        lines.append("")
        lines.append("<details><summary>📜 Historial de rondas</summary>")
        lines.append("")
        lines.append("| Ronda | Respuesta | Votaron bien | Detalle |")
        lines.append("| :---: | :---: | :---: | :--- |")
        for r in rounds:
            rid = round_id(r)
            if rid not in resolved:
                continue
            res = resolved[rid]
            ans = "🤖 IA" if res["answer_is_ai"] else "🧑 Humano"
            lines.append(f"| #{rid} | {ans} | {res['correct']}/{res['total']} | {r.get('topic','')} |")
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def inject(readme: str, block: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    replacement = f"{BEGIN}\n{block}\n{END}"
    if pattern.search(readme):
        return pattern.sub(lambda _: replacement, readme)
    return readme


def main() -> int:
    rounds = load(ROUNDS_FILE, {"rounds": []})["rounds"]
    state = load(STATE_FILE, None) or init_state(rounds)

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    action = os.environ.get("TURING_ACTION", "")

    if action == "vote" and event_path and Path(event_path).exists():
        with open(event_path, encoding="utf-8") as f:
            event = json.load(f)
        issue = event.get("issue", {})
        title = (issue.get("title") or "").strip()
        user = issue.get("user", {}).get("login", "")

        m = re.match(r"vote\|(\d+)\|(ai|human)$", title, re.IGNORECASE)
        if not m:
            print(f"Ignoring issue: not a vote format: {title!r}")
            return 0
        rid, guess = m.group(1), m.group(2).lower()

        if rid not in {round_id(r) for r in rounds}:
            print(f"Ignoring: unknown round {rid}")
            print("COMMENT=⚠️ Esa ronda no existe.")
            return 0

        if not record_vote(state, rid, guess, user):
            print(f"Duplicate or closed vote by {user} on round {rid}")
            print("COMMENT=⚠️ Ya votaste en esta ronda (o la ronda ya cerró).")
            return 0

        save(STATE_FILE, state)
        print(f"Recorded vote: @{user} -> {guess} on round {rid}")

        resolved = resolve_if_ready(state, rounds)
        if resolved:
            save(STATE_FILE, state)
            print(f"Round {rid} resolved: is_ai={resolved['answer_is_ai']}, "
                  f"correct={resolved['correct']}/{resolved['total']}")

        # refresh README
        if README.exists():
            readme = README.read_text(encoding="utf-8")
            README.write_text(inject(readme, render(state, rounds)), encoding="utf-8")
        print("COMMENT=✅ ¡Voto registrado! Gracias por jugar 🎮")
        return 0

    # default: just refresh the README block
    save(STATE_FILE, state)
    if README.exists():
        readme = README.read_text(encoding="utf-8")
        README.write_text(inject(readme, render(state, rounds)), encoding="utf-8")
    print("Refreshed game block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
