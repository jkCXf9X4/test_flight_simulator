// Entity plane of the aircraft federation: one part usage per aircraft
// process, its simulation identity, scenario, RPR endpoint and launch
// contract.
//
// The aircraft is not restated. `Aircraft::AircraftModel` is the real
// architecture imported from 3rd_party/airplane/architecture/aircraft.sysml;
// every entity composes it through `AircraftEntity`. The entity plane adds
// only what the federation needs per aircraft: identity, scenario, endpoint
// and launch. `PysosSoS::LaunchSpec` is the shared launch vocabulary shipped
// by pysos_sysml. Both imports are resolved by scripts/entity_manifest.py.
//
// `controlPort` is still required by the pysos_sysml subset, so it lowers a
// vestigial control endpoint; the aircraft no longer consumes control, and
// only PYSOS_TELEMETRY_PORT (the RPR bind port) is read at runtime.
package AircraftFederation {
  private import Aircraft::*;
  private import PysosSoS::*;

  part def AircraftEntity {
    part aircraft : AircraftModel;
  }

  part def Federation {
    part red_interceptor : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 1;
      attribute marking : String = "RED-1";
      attribute scenario : String = "high_altitude_intercept";
      attribute telemetryPort : Integer = 5510;
      attribute controlPort : Integer = 5511;
      attribute command : String = "python scripts/run_instance_process.py --realtime --stop-time 120 --offset-north-km 0 --offset-east-km 0 --waypoint-frame federation --reference-latitude-deg -2.957519 --reference-longitude-deg 39.232955 --reference-altitude-m 0 --entity-site 1 --entity-application 1 --entity 1 --marking RED-1";
      attribute cwd : String = ".";
      part launch : LaunchSpec {
        attribute mode : String = "supervised";
        attribute readiness : String = "port_bound";
        attribute timeout_s : Real = 30.0;
        attribute order : Integer = 2;
        attribute after_process : String = "supervisor";
      }
    }

    part red_striker : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 2;
      attribute marking : String = "RED-2";
      attribute scenario : String = "deep_strike_penetration";
      attribute telemetryPort : Integer = 5512;
      attribute controlPort : Integer = 5513;
      attribute command : String = "python scripts/run_instance_process.py --realtime --stop-time 120 --offset-north-km 0 --offset-east-km 5 --waypoint-frame federation --reference-latitude-deg -2.957519 --reference-longitude-deg 39.232955 --reference-altitude-m 0 --entity-site 1 --entity-application 1 --entity 2 --marking RED-2";
      attribute cwd : String = ".";
      part launch : LaunchSpec {
        attribute mode : String = "supervised";
        attribute readiness : String = "port_bound";
        attribute timeout_s : Real = 30.0;
        attribute order : Integer = 2;
        attribute after_process : String = "supervisor";
      }
    }

    part blue_cas : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 3;
      attribute marking : String = "BLUE-1";
      attribute scenario : String = "cas_multi_store_support";
      attribute telemetryPort : Integer = 5514;
      attribute controlPort : Integer = 5515;
      attribute command : String = "python scripts/run_instance_process.py --realtime --stop-time 120 --offset-north-km 0 --offset-east-km 10 --waypoint-frame federation --reference-latitude-deg -2.957519 --reference-longitude-deg 39.232955 --reference-altitude-m 0 --entity-site 1 --entity-application 1 --entity 3 --marking BLUE-1";
      attribute cwd : String = ".";
      part launch : LaunchSpec {
        attribute mode : String = "supervised";
        attribute readiness : String = "port_bound";
        attribute timeout_s : Real = 30.0;
        attribute order : Integer = 2;
        attribute after_process : String = "supervisor";
      }
    }

    part blue_baseline : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 4;
      attribute marking : String = "BLUE-2";
      attribute scenario : String = "test_scenario";
      attribute telemetryPort : Integer = 5516;
      attribute controlPort : Integer = 5517;
      attribute command : String = "python scripts/run_instance_process.py --realtime --stop-time 120 --offset-north-km 0 --offset-east-km 15 --waypoint-frame federation --reference-latitude-deg -2.957519 --reference-longitude-deg 39.232955 --reference-altitude-m 0 --entity-site 1 --entity-application 1 --entity 4 --marking BLUE-2";
      attribute cwd : String = ".";
      part launch : LaunchSpec {
        attribute mode : String = "supervised";
        attribute readiness : String = "port_bound";
        attribute timeout_s : Real = 30.0;
        attribute order : Integer = 2;
        attribute after_process : String = "supervisor";
      }
    }
  }
}
