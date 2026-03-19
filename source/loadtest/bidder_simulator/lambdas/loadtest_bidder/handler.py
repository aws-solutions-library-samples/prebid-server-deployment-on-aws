# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
import random
import os
import time
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, _):
    try:
        BID_RESPONSES_DELAY_PERCENTAGE = float(os.environ['BID_RESPONSES_DELAY_PERCENTAGE'])
        BID_RESPONSES_TIMEOUT_PERCENTAGE = float(os.environ['BID_RESPONSES_TIMEOUT_PERCENTAGE'])

        A_BID_RESPONSE_DELAY_PROBABILITY = float(os.environ['A_BID_RESPONSE_DELAY_PROBABILITY'])
        A_BID_RESPONSE_TIMEOUT_PROBABILITY = float(os.environ['A_BID_RESPONSE_TIMEOUT_PROBABILITY'])
    except Exception as e:
        logger.exception("Fail to read environment variables", e)
        raise e
    
    tmax_in_millis = 1000
    tmax_in_seconds = tmax_in_millis * 0.001

    if random.random() < BID_RESPONSES_DELAY_PERCENTAGE * A_BID_RESPONSE_DELAY_PROBABILITY:
        logger.info("Simulate delayed Bid Response")
        delay_in_seconds = random.random() * tmax_in_seconds
        time.sleep(delay_in_seconds)

    if random.random() < BID_RESPONSES_TIMEOUT_PERCENTAGE * A_BID_RESPONSE_TIMEOUT_PROBABILITY:
        logger.info("Simulate timeout scenario")
        timeout = 2 * tmax_in_seconds
        time.sleep(timeout)

    bid_response = get_bidder_response("bid_response.json")
    
    return create_alb_response(200, bid_response)


def create_alb_response(status_code, body):
    """
    Create response in ALB format.
    
    ALB requires:
    - statusCode (int)
    - statusDescription (string)
    - headers (dict)
    - body (string)
    - isBase64Encoded (bool)
    """
    return {
        'statusCode': status_code,
        'statusDescription': f'{status_code} {"OK" if status_code == 200 else "Error"}',
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(body),
        'isBase64Encoded': False
    }

def get_bidder_response(bid_response_json):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    bid_response_path = os.path.join(dir_path, bid_response_json)

    with open(bid_response_path, 'r') as file:
        return json.load(file)