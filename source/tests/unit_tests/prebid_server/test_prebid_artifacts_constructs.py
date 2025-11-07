# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/prebid_artifacts_constructs.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_prebid_artifacts_constructs.py
###############################################################################


import uuid
from unittest.mock import MagicMock
from unit_tests.test_commons import mocked_common_services, FakeClass, reload_module

@mocked_common_services(
    add_patch=[
        "prebid_server.prebid_artifacts_constructs.super",
    ]
)
def test_artifact_manager():

    mock_def = MagicMock()
    reload_module("prebid_server.prebid_artifacts_constructs")
    from prebid_server.prebid_artifacts_constructs import ArtifactsManager
    
    ArtifactsManager.__init__(
        self=mock_def,
        scope=FakeClass(),
        id=str(uuid.uuid4()))

    ArtifactsManager.create_artifact_bucket(self=mock_def)
    ArtifactsManager.create_custom_resource_lambda(self=mock_def)