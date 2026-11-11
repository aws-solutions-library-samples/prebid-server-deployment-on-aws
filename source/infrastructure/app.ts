#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { App } from "aws-cdk-lib";
import { PrebidServerStack } from "./lib/prebid_server/prebid-server-stack";
import { isContextTrue } from "./lib/shared/stack-constants";
import { BidderSimulatorStack } from "./lib/bidder_simulator/bidder-simulator-stack";

const app = new App();

// Whether to synthesize the BidderSimulatorStack template is a build-time
// decision read from CDK context. All runtime configuration (log analytics,
// connectivity) is supplied at deploy time via CloudFormation parameters —
// there are no cross-stack references. deploy.sh performs the two-step
// deployment and passes BidderSimulatorStack outputs as PrebidServerStack
// CloudFormation parameters.
const deployBiddingSimulator = isContextTrue(app.node.tryGetContext("deployBiddingSimulator"));

if (deployBiddingSimulator) {
  new BidderSimulatorStack(app, "BiddingServerSimulator");
}

new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
