#!/usr/bin/env python3
import json
import subprocess
import time
import os
import re
import datetime
import argparse
import sys
from collections import namedtuple

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Path to xchain-cli - configurable via command line
DEFAULT_XCHAIN_CLI = "./bin/xchain-cli"
# Default proposer address
DEFAULT_ADDRESS = "TeyyPLpp9L7QAcxHangtcHTu7HUZ6iydY"

# Configuration for proposal
ProposalConfig = namedtuple('ProposalConfig', [
    'vote_duration_blocks', 
    'trigger_buffer', 
    'block_num_buffer', 
    'min_vote_percent'
])

DEFAULT_CONFIG = ProposalConfig(
    vote_duration_blocks=40,  # ~2 minutes assuming 3 second blocks
    trigger_buffer=10,        # Buffer of 10 blocks
    block_num_buffer=5,       # Buffer after trigger
    min_vote_percent=51       # Default voting threshold
)

def print_status(message, status="info"):
    """Print formatted status messages"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = f"[{timestamp}] "
    
    if status == "info":
        print(f"{Colors.BLUE}{prefix}INFO:{Colors.ENDC} {message}")
    elif status == "success":
        print(f"{Colors.GREEN}{prefix}SUCCESS:{Colors.ENDC} {message}")
    elif status == "error":
        print(f"{Colors.RED}{prefix}ERROR:{Colors.ENDC} {message}")
    elif status == "warning":
        print(f"{Colors.YELLOW}{prefix}WARNING:{Colors.ENDC} {message}")
    elif status == "debug":
        if args.verbose:
            print(f"{Colors.CYAN}{prefix}DEBUG:{Colors.ENDC} {message}")
    elif status == "header":
        print(f"\n{Colors.HEADER}{Colors.BOLD}{prefix}{message}{Colors.ENDC}\n")

def run_command(cmd, show_output=True):
    """Run a shell command and return the output with better error handling"""
    if show_output or args.verbose:
        print_status(f"Executing: {cmd}", "debug")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            print_status(f"Command failed: {cmd}", "error")
            print_status(f"Error: {result.stderr}", "error")
            return None
        
        return result.stdout.strip()
    except Exception as e:
        print_status(f"Exception running command: {str(e)}", "error")
        return None

def check_xchain_cli():
    """Check if xchain-cli is available"""
    print_status("Checking if xchain-cli is available...", "header")
    
    result = run_command(f"{args.cli} --version", show_output=False)
    if not result:
        print_status("Could not find or execute xchain-cli. Please make sure it's installed and the path is correct.", "error")
        return False
    
    print_status(f"Found xchain-cli: {result}", "success")
    return True

def get_address():
    """Get and validate the user's address"""
    print_status("Checking address...", "header")
    
    address = args.address
    if not address:
        # Try to get default address from xchain-cli
        result = run_command(f"{args.cli} account default")
        if result and "address" in result:
            try:
                address_match = re.search(r"address: ([A-Za-z0-9]+)", result)
                if address_match:
                    address = address_match.group(1)
                    use_default = input(f"Use default address {address}? (Y/n): ").strip().lower()
                    if use_default and use_default != "y":
                        address = input("Enter your address: ").strip()
            except:
                pass
    
    if not address:
        address = input("Enter your address: ").strip()
        if not address:
            address = DEFAULT_ADDRESS
            print_status(f"Using default address: {address}", "warning")
    
    # Validate address format (basic check)
    if not re.match(r"^[A-Za-z0-9]+$", address):
        print_status("Address format appears invalid. Continuing anyway, but this might cause issues.", "warning")
    
    return address

def check_governance_initialized(address):
    """Check if governance tokens have been initialized"""
    print_status("Checking if governance tokens are initialized...", "header")
    
    output = run_command(f"{args.cli} governToken query -a {address}")
    if not output:
        if args.interactive:
            init = input("Governance tokens not found. Would you like to initialize them? (y/N): ").strip().lower()
            if init == 'y':
                print_status("Attempting to initialize governance tokens...", "info")
                init_output = run_command(f"{args.cli} governToken init --fee 1000")
                if init_output and "Tx id:" in init_output:
                    print_status("Successfully initialized governance tokens.", "success")
                    txid_match = re.search(r"Tx id: ([a-f0-9]+)", init_output)
                    if txid_match:
                        print_status(f"Waiting for transaction to be confirmed...", "info")
                        time.sleep(5)  # Wait for confirmation
                        return True
                    return True
                else:
                    print_status("Failed to initialize governance tokens.", "error")
                    return False
            else:
                print_status("Skipping governance token initialization.", "warning")
                return False
        else:
            print_status("Governance tokens not initialized.", "error")
            return False
    
    try:
        # Parse the balance from the response
        response_text = output.split("contract response: ", 1)[1] if "contract response: " in output else output
        response = json.loads(response_text)
        balance = response.get("total_balance", "0")
        print_status(f"Current governance token balance: {balance}", "success")
        return True
    except:
        print_status("Could not parse token balance, but governance appears to be initialized.", "warning")
        return True

