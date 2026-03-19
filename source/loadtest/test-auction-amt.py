#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test script for validating AMT adapter auction requests with Prebid Server.

This script sends auction requests to a deployed Prebid Server instance with
the AMT adapter enabled and validates the response structure.

Usage:
    python test-auction-amt.py --endpoint <cloudfront-url>
    python test-auction-amt.py --endpoint <cloudfront-url> --request-file custom-request.json
    python test-auction-amt.py --endpoint <cloudfront-url> --verbose
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import requests


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def load_request_json(file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load auction request JSON from file.
    
    Args:
        file_path: Path to JSON file. If None, uses default test-auction-amt-request.json
        
    Returns:
        Dictionary containing the auction request
        
    Raises:
        FileNotFoundError: If the request file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    if file_path is None:
        # Use default request file in amt-bidder directory
        script_dir = Path(__file__).parent
        file_path = script_dir / "amt-bidder" / "test-auction-amt-request.json"
    else:
        file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Request file not found: {file_path}")
    
    with open(file_path, 'r') as f:
        return json.load(f)


def send_auction_request(endpoint: str, request_data: Dict[str, Any], verbose: bool = False) -> requests.Response:
    """
    Send auction request to Prebid Server.
    
    Args:
        endpoint: CloudFront or ALB endpoint URL
        request_data: Auction request payload
        verbose: Whether to print detailed request information
        
    Returns:
        Response object from the request
    """
    # Ensure endpoint has proper format
    if not endpoint.startswith(('http://', 'https://')):
        endpoint = f"https://{endpoint}"
    
    # Remove trailing slash if present
    endpoint = endpoint.rstrip('/')
    
    # Construct auction endpoint
    auction_url = f"{endpoint}/openrtb2/auction"
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    if verbose:
        print(f"\n{Colors.BLUE}=== REQUEST DETAILS ==={Colors.END}")
        print(f"URL: {auction_url}")
        print(f"Headers: {json.dumps(headers, indent=2)}")
        print(f"Payload:\n{json.dumps(request_data, indent=2)}")
    
    try:
        response = requests.post(
            auction_url,
            json=request_data,
            headers=headers,
            timeout=10
        )
        return response
    except requests.exceptions.RequestException as e:
        print(f"{Colors.RED}Error sending request: {e}{Colors.END}")
        sys.exit(1)


def validate_response(response: requests.Response, verbose: bool = False) -> bool:
    """
    Validate the auction response structure.
    
    Args:
        response: Response object from the auction request
        verbose: Whether to print detailed validation information
        
    Returns:
        True if validation passes, False otherwise
    """
    validation_passed = True
    
    print(f"\n{Colors.BLUE}=== RESPONSE VALIDATION ==={Colors.END}")
    
    # Check HTTP status
    if response.status_code == 200:
        print(f"{Colors.GREEN}\u2713{Colors.END} HTTP Status: {response.status_code}")
    else:
        print(f"{Colors.RED}\u2717{Colors.END} HTTP Status: {response.status_code} (expected 200)")
        print(f"\n{Colors.YELLOW}Response Headers:{Colors.END}")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")
        print(f"\n{Colors.YELLOW}Response Body:{Colors.END}")
        print(response.text)
        validation_passed = False
        return validation_passed
    
    # Parse response JSON
    try:
        response_data = response.json()
    except json.JSONDecodeError as e:
        print(f"{Colors.RED}\u2717{Colors.END} Invalid JSON response: {e}")
        return False
    
    # Always show response headers and body for transparency
    print(f"\n{Colors.BLUE}Response Headers:{Colors.END}")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    
    print(f"\n{Colors.BLUE}Response Body:{Colors.END}")
    print(json.dumps(response_data, indent=2))
    
    if verbose:
        print(f"\n{Colors.BLUE}Detailed Validation:{Colors.END}")
    
    # Validate response structure
    required_fields = ['id', 'seatbid', 'cur']
    for field in required_fields:
        if field in response_data:
            print(f"{Colors.GREEN}\u2713{Colors.END} Field '{field}' present")
        else:
            print(f"{Colors.RED}\u2717{Colors.END} Field '{field}' missing")
            validation_passed = False
    
    # Validate seatbid structure
    if 'seatbid' in response_data and len(response_data['seatbid']) > 0:
        print(f"{Colors.GREEN}\u2713{Colors.END} Seatbid array contains {len(response_data['seatbid'])} seat(s)")
        
        for idx, seatbid in enumerate(response_data['seatbid']):
            seat_name = seatbid.get('seat', 'unknown')
            print(f"\n{Colors.BOLD}Seat {idx + 1}: {seat_name}{Colors.END}")
            
            # Check for bids
            if 'bid' in seatbid and len(seatbid['bid']) > 0:
                print(f"{Colors.GREEN}\u2713{Colors.END} Contains {len(seatbid['bid'])} bid(s)")
                
                for bid_idx, bid in enumerate(seatbid['bid']):
                    print(f"\n  {Colors.BOLD}Bid {bid_idx + 1}:{Colors.END}")
                    
                    # Validate bid fields
                    bid_fields = {
                        'id': bid.get('id'),
                        'impid': bid.get('impid'),
                        'price': bid.get('price'),
                        'crid': bid.get('crid')
                    }
                    
                    for field_name, field_value in bid_fields.items():
                        if field_value is not None:
                            print(f"  {Colors.GREEN}\u2713{Colors.END} {field_name}: {field_value}")
                        else:
                            print(f"  {Colors.RED}\u2717{Colors.END} {field_name}: missing")
                            validation_passed = False
            else:
                print(f"{Colors.YELLOW}!{Colors.END} No bids in seatbid")
    else:
        print(f"{Colors.YELLOW}!{Colors.END} Seatbid array is empty (no bids returned)")
    
    return validation_passed


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Test AMT adapter auction requests with Prebid Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with CloudFront endpoint
  python test-auction-amt.py --endpoint d1234567890.cloudfront.net
  
  # Test with custom request file
  python test-auction-amt.py --endpoint d1234567890.cloudfront.net --request-file my-request.json
  
  # Verbose output
  python test-auction-amt.py --endpoint d1234567890.cloudfront.net --verbose
        """
    )
    
    parser.add_argument(
        '--endpoint',
        required=True,
        help='CloudFront or ALB endpoint URL (e.g., d1234567890.cloudfront.net)'
    )
    
    parser.add_argument(
        '--request-file',
        help='Path to custom auction request JSON file (default: amt-bidder/test-auction-amt-request.json)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output with full request/response details'
    )
    
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}AMT Adapter Auction Test{Colors.END}")
    print("=" * 50)
    
    # Load request data
    try:
        request_data = load_request_json(args.request_file)
        request_file_used = args.request_file if args.request_file else "amt-bidder/test-auction-amt-request.json"
        print(f"{Colors.GREEN}\u2713{Colors.END} Loaded auction request from: {request_file_used}")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"{Colors.RED}\u2717{Colors.END} Failed to load request: {e}")
        sys.exit(1)
    
    # Send auction request
    print(f"\n{Colors.BLUE}Sending auction request to: {args.endpoint}{Colors.END}")
    print("=" * 80)
    response = send_auction_request(args.endpoint, request_data, args.verbose)
    
    # Validate response
    validation_passed = validate_response(response, args.verbose)
    
    # Print summary
    print(f"\n{Colors.BOLD}=== TEST SUMMARY ==={Colors.END}")
    if validation_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}\u2713 All validations passed!{Colors.END}")
        sys.exit(0)
    else:
        print(f"{Colors.RED}{Colors.BOLD}\u2717 Some validations failed{Colors.END}")
        sys.exit(1)


if __name__ == '__main__':
    main()
