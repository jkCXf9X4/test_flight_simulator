// Entity plane of the aircraft federation: the aircraft/entity/application
// layers, promoted from the interface mockup. Host processes, the simulation
// architecture and its connects stay in the system plane
// (`federation_system.sysml`); nothing here starts a supervisor or draws an
// architecture edge.
//
// Layers in this file:
//   1. endpoint contract        `RprBroadcast` / `RprListener` role markers
//   2. AircraftVariant          inheritance seam onto `Aircraft::AircraftModel`
//   3. ParameterSet sets + binds  per-variant scenario/identity/transport values
//   4. Application + Participant  how the runnable app is started and joined
//
// Scenario, identity and transport values live in the variant sets only; there
// is no second copy on a participant. Each full variant set is exported to
// `build/ssp/variants/<Variant>.ssp`, e.g.
// `pyssp_sysml2.generate_ssp(..., composition="RedInterceptor")`.
package AircraftFederation {
  private import Aircraft::*;
  private import PysosSoS::*;
  private import PysspCore::*;

  // -- endpoint contract ---------------------------------------------------
  // Port defs are role markers, not fact carriers. A value on a port def is a
  // second source of truth no binding reaches, so it can drift from the FMU.
  // Listener host/port belongs to the orchestrator application in the system
  // plane, which is why `RprListener` is declared but not used here.
  port def RprBroadcast;

  port def RprListener;

  // -- 1. aircraft variant: the real model, as an exportable root ----------
  // The variant adds no attributes: only binds and recognisable metadata.
  // `pyssp_sysml2` projects the inherited components, ports, FMU metadata and
  // connections. Build metadata is inherited; do not set `ssp_meta`, and do
  // not restate the FMU source per variant.
  part def AircraftVariant :> AircraftModel;

  // -- 2. named parameter sets ---------------------------------------------
  // Scenario values (environment + autopilot).
  attribute def RedInterceptorScenario :> ParameterSet {
    attribute initX_km : Real = 0.0;
    attribute initY_km : Real = 0.0;
    attribute initZ_km : Real = 0.0;
    attribute waypointProximity_km : Real = 10.0;
    attribute waypointCount : Integer = 10;
    attribute targetAirspeed_mps : Real = 500.0;
    attribute waypointX_km : Real[10] = (14.101, -40.886, 11.155, 13.975, 16.796, 19.617, 22.438, 25.259, 28.080, 30.901);
    attribute waypointY_km : Real[10] = (62.131, 285.762, 500.929, 512.593, 524.256, 535.920, 547.584, 559.247, 570.911, 582.575);
    attribute waypointZ_km : Real[10] = (4.217, 8.924, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0);
  }

  // Payload identity: RPR reference origin and entity/marking.
  attribute def RedInterceptorIdentity :> ParameterSet {
    attribute reference_latitude_deg : Real = -2.957519;
    attribute reference_longitude_deg : Real = 39.232955;
    attribute reference_altitude_m : Real = 0.0;
    attribute entity_site : Integer = 1;
    attribute entity_application : Integer = 1;
    attribute entity_entity : Integer = 1;
    attribute marking_characters : String = "RED-1";
  }

  // Transport deployment: `rpr_entity.parameters` (RprDeployment).
  attribute def RedInterceptorTransport :> ParameterSet {
    attribute transport : String = "udp";
    attribute bind_address : String = "127.0.0.1:5510";
    attribute peer_address : String = "127.0.0.1:5505";
  }

  // Scenario values (environment + autopilot).
  attribute def RedStrikerScenario :> ParameterSet {
    attribute initX_km : Real = 0.0;
    attribute initY_km : Real = 5.0;
    attribute initZ_km : Real = 0.0;
    attribute waypointProximity_km : Real = 10.0;
    attribute waypointCount : Integer = 10;
    attribute targetAirspeed_mps : Real = 260.0;
    attribute waypointX_km : Real[10] = (679.666, 822.619, 608.958, -110.679, -565.416, -570.833, -576.249, -581.666, -587.083, -592.500);
    attribute waypointY_km : Real[10] = (160.430, 612.591, 434.156, 329.579, 1228.491, 1239.199, 1249.907, 1260.615, 1271.323, 1282.031);
    attribute waypointZ_km : Real[10] = (8.694, 8.460, 10.991, 11.082, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0);
  }

  // Payload identity: RPR reference origin and entity/marking.
  attribute def RedStrikerIdentity :> ParameterSet {
    attribute reference_latitude_deg : Real = -2.957519;
    attribute reference_longitude_deg : Real = 39.232955;
    attribute reference_altitude_m : Real = 0.0;
    attribute entity_site : Integer = 1;
    attribute entity_application : Integer = 1;
    attribute entity_entity : Integer = 2;
    attribute marking_characters : String = "RED-2";
  }

  // Transport deployment: `rpr_entity.parameters` (RprDeployment).
  attribute def RedStrikerTransport :> ParameterSet {
    attribute transport : String = "udp";
    attribute bind_address : String = "127.0.0.1:5512";
    attribute peer_address : String = "127.0.0.1:5505";
  }

  // Scenario values (environment + autopilot).
  attribute def BlueCasScenario :> ParameterSet {
    attribute initX_km : Real = 0.0;
    attribute initY_km : Real = 10.0;
    attribute initZ_km : Real = 0.0;
    attribute waypointProximity_km : Real = 10.0;
    attribute waypointCount : Integer = 10;
    attribute targetAirspeed_mps : Real = 220.0;
    attribute waypointX_km : Real[10] = (-148.522, -135.806, -142.409, -212.570, -217.158, -221.746, -226.334, -230.922, -235.510, -240.098);
    attribute waypointY_km : Real[10] = (121.735, 71.686, 263.272, 93.700, 82.612, 71.523, 60.435, 49.347, 38.258, 27.170);
    attribute waypointZ_km : Real[10] = (2.635, 5.018, 3.400, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0);
  }

  // Payload identity: RPR reference origin and entity/marking.
  attribute def BlueCasIdentity :> ParameterSet {
    attribute reference_latitude_deg : Real = -2.957519;
    attribute reference_longitude_deg : Real = 39.232955;
    attribute reference_altitude_m : Real = 0.0;
    attribute entity_site : Integer = 1;
    attribute entity_application : Integer = 1;
    attribute entity_entity : Integer = 3;
    attribute marking_characters : String = "BLUE-1";
  }

  // Transport deployment: `rpr_entity.parameters` (RprDeployment).
  attribute def BlueCasTransport :> ParameterSet {
    attribute transport : String = "udp";
    attribute bind_address : String = "127.0.0.1:5514";
    attribute peer_address : String = "127.0.0.1:5505";
  }

  // Scenario values (environment + autopilot).
  attribute def BlueBaselineScenario :> ParameterSet {
    attribute initX_km : Real = 0.0;
    attribute initY_km : Real = 15.0;
    attribute initZ_km : Real = 0.0;
    attribute waypointProximity_km : Real = 10.0;
    attribute waypointCount : Integer = 10;
    attribute targetAirspeed_mps : Real = 680.0;
    attribute waypointX_km : Real[10] = (14.101, -40.886, 11.155, 13.975, 16.796, 19.617, 22.438, 25.259, 28.080, 30.901);
    attribute waypointY_km : Real[10] = (77.131, 300.762, 515.929, 527.593, 539.256, 550.920, 562.584, 574.247, 585.911, 597.575);
    attribute waypointZ_km : Real[10] = (4.217, 8.924, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
  }

  // Payload identity: RPR reference origin and entity/marking.
  attribute def BlueBaselineIdentity :> ParameterSet {
    attribute reference_latitude_deg : Real = -2.957519;
    attribute reference_longitude_deg : Real = 39.232955;
    attribute reference_altitude_m : Real = 0.0;
    attribute entity_site : Integer = 1;
    attribute entity_application : Integer = 1;
    attribute entity_entity : Integer = 4;
    attribute marking_characters : String = "BLUE-2";
  }

  // Transport deployment: `rpr_entity.parameters` (RprDeployment).
  attribute def BlueBaselineTransport :> ParameterSet {
    attribute transport : String = "udp";
    attribute bind_address : String = "127.0.0.1:5516";
    attribute peer_address : String = "127.0.0.1:5505";
  }

  // Export roots. All four variants are full; each binds the same 19 model
  // parameters from its own scenario, identity, and transport sets.
  part def RedInterceptor :> AircraftVariant {
    attribute experiment : BaselineExperiment;
    attribute scenario : RedInterceptorScenario;
    attribute identity : RedInterceptorIdentity;
    attribute transport : RedInterceptorTransport;

    bind environment.parameters.initX_km = scenario.initX_km;
    bind environment.parameters.initY_km = scenario.initY_km;
    bind environment.parameters.initZ_km = scenario.initZ_km;
    bind autopilot_module.parameters.waypointProximity_km = scenario.waypointProximity_km;
    bind autopilot_module.parameters.waypointCount = scenario.waypointCount;
    bind autopilot_module.parameters.targetAirspeed_mps = scenario.targetAirspeed_mps;
    bind autopilot_module.parameters.waypointX_km = scenario.waypointX_km;
    bind autopilot_module.parameters.waypointY_km = scenario.waypointY_km;
    bind autopilot_module.parameters.waypointZ_km = scenario.waypointZ_km;
    bind rpr_state_source.parameters.reference_latitude_deg = identity.reference_latitude_deg;
    bind rpr_state_source.parameters.reference_longitude_deg = identity.reference_longitude_deg;
    bind rpr_state_source.parameters.reference_altitude_m = identity.reference_altitude_m;
    bind rpr_state_source.parameters.entity_site = identity.entity_site;
    bind rpr_state_source.parameters.entity_application = identity.entity_application;
    bind rpr_state_source.parameters.entity_entity = identity.entity_entity;
    bind rpr_state_source.parameters.marking_characters = identity.marking_characters;
    bind rpr_entity.parameters.transport = transport.transport;
    bind rpr_entity.parameters.bind_address = transport.bind_address;
    bind rpr_entity.parameters.peer_address = transport.peer_address;
  }

  part def RedStriker :> AircraftVariant {
    attribute experiment : BaselineExperiment;
    attribute scenario : RedStrikerScenario;
    attribute identity : RedStrikerIdentity;
    attribute transport : RedStrikerTransport;

    bind environment.parameters.initX_km = scenario.initX_km;
    bind environment.parameters.initY_km = scenario.initY_km;
    bind environment.parameters.initZ_km = scenario.initZ_km;
    bind autopilot_module.parameters.waypointProximity_km = scenario.waypointProximity_km;
    bind autopilot_module.parameters.waypointCount = scenario.waypointCount;
    bind autopilot_module.parameters.targetAirspeed_mps = scenario.targetAirspeed_mps;
    bind autopilot_module.parameters.waypointX_km = scenario.waypointX_km;
    bind autopilot_module.parameters.waypointY_km = scenario.waypointY_km;
    bind autopilot_module.parameters.waypointZ_km = scenario.waypointZ_km;
    bind rpr_state_source.parameters.reference_latitude_deg = identity.reference_latitude_deg;
    bind rpr_state_source.parameters.reference_longitude_deg = identity.reference_longitude_deg;
    bind rpr_state_source.parameters.reference_altitude_m = identity.reference_altitude_m;
    bind rpr_state_source.parameters.entity_site = identity.entity_site;
    bind rpr_state_source.parameters.entity_application = identity.entity_application;
    bind rpr_state_source.parameters.entity_entity = identity.entity_entity;
    bind rpr_state_source.parameters.marking_characters = identity.marking_characters;
    bind rpr_entity.parameters.transport = transport.transport;
    bind rpr_entity.parameters.bind_address = transport.bind_address;
    bind rpr_entity.parameters.peer_address = transport.peer_address;
  }

  part def BlueCas :> AircraftVariant {
    attribute experiment : BaselineExperiment;
    attribute scenario : BlueCasScenario;
    attribute identity : BlueCasIdentity;
    attribute transport : BlueCasTransport;

    bind environment.parameters.initX_km = scenario.initX_km;
    bind environment.parameters.initY_km = scenario.initY_km;
    bind environment.parameters.initZ_km = scenario.initZ_km;
    bind autopilot_module.parameters.waypointProximity_km = scenario.waypointProximity_km;
    bind autopilot_module.parameters.waypointCount = scenario.waypointCount;
    bind autopilot_module.parameters.targetAirspeed_mps = scenario.targetAirspeed_mps;
    bind autopilot_module.parameters.waypointX_km = scenario.waypointX_km;
    bind autopilot_module.parameters.waypointY_km = scenario.waypointY_km;
    bind autopilot_module.parameters.waypointZ_km = scenario.waypointZ_km;
    bind rpr_state_source.parameters.reference_latitude_deg = identity.reference_latitude_deg;
    bind rpr_state_source.parameters.reference_longitude_deg = identity.reference_longitude_deg;
    bind rpr_state_source.parameters.reference_altitude_m = identity.reference_altitude_m;
    bind rpr_state_source.parameters.entity_site = identity.entity_site;
    bind rpr_state_source.parameters.entity_application = identity.entity_application;
    bind rpr_state_source.parameters.entity_entity = identity.entity_entity;
    bind rpr_state_source.parameters.marking_characters = identity.marking_characters;
    bind rpr_entity.parameters.transport = transport.transport;
    bind rpr_entity.parameters.bind_address = transport.bind_address;
    bind rpr_entity.parameters.peer_address = transport.peer_address;
  }

  part def BlueBaseline :> AircraftVariant {
    attribute experiment : BaselineExperiment;
    attribute scenario : BlueBaselineScenario;
    attribute identity : BlueBaselineIdentity;
    attribute transport : BlueBaselineTransport;

    bind environment.parameters.initX_km = scenario.initX_km;
    bind environment.parameters.initY_km = scenario.initY_km;
    bind environment.parameters.initZ_km = scenario.initZ_km;
    bind autopilot_module.parameters.waypointProximity_km = scenario.waypointProximity_km;
    bind autopilot_module.parameters.waypointCount = scenario.waypointCount;
    bind autopilot_module.parameters.targetAirspeed_mps = scenario.targetAirspeed_mps;
    bind autopilot_module.parameters.waypointX_km = scenario.waypointX_km;
    bind autopilot_module.parameters.waypointY_km = scenario.waypointY_km;
    bind autopilot_module.parameters.waypointZ_km = scenario.waypointZ_km;
    bind rpr_state_source.parameters.reference_latitude_deg = identity.reference_latitude_deg;
    bind rpr_state_source.parameters.reference_longitude_deg = identity.reference_longitude_deg;
    bind rpr_state_source.parameters.reference_altitude_m = identity.reference_altitude_m;
    bind rpr_state_source.parameters.entity_site = identity.entity_site;
    bind rpr_state_source.parameters.entity_application = identity.entity_application;
    bind rpr_state_source.parameters.entity_entity = identity.entity_entity;
    bind rpr_state_source.parameters.marking_characters = identity.marking_characters;
    bind rpr_entity.parameters.transport = transport.transport;
    bind rpr_entity.parameters.bind_address = transport.bind_address;
    bind rpr_entity.parameters.peer_address = transport.peer_address;
  }

  // -- 3. application: how the runnable participant is started -------------
  // Process facts only. Non-FMU policy such as the waypoint frame lives here,
  // not on the aircraft model. The command names the variant to run; scenario,
  // identity and transport come from that variant's exported SSP.
  part def AircraftApplication :> Application {
    attribute participant : String;
    attribute roles : String = "aircraft";
    attribute command : String;
    attribute cwd : String = ".";
    attribute waypointFrame : String = "federation";
    attribute scenario : String;
    part launch : LaunchSpec;
  }

  part def RedInterceptorApp :> AircraftApplication {
    attribute participant : String = "red_interceptor";
    attribute command : String = "python scripts/run_instance_process.py --realtime --variant RedInterceptor";
    attribute scenario : String = "high_altitude_intercept";
    part launch : LaunchSpec {
      attribute mode : String = "supervised";
      attribute readiness : String = "port_bound";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 2;
      attribute after_process : String = "supervisor";
    }
  }

  part def RedStrikerApp :> AircraftApplication {
    attribute participant : String = "red_striker";
    attribute command : String = "python scripts/run_instance_process.py --realtime --variant RedStriker";
    attribute scenario : String = "deep_strike_penetration";
    part launch : LaunchSpec {
      attribute mode : String = "supervised";
      attribute readiness : String = "port_bound";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 2;
      attribute after_process : String = "supervisor";
    }
  }

  part def BlueCasApp :> AircraftApplication {
    attribute participant : String = "blue_cas";
    attribute command : String = "python scripts/run_instance_process.py --realtime --variant BlueCas";
    attribute scenario : String = "cas_multi_store_support";
    part launch : LaunchSpec {
      attribute mode : String = "supervised";
      attribute readiness : String = "port_bound";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 2;
      attribute after_process : String = "supervisor";
    }
  }

  part def BlueBaselineApp :> AircraftApplication {
    attribute participant : String = "blue_baseline";
    attribute command : String = "python scripts/run_instance_process.py --realtime --variant BlueBaseline";
    attribute scenario : String = "test_scenario";
    part launch : LaunchSpec {
      attribute mode : String = "supervised";
      attribute readiness : String = "port_bound";
      attribute timeout_s : Real = 30.0;
      attribute order : Integer = 2;
      attribute after_process : String = "supervisor";
    }
  }

  // -- 4. the join: one participant per aircraft ---------------------------
  // No `telemetryPort` attribute: the bind port lives in the variant transport
  // set, so the endpoint has exactly one owner.
  part def RedInterceptorParticipant {
    part aircraft : RedInterceptor;
    part application : RedInterceptorApp;
    port telemetry : RprBroadcast;
  }

  part def RedStrikerParticipant {
    part aircraft : RedStriker;
    part application : RedStrikerApp;
    port telemetry : RprBroadcast;
  }

  part def BlueCasParticipant {
    part aircraft : BlueCas;
    part application : BlueCasApp;
    port telemetry : RprBroadcast;
  }

  part def BlueBaselineParticipant {
    part aircraft : BlueBaseline;
    part application : BlueBaselineApp;
    port telemetry : RprBroadcast;
  }

  // -- 5. federation body --------------------------------------------------
  // Scalar participant usages only. The orchestrator, timing and the
  // architecture connects belong to the system plane.
  part def Federation {
    part red_interceptor : RedInterceptorParticipant;
    part red_striker : RedStrikerParticipant;
    part blue_cas : BlueCasParticipant;
    part blue_baseline : BlueBaselineParticipant;
  }
}
