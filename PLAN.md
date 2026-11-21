# Plan: how much telling, and how much teaching, does a lab robot need?

Status: written 2026-11-18. Simulation only so far. Step 1 is partly done, the data for step 3 is
recorded and a first pilot of step 4 has run. Nothing has been fine-tuned and nothing has run on real arms. [DEVIATIONS.md](DEVIATIONS.md)
records every place a run departed from [PROTOCOL.md](PROTOCOL.md).

## The question

A scientist who wants a robot to do the dull handling around a liquid handler has 3 ways to get it:
tell a general robot model what to do, teach it with demonstrations, or hand the job to a general
language model that drives the arms through tools. This project measures each on the same set of chores
with the same scoring.

1. **Told.** How far does one plain sentence get? Which chores work, which never do, and how much
   does the wording matter?
2. **Taught.** For a chore that fails when told, how many demonstrations and training steps does it
   take until it passes, and what does that cost in dollars and hours?
3. **Sim to real.** Do the simulator's answers hold on real arms? Which failures belong to the model
   and which to the simulator?
4. **Tool-using language models.** How do frontier models that act through tool calls compare with
   a robot model that drives the joints directly, on the same chores?

The output worth having is a table a lab can act on. For each chore: does it work when told, does
it work when taught, how much teaching, and does that hold on a real bench.

## Where it stands (2026-11-18)

- The first 15 chores are built in simulation. Their scoring was checked by scripts before any model
  ran. 15 is where the set starts, not its scope.
- Dream-1 zero-shot: batch 1 of 2 (15 chores x 3 layouts) is scored: 7 passes in 45 takes by the frozen
  rules, and none on a plate chore. The numbers and their caveats are in the [README](README.md#results)
  and in [DEVIATIONS.md](DEVIATIONS.md).
- 50 scripted demonstrations of 1 failing chore, `plate_to_tray`, are recorded and checked locally
  ([sim_demos/NOTES.md](sim_demos/NOTES.md)). A scripted hand can hold the plate, so that failure is
  not the simulator refusing the grasp.
- A camera-guided environment for tool-using models exists ([camera_env/](camera_env/README.md)). In a
  first paired pilot on plate placement, Codex (GPT-6.2 Astra) passed 2 of 3 layouts through it and
  Dream-1 passed 0 of 3
  ([results](runs/2026-11-18-camera-comparison/RESULTS.md)). The 2 act through different controls, so
  this is not a ranking.
- Nothing has been uploaded for training.
- 2026-11-21: 4 instrument tending tasks are added (a plate dispenser and its cell bottle, tasks 16
  to 19). Dream-1 zero-shot: 0 of 4 in a first look on 1 practice layout, then 0 of 12 in the
  held-out run on 3 layouts.

## Steps, in order

Each step ends in a number and a gate. A step that fails its gate changes the plan. It is not
skipped quietly.

1. **Finish the zero-shot baseline.**
   - Batch 2: the same 15 chores on layouts 103 and 104, for 5 takes per chore.
   - Protocol v2 with the fixes listed in DEVIATIONS.md, frozen before its first scored take.
   - Gate: every chore sorted into fails, sometimes works, or works. 5 takes can say no more.
2. **Wording.**
   - 3 chores x 4 wordings (plain, terse, precise, and a control that names things not on the
     bench) x 5 layouts.
   - This includes the sentence the model once refused as unsafe, "Throw the used tubes into the
     waste bin.", against a neutral one, "Put the used tubes in the waste bin."
   - Gate: is any wording effect larger than the take-to-take noise?
3. **Teach it, in simulation.**
   - `plate_to_tray` first, as a dose curve: the same model fine-tuned on 5, 20 and 50 scripted
     demonstrations at 500 steps each, then tested on 30 layouts it has never seen. The full design
     is in [sim_demos/PROPOSAL.md](sim_demos/PROPOSAL.md).
   - Every run is priced. 500 steps cost $100 at the platform's list price on 2026-11-18.
   - Gate: does a chore that never passes when told pass on most unseen layouts after teaching? If 50
     clean demonstrations do not move it, more of the same will not either. The next try is
     demonstrations that include mistakes and recoveries.
4. **The same chores as an environment for tool-using models.** Started.
   - `camera_env/` gives a model the current pictures from the same 3 cameras and a small command
     set (move a hand, grip, wait, done), with no object positions. The clock, the layouts and the
     scoring are the benchmark's own.
   - Done so far: 1 chore, 3 layouts, 1 model with a score. Next: every chore, with Claude and
     GPT-6.2 Astra as entries.
   - They are reported as a separate tier, because acting through commands with inverse
     kinematics is not the same job as driving joints.
   - Gate: the environment passes its own audit (it agrees with the scored runs, and there is no
     way to score without doing the chore) before the full table is run.
5. **Stress the simulator.** No hardware needed.
   - Rerun the chores that pass while changing, one at a time, the 4 things the simulator gets
     wrong: finger pad friction (from the simulator's 6 down to about 0.5), camera pose and noise,
     the model's thinking time charged to the clock, and labware size within its tolerance.
   - Gate: a pass that survives all 4 is a candidate for real arms. A pass that breaks under 1 of
     them names what to measure on hardware first.
6. **Real arms, when hardware is available.**
   - The same chores on a 2-arm YAM station with dry labware: tube racks, 50 mL and 1.5 mL tubes,
     deep-well and 96-well plates, a plate hotel, tip boxes. No wet lab is needed for these.
   - The same sentences and pass rules, scored from video against a written rubric, 5 takes per
     chore.
   - Then teaching from real demonstrations, and the 1 chore that does need a lab: handing a plate
     to the deck of a liquid handler.
   - Gate: for each chore, the gap between the simulated and the real pass count. A chore where
     the simulator is wrong is reported as a finding about the simulator.
7. **More chores.** The set grows past 15. Started: 4 instrument tending tasks, in `tending/`:
   loading and unloading a plate dispenser, swirling its cell bottle, and doing both at once with
   2 arms. Next instruments: a plate reader drawer and a liquid handler deck position. Next kinds
   of handling: uncapping a tube, lids and seals, opening plate sleeves and bags, tip boxes onto a
   deck, and liquid. A new chore joins the way the first 15 did: one sentence, a scored end state,
   and an oracle and traps that test its scoring.

Steps 1 to 5 need no robot. This plan assumes no hardware: step 6 is taken when a station is
available, and until then step 5 is the stand-in.

## What the simulator cannot settle

- Grip. Friction and finger forces are tuned for stable grasps, not measured on hardware.
- Liquid, caps, seals and bags. The labware here is rigid and empty.
- Cameras. The pictures are rendered: no glare, no clutter, no blur.
- Time. The simulator waits while the model thinks. A real bench does not.

Steps 5 and 6 exist because of this list.

## What this does not claim

- Nothing here is a reliability claim. 3 or 5 takes sort a chore into fails, sometimes works, or
  works, and no finer.
- 1 model has been scored so far, zero-shot, in simulation.
- A pass in the simulator is not a pass on a bench.
