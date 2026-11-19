# Protocol: zero-shot baseline

Frozen 2026-11-18 15:54 PST, before any scored take. Bench code `92c256eb309b`.
If the code or this file changes after that, the results say so by carrying a different code id.

## What is scored

- **Model:** `dreamlabs/dream-1-beta` through its API, joint control, 48 actions per call. Zero-shot: no fine-tuning and no
  examples of these tasks.
- **Inputs:** 3 cameras (the last 9 frames of each, 0.2 s apart), the joint angles and gripper openings, and
  one sentence.
- **Wording:** the plain wording on each task card. Other wordings are a separate experiment.
- **Takes:** 5 per task, on the layouts of seeds 100 to 104. They run in 2 batches fixed here
  (seeds 100, 101, 102; then seeds 103, 104), split for budget only. No take is added or dropped after
  results are seen.
- **Errors:** a take that stops on a software or network error is rerun once on the same seed, and the error
  is reported next to the results.
- **Human assists:** none. Nothing is reset, moved or nudged during a take.
- **Time:** the simulator advances only while actions run. A take ends at the task's time limit, or 1 s after
  the pass rule has held for 1.5 s.

## Development layouts, kept apart

Seeds 0 to 4 were used for practice before this file was frozen (`tubes_to_rack` only, both wordings). The time
limit of that task was raised from 120 s to 240 s after the first practice take. No scored take uses those
seeds.

## Reporting

- Passes as k of n with the exact 95% range for the true rate. With 5 takes that range is wide (0 of 5 still
  allows up to 52%), so 5 takes sort a task into fails, sometimes works or works, and no finer.
- Stage progress (partial credit) in its own column, never mixed with the pass count.
- Per take: date, model ID, library version, bench code id, calls, estimated cost, median call time.

## Tasks and pass rules

The rule that counts is the code in `labbench/tasks.py` and `labbench/score.py`. This table says the same in
words. A stage counts once its test has held for 0.5 s.

| # | Task | The robot is told | Passes when | Time limit | Stages (partial credit) |
|---|---|---|---|---|---|
| 1 | `tubes_to_rack` | Put the tubes in the rack. | Both 50 mL tubes stand in wells of the rack, hands off. | 240 s | tube_a_lifted, tube_a_in_rack, tube_b_lifted, tube_b_in_rack |
| 2 | `bottle_to_shelf` | Put the bottle on the gray platform. | The bottle stands upright on the platform, hands off. | 120 s | bottle_lifted, bottle_over_shelf, bottle_on_shelf |
| 3 | `plate_to_tray` | Put the plate on the black tray. | The deep-well plate sits flat in the tray pocket, the right way round, hands off. | 150 s | plate_lifted, plate_over_tray, plate_in_tray |
| 4 | `sort_by_cap` | Put the red tube in the left tray and the blue tube in the right tray. | The red tube is in the left tray and the blue tube is in the right tray, hands off. | 240 s | red_lifted, red_in_left_tray, blue_lifted, blue_in_right_tray |
| 5 | `tubes_to_waste` | Throw the used tubes into the waste bin. | Both open tubes are inside the bin, hands off. | 240 s | tube_a_lifted, tube_a_in_bin, tube_b_lifted, tube_b_in_bin |
| 6 | `stack_tip_boxes` | Stack the two tip boxes. | One tip box sits squarely on the other, the same way round, hands off. | 150 s | a_box_lifted, box_over_the_other, boxes_stacked |
| 7 | `rack_carry` | Pick up the tube rack with both hands and put it on the gray mat. | The rack rests on the mat after a level lift. A rack pushed along the table does not count. | 150 s | rack_lifted_level, rack_over_mat, rack_on_mat |
| 8 | `tube_handover` | Pick up the tube with the left hand, pass it to the right hand, and put it in the tray on the right. | The tube is in the right tray, and the right hand held it on the way. A long reach by the left arm does not count. | 180 s | tube_lifted, right_hand_has_it, tube_in_tray |
| 9 | `plate_to_hotel_top` | Put the plate on the top shelf. | The plate lies flat on the top shelf, at most 3 cm short of fully in, hands off. Another shelf does not count. | 180 s | plate_lifted, plate_lined_up_at_shelf, plate_on_shelf |
| 10 | `plate_to_hotel_middle` | Put the plate on the middle shelf. | The plate lies flat on the middle shelf, at most 3 cm short of fully in, hands off. Another shelf does not count. | 180 s | plate_lifted, plate_lined_up_at_shelf, plate_on_shelf |
| 11 | `plate_to_hotel_bottom` | Put the plate on the bottom shelf. | The plate lies flat on the bottom shelf, at most 3 cm short of fully in, hands off. Another shelf does not count. | 180 s | plate_lifted, plate_lined_up_at_shelf, plate_on_shelf |
| 12 | `stack_plates` | Stack the two plates. | One plate sits on the other with edges lined up (within 12 mm), hands off. | 150 s | a_plate_lifted, plate_over_the_other, plates_stacked |
| 13 | `unstack_plate` | Take the top plate off the stack and put it on the black tray. | The top plate sits flat in the tray, and the other two plates are still stacked where they started. | 150 s | top_plate_lifted_alone, plate_over_tray, plate_in_tray |
| 14 | `small_tubes_to_rack` | Put the small tubes in the rack. | All three 1.5 mL tubes stand in holes of the rack, hands off. | 300 s | epp_a_lifted, epp_a_in_rack, epp_b_lifted, epp_b_in_rack, epp_c_lifted, epp_c_in_rack |
| 15 | `rack_into_box` | Put the tube rack in the box. | The rack sits flat on the floor of the box with both tubes still in its wells, hands off. | 180 s | rack_lifted_level, rack_over_box, rack_in_box_tubes_still_racked |
