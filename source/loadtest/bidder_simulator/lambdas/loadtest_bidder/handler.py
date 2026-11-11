# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
import random
import os
import time
import json
import re

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Static creative assets per imp type — keyed by detected ad format
BANNER_CREATIVES = [
    {
        "crid": "banner_creative_1",
        "adm": "<a href=\"https://www.amazon.com\" target=\"_blank\"><img src=\"/assets/banners/CarAd-4.jpg\" width=\"300\" height=\"250\"></a>",
        "w": 300, "h": 250, "price": 3.25,
    },
    {
        "crid": "banner_creative_2",
        "adm": "<iframe src='/assets/banners/Soccer.jpeg' width='300' height='250'></iframe>",
        "w": 300, "h": 250, "price": 2.75,
    },
]

VIDEO_CREATIVES = [
    {
        "crid": "video_creative_outstream",
        "adm": "<VAST version='3.0'><Ad id='12345'><InLine><AdSystem>Test Ad System</AdSystem><AdTitle>Basic Outstream</AdTitle><Creatives><Creative><Linear><Duration>00:00:05</Duration><VideoClicks><ClickThrough><![CDATA[https://www.amazon.com]]></ClickThrough></VideoClicks><MediaFiles><MediaFile delivery='progressive' type='video/mp4' width='360' height='360' bitrate='500'><![CDATA[/assets/videos/outstream/creative_2_360x360_20s.mp4]]></MediaFile></MediaFiles></Linear></Creative></Creatives></InLine></Ad></VAST>",
        "w": 360, "h": 360, "price": 12.50, "dur": 5,
    },
    {
        "crid": "video_creative_instream_preroll",
        "adm": "<VAST version='3.0'><Ad id='67890'><InLine><AdSystem>Test Ad System</AdSystem><AdTitle>Basic Instream Preroll</AdTitle><Creatives><Creative><Linear><Duration>00:00:15</Duration><VideoClicks><ClickThrough><![CDATA[https://www.amazon.com]]></ClickThrough></VideoClicks><MediaFiles><MediaFile delivery='progressive' type='video/mp4' width='360' height='360' bitrate='500'><![CDATA[/assets/videos/outstream/20250317_1119_Beekeeper_Harmony.mp4]]></MediaFile></MediaFiles></Linear></Creative></Creatives></InLine></Ad></VAST>",
        "w": 360, "h": 360, "price": 22.50, "dur": 15,
    },
    {
        "crid": "video_creative_instream_midroll",
        "adm": "<VAST version='3.0'><Ad id='67891'><InLine><AdSystem>Test Ad System</AdSystem><AdTitle>Basic Instream Midroll</AdTitle><Creatives><Creative><Linear><Duration>00:00:30</Duration><VideoClicks><ClickThrough><![CDATA[https://www.amazon.com]]></ClickThrough></VideoClicks><MediaFiles><MediaFile delivery='progressive' type='video/mp4' width='360' height='360' bitrate='500'><![CDATA[/assets/videos/outstream/20250317_1119_Beekeeper_Harmony.mp4]]></MediaFile></MediaFiles></Linear></Creative></Creatives></InLine></Ad></VAST>",
        "w": 360, "h": 360, "price": 35.00, "dur": 30,
    },
]


def lambda_handler(event, _):
    try:
        BID_RESPONSES_DELAY_PERCENTAGE = float(os.environ['BID_RESPONSES_DELAY_PERCENTAGE'])
        BID_RESPONSES_TIMEOUT_PERCENTAGE = float(os.environ['BID_RESPONSES_TIMEOUT_PERCENTAGE'])

        A_BID_RESPONSE_DELAY_PROBABILITY = float(os.environ['A_BID_RESPONSE_DELAY_PROBABILITY'])
        A_BID_RESPONSE_TIMEOUT_PROBABILITY = float(os.environ['A_BID_RESPONSE_TIMEOUT_PROBABILITY'])

        DEMO_CLOUDFRONT_DOMAIN = os.environ.get('DEMO_CLOUDFRONT_DOMAIN', '')
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

    # Parse incoming bid request to build a matching response
    bid_request = parse_bid_request(event)
    if bid_request:
        bid_response = build_dynamic_response(bid_request)
    else:
        # Fallback to static response if request can't be parsed
        bid_response = get_bidder_response("bid_response.json")

    # Replace relative URLs with CloudFront domain
    if DEMO_CLOUDFRONT_DOMAIN:
        bid_response = replace_urls_with_cloudfront(bid_response, DEMO_CLOUDFRONT_DOMAIN)

    return create_alb_response(200, bid_response)