def get_current_height():
    """Get the current blockchain height"""
    output = run_command(f"{args.cli} status")
    if not output:
        print_status("Failed to get blockchain status.", "error")
        return None
    
    try:
        status_json = json.loads(output)
        current_height = int(status_json["blockchains"][0]["ledger"]["trunkHeight"])
        print_status(f"Current blockchain height: {current_height}", "success")
        return current_height
    except (json.JSONDecodeError, KeyError) as e:
        print_status(f"Error parsing blockchain height: {str(e)}", "error")
        return None

def get_config_from_user(current_height):
    """Get proposal configuration from user"""
    print_status("Configuring proposal parameters...", "header")
    
    config = DEFAULT_CONFIG
    
    if args.interactive:
        print(f"Current blockchain height: {current_height}")
        print(f"Default voting duration: {config.vote_duration_blocks} blocks")
        
        try:
            user_duration = input(f"Enter voting duration in blocks (default: {config.vote_duration_blocks}): ").strip()
            if user_duration and user_duration.isdigit():
                config = config._replace(vote_duration_blocks=int(user_duration))
            
            user_min_vote = input(f"Enter minimum vote percent (default: {config.min_vote_percent}): ").strip()
            if user_min_vote and user_min_vote.isdigit() and 1 <= int(user_min_vote) <= 100:
                config = config._replace(min_vote_percent=int(user_min_vote))
            
            user_buffer = input(f"Enter trigger buffer blocks (default: {config.trigger_buffer}): ").strip()
            if user_buffer and user_buffer.isdigit():
                config = config._replace(trigger_buffer=int(user_buffer))
        except Exception as e:
            print_status(f"Error processing input: {str(e)}, using defaults", "warning")
    
    # Calculate key heights based on configuration
    stop_vote_height = current_height + config.vote_duration_blocks
    trigger_height = stop_vote_height + config.trigger_buffer
    block_num_height = trigger_height + config.block_num_buffer
    
    print_status(f"Vote will end at height: {stop_vote_height}", "info")
    print_status(f"Trigger will execute at height: {trigger_height}", "info")
    print_status(f"Block num height set to: {block_num_height}", "info")
    
    return config, stop_vote_height, trigger_height, block_num_height

def create_proposal_json(proposer, current_height, config_params):
    """Create the proposal.json file"""
    print_status("Creating proposal.json...", "header")
    
    config, stop_vote_height, trigger_height, block_num_height = config_params
    
    # Get current timestamp in nanoseconds (as integer instead of scientific notation)
    # Add 10 minutes worth of nanoseconds to ensure it's in the future
    current_timestamp_ns = int(time.time() * 1e9)
    future_timestamp_ns = current_timestamp_ns + (10 * 60 * 1e9)
    
    # Format as string without scientific notation
    future_timestamp_str = str(int(future_timestamp_ns))
    
    # Define proposal structure
    proposal = {
        "args": {
            "min_vote_percent": str(config.min_vote_percent),
            "stop_vote_height": str(stop_vote_height)
        },
        "trigger": {
            "height": trigger_height,
            "module": "xkernel",
            "contract": "$consensus",
            "method": "updateConsensus",
            "args": {
                "name": "tdpos",
                "config": {
                    "version": "3",
                    "proposer_num": "1",  # Set to 1 for single node
                    "period": "10000",
                    "alternate_interval": "10000",
                    "term_interval": "30000",
                    "timestamp": future_timestamp_str,  # Use proper timestamp format
                    "block_num": str(block_num_height),
                    "vote_unit_price": "1",
                    "init_proposer": {
                        "1": [
                            proposer
                        ]
                    }
                }
            }
        }
    }
    
    # Create directory if it doesn't exist
    os.makedirs("proposal-app", exist_ok=True)
    
    # Write proposal to file
    proposal_path = "proposal-app/proposal.json"
    with open(proposal_path, "w") as f:
        json.dump(proposal, f, indent=2)
    
    print_status(f"Created proposal at {os.path.abspath(proposal_path)}", "success")
    
    # Show the proposal to the user in interactive mode
    if args.interactive:
        show_proposal = input("Show proposal details? (y/N): ").strip().lower()
        if show_proposal == 'y':
            print(json.dumps(proposal, indent=2))
    
    return proposal, proposal_path

