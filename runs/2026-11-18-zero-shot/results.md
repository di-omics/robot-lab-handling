Simulation only. Model: dreamlabs/dream-1-beta. Run date: 2026-11-18. dreamlabs 1.0.42. Bench code 92c256eb309b.

| Task | Wording | Passes | True rate could be | Mean stage progress | Median time to pass | Calls | Est. cost |
|---|---|---|---|---|---|---|---|
| tubes_to_rack | plain | 1 of 3 | 1 to 91% | 75% | 220 s | 292 | $0.41 |
| bottle_to_shelf | plain | 0 of 3 | 0 to 71% | 33% | n/a | 153 | $0.21 |
| plate_to_tray | plain | 0 of 3 | 0 to 71% | 22% | n/a | 189 | $0.27 |
| sort_by_cap | plain | 1 of 3 | 1 to 91% | 75% | 121 s | 251 | $0.35 |
| tubes_to_waste | plain | 2 of 3 | 9 to 99% | 75% | 81 s | 169 | $0.24 |
| stack_tip_boxes | plain | 0 of 3 | 0 to 71% | 11% | n/a | 189 | $0.27 |
| rack_carry | plain | 2 of 3 | 9 to 99% | 67% | 79 s | 131 | $0.18 |
| tube_handover | plain | 1 of 3 | 1 to 91% | 44% | 138 s | 208 | $0.29 |
| plate_to_hotel_top | plain | 0 of 3 | 0 to 71% | 0% | n/a | 225 | $0.32 |
| plate_to_hotel_middle | plain | 0 of 3 | 0 to 71% | 0% | n/a | 225 | $0.32 |
| plate_to_hotel_bottom | plain | 0 of 3 | 0 to 71% | 33% | n/a | 225 | $0.32 |
| stack_plates | plain | 0 of 3 | 0 to 71% | 0% | n/a | 189 | $0.27 |
| unstack_plate | plain | 0 of 3 | 0 to 71% | 22% | n/a | 189 | $0.27 |
| small_tubes_to_rack | plain | 0 of 3 | 0 to 71% | 33% | n/a | 375 | $0.53 |
| rack_into_box | plain | 0 of 3 | 0 to 71% | 22% | n/a | 225 | $0.32 |

Passes are full successes. The range is the exact 95% range for that many passes in that many takes. Stage progress is partial credit and is a different measure: never read it as a success rate.

16 take(s) stopped on an error and are not counted: tubes_to_rack seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); tubes_to_waste seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); unstack_plate seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); bottle_to_shelf seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_bottom seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_middle seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_hotel_top seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); plate_to_tray seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); rack_carry seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); rack_into_box seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); small_tubes_to_rack seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); sort_by_cap seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); tubes_to_waste seed 102 (DreamBadRequest: DreamAPI refused the inference request: DA-4000 BAD_REQUEST (ma); tubes_to_waste seed 100 (DreamBadRequest: DreamAPI refused the inference request: DA-4000 BAD_REQUEST (ma); unstack_plate seed 100 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: ); bottle_to_shelf seed 101 (DreamProtocolError: could not reach Dream Labs at https://api.dreamlabs.ai:443: )
