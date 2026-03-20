# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import uuid
import time
import requests
import pytest
from conftest import SKIP_REASON, TEST_REGIONS, logging

logger = logging.getLogger(__name__)

CLOUDFRONT_ENDPOINT = os.environ["CLOUDFRONT_ENDPOINT"]
url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"



@pytest.mark.run(order=1)
def test_auction_request():
    random_id = uuid.uuid4().hex

    auction_request = {
        "id": random_id,
        "imp": [
            {
                "id": "banner_imp_1",
                "banner": {"w": 300, "h": 250},
                "ext": {
                    "amt": {
                        "placementId": "placement_1",
                        "bidFloor": 1,
                        "bidCeiling": 100000
                    }
                }
            },
            {
                "id": "banner_imp_2",
                "banner": {"w": 300, "h": 250},
                "ext": {
                    "amt": {
                        "placementId": "placement_2",
                        "bidFloor": 1,
                        "bidCeiling": 50
                    }
                }
            }
        ],
        "device": {
            "pxratio": 4.2,
            "dnt": 2,
            "language": "en",
            "ifa": "ifaId"
        },
        "site": {
            "page": "prebid.org",
            "publisher": {
                "id": "publisherId"
            }
        },
        "at": 1,
        "tmax": 5000,
        "cur": [
            "USD"
        ],
        "source": {
            "fd": 1,
            "tid": "tid"
        },
        "ext": {
            "prebid": {
                "targeting": {
                    "pricegranularity": {
                        "precision": 2,
                        "ranges": [
                            {
                                "max": 20,
                                "increment": 0.1
                            }
                        ]
                    }
                },
                "cache": {
                    "bids": {}
                },
                "auctiontimestamp": 1000
            }
        },
        "regs": {"ext": {"gdpr": 0}}
    }

    time.sleep(5)
    auction_resonse = requests.post(url, json=auction_request)
    logger.info(auction_resonse)
    assert auction_resonse.status_code == 200
    logger.info(auction_resonse.json())

    if (
        os.environ.get("AMT_ADAPTER_ENABLED") and 
        os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT") and
        os.environ["TEST_AWS_REGION"] in TEST_REGIONS
    ):
        assert auction_resonse.json()["id"] == random_id
        assert auction_resonse.json()["cur"] == "USD"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["impid"] == "banner_imp_1"
        assert auction_resonse.json()["seatbid"][0]["bid"][1]["impid"] == "banner_imp_2"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["price"] == 3.25
        assert auction_resonse.json()["seatbid"][0]["bid"][1]["price"] == 2.75
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["crid"] == "banner_creative_1"
        assert auction_resonse.json()["seatbid"][0]["bid"][1]["crid"] == "banner_creative_2"
        assert auction_resonse.json()["seatbid"][0]["seat"] == "amt"

    else:
        logger.info(SKIP_REASON)
        logger.info("Skipping detailed test_auction_request as AMT_ADAPTER_ENABLED or AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT is not set")



