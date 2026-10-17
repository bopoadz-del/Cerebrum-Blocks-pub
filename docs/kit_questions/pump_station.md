# Water Pump Station Operations — Questions I Cannot Answer

Answer format: value · unit · station · pump / model · source · date

1 — Station and pump register

· 1.1 [GATE] Your station register — station name/ID, number of pumps (duty/standby/assist), pump make/model/impeller diameter/trim, rated flow and head at duty point, BEP flow, motor rated power/voltage/FLC, VFD fitted and speed range, static lift min/max, rising main diameter/length/material, wet well volume (gross and working), design peak inflow — with the source of each.
· 1.2 [GATE] Which of your pumps are oversized for present demand, and how you run them.
· 1.3 [GATE] Which of your pumps are duty-assist vs duty-standby, and how each is sequenced.

2 — Energy and operating cost

· 2.1 [GATE] Your specific energy consumption per station (kWh/m³), energy at BEP vs your actual operating point, electricity tariff peak and off-peak, demand/capacity charge, standby generator running cost, power factor penalty threshold — with source.
· 2.2 [GATE] Your target specific energy per m³, and the actual — with the gap.
· 2.3 [GATE] Where pumping is shifted to off-peak on your network, and what governs the window.
· 2.4 [GATE] What a 1% efficiency loss costs annually at each of your stations.

3 — Maintenance and failure cost

· 3.1 [GATE] Your cost and lead time per item — pump overhaul, impeller replacement, mechanical seal, bearing, motor rewind, motor replacement, VFD replacement, emergency callout, crane/lifting for pump removal, rising main repair, wet well clean-out.
· 3.2 [GATE] Your cost of a lost hour per station — offline with storage covering, offline storage exhausted, sewage overflow, regulatory penalty, tankering, customer compensation.
· 3.3 [GATE] Your MTBF per pump type and the dominant failure mode on your estate.
· 3.4 [GATE] Your spares holding, and your longest lead item that would keep a station down.

4 — Hydraulic envelope

· 4.1 [GATE] Your NPSHa at design condition and at worst case (summer, low level, max flow, dirty screen) — with the calculation basis.
· 4.2 [GATE] Your NPSHr per pump from datasheet — with trim, speed, flow — and the NPSH margin your standard requires (fixed head, percentage, or per ANSI/HI 9.6.1 class), and where that margin is written.
· 4.3 [GATE] Your POR and AOR as applied on your stations — the flow ranges you run within routinely, and what authorises AOR operation and for how long.
· 4.4 [GATE] Your minimum continuous flow per pump, and what enforces it.
· 4.5 [GATE] Your maximum flow / runout, maximum discharge pressure, rising main pressure rating, maximum permitted surge pressure.
· 4.6 [GATE] Your minimum submergence over suction, maximum starts per hour, maximum continuous run time, motor current and temperature limits, vibration alarm and trip levels.
· 4.7 [GATE] Which pumps in your estate are high or very high suction energy, and how you know.

5 — Named calculations

· 5.1 [GATE] For each calculation on your stations — NPSHa, NPSH margin, system head curve, duty point, efficiency, specific energy, affinity law speed change, parallel combined curve, surge on power failure, surge on valve closure, air vessel sizing, wet well volume/cycle time, starts per hour, retention time (septicity/H₂S), friction loss, rising main velocity min/max — the inputs you use, the standard each follows, and who owns it.
· 5.2 [GATE] Your surge/transient study — date last done, and what has changed since (pump, valve closure time, main, air vessel).
· 5.3 [GATE] Your minimum wet well volume that keeps starts per hour within the motor limit at design inflow — per station.
· 5.4 [GATE] Your retention time threshold that triggers septicity and H₂S generation in sewage service.
· 5.5 [GATE] Your parallel operation check — whether each pump stays within POR when running together on your stations.

6 — Control, protection and SCADA

· 6.1 [GATE] Your protection list per station — low level/dry run, high level, high-high/overflow, low suction, high discharge, motor overcurrent, motor over-temperature, seal water/failure, vibration, bearing temperature, surge/NRV failure, no-flow detection, VFD fault — with setpoint, trip or alarm, how verified, last tested.
· 6.2 [GATE] Which protections are currently overridden, bypassed, forced, or in manual anywhere in your estate — where that is recorded, who approves, and the maximum duration.
· 6.3 [GATE] How anyone reading the P&ID or SCADA screen would know a protection is bypassed — where that lives, and whether it is linked to anything a system could read.
· 6.4 [GATE] Your control philosophy per station (level, pressure, flow, time-of-day, optimisation), and who may change it.
· 6.5 [GATE] Your power failure and restoration behaviour, and whether restart is staggered.
· 6.6 [GATE] Your telemetry failure behaviour — fail to stop, fail to run, last known state.

7 — Operational decision

· 7.1 [GATE] Your priority order when a pump or station is in trouble.
· 7.2 [GATE] What makes each option impossible on your stations — run standby, run both duty, run outside POR/in AOR, run with protection bypassed, reduce speed on VFD, throttle discharge, draw wet well down further, bypass pumping/tanker, shut station down, restart after trip.
· 7.3 [GATE] Your hard limits that can never be traded, whatever the pressure.
· 7.4 [GATE] Your authority matrix — operate outside POR, bypass or force a protection, reset a trip without investigation, run pump below minimum flow, exceed starts per hour, defer safety-critical maintenance, enter wet well or dry well, discharge to environment.