def submit_proposal(proposal_path):
    """Submit the proposal to the blockchain"""
    print_status("Submitting proposal...", "header")
    
    if args.interactive:
        confirm = input("Ready to submit proposal? (Y/n): ").strip().lower()
        if confirm and confirm != 'y':
            print_status("Proposal submission cancelled by user.", "warning")
            return None
    
    result = run_command(f"{args.cli} proposal propose --proposal {proposal_path} --fee 100")
    if not result:
        print_status("Proposal submission failed.", "error")
        return None
    
    print_status("Proposal submission result:", "success")
    
    # Extract the proposal ID and transaction ID
    pid_match = re.search(r"contract response: (\d+)", result)
    txid_match = re.search(r"Tx id: ([a-f0-9]+)", result)
    
    pid = None
    txid = None
    
    if pid_match:
        pid = pid_match.group(1)
        print_status(f"Proposal ID: {pid}", "success")
    
    if txid_match:
        txid = txid_match.group(1)
        print_status(f"Transaction ID: {txid}", "success")
        
        # Wait for transaction to be confirmed
        print_status("Waiting for transaction to be confirmed...", "info")
        time.sleep(5)
        
        # If we couldn't get the PID directly, try to extract it from the transaction
        if not pid and txid:
            tx_result = run_command(f"{args.cli} tx query {txid}")
            if tx_result:
                # Look for proposal ID in transaction outputs
                for line in tx_result.split("\n"):
                    if "bucket" in line and "proposal" in line and "key" in line:
                        key_match = re.search(r"\"key\": \"(\d+)\"", line)
                        if key_match:
                            pid = key_match.group(1)
                            print_status(f"Extracted Proposal ID from transaction: {pid}", "success")
                            break
    
    # If we still don't have a PID, ask for user input
    if not pid and args.interactive:
        pid = input("Could not automatically determine proposal ID. Please enter it manually: ").strip()
    
    return pid, txid

def get_governance_tokens(address):
    """Get the amount of governance tokens for an address"""
    print_status(f"Checking governance tokens for {address}...", "header")
    
    output = run_command(f"{args.cli} governToken query -a {address}")
    if not output:
        print_status("Failed to query governance tokens.", "error")
        return 0
    
    try:
        # Parse the response to get available balance
        response_text = output.split("contract response: ", 1)[1] if "contract response: " in output else output
        response = json.loads(response_text)
        
        total_balance = int(response.get("total_balance", 0))
        locked_balances = response.get("locked_balances", {})
        
        # Calculate available balance by subtracting locked amounts
        locked_ordinary = int(locked_balances.get("ordinary", 0))
        locked_tdpos = int(locked_balances.get("tdpos", 0))
        
        available_balance = total_balance - locked_ordinary - locked_tdpos
        
        print_status(f"Total governance tokens: {total_balance}", "info")
        print_status(f"Locked tokens: {locked_ordinary + locked_tdpos}", "info")
        print_status(f"Available tokens for voting: {available_balance}", "success")
        
        return available_balance
    except Exception as e:
        print_status(f"Error getting governance tokens: {str(e)}", "error")
        return 0

def vote_on_proposal(pid, address, tokens):
    """Vote on the proposal with all available tokens"""
    print_status(f"Voting on proposal {pid}...", "header")
    
    if tokens <= 0:
        print_status("No governance tokens available for voting!", "error")
        return None
    
    # Use slightly less than the total available to ensure it works
    voting_amount = int(tokens * 0.9)
    
    if args.interactive:
        user_amount = input(f"Enter amount to vote with (default: {voting_amount}): ").strip()
        if user_amount and user_amount.isdigit() and int(user_amount) > 0:
            voting_amount = int(user_amount)
            if voting_amount > tokens:
                print_status(f"Amount exceeds available tokens ({tokens}), using maximum available", "warning")
                voting_amount = tokens
    
    print_status(f"Voting with {voting_amount} tokens...", "info")
    
    result = run_command(f"{args.cli} proposal vote --pid {pid} --amount {voting_amount} --fee 100")
    if not result:
        print_status("Vote submission failed.", "error")
        return None
    
    print_status("Vote submitted successfully", "success")
    
    # Extract transaction ID
    txid_match = re.search(r"Tx id: ([a-f0-9]+)", result)
    if txid_match:
        txid = txid_match.group(1)
        print_status(f"Vote Transaction ID: {txid}", "success")
        
        # Wait for transaction to be confirmed
        print_status("Waiting for vote transaction to be confirmed...", "info")
        time.sleep(5)
        
        return txid
    
    return None

