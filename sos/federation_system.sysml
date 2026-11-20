// System plane of the aircraft federation: the aircraft itself, every other
// piece of software that runs, the frame and timing they share, the flows
// between them, and the artifacts a run is judged by.
//
// Authored in SysML v2 and lowered by scripts/sos_model.py (pycps_sysml2 IR).
// The entity plane — the four named aircraft instances with their ports,
// scenarios and run parameters — stays in sos/aircraft_federation.sysml and is
// lowered by pysos_sysml to the pysos_coordinate manifest. Two files because the
// pysos_sysml subset rejects ports, connections and extra attributes; see
// docs/sos_model.md §3.
//
// The aircraft is imported from 3rd_party/airplane/architecture/aircraft.sysml
// (package Aircraft) instead of being restated here. The SSP's
// SystemStructure.ssd stays authoritative for field-level wiring;
// scripts/sos_model.py --artifacts proves the built scenario.ssp still matches
// the imported model, component by component.
package FederationSystem {
  private import Aircraft::*;

  // -- interfaces: the flow contract lives on the port type ---------------
  // `external` marks the process boundary: these ports are the UDP edge, not
  // SSP connectors, so the artifact check must not look for them in the SSD.
  port def TelemetryInterface {
    attribute protocol : String = "udp";
    attribute encoding : String = "json-udp";
    attribute rate_hz : Real = 10.0;
    attribute external : Boolean = true;
  }

  port def ControlInterface {
    attribute protocol : String = "udp";
    attribute encoding : String = "json-udp";
    attribute rate_hz : Real = 10.0;
    attribute external : Boolean = true;
  }

  port def RprInterface {
    attribute protocol : String = "udp";
    attribute encoding : String = "rpr";
    attribute rate_hz : Real = 10.0;
  }

  port def RprListener {
    attribute udp_port : Integer = 5505;
    attribute protocol : String = "udp";
    attribute encoding : String = "rpr";
    attribute rate_hz : Real = 10.0;
  }

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
  // ports, parameter defaults, FMU sources and the 24 inter-component
  // connections all come from AircraftModel.
  // The federation adds only the two boundary ports the airplane architecture
  // does not declare: the UDP edge served by UdpBridge (no SSP connector).
  part def AircraftInstance {
    part aircraft : AircraftModel;
    port telemetry : TelemetryInterface;
    port control : ControlInterface;
  }

  // -- parameter overrides -------------------------------------------------
  // The federation overrides exactly one aircraft parameter set member:
  // ControlParameters.useBridgeInput (pilot commands steer the aircraft). Every
  // other deviation is per instance and comes from the manifest/scenario:
  // UdpParameters.telemetry_port/control_port from the instance endpoints,
  // EnvironmentParameters.initX_km/initY_km from the placement offsets,
  // AutopilotParameters.waypoint*/targetAirspeed_mps from the scenario, and
  // UdpParameters.reference_* from FrameOrigin. The artifact check proves all
  // of them landed in the built SSV/SSM.
  part def FederationOverrides {
    attribute bridge_input : Boolean = false;
  }

  // -- host-side participants ---------------------------------------------
  part def Orchestrator {
    port telemetry_in : TelemetryInterface;
    port rpr_out : RprInterface;
    port rpr_in : RprListener;
    attribute roles : String = "supervisor,recorder";
    attribute launch : String = "operator";
    attribute cwd : String = ".";
    attribute command : String = "python scripts/run_e2e_rpr.py --manifest manifests/aircraft_federation.manifest.json --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --run-dir build/runs/sos4 --realtime";
  }

  part def Viewer {
    port telemetry_in : TelemetryInterface;
    attribute roles : String = "visualizer";
    attribute launch : String = "manual";
    attribute cwd : String = ".";
    attribute command : String = "python -m flight_viewer --source json-udp --sink rerun --spawn --scenario 3rd_party/airplane/resources/scenarios/test_scenario.json --telemetry 5510:1 --telemetry 5512:2 --telemetry 5514:3 --telemetry 5516:4 --record build/runs/sos4/flight_viewer.jsonl";
  }

  part def Pilot {
    port control_out : ControlInterface;
    attribute roles : String = "operator";
    attribute launch : String = "human";
    attribute cwd : String = ".";
    attribute command : String = "python scripts/send_pilot_command.py";
  }

  part def Builder {
    attribute roles : String = "builder";
    attribute launch : String = "operator";
    attribute cwd : String = ".";
    attribute command : String = "python scripts/build_airplane.py";
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
    part overrides : FederationOverrides;
    part instances : AircraftInstance [4];
    part orchestrator : Orchestrator;
    part viewer : Viewer;
    part pilot : Pilot;
    part builder : Builder;
    part artifacts : Artifacts;

    connection telemetry_to_orchestrator connect instances.telemetry to orchestrator.telemetry_in;
    connection rpr_recorder_loopback connect orchestrator.rpr_out to orchestrator.rpr_in;
    connection telemetry_to_viewer connect instances.telemetry to viewer.telemetry_in;
    connection pilot_control connect pilot.control_out to instances.control;
  }
}