8 — Confined space and site safety

· 8.1 [GATE] Which of your spaces are classified as confined spaces — wet well, dry well, valve chamber, screen chamber — and your atmospheric entry limits as practised.
· 8.2 [GATE] Your H₂S limits for sewage stations — alarm, evacuation — as set on your sites.
· 8.3 [GATE] Your isolation and lock-off procedure before mechanical work — electrical, hydraulic, stored energy.
· 8.4 [GATE] Your lifting plan requirement for pump removal, and maximum load of your fixed lifting equipment per station.
· 8.5 [GATE] Your written emergency protocols — gas, drowning, entrapment, electrical, overflow, flood.

9 — Evidence standard

· 9.1 [GATE] Per figure class — NPSHr, NPSHa, duty point, pump curve, surge pressure, protection setpoint, wet well volume, exposure limit — what your organisation accepts as proof, and what it rejects even if it states the number.
· 9.2 [GATE] Minimum acceptable citation per source type — pump datasheet/curve (model, impeller trim, speed), motor datasheet, surge/transient study (date, configuration modelled), design basis report, SCADA configuration (live, not design intent), standard, maintenance record.
· 9.3 [GATE] Mandatory qualifiers your organisation requires — NPSHr, NPSHa, duty point, flow, head, protection setpoint — with the "3% head-drop requires margin" note on NPSHr and the "design or worst case" note on NPSHa.
· 9.4 [GATE] Your derivation rules — affinity laws, interpolating along a curve, extrapolating beyond published curve, calculating NPSHa, combining curves for parallel, head/pressure conversion, carrying curve across trims, carrying surge across stations, estimating wet well volume — allowed or not on your stations.
· 9.5 [GATE] Your staleness rules per figure — surge study, pump curve, NPSHa calculation, protection setpoints, efficiency/specific energy, wet well working volume — valid for how long, stale immediately on what.
· 9.5.2 [GATE] Confirm the live-state rule — no answer about a protection or an operating limit without checking whether that protection is currently bypassed or forced.
· 9.6 [GATE] Your conflict resolution — design document vs live SCADA setpoint, manufacturer limit vs operating procedure — which governs on your stations, and which the system should quote.
· 9.7 [GAP] Partial-evidence disclosure wording per situation, and which figures must never be offered as estimates — confirmed explicitly against your Section 10 list.

10 — Never-estimate

· 10.1 [GATE] Which figures your organisation treats as absolute — NPSH margin requirement, maximum surge pressure, high-high level/overflow setpoint, H₂S evacuation limit, minimum submergence, minimum continuous flow, POR and AOR boundaries, maximum discharge pressure, rising main pressure rating, maximum starts per hour, motor current and temperature limits, vibration trip levels, confined-space atmospheric limits, lifting equipment maximum load, electrical isolation values.
· 10.2 [GAP] Which of the above have caught you out, and how.

11 — May-estimate

· 11.1 [GAP] Figures you accept as estimates — expected run hours, energy forecast, remaining bearing life — and the exact wording you want attached.

12 — Refusals

· 12.1 [GATE] Your list of questions that must be refused outright — run this pump harder, bypass this trip, enter the wet well, reset and restart, main take this pressure — and what the system should say instead.

13 — Precedence

· 13.1 [GATE] Your ranking, highest first — national regulation/discharge consent, standard, design basis report, transient/surge study, manufacturer datasheet and curve, live SCADA configuration, operating procedure, maintenance record, shift instruction.
· 13.2 [GATE] When live SCADA setpoint and design document differ on your stations — which governs, and which the system should quote.
· 13.3 [GATE] When manufacturer limit and your procedure differ — which governs.
· 13.4 [GATE] How anyone knows a curve, study or setpoint is the current one on your estate.
· 13.5 [GAP] Which figures are station-specific on your estate and never carried between stations.
· 13.6 [GAP] Which are pump-specific rather than model-specific — after trim or wear, actual efficiency, vibration baseline.

14 — Unit-confusion history

· 14.1 [GAP] Where a head vs pressure conversion error has occurred on your stations.
· 14.2 [GAP] Where a gross vs working volume error has caused a cycling or overflow problem on yours.
· 14.3 [GAP] Where an NPSHr-as-a-limit assumption has caused damage on yours.

15 — Incidents

· 15.1 [GAP] A figure taken from the wrong curve, trim, or a superseded study.
· 15.2 [GAP] A limit correct for one pump or station and wrong for another.
· 15.3 [GAP] A time someone assumed a figure because it "looked normal".
· 15.4 [GAP] A protection believed active that was bypassed or forced.
· 15.5 [GAP] A cavitation or dry-run event, and the number behind it.
· 15.6 [GAP] A surge or burst event traced to a change that invalidated the study.
· 15.7 [GAP] An overflow, and what the setpoint or telemetry actually said.
· 15.8 [GAP] A unit confusion — head, pressure, volume, power.
· 15.9 [GAP] What a new operator or duty engineer most commonly gets wrong in their first six months.

16 — The five questions

· 16.1 [GAP] Five things you'd ask a system per shift and trust completely.
