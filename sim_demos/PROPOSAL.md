# Proposal: how many demonstrations does a failing lab chore need?

**Status: ready to run, not run. Nothing has been uploaded, no fine-tune has been started, and $0 has been spent.**

## The question

Dream-1, a general robot model, has not once put a plate on the reader tray when simply told to: 0 of 3 scored
takes, and 0 of 18 across the 6 plate chores. How many demonstrations does it take to turn
that into a chore that works, and what does it cost?

It is the practical form of a bigger question: how much does a general robot model already know, and how little
teaching finishes the job?

The answer proposed here is a dose curve. Fine-tune the same model on 5, 20 and 50 demonstrations, and test each
one on 30 layouts it has never seen.

## What is ready

| | |
|---|---|
| Demonstrations | 50 scripted runs of the chore in the simulator. The bench's own scoring passed 50 of 50. That is 16.75 min of robot time. |
| Format | 3 cameras, joint states and actions, in the layout the model is fed at run time. It passes Dream's own dataset check with no notes. |
| Proof the data carries the chore | Replaying only the stored actions solves the chore again on 50 of 50 layouts. With the gripper held open, it is 0 of 50. |
| Dose sets | The first 5, 20 and 50 demonstrations as 3 datasets: 1.7, 6.9 and 16.75 min. Each passes the check. |
| Cost so far | $0. Everything ran on this computer. |

## What building it showed

1. **The plate can be gripped, but only just.** The fingers open to 93.6 mm and the plate is 85.5 mm wide, so there
   are 4 mm to spare on each side. The hand must be more than 91% open and centred to within 4 mm.
2. **Dream-1 closes its hand too early.** In the first 2 logged takes the left hand started open, dropped below 50% open
   within 10 s, and stayed there for most of the take (56 of 63 calls on one layout, 37 of 63 on the other). A hand
   that closed cannot go around the plate. This is a lead, not a tested cause.
3. **A hard grip fails twice in this simulator.** A snap close hooks the plate on a finger, and a full-force close
   lets it slide off centre. The demonstrations close gently instead: over 0.6 s, with about 15 N per finger.

So the fine-tune has one clear thing to learn: keep the hand open until it is around the plate, then close gently.
That can be read from every test take, pass or fail.

## The experiment

- **Train:** 3 fine-tunes of Dream-1, on the first 5, 20 and 50 demonstrations. Each runs 500 steps with a cosine
  schedule and the service's default settings, so the only thing that changes is how many demonstrations it sees.
- **Test:** the untrained model and the 3 fine-tunes, each on the same 30 unseen layouts (seeds 42000 to 42029).
  1 take per layout, with the same sentence and 150 s limit as the zero-shot runs. The rules are frozen in a
  protocol file before the first take.
- **Report:** passes as k of 30 with the exact 95% range. Beside it: how far each take got (lifted, over the tray,
  seated) and how open the hand was when it reached the plate.
- **Side checks on the 50-demonstration model, 10 takes per chore:** 2 other plate chores, to see if the skill
  carries over, and 2 tube chores Dream-1 sometimes passes, to see if it forgot anything.

The 30 test layouts are new draws from the same small jitter the demonstrations cover: the plate within 1.2 cm and
7 degrees. A plate moved further is a separate, later test.

| Version | Fine-tunes | Training | Testing, at most | Total, at most |
|---|---|---|---|---|
| Smallest: 50 demonstrations only | 1 | $100 | $5 | $105 |
| Dose curve: 5, 20 and 50 | 3 | $300 | $11 | $311 |
| Dose curve plus side checks | 3 | $300 | $20 | $320 |

Training costs $100 per 500-step fine-tune and cannot be cancelled once queued. Testing is estimated at $0.09 per
take: 63 calls at the base model's $0.0014 per call. The price per call of a fine-tuned model is not confirmed.

## What each result would mean

| Result with 50 demonstrations | Reading | Next step |
|---|---|---|
| Works: 24 or more of 30 (true rate at least 61%) | 17 min of clean demonstrations teach a chore with 4 mm of tolerance. | The dose curve says how few are enough. Then the same test on the real arms, with a person recording the demonstrations. |
| Sometimes: 1 to 23 of 30 | Learnable, not yet reliable. | Read the hand opening and the stage where takes stop. Then add more, or more varied, demonstrations. |
| Fails: 0 of 30 (true rate under 12%) | 50 clean demonstrations and 500 steps are not enough here. | Check the hand opening first. Then try more steps, or demonstrations that show recoveries. |

## The caveat that matters

The demonstrations are scripted with perfect knowledge of where the plate is, in a simulator, and every one is a
clean first-try success. A pass would show that the model can learn this chore from 17 min of clean examples in
simulation. It would not show the same on real arms, where demonstrations come from a person and the model has to
find the plate through its cameras.

## To run it

2 decisions for the account owner: which version, and a yes on the spend. The exact commands, each marked NOT RUN,
are in [NOTES.md](NOTES.md), with the full record of how the demonstrations were built and checked.
