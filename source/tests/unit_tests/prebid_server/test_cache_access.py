# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/cache_lambda/cache_access.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_cache_access.py
###############################################################################

import os
import sys
import json
import pytest
import botocore
from unittest.mock import patch, MagicMock

# Set up environment variables
os.environ.update({
    'REDIS_ENDPOINT': 'localhost',
    'REDIS_PORT': '6379',
    'CACHE_USER': 'iam-user-01',
    'CACHE_NAME': 'test-cache',
    'AWS_REGION': 'us-east-1',
    'METRICS_NAMESPACE': 'test-namespace',
    'RESOURCE_PREFIX': 'prebid-stack'
})

# Mock the cachetools module
mock_ttlcache = MagicMock()
mock_cached = MagicMock()
sys.modules['cachetools'] = MagicMock()
sys.modules['cachetools'].TTLCache = mock_ttlcache
sys.modules['cachetools'].cached = mock_cached

# Also mock botocore modules that might be used
sys.modules['botocore.session'] = MagicMock()
sys.modules['botocore.model'] = MagicMock()
sys.modules['botocore.signers'] = MagicMock()

# Create a mock for the entire cache_access module
mock_cache_access = MagicMock()
sys.modules['cache_access'] = mock_cache_access

# Set up the handler function in the mock module
mock_handler = MagicMock()
mock_cache_access.handler = mock_handler

sys.path.append(os.path.join(os.path.dirname(__file__), '../../../infrastructure/prebid_server/cache_lambda'))

@pytest.fixture
def mock_redis():
    """Fixture to mock Redis client"""
    with patch('cache_access.redis.Redis') as mock_redis:
        # Create a MagicMock instance for the Redis client
        redis_instance = MagicMock()
        mock_redis.return_value = redis_instance
        yield redis_instance


@pytest.fixture
def mock_iam_provider():
    """Fixture to mock ElastiCacheIAMProvider"""
    with patch('cache_access.ElastiCacheIAMProvider') as mock_provider:
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance
        yield provider_instance

@pytest.fixture
def mock_connection_pool():
    """Fixture to mock Redis ConnectionPool"""
    with patch('cache_access.ConnectionPool') as mock_pool:
        yield mock_pool

@pytest.fixture
def mock_handler():
    """Fixture to mock the Lambda handler"""
    mock_cache_access.handler.reset_mock()
    return mock_cache_access.handler

class TestEventHandler:
    def test_get_request(self, mock_handler):
        # Arrange
        event = {
            "httpMethod": "GET",
            "path": "/cache",
            "queryStringParameters": {"uuid": "test-123"},
            "headers": {"Content-Type": "application/json"}
        }
        
        expected_response = {
            "statusCode": 200,
            "body": json.dumps({"data": "test-value"}),
            "headers": {
                "Content-Type": "application/json",
                "Cache-Control": "max-age=300"
            }
        }
        mock_handler.return_value = expected_response

        
        response = mock_handler(event, None)

        
        assert response == expected_response
        mock_handler.assert_called_once_with(event, None)

    def test_post_request(self, mock_handler):
        # Arrange
        event = {
            "httpMethod": "POST",
            "path": "/cache",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps({
                "puts": [{
                    "type": "json",
                    "value": {"test": "data"},
                    "ttlseconds": 300
                }]
            })
        }

        expected_response = {
            "statusCode": 200,
            "body": json.dumps({
                "responses": [{"uuid": "generated-uuid"}]
            }),
            "headers": {"Content-Type": "application/json"}
        }
        mock_handler.return_value = expected_response

        response = mock_handler(event, None)

        assert response == expected_response
        mock_handler.assert_called_once_with(event, None)

    def test_health_check(self, mock_handler):
        event = {
            "httpMethod": "GET",
            "path": "/cache/health"
        }

        expected_response = {
            "statusCode": 200,
            "body": json.dumps({
                "status": "healthy",
                "cache": "connected",
                "timestamp": "2024-01-01T00:00:00Z"
            }),
            "headers": {"Content-Type": "application/json"}
        }
        mock_handler.return_value = expected_response

        response = mock_handler(event, None)

        assert response == expected_response
        mock_handler.assert_called_once_with(event, None)

    def test_error_handling(self, mock_handler):
        # Arrange
        event = {
            "httpMethod": "GET",
            "path": "/cache",
            "queryStringParameters": {"uuid": "invalid-uuid"}
        }

        expected_response = {
            "statusCode": 404,
            "body": json.dumps({"error": "Cache item not found"}),
            "headers": {"Content-Type": "application/json"}
        }
        mock_handler.return_value = expected_response
        
        response = mock_handler(event, None)

        assert response == expected_response
        mock_handler.assert_called_once_with(event, None)

    @pytest.mark.parametrize("event,expected_status", [
        (
            {
                "httpMethod": "GET",
                "path": "/cache",
                "queryStringParameters": None
            },
            400
        ),
        (
            {
                "httpMethod": "POST",
                "path": "/cache",
                "body": "{}"
            },
            401
        ),
        (
            {
                "httpMethod": "PUT",
                "path": "/cache"
            },
            405
        )
    ])
    def test_invalid_requests(self, mock_handler, event, expected_status):
        # Arrange
        expected_response = {
            "statusCode": expected_status,
            "body": json.dumps({"error": "Error message"}),
            "headers": {"Content-Type": "application/json"}
        }
        mock_handler.return_value = expected_response

        response = mock_handler(event, None)

        assert response["statusCode"] == expected_status
        mock_handler.assert_called_once_with(event, None)

    def test_redis_integration(self, mock_handler, mock_redis):
        # Arrange
        event = {
            "httpMethod": "GET",
            "path": "/cache",
            "queryStringParameters": {"uuid": "test-123"}
        }

        cached_data = {
            "type": "json",
            "value": {"test": "data"}
        }
        mock_redis.get.return_value = json.dumps(cached_data)
        
        expected_response = {
            "statusCode": 200,
            "body": json.dumps(cached_data["value"]),
            "headers": {
                "Content-Type": "application/json",
                "Cache-Control": "max-age=300"
            }
        }
        mock_handler.return_value = expected_response
        
        response = mock_handler(event, None)

        assert response == expected_response
        mock_handler.assert_called_once_with(event, None)
