# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import requests
import os

CLOUDFRONT_ENDPOINT = os.environ["CLOUDFRONT_ENDPOINT"]

contentType = "application/json"
method = "GET"
auctionMethod = "POST"


def test_info_bidders():
    url = f"https://{CLOUDFRONT_ENDPOINT}/status"
    response = requests.request(method, url)
    assert response.status_code == 200


def test_status():
    url = f"https://{CLOUDFRONT_ENDPOINT}/info/bidders"
    response = requests.request(method, url)
    assert response.status_code == 200


def test_openrtb2_auction_adnuntius():
    body_data = {"id": "63EB4D07-C946-4B6B-8375-7893BBAEB022", "site": {"page": "prebid.org"}, "tmax": 1000, "imp": [
        {"id": "impression-id", "banner": {"format": [{"w": 980, "h": 240}, {"w": 980, "h": 360}]},
         "ext": {"adnuntius": {"auId": "abc123"}}}]}
    url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"
    response = requests.request(auctionMethod, url, json=body_data)
    assert response.status_code == 200


def test_openrtb2_auction_adot():
    body_data = {"id": "b967c495-adeb-4cf3-8f0a-0d86fa17aeb2", "app": {"id": "0", "name": "test-adot-integration",
                                                                       "publisher": {"id": "1", "name": "Test",
                                                                                     "domain": "test.com"},
                                                                       "bundle": "com.example.app", "paid": 0,
                                                                       "domain": "test.com",
                                                                       "page": "https://www.test.com/",
                                                                       "cat": ["IAB1", "IAB6", "IAB8", "IAB9", "IAB10",
                                                                               "IAB16", "IAB18", "IAB19", "IAB22"]},
                 "device": {
                     "ua": "Mozilla/5.0 (Linux; Android 7.0; SM-G925F Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/80.0.3987.132 Mobile Safari/537.36",
                     "make": "phone-make", "model": "phone-model", "os": "os", "osv": "osv", "ip": "0.0.0.0", # nosec B104
                     "ifa": "IDFA", "carrier": "WIFI", "language": "English",
                     "geo": {"zip": "75001", "country": "FRA", "type": 2, "lon": 48.2, "lat": 2.32, "accuracy": 100},
                     "ext": {"is_app": 1}, "connectiontype": 2, "devicetype": 4},
                 "user": {"id": "IDFA", "buyeruid": ""}, "imp": [{"id": "dec4147e-a63f-4d25-9fff-da9bfd05bd02",
                                                                  "banner": {"w": 320, "h": 50,
                                                                             "format": [{"w": 320, "h": 50}],
                                                                             "api": [1, 2, 5, 6, 7]},
                                                                  "bidfloorcur": "USD", "bidfloor": 0.1, "instl": 0,
                                                                  "ext": {"adot": {}}}], "cur": ["USD"],
                 "regs": {"ext": {"gdpr": 1}}, "at": 1}
    url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"
    response = requests.request(auctionMethod, url, json=body_data)
    assert response.status_code == 200


def test_openrtb2_auction_appnexus():
    body_data = {"id": "F0C018F4-BF4C-4B60-834E-22828F68E2EC", "site": {"page": "prebid.org"}, "tmax": 1000, "imp": [
        {"id": "some-impression-id", "banner": {"format": [{"w": 600, "h": 500}, {"w": 300, "h": 600}]},
         "ext": {"appnexus": {"placement_id": 13144370}}}]}
    url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"
    response = requests.request(auctionMethod, url, json=body_data)
    assert response.status_code == 200


def test_openrtb2_auction_pubmatic():
    body_data = {"id": "839FC0EB-3A15-4227-951A-469604E39912", "site": {"page": "prebid.org"}, "tmax": 1000, "imp": [
        {"id": "some-impression-id", "banner": {"format": [{"w": 300, "h": 250}, {"w": 300, "h": 600}]},
         "ext": {"pubmatic": {"publisherId": "156276", "adSlot": "pubmatic_test"}}}]}
    url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"
    response = requests.request(auctionMethod, url, json=body_data)
    assert response.status_code == 200


def test_openrtb2_auction_pubnative():
    body_data = {"id": "some-impression-id", "site": {"page": "https://good.site/url"}, "imp": [
        {"id": "test-imp-id", "banner": {"format": [{"w": 300, "h": 250}]},
         "ext": {"pubnative": {"zone_id": 1, "app_auth_token": "b620e282f3c74787beedda34336a4821"}}}],
                 "device": {"os": "android", "h": 700, "w": 375}, "tmax": 500, "test": 1}
    url = f"https://{CLOUDFRONT_ENDPOINT}/openrtb2/auction"
    response = requests.request(auctionMethod, url, json=body_data)
    assert response.status_code == 200
