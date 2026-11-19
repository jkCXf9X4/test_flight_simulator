def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: requires multicast on the local interface; set DIS_NETWORK_TESTS=1 to run",
    )
