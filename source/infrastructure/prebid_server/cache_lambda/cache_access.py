# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
AWS Lambda function that implements a caching service for Prebid Server.

API Endpoints:
    - POST /cache: Store items in cache
    - GET /cache?uuid={uuid}: Retrieve cached item
    - GET /cache/health: Check service health status

Environment Variables Required:
    - REDIS_ENDPOINT: Redis server hostname
    - REDIS_PORT: Redis server port
    - CACHE_USER: Username for IAM authentication
    - CACHE_NAME: Name of the ElastiCache instance
    - AWS_REGION: AWS region where the cache is deployed
"""


import os
import json
import uuid
import logging
from datetime import datetime, UTC
import redis
from redis import ConnectionPool

from typing import Tuple, Union
from urllib.parse import ParseResult, urlencode, urlunparse
import botocore.session
import redis
from botocore.model import ServiceId
from botocore.signers import RequestSigner
from cachetools import TTLCache, cached
import uuid

from cloudwatch_metrics import metrics
metrics_namespace = os.environ["METRICS_NAMESPACE"]
resource_prefix = os.environ["RESOURCE_PREFIX"]

redis_host = os.environ["REDIS_ENDPOINT"]
redis_port = os.environ["REDIS_PORT"]
cache_user = os.environ["CACHE_USER"]
cache_name = os.environ["CACHE_NAME"]
region = os.environ["AWS_REGION"]

ALLOWED_TYPES = {"xml", "json"}
DEFAULT_TTL_SECONDS = 300
TTL_MAX_SECONDS = 3600

logger = logging.getLogger()
logger.setLevel(logging.INFO)

metrics_client = metrics.Metrics(metrics_namespace, resource_prefix, logger)

class ElastiCacheIAMProvider(redis.CredentialProvider):
    def __init__(self, user, cache_name, region="us-east-1"):
        self.user = user
        self.cache_name = cache_name
        self.is_serverless = True
        self.region = region

        session = botocore.session.get_session()
        self.request_signer = RequestSigner(
            ServiceId("elasticache"),
            self.region,
            "elasticache",
            "v4",
            session.get_credentials(),
            session.get_component("event_emitter"),
        )

    # Generated IAM tokens are valid for 15 minutes
    @cached(cache=TTLCache(maxsize=128, ttl=900))
    def get_credentials(self) -> Union[Tuple[str], Tuple[str, str]]:
        query_params = {"Action": "connect", "User": self.user}
        if self.is_serverless:
            query_params["ResourceType"] = "ServerlessCache"
        url = urlunparse(
            ParseResult(
                scheme="https",
                netloc=self.cache_name,
                path="/",
                query=urlencode(query_params),
                params="",
                fragment="",
            )
        )
        signed_url = self.request_signer.generate_presigned_url(
            {"method": "GET", "url": url, "body": {}, "headers": {}, "context": {}},
            operation_name="connect",
            expires_in=900,
            region_name=self.region,
        )
        # RequestSigner only seems to work if the URL has a protocol, but
        # Elasticache only accepts the URL without a protocol
        # So strip it off the signed URL before returning
        return (self.user, signed_url.removeprefix("https://"))


creds_provider = ElastiCacheIAMProvider(user=cache_user, cache_name=cache_name, region=region)

# Create a global connection pool
redis_pool = ConnectionPool(
    host=redis_host, 
    port=int(redis_port),
    credential_provider=creds_provider,
    decode_responses=True,
    connection_class=redis.SSLConnection,
    ssl_cert_reqs="none",
    socket_timeout=5,  # Reduce timeout for faster failure detection, cold start issue
    socket_keepalive=True,
    retry_on_timeout=True,
)

redis_client = redis.Redis(connection_pool=redis_pool)

def handler(event, _):
    """
    Main Lambda handler that routes HTTP requests to appropriate handlers.

    Args:
        event: API Gateway Lambda proxy event
        _: Lambda context object (unused)

    Returns:
        dict: HTTP response based on the request path and method
    """
    try:
        path = event["path"]

        if path == "/cache/health":
            return handle_health_check()

        if path != "/cache":
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Not found"})
            }

        http_method = event["httpMethod"]

        if http_method == "GET":
            return handle_get_request(event)

        if http_method == "POST":
            return handle_post_request(event)

        return {
            "statusCode": 405,
            "body": json.dumps({"error": "Method not allowed"})
        }

    except Exception as e:
        logger.error("Unexpected error", exc_info=e)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }


def handle_health_check():
    """
    Returns health status of the service and Redis cache connection.
    
    Returns:
        dict: HTTP response with health status, cache status, and timestamp
    """
    redis_client.ping()
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "healthy",
                "cache": "connected",
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            }
        )
    }


def handle_get_request(event):
    """
    Retrieves cached value from Cache using UUID parameter.

    Args:
        event: Lambda event containing UUID query parameter

    Returns:
        dict: HTTP response with cached value or error message
    """
    key = event.get("queryStringParameters", {}).get("uuid")
    if not key:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing uuid parameter"})
        }

    try:
        value = redis_client.get(key)
        if value is None:
            metrics_client.put_metrics_count_value_1(
                metric_name="GetNotFound")
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Uuid not found"})
            }

        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError as e:
                logger.error("Unicode decode error", exc_info=e)
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "Invalid encoding in cached value"})
                }

        try:
            parsed_value = json.loads(value)
            if not isinstance(parsed_value, dict) \
                    or "type" not in parsed_value \
                    or "value" not in parsed_value:
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "Invalid cached value structure"})
                }

            remaining_ttl = redis_client.ttl(key)
            
            metrics_client.put_metrics_count_value_1(
                metric_name="GetSuccess")
            return {
                "statusCode": 200,
                "headers": {
                    # https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Expiration.html#expiration-individual-objects
                    "Cache-Control": f"max-age={remaining_ttl}",
                    "Content-Type": f"application/{parsed_value['type']}"
                },
                "body": json.dumps(parsed_value["value"])
            }
        except json.JSONDecodeError:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Invalid cached value format"})
            }

    except redis.RedisError as e:
        logger.error("Redis error", exc_info=e)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Cache error"})
        }


def validate_post_body(request_data):
    """
    Validates the body for POST requests.

    Returns:
        bool: True if body is valid, False otherwise
    """
    if not isinstance(request_data, dict):
        return False
    if "puts" not in request_data:
        return False
    if not isinstance(request_data["puts"], list):
        return False
    if not validate_post_puts(request_data["puts"]):
        return False

    return True


def validate_post_puts(puts):
    for item in puts:
        if not isinstance(item, dict):
            return False
        if "type" not in item or "value" not in item:
            return False
        if item["type"] not in ALLOWED_TYPES:
            return False
        if not validate_post_ttlseconds(item.get("ttlseconds", 0)):
            return False

    return True


def validate_post_ttlseconds(ttlseconds):
    try:
        ttl = int(ttlseconds)
        if ttl <= 0 or ttl > TTL_MAX_SECONDS:
            return False
    except ValueError:
        return False

    return True


def handle_post_request(event):
    """
    Handles POST requests to store items in Redis cache.

    Args:
        event: Lambda event

    Returns:
        dict: HTTP response with generated UUIDs or error message
    """
    body = event.get("body")
    if not body:
        metrics_client.put_metrics_count_value_1(
            metric_name="PostFail")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing request body"})
        }

    request_data = json.loads(body)
    if not validate_post_body(request_data):
        metrics_client.put_metrics_count_value_1(
            metric_name="PostFail")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid request body"})
        }

    try:
        responses = []
        item_count = len(request_data["puts"])
        metrics_client.put_metrics_count_value_custom(
            metric_name="PostCount", value=item_count)
        
        for item in request_data["puts"]:
            # Handle optional TTL
            ttlseconds = int(item.get("ttlseconds", DEFAULT_TTL_SECONDS))
            if ttlseconds <= 0 or ttlseconds > TTL_MAX_SECONDS:
                ttlseconds = DEFAULT_TTL_SECONDS

            # Generate UUID and store in Redis
            key = str(uuid.uuid4())
            cache_value = {
                "type": item["type"].lower(),
                "value": item["value"]
            }

            # Store in Redis with TTL
            redis_client.setex(
                key,
                ttlseconds,
                json.dumps(cache_value)
            )
            responses.append({"uuid": key})

        metrics_client.put_metrics_count_value_1(
            metric_name="PostSuccess")
        return {
            "statusCode": 200,
            "body": json.dumps({"responses": responses})
        }

    except redis.RedisError as e:
        logger.error("Redis error", exc_info=e)
        
        metrics_client.put_metrics_count_value_1(
            metric_name="PostFail")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Cache error"})
        }
