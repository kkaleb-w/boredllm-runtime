# boredllm-runtime

The runtime for [BoredLLM](https://github.com/kkaleb-w/BoredLLM). That repository is the design
dossier and holds no code. This one holds the implementation.

The creature is a small language model placed in a dull, enclosed world with **no instructions
anywhere in its input**. It receives a state, never an order, and continues it. Drives replace
prompts. The world owns every fact. Phase 1 asks whether the output stays a trajectory rather
than collapsing into a loop or a template.

## Files

| File | Job |
|---|---|
| `creature.py` | the tick loop, the metrics, and the runner for N creatures in one process |
| `world.py` | the room, the clock, real weather, and the oracle audit |
| `mind.py` | drives, memory, sleep, and prompt composition |
| `api.py` | DeepInfra client. The model identifier is pinned and written into every record |

## Run it

```bash
export DEEPINFRA_API_KEY=...          # or leave it in ~/.hermes/.env
python3 creature.py --ticks 20 --creatures 2 --rate fast
python3 creature.py --ticks 2880 --creatures 3 --rate wall --interval 600   # a real 20 day run
```

Artifacts land in `~/creature/runs/<tag>-<stamp>/`: `ticks.jsonl` (the record, one line per
tick, plus sleep events) and `transcript.txt` (readable, every fifth tick).

## The constraints that are not optional

Each one below was measured. Every one of them was a run that failed without it.

1. **No imperative in the input.** Nothing tells the creature what it is or what to do. It gets
   an observation and its own last thought, and continues.
2. **The input contains only what the creature observes**, rendered in its own flat first
   person. Third-person or lyrical description of the room flips the model from inhabiting the
   stream into analysing it as literature. Measured: inhabiting went from 33 percent to 88
   percent on this change alone.
3. **Thoughts only in the self-view, never prior observations.** Replaying the world's own
   observation lines into the stream is a self-similarity attractor. Repetition goes from about
   0.01 to about 0.32 when prior observations are included.
4. **No labelled history.** A `just now: ...` label is structural, so the model continues the
   *label* and starts answering it, which seeds a multiple-choice template.
5. **A moving clock.** In fast mode the virtual clock must advance, or every observation is
   identical and the run measures the freeze rather than the creature.
6. **One small world detail changes per tick.** Not interesting, just not identical. A fully
   static world gives the stream nothing to move along.
7. **Level 0/1 self-view only, hard capped.** Never the full log: that is self-omniscience, and
   it is a documented accelerant for repetition loops.

## What Phase 1 found

20 ticks, 2 creatures, `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`, one process, cost $0.0002.

| Creature | mean rep | max rep | dupes | empty | inhabiting | commentary | invented a fact |
|---|---|---|---|---|---|---|---|
| c0 | 0.152 | 1.0 | 1 | 1 | 55% | 30% | **70%** |
| c1 | 0.056 | 0.196 | 0 | 0 | 55% | 15% | **75%** |

**Repetition is under control; invention is not.** About seven ticks in ten assert something the
world does not contain. Given a room with a table, a cup, a locked door and a window, the
creatures produced walls, a lamp, a chair, a plate, water, a house with other rooms, a
photograph, a drawing of a tree, a phone receiver and a person named only as `J----`.

The conclusion, and it is the important one: **an oracle with no consequences is decorative.**
The world can own the facts, but if nothing ever fails, a fact the creature invents is
indistinguishable from a fact it observed, and it builds a life in a room that does not exist.
Being told the truth is not the same as being unable to be wrong.

The fix belongs to Phase 2, and it is that the world must be able to **contradict**: an action
against an invented object has to fail, and the next observation has to implicitly correct the
previous invention. Observation alone cannot hold the creature inside the world.

## Live view

**https://bored.kkaleb.com** — one number, one line, one column. No chrome.

```bash
python3 view_server.py --port 4180            # serves view/ and /snapshot.json
```

`snapshot.py` compresses a run directory into a small JSON the page polls. The page is
read-only in both directions: it writes nothing to the run and can send nothing back, so the
observer cannot perturb the creature (BoredLLM doc 18). Exposed through the existing Cloudflare
tunnel on `kkaleb.com` as `bored.kkaleb.com -> 127.0.0.1:4180`, which opens no inbound port
because the tunnel dials out. Runs as `bored-view.service` under `systemd --user`.

## Model

`meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`. Chosen by measurement, not preference: 0.5B
collapses (loops, or templates), and Qwen3.5-9B produced 8 duplicates and 9 empty responses out
of 30 while costing 3.4 times more. Cost at study scale is about $0.01 per creature for a 20 day
run.

## Not here yet

- Actions, and the refusal mechanism that makes the oracle bind
- The synthetic web, and the corpus
- The monitoring export
- Base-versus-instruct at 8B
