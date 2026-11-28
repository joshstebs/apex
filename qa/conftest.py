import os

import pytest

from qa.offline import install_egress_guard


def pytest_sessionstart(session):
    install_egress_guard()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    executable = os.environ.get("APEX_CHROMIUM_EXECUTABLE")
    if executable:
        return {**browser_type_launch_args, "executable_path": executable}
    return browser_type_launch_args


def pytest_addoption(parser):
    parser.addoption("--commercial-root", default="static/commercial")
    parser.addoption("--commercial-snapshot", action="store_true")
    parser.addoption("--tenant-fixture-plugin")
