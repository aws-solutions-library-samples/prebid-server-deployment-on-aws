# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/prebid_glue_constructs.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_prebid_glue_constructs.py
###############################################################################

import uuid
from unittest.mock import MagicMock, Mock
from unit_tests.test_commons import mocked_common_services, FakeClass, reload_module


@mocked_common_services(
    add_patch=[
        "prebid_server.prebid_glue_constructs.super",
    ],
)
def test_s3_location():
    mock_def = MagicMock(bucket_arn="arn/bucket")
    reload_module("prebid_server.prebid_glue_constructs")
    from prebid_server.prebid_glue_constructs import S3Location

    S3Location.__init__(self=mock_def, scope=FakeClass(), s3_location_id=str(uuid.uuid4()), s3_bucket=mock_def)
    s3_location = S3Location._create_s3_location(self=mock_def, s3_location_id=str(uuid.uuid4()))
    assert len(s3_location.method_calls) == 2


@mocked_common_services(
    add_patch=[
        "prebid_server.prebid_artifacts_constructs.ArtifactsManager",
        "prebid_server.prebid_glue_constructs.super",
    ]
)
def test_glue_etl():
    mock_src_bucket = MagicMock(bucket_arn="test_arn/source_bucket")
    mock_artifact_bucket = MagicMock(bucket_arn="test_arn/artifactbucket")
    from prebid_server.prebid_glue_constructs import GlueEtl
    mock_def = Mock(spec=GlueEtl)
    mock_def.artifact_bucket = mock_artifact_bucket
    mock_def.source_bucket = mock_src_bucket
    reload_module("prebid_server.prebid_glue_constructs")

    mock_def.__init__(
        scope=FakeClass(),
        id=str(uuid.uuid4()),
        artifacts_construct=MagicMock(bucket=mock_artifact_bucket),
        script_file_name="filename",
    )

    mock_def._create_output_bucket()
    mock_def._create_glue_database()
    mock_def._create_glue_job()
    mock_def._create_glue_job_trigger()