def get_proposal_status(pid, txid=None):
    """Get the current status of a proposal"""
    # First try direct query
    output = run_command(f"{args.cli} proposal query -p {pid}")
    
    if output and "contract response:" in output:
        try:
            response_text = output.split("contract response: ", 1)[1]
            proposal_data = json.loads(response_text)
            return proposal_data
        except (json.JSONDecodeError, IndexError) as e:
            print_status(f"Error parsing proposal query: {str(e)}", "debug")
    
    # Fallback to transaction if we have one
    if txid:
        try:
            tx_result = run_command(f"{args.cli} tx query {txid}")
            if tx_result:
                tx_json = json.loads(tx_result)
                
                # Extract proposal information from transaction outputs
                for output in tx_json.get("txOutputsExt", []):
                    if output.get("bucket") == "proposal" and output.get("key") == pid:
                        try:
                            value_str = output.get("value", "{}")
                            proposal_data = json.loads(value_str)
                            return proposal_data
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print_status(f"Error extracting proposal status from transaction: {str(e)}", "debug")
    
    return None

def format_time_remaining(seconds):
    """Format seconds into a readable time remaining string"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
        else:
            return f"{hours} hour{'s' if hours != 1 else ''}"

def check_consensus_status():
    """Check if consensus has changed to tdpos"""
    try:
        status_output = run_command(f"{args.cli} status", show_output=False)
        if not status_output:
            return False
            
        status_json = json.loads(status_output)
        
        # Check the consensus name in the blockchain status
        consensus_name = status_json.get("blockchains", [{}])[0].get("consensusName", "")
        if consensus_name.lower() == "tdpos":
            return True
            
        # Double-check in consensus status 
        consensus = status_json.get("blockchains", [{}])[0].get("consensus", {})
        if consensus.get("name", "").lower() == "tdpos":
            return True
            
        return False
    except Exception as e:
        print_status(f"Error checking consensus status: {str(e)}", "debug")
        return False

def monitor_proposal(pid, txid=None, stop_vote_height=None, trigger_height=None):
    """Monitor the status of the proposal with interactive UI"""
    print_status(f"Monitoring proposal {pid}...", "header")
    
    if args.interactive:
        print(f"{Colors.BOLD}Press Ctrl+C to stop monitoring at any time{Colors.ENDC}")
    
    max_checks_after_trigger = 20  # Set a maximum number of checks after trigger height
    checks_after_trigger = 0
    
    try:
        last_height = None
        while True:
            # Get current blockchain height
            current_height = get_current_height()
            if not current_height:
                print_status("Failed to get blockchain height, retrying in 10 seconds...", "warning")
                time.sleep(10)
                continue
            
            # Only show updates when height changes
            if last_height is not None and current_height == last_height and not args.verbose:
                # Wait a bit before checking again
                time.sleep(3)
                continue
                
            last_height = current_height
            
            # Get proposal data
            proposal_data = get_proposal_status(pid, txid)
            
            if proposal_data:
                status = proposal_data.get("status", "unknown")
                vote_amount = proposal_data.get("vote_amount", "0")
                
                try:
                    if not stop_vote_height:
                        stop_vote_height = int(proposal_data.get("args", {}).get("stop_vote_height", "0"))
                except (ValueError, TypeError):
                    stop_vote_height = 0
                
                try:
                    if not trigger_height:
                        trigger_height = int(proposal_data.get("trigger", {}).get("height", 0))
                except (ValueError, TypeError):
                    trigger_height = 0
                
                # Calculate time remaining based on block heights and estimated block time (3 seconds)
                blocks_until_vote_end = max(0, stop_vote_height - current_height)
                blocks_until_trigger = max(0, trigger_height - current_height)
                
                seconds_per_block = 3  # Estimated seconds per block
                vote_time_remaining = blocks_until_vote_end * seconds_per_block
                trigger_time_remaining = blocks_until_trigger * seconds_per_block
                
                # Display status
                print_status(f"Status: {status}, Votes: {vote_amount}", "info")
                print_status(f"Current height: {current_height}, Stop vote: {stop_vote_height}, Trigger: {trigger_height}", "info")
                
                if blocks_until_vote_end > 0:
                    print_status(f"Voting ends in {blocks_until_vote_end} blocks (~{format_time_remaining(vote_time_remaining)})", "info")
                elif blocks_until_trigger > 0:
                    print_status(f"Waiting for trigger in {blocks_until_trigger} blocks (~{format_time_remaining(trigger_time_remaining)})", "info")
                else:
                    print_status("Waiting for consensus change...", "info")
                
                # Check if consensus has changed
                if current_height >= trigger_height:
                    checks_after_trigger += 1
                    
                    if check_consensus_status():
                        print_status("SUCCESS: Consensus has been changed to tdpos", "success")
                        break
                    elif checks_after_trigger >= max_checks_after_trigger:
                        print_status("Maximum number of checks reached after trigger height. Please verify manually.", "warning")
                        break
                    
                    print_status(f"Consensus not changed yet. Checks remaining: {max_checks_after_trigger - checks_after_trigger}", "warning")
                
                # Check if proposal is completed
                if status.lower() in ["completed_success", "completed", "passed"]:
                    print_status(f"Proposal is {status}! Checking if consensus has changed...", "success")
                    if check_consensus_status():
                        print_status("SUCCESS: Consensus has been changed to tdpos", "success")
                        break
                elif status.lower() in ["rejected", "expired"]:
                    print_status(f"Proposal has been {status}. Monitoring complete.", "warning")
                    break
            else:
                print_status(f"Could not retrieve status for proposal {pid}", "warning")
                
                # Check if consensus has changed anyways
                if check_consensus_status():
                    print_status("SUCCESS: Consensus has been changed to tdpos", "success")
                    break
            
            # Wait before checking again
            sleep_time = 10 if not args.verbose else 5
            print_status(f"Next update in {sleep_time} seconds...", "debug")
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print_status("\nMonitoring stopped by user", "warning")
    except Exception as e:
        print_status(f"Error monitoring proposal: {str(e)}", "error")

def main():
    """Main function to run the proposer script"""
    if not check_xchain_cli():
        sys.exit(1)
    
    # Step 1: Get and validate address
    proposer_address = get_address()
    
    # Step 2: Check if governance is initialized
    initialized = check_governance_initialized(proposer_address)
    if not initialized and not args.interactive:
        sys.exit(1)
    
    # Step 3: Get current height
    current_height = get_current_height()
    if not current_height:
        sys.exit(1)
    
    # Step 4: Get configuration
    config_params = get_config_from_user(current_height)
    
    # Step 5: Create proposal.json
    proposal_obj, proposal_path = create_proposal_json(proposer_address, current_height, config_params)
    
    # Step 6: Submit proposal
    pid_txid = submit_proposal(proposal_path)
    if not pid_txid:
        sys.exit(1)
    
    pid, txid = pid_txid
    
    # Step 7: Get governance tokens
    tokens = get_governance_tokens(proposer_address)
    
    # Step 8: Vote on proposal
    vote_txid = None
    if tokens > 0:
        vote_txid = vote_on_proposal(pid, proposer_address, tokens)
    else:
        print_status("No governance tokens available for voting.", "error")
        if args.interactive:
            continue_anyway = input("Continue monitoring anyway? (Y/n): ").strip().lower()
            if continue_anyway and continue_anyway != 'y':
                sys.exit(1)
    
    # Step 9: Monitor proposal status
    _, stop_vote_height, trigger_height, _ = config_params
    monitor_proposal(pid, vote_txid or txid, stop_vote_height, trigger_height)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TDPoS Consensus Proposal Tool")
    parser.add_argument("--cli", default=DEFAULT_XCHAIN_CLI, help=f"Path to xchain-cli (default: {DEFAULT_XCHAIN_CLI})")
    parser.add_argument("--address", help="Address to use as proposer (default: auto-detect)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    args = parser.parse_args()
    
    # Enable interactive mode by default if running in a terminal
    if sys.stdout.isatty() and not args.interactive:
        args.interactive = True
    
    main()
