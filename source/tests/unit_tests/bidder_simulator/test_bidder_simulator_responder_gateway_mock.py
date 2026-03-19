# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# ###############################################################################
# PURPOSE:
#   * Unit test for BidderSimulatorStack Responder Gateway creation (mock version).
#   * This test verifies the conditional logic without requiring aws_rtbfabric module.
# USAGE:
#   ./run-unit-tests.sh --test-file-name bidder_simulator/test_bidder_simulator_responder_gateway_mock.py
###############################################################################

import sys
from unittest.mock import Mock, patch, MagicMock
from aws_cdk import App


class TestBidderSimulatorResponderGatewayMock:
    """Test Responder Gateway conditional logic in BidderSimulatorStack"""

    def test_responder_gateway_method_called_with_flag(self):
        """
        Test that _create_responder_gateway_if_enabled is called when flag is true.
        
        Validates that the conditional logic correctly checks the includeRtbFabric context.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Mock the aws_rtbfabric module to avoid import errors
        with patch.dict('sys.modules', {'aws_cdk.aws_rtbfabric': Mock()}):
            # Import after mocking
            sys.path.insert(0, "./loadtest/bidder_simulator")
            from bidder_simulator_stack import BidderSimulatorStack
            
            # Mock the _create_responder_gateway_if_enabled method
            with patch.object(BidderSimulatorStack, '_create_responder_gateway_if_enabled') as mock_method:
                # Act
                stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
                
                # Assert - Method should be called once
                mock_method.assert_called_once()

    def test_responder_gateway_skipped_without_flag(self):
        """
        Test that responder gateway creation is skipped when flag is false.
        
        Validates Requirement 2.2: When the Deploy_Script is executed without 
        the `--include-rtb-fabric` flag, THEN THE CDK_Stack SHALL NOT create 
        any RTB_Fabric resources.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": False,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Mock the aws_rtbfabric module
        mock_rtbfabric = Mock()
        mock_cfn_responder_gateway = Mock()
        mock_rtbfabric.CfnResponderGateway = mock_cfn_responder_gateway
        
        with patch.dict('sys.modules', {'aws_cdk.aws_rtbfabric': mock_rtbfabric}):
            # Import after mocking
            sys.path.insert(0, "./loadtest/bidder_simulator")
            from bidder_simulator_stack import BidderSimulatorStack
            
            # Act
            stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
            
            # Assert - CfnResponderGateway should NOT be instantiated
            mock_cfn_responder_gateway.assert_not_called()

    def test_responder_gateway_created_with_flag(self):
        """
        Test that responder gateway is created when flag is true.
        
        Validates Requirement 4.2: WHERE the `--include-rtb-fabric` flag is set, 
        WHEN the CDK_Stack is deployed, THEN THE CDK_Stack SHALL create a 
        Responder_Gateway.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Mock the aws_rtbfabric module
        mock_rtbfabric = Mock()
        mock_cfn_responder_gateway = Mock()
        mock_gateway_instance = MagicMock()
        mock_gateway_instance.attr_gateway_id = "test-gateway-id"
        mock_gateway_instance.attr_arn = "arn:aws:rtbfabric:us-east-1:123456789:gateway/test"
        mock_cfn_responder_gateway.return_value = mock_gateway_instance
        mock_rtbfabric.CfnResponderGateway = mock_cfn_responder_gateway
        
        with patch.dict('sys.modules', {'aws_cdk.aws_rtbfabric': mock_rtbfabric}):
            # Import after mocking
            sys.path.insert(0, "./loadtest/bidder_simulator")
            from bidder_simulator_stack import BidderSimulatorStack
            
            # Act
            stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
            
            # Assert - CfnResponderGateway should be instantiated once
            mock_cfn_responder_gateway.assert_called_once()
            
            # Verify the gateway was created with correct parameters
            call_args = mock_cfn_responder_gateway.call_args
            assert call_args[1]['port'] == 443
            assert call_args[1]['protocol'] == "HTTPS"
            assert 'vpc_id' in call_args[1]
            assert 'subnet_ids' in call_args[1]
            assert 'security_group_ids' in call_args[1]
            assert 'domain_name' in call_args[1]
