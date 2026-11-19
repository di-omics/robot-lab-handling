Simulation only. Model: dreamlabs/dream-1-beta. Run date: 2026-11-18. dreamlabs 1.0.42. Bench code 92c256eb309b.

| Task | Wording | Passes | True rate could be | Mean stage progress | Median time to pass | Calls | Est. cost |
|---|---|---|---|---|---|---|---|
| tubes_to_rack | plain | 1 of 3 | 1 to 91% | 75% | 220 s | 292 | $0.41 |
| bottle_to_shelf | plain | 0 of 2 | 0 to 84% | 50% | n/a | 102 | $0.14 |
| plate_to_tray | plain | 0 of 2 | 0 to 84% | 17% | n/a | 126 | $0.18 |
| sort_by_cap | plain | 0 of 2 | 0 to 84% | 62% | n/a | 200 | $0.28 |
| tubes_to_waste | plain | 1 of 1 | 2 to 100% | 100% | 66 s | 28 | $0.04 |
| stack_tip_boxes | plain | 0 of 3 | 0 to 71% | 11% | n/a | 189 | $0.27 |
| rack_carry | plain | 1 of 2 | 1 to 99% | 67% | 50 s | 85 | $0.12 |
| tube_handover | plain | 1 of 3 | 1 to 91% | 44% | 138 s | 208 | $0.29 |
| plate_to_hotel_top | plain | 0 of 2 | 0 to 84% | 0% | n/a | 150 | $0.21 |
| plate_to_hotel_middle | plain | 0 of 2 | 0 to 84% | 0% | n/a | 150 | $0.21 |
| plate_to_hotel_bottom | plain | 0 of 2 | 0 to 84% | 33% | n/a | 150 | $0.21 |
| stack_plates | plain | 0 of 3 | 0 to 71% | 0% | n/a | 189 | $0.27 |
| unstack_plate | plain | 0 of 2 | 0 to 84% | 33% | n/a | 126 | $0.18 |
| small_tubes_to_rack | plain | 0 of 2 | 0 to 84% | 42% | n/a | 250 | $0.35 |
| rack_into_box | plain | 0 of 2 | 0 to 84% | 33% | n/a | 150 | $0.21 |

Passes are full successes. The range is the exact 95% range for that many passes in that many takes. Stage progress is partial credit and is a different measure: never read it as a success rate.

16 take(s) stopped on an error and are not counted: tubes_to_rack seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); tubes_to_waste seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); unstack_plate seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); bottle_to_shelf seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_bottom seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_middle seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_top seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_tray seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); rack_carry seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); rack_into_box seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); small_tubes_to_rack seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); sort_by_cap seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); tubes_to_waste seed 102 (DreamBadRequest: DreamAPI refused the inference request: DA-4000 BAD_REQUEST (ma); tubes_to_waste seed 100 (DreamBadRequest: DreamAPI refused the inference request: DA-4000 BAD_REQUEST (ma); unstack_plate seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); bottle_to_shelf seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: )
