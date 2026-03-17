# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import App

from bidder_simulator_stack import BidderSimulatorStack

app = App()
BidderSimulatorStack(
    app,
    "BidderSimulator"
)
app.synth()