def parse_bid_request(event):
    """Extract the OpenRTB bid request from the ALB event body."""
    try:
        body = event.get('body', '')
        if not body:
            return None
        return json.loads(body)
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Could not parse bid request body, falling back to static response")
        return None


def build_dynamic_response(bid_request):
    """
    Build an OpenRTB bid response that matches the incoming request.

    - Echoes back the correct impid for each impression
    - Includes dur on video bids so the /openrtb2/video pod endpoint can slot them
    - Selects appropriate creative based on imp type (banner vs video)
    - Matches banner bid dimensions to the impression's requested sizes
    """
    request_id = bid_request.get('id', 'response_id')
    imps = bid_request.get('imp', [])

    bids = []
    banner_idx = 0
    video_idx = 0

    for imp in imps:
        imp_id = imp.get('id', '')
        is_video = 'video' in imp

        if is_video:
            # Pick a video creative cycling through the list
            creative = VIDEO_CREATIVES[video_idx % len(VIDEO_CREATIVES)]
            video_idx += 1

            # Determine appropriate dur based on imp video constraints
            min_dur = imp.get('video', {}).get('minduration', 5)
            max_dur = imp.get('video', {}).get('maxduration', 30)

            # Pick the creative's dur if it fits, otherwise clamp to max
            dur = min(max(creative['dur'], min_dur), max_dur)

            bid = {
                "id": f"bid_{imp_id}",
                "impid": imp_id,
                "price": creative['price'],
                "adm": creative['adm'],
                "adomain": ["amazon.com"],
                "crid": creative['crid'],
                "w": creative['w'],
                "h": creative['h'],
                "dur": dur,
            }
        else:
            # Banner
            creative = BANNER_CREATIVES[banner_idx % len(BANNER_CREATIVES)]
            banner_idx += 1

            # Match bid dimensions to the impression's requested sizes
            banner = imp.get('banner', {})
            formats = banner.get('format', [])
            if formats:
                bid_w = formats[0].get('w', creative['w'])
                bid_h = formats[0].get('h', creative['h'])
            else:
                bid_w = banner.get('w', creative['w'])
                bid_h = banner.get('h', creative['h'])

            bid = {
                "id": f"bid_{imp_id}",
                "impid": imp_id,
                "price": creative['price'],
                "adm": creative['adm'],
                "adomain": ["amazon.com"],
                "crid": creative['crid'],
                "w": bid_w,
                "h": bid_h,
            }

        bids.append(bid)

    return {
        "id": request_id,
        "seatbid": [{"bid": bids}] if bids else [],
    }


def replace_urls_with_cloudfront(bid_response, cloudfront_domain):
    """
    Replace all relative URLs (starting with /assets/) with full CloudFront URLs.

    Args:
        bid_response: The bid response dictionary
        cloudfront_domain: The CloudFront domain name (e.g., d1234567890abc.cloudfront.net)

    Returns:
        Modified bid response with updated URLs
    """
    bid_response_str = json.dumps(bid_response)

    # Replace relative URLs like /assets/... with https://cloudfront_domain/assets/...
    # This handles both quoted URLs in JSON and URLs within CDATA sections
    bid_response_str = re.sub(
        r'(["\']|<!\[CDATA\[)(/assets/[^"\'>\]]+)',
        rf'\1https://{cloudfront_domain}\2',
        bid_response_str
    )

    return json.loads(bid_response_str)


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
    """Load static fallback response from file."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    bid_response_path = os.path.join(dir_path, bid_response_json)

    with open(bid_response_path, 'r') as file:
        return json.load(file)
