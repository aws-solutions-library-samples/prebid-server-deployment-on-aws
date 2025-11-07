# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/prebid_datasync_constructs.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_prebid_datasync_constructs.py
###############################################################################


import uuid
from unittest.mock import MagicMock
from unit_tests.test_commons import mocked_common_services, FakeClass, reload_module

add_patch = [
    "prebid_server.prebid_datasync_constructs.super",
]


@mocked_common_services(
    add_patch=add_patch,
)
def test_efs_location():
    mock_def = MagicMock()
    reload_module("prebid_server.prebid_datasync_constructs")
    from prebid_server.prebid_datasync_constructs import EfsLocation

    EfsLocation.__init__(self=mock_def, scope=FakeClass(), id=str(uuid.uuid4()), prebid_vpc=mock_def,
                         efs_path="test/path", efs_ap=mock_def, efs_filesystem=mock_def)
    datasync_efs_location = EfsLocation._create_efs_location(self=mock_def)
    assert len(datasync_efs_location.method_calls) == 1


@mocked_common_services(
    add_patch=add_patch,
)
def test_efs_cleanup():
    mock_def = MagicMock(task="datasync-task", node=MagicMock(try_get_context=MagicMock(return_value="12345"),
                                                              try_find_child=MagicMock(return_value=True)),
                         bucket="s3-bucket")
    reload_module("prebid_server.prebid_datasync_constructs")
    from prebid_server.prebid_datasync_constructs import EfsCleanup

    EfsCleanup.__init__(
        self=mock_def,
        scope=FakeClass(),
        id=str(uuid.uuid4()),
        vpc=mock_def,
        efs_ap=mock_def,
        efs_filesystem=mock_def,
        report_bucket=mock_def,
        fargate_cluster_arn=mock_def,
        datasync_tasks={
            "logs": mock_def,
            "metrics": mock_def,
        },
        operational_metrics_layer=mock_def,
    )