@pytest.mark.run(order=2)
def test_outstream_video_auction_request():
    random_id = uuid.uuid4().hex

    auction_request = {
        "id": random_id,
        "imp": [
            {
                "id": "outstream_video_imp_1",
                "video": {
                    "mimes": ["video/mp4"],
                    "protocols": [1, 2, 3, 4, 5, 6, 7, 8],
                    "w": 360,
                    "h": 360,
                    "placement": 3
                },
                "ext": {
                    "amt": {
                        "placementId": "placement_1",
                        "bidFloor": 1,
                        "bidCeiling": 100000
                    }
                }
            }
        ],
        "device": {
            "pxratio": 4.2,
            "dnt": 2,
            "language": "en",
            "ifa": "ifaId"
        },
        "site": {
            "page": "prebid.org",
            "publisher": {
                "id": "publisherId"
            }
        },
        "at": 1,
        "tmax": 5000,
        "cur": ["USD"],
        "source": {
            "fd": 1,
            "tid": "tid"
        },
        "ext": {
            "prebid": {
                "targeting": {
                    "pricegranularity": {
                        "precision": 2,
                        "ranges": [
                            {
                                "max": 20,
                                "increment": 0.1
                            }
                        ]
                    }
                },
                "cache": {
                    "bids": {},
                    "vastxml": {}
                },
                "auctiontimestamp": 1000
            }
        },
        "regs": {"ext": {"gdpr": 0}}
    }

    time.sleep(5)
    auction_resonse = requests.post(url, json=auction_request)
    logger.info(auction_resonse)
    assert auction_resonse.status_code == 200
    logger.info(auction_resonse.json())

    if (
        os.environ.get("AMT_ADAPTER_ENABLED") and
        os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT") and
        os.environ["TEST_AWS_REGION"] in TEST_REGIONS
    ):
        assert auction_resonse.json()["id"] == random_id
        assert auction_resonse.json()["cur"] == "USD"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["impid"] == "outstream_video_imp_1"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["price"] == 12.50
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["crid"] == "outstream_video_creative_1"
        assert auction_resonse.json()["seatbid"][0]["seat"] == "amt"
        assert "VAST" in auction_resonse.json()["seatbid"][0]["bid"][0].get("adm", "")

    else:
        logger.info(SKIP_REASON)
        logger.info("Skipping detailed test_outstream_video_auction_request as AMT_ADAPTER_ENABLED or AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT is not set")


@pytest.mark.run(order=3)
def test_instream_video_auction_request():
    random_id = uuid.uuid4().hex

    auction_request = {
        "id": random_id,
        "imp": [
            {
                "id": "instream_video_imp_1",
                "video": {
                    "mimes": ["video/mp4"],
                    "protocols": [1, 2, 3, 4, 5, 6, 7, 8],
                    "w": 640,
                    "h": 480,
                    "playbackmethod": [2],
                    "placement": 1,
                    "skip": 1
                },
                "ext": {
                    "amt": {
                        "placementId": "placement_1",
                        "bidFloor": 1,
                        "bidCeiling": 100000
                    }
                }
            }
        ],
        "device": {
            "pxratio": 4.2,
            "dnt": 2,
            "language": "en",
            "ifa": "ifaId"
        },
        "site": {
            "page": "prebid.org",
            "publisher": {
                "id": "publisherId"
            }
        },
        "at": 1,
        "tmax": 5000,
        "cur": ["USD"],
        "source": {
            "fd": 1,
            "tid": "tid"
        },
        "ext": {
            "prebid": {
                "targeting": {
                    "pricegranularity": {
                        "precision": 2,
                        "ranges": [
                            {
                                "max": 25,
                                "increment": 0.1
                            }
                        ]
                    }
                },
                "cache": {
                    "bids": {},
                    "vastxml": {}
                },
                "auctiontimestamp": 1000
            }
        },
        "regs": {"ext": {"gdpr": 0}}
    }

    time.sleep(5)
    auction_resonse = requests.post(url, json=auction_request)
    logger.info(auction_resonse)
    assert auction_resonse.status_code == 200
    logger.info(auction_resonse.json())

    if (
        os.environ.get("AMT_ADAPTER_ENABLED") and
        os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT") and
        os.environ["TEST_AWS_REGION"] in TEST_REGIONS
    ):
        assert auction_resonse.json()["id"] == random_id
        assert auction_resonse.json()["cur"] == "USD"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["impid"] == "instream_video_imp_1"
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["price"] == 22.50
        assert auction_resonse.json()["seatbid"][0]["bid"][0]["crid"] == "instream_video_creative_1"
        assert auction_resonse.json()["seatbid"][0]["seat"] == "amt"
        assert "VAST" in auction_resonse.json()["seatbid"][0]["bid"][0].get("adm", "")

    else:
        logger.info(SKIP_REASON)
        logger.info("Skipping detailed test_instream_video_auction_request as AMT_ADAPTER_ENABLED or AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT is not set")
