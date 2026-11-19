package AircraftFederation {
  part def AircraftEntity {
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
      attribute command : String = "python scripts/run_instance_process.py";
      attribute cwd : String = ".";
    }

    part red_striker : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 2;
      attribute marking : String = "RED-2";
      attribute scenario : String = "deep_strike_penetration";
      attribute telemetryPort : Integer = 5512;
      attribute controlPort : Integer = 5513;
      attribute command : String = "python scripts/run_instance_process.py";
      attribute cwd : String = ".";
    }

    part blue_cas : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 3;
      attribute marking : String = "BLUE-1";
      attribute scenario : String = "cas_multi_store_support";
      attribute telemetryPort : Integer = 5514;
      attribute controlPort : Integer = 5515;
      attribute command : String = "python scripts/run_instance_process.py";
      attribute cwd : String = ".";
    }

    part blue_baseline : AircraftEntity {
      attribute site : Integer = 1;
      attribute application : Integer = 1;
      attribute entity : Integer = 4;
      attribute marking : String = "BLUE-2";
      attribute scenario : String = "test_scenario";
      attribute telemetryPort : Integer = 5516;
      attribute controlPort : Integer = 5517;
      attribute command : String = "python scripts/run_instance_process.py";
      attribute cwd : String = ".";
    }
  }
}
