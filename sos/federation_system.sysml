// System plane of the aircraft federation: the aircraft itself, every other
// piece of software that runs, the frame and timing they share, the flows
// between them, and the artifacts a run is judged by.
//
// Authored in SysML v2 and lowered by scripts/sos_model.py (pycps_sysml2 IR).
// The entity plane — the four named aircraft instances with their ports,
// scenarios and run parameters — stays in sos/aircraft_federation.sysml and is
// lowered by pysos_sysml to the pysos_coordinate manifest. Both planes import
// the same Aircraft model and the same PysosSoS::LaunchSpec vocabulary. Two
// files remain because the pysos_sysml subset still rejects ports,
// connections and timing; see docs/sos_model.md §3.
//
// The aircraft is imported from 3rd_party/airplane/architecture/aircraft.sysml
// (package Aircraft) instead of being restated here. The SSP's
// SystemStructure.ssd stays authoritative for field-level wiring;
// scripts/sos_model.py --artifacts proves the built scenario.ssp still matches
// the imported model, component by component.
package FederationSystem {
  private import Aircraft::*;
  private import PysosSoS::*;
  private import RprEntity::*;

  // -- interfaces: role markers, not fact carriers ------------------------
  // The aircraft broadcasts RPR entity-state packets: one outbound edge per
  // instance, addressed to the recorder. Transport lives in the entity plane's
  // transport sets, the wire version in RprEntity::RprContract, cadence in
  // Timing, and the listener endpoint on Orchestrator. `sos_model.py` derives
  // the flow contract from those owners and fails on disagreement.
  // A port usage on the AircraftInstance wrapper is the process boundary, so
  // externality is structural and nothing is authored here.
  port def RprBroadcast;

  port def RprListener;

  // -- shared frame --------------------------------------------------------
  part def FrameOrigin {
    attribute mode : String = "federation";
    attribute axis_order : String = "x_north_y_east_z_up_km";
    attribute reference : String = "3rd_party/airplane/resources/scenarios/test_scenario.json#points[0]";
    attribute waypoint_frame : String = "federation";
    attribute latitude_deg : Real = -2.957519;
    attribute longitude_deg : Real = 39.232955;
    attribute altitude_m : Real = 0.0;
  }

  // -- federation timing contract -----------------------------------------
  part def Timing {
    attribute realtime_class : String = "soft_realtime";
    attribute policy : String = "wall_clock";
    attribute realtime : Boolean = true;
    attribute step_size_s : Real = 0.1;
    attribute stop_time_s : Real = 120.0;
    attribute recording_interval_s : Real = 0.25;
    attribute sample_period_s : Real = 0.1;
    attribute fanin_watchdog_s : Real = 2.0;
    attribute epoch : String = "per_process_monotonic";
    attribute barrier : String = "none";
    attribute overrun_policy : String = "lag";
  }

  // -- the actual aircraft ------------------------------------------------
  // Imported from the airplane submodule, not duplicated: component defs,
  // ports, parameter defaults, FMU sources and the inter-component
  // connections all come from AircraftModel.
  // The federation adds only the boundary port the airplane architecture does
  // not declare: the RPR broadcast edge served by `rpr_entity` (no SSP
  // connector). `telemetry` is the manifest endpoint name; its type is RPR.
  part def AircraftInstance {
    part aircraft : AircraftModel;
    port telemetry : RprBroadcast;
  }

  // -- host-side participants ---------------------------------------------
  // The orchestrator supervises the instance processes and listens on the
  // dedicated RPR fan-in port; it writes truth/measure/rrd, never a live JSON
  // stream.
  part def Orchestrator :> Application {
    port rpr_in : RprListener;
    attribute rprHost : String = "127.0.0.1";
    attribute rprPort : Integer = 5505;
    attribute roles : String = "supervisor,recorder";
    attribute cwd : String = ".";
    attribute command : String = "python scripts/run_e2e_rpr.py --manifest manifests/aircraft_federation.manifest.json --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --run-dir build/runs/sos4 --realtime";
    part launch : LaunchSpec {
      attribute mode : String = "operator";
      attribute readiness : String = "port_bound";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 1;
      attribute after_process : String = "builder";
    }
  }

  // The viewer replays the recorder truth stream; it owns no UDP socket.
  part def Viewer :> Application {
    attribute roles : String = "visualizer";
    attribute cwd : String = ".";
    attribute command : String = "python -m flight_viewer --source jsonl --path build/runs/sos4/truth.jsonl --sink rerun --spawn --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --realtime";
    part launch : LaunchSpec {
      attribute mode : String = "manual";
      attribute readiness : String = "none";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 2;
      attribute after_process : String = "recorder";
    }
  }

  part def Builder :> Application {
    attribute roles : String = "builder";
    attribute cwd : String = ".";
    attribute command : String = "python scripts/build_airplane.py";
    part launch : LaunchSpec {
      attribute mode : String = "operator";
      attribute readiness : String = "none";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 0;
      attribute after_process : String = "";
    }
  }

  part def Artifacts {
    attribute run_dir : String = "build/runs/sos4";
    attribute truth : String = "truth.jsonl";
    attribute truth_meta : String = "truth.meta.json";
    attribute measurements : String = "measurements.csv";
    attribute comparison : String = "comparison.csv";
    attribute separation : String = "separation.csv";
    attribute rrd : String = "recording.rrd";
    attribute run_json : String = "run.json";
    attribute instances_dir : String = "instances/";
    attribute logs_dir : String = "logs/";
  }

  // -- the system description ---------------------------------------------
  part def SystemDescription {
    attribute federation : String = "AircraftFederation";
    attribute entity_model : String = "sos/aircraft_federation.sysml";
    attribute manifest : String = "manifests/aircraft_federation.manifest.json";
    attribute scenarios_dir : String = "3rd_party/airplane/resources/scenarios";
    attribute source_ssp : String = "build/ssp/scenario.ssp";
    attribute aircraft_ssp : String = "3rd_party/airplane/build/ssp/aircraft.ssp";
    attribute architecture : String = "3rd_party/airplane/architecture/aircraft.sysml";
    attribute scenario_binding : String = "MissionScenario.ssv";
    attribute scenario_mapping : String = "HighAltitudeIntercept.ssm";

    part origin : FrameOrigin;
    part timing : Timing;
    part instances : AircraftInstance [4];
    part orchestrator : Orchestrator;
    part viewer : Viewer;
    part builder : Builder;
    part artifacts : Artifacts;

    connection rpr_broadcast connect instances.telemetry to orchestrator.rpr_in;
  }
}
