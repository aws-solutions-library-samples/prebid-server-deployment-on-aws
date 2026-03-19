# Load Test

This document provides instructions for setting up and running load tests on a Prebid Server on AWS deployment using a simulated bidding server and the AMT bid adapter. The load test helps evaluate the performance and stability of the Prebid Server under simulated auction conditions.

## Quick Start

Deploy the solution with the bidder simulator using the `deploy.sh` script:

```bash
./deploy.sh --deploy-bidding-simulator --profile <your-profile> --region <your-region>
```

This automatically:
- Deploys the bidder simulator stack with CloudFront, ALB, and Lambda
- Copies AMT bidder files to the Docker build context
- Includes AMT bidder files in the Docker build
- Configures the AMT adapter in Prebid Server
- Sets up environment variables for the simulator endpoint

## Test Auction Requests

After deployment, use the provided test script to validate the setup:

```bash
cd source/loadtest
python test-auction-amt.py --endpoint <your-cloudfront-dns-name-without-https>
```

### Example Output

```
=== Auction Request ===
{
  "id": "test-auction-123",
  "imp": [
    {
      "id": "imp1",
      "banner": {"w": 300, "h": 250},
      "ext": {
        "amt": {
          "placementId": "test-placement",
          "bidFloor": 1.0,
          "bidCeiling": 100.0
        }
      }
    }
  ],
  ...
}

=== Auction Response ===
{
  "id": "test-auction-123",
  "seatbid": [
    {
      "bid": [
        {
          "id": "bid_1",
          "impid": "imp1",
          "price": 5.55,
          "crid": "creative-123"
        }
      ],
      "seat": "amt"
    }
  ],
  ...
}

✓ Auction successful - received 1 bid(s)
```

### Test Script Options

```bash
python test-auction-amt.py --help
```

### Example JSON Files

Example request and response files are provided in `source/loadtest/amt-bidder/`:
- `test-auction-amt-request.json` - Example request format
- `test-auction-amt-response.json` - Example expected response format

## Deployment Options

### Deploy with Analytics

To enable analytics logging during load testing:

```bash
./deploy.sh --deploy-bidding-simulator --enable-log-analytics --profile <your-profile> --region <your-region>
```

### Verify Deployment

After deployment completes:
1. Check CloudFormation console for the `BiddingServerSimulator` stack
2. Note the simulator endpoint URL from the stack outputs
3. Verify the Prebid Server ECS tasks have the correct environment variables:
   - `AMT_ADAPTER_ENABLED=true`
   - `AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT=<simulator-url>`
   - `LOG_ANALYTICS_ENABLED=true` (if analytics enabled)

## Bidder Simulator Configuration

The bidder simulator uses Application Load Balancer (ALB), and Lambda to respond to bid requests from Prebid Server. This architecture enables both direct internet access and RTB Fabric integration.

### Bidder Type Selection

Select the bidder type during deployment:

```bash
cd source/loadtest/bidder_simulator

# For load testing
cdk deploy
```

### Bid Response Format

The bid response follows the [OpenRTB specification](https://www.iab.com/wp-content/uploads/2016/03/OpenRTB-API-Specification-Version-2-5-FINAL.pdf#page=32):

```json
{
  "id": "request_id",
  "seatbid": [
    {
      "bid": [
        {
          "id": "bid_id_1",
          "impid": "imp_id_1",
          "price": 3.33,
          "crid": "creativeId"
        },
        {
          "id": "bid_id_2",
          "impid": "imp_id_1",
          "price": 5.55,
          "crid": "creativeId"
        }
      ]
    }
  ]
}
```

### Simulate Bid Response Delays

Configure bid response delays using CloudFormation parameters:
- `BID_RESPONSES_DELAY_PERCENTAGE`: Portion of requests that will experience delays (0.0 to 1.0)
- `A_BID_RESPONSE_DELAY_PROBABILITY`: Likelihood of an individual bid response being delayed (0.0 to 1.0)

By default, delayed bid response simulation is disabled.

### Simulate Bid Response Timeouts

Configure bid response timeouts using CloudFormation parameters:
- `BID_RESPONSES_TIMEOUT_PERCENTAGE`: Portion of requests that will experience timeouts (0.0 to 1.0)
- `A_BID_RESPONSE_TIMEOUT_PROBABILITY`: Likelihood of an individual bid response timing out (0.0 to 1.0)

By default, timeout simulation is disabled.

## Load Testing with JMeter

### Update or Create Test Plan

1. Download and install [Apache JMeter](https://jmeter.apache.org/download_jmeter.cgi)
2. Open the example test plan: `source/loadtest/jmx/prebid_server_test_plan_using_amt_adapter.jmx`
3. Update the `url` in User Defined Variables with your CloudFront endpoint
4. Optional: Update HTTP Request settings under Thread Group
5. Start the tests to verify proper operation

### Distributed Load Testing (DLT)

Use the [Distributed Load Testing on AWS](https://aws.amazon.com/solutions/implementations/distributed-load-testing-on-aws/) solution to automate load tests:

1. Follow the DLT implementation guide to set up the solution
2. Upload your JMeter test plan to start load tests

## Programmatic Testing

Use the provided `test-auction-amt.py` script:

```bash
cd source/loadtest
python test-auction-amt.py --endpoint <your-cloudfront-endpoint-dns-name-without-https>
```

The script provides:
- Automatic request formatting
- Response validation
- Clear success/failure indicators
- Detailed output of bid information
