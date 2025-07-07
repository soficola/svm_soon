import os
import sys
import time
import json
import logging
from typing import Dict, Any, List, Optional

import requests
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import BlockNotFound
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

# Set up a logger for clear, standardized output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s] - %(message)s',
    stream=sys.stdout
)

# --- System Configuration ---
# Source chain (e.g., Ethereum Mainnet, Goerli Testnet)
SOURCE_CHAIN_RPC_URL = os.getenv('SOURCE_CHAIN_RPC_URL', 'https://rpc.ankr.com/eth_goerli')

# A mock destination API endpoint for simulating the relaying action
DESTINATION_API_ENDPOINT = os.getenv('DESTINATION_API_ENDPOINT', 'https://jsonplaceholder.typicode.com/posts')

# --- Bridge Configuration ---
# The address of the bridge contract on the source chain to monitor
# This is an example address on Goerli Testnet
BRIDGE_CONTRACT_ADDRESS = os.getenv('BRIDGE_CONTRACT_ADDRESS', '0x1234567890123456789012345678901234567890') # Replace with a real one for a real test

# The simplified ABI (Application Binary Interface) for the bridge contract.
# We only need the definition of the event we are interested in.
BRIDGE_CONTRACT_ABI = json.loads('''
[
  {
    "anonymous": false,
    "inputs": [
      {
        "indexed": true,
        "internalType": "address",
        "name": "sender",
        "type": "address"
      },
      {
        "indexed": true,
        "internalType": "uint256",
        "name": "destinationChainId",
        "type": "uint256"
      },
      {
        "indexed": false,
        "internalType": "address",
        "name": "recipient",
        "type": "address"
      },
      {
        "indexed": false,
        "internalType": "address",
        "name": "token",
        "type": "address"
      },
      {
        "indexed": false,
        "internalType": "uint256",
        "name": "amount",
        "type": "uint256"
      },
      {
        "indexed": false,
        "internalType": "uint256",
        "name": "nonce",
        "type": "uint256"
      }
    ],
    "name": "TokensLocked",
    "type": "event"
  }
]
''')

# The name of the event to listen for
EVENT_NAME = 'TokensLocked'

# --- Scanner Configuration ---
# How often the orchestrator should check for new blocks (in seconds)
SCAN_INTERVAL_SECONDS = 15

# The maximum number of blocks to scan in a single request to the RPC node
# A smaller number is safer and less likely to cause timeouts on public RPCs
MAX_BLOCK_RANGE = 500

# The number of blocks to wait for finality before processing an event.
# This helps prevent processing events from blocks that might be reorganized.
CONFIRMATION_BLOCKS = 12

class BlockchainConnector:
    """A wrapper class for Web3.py to manage the connection to a blockchain node."""

    def __init__(self, rpc_url: str):
        """
        Initializes the connector with an RPC URL.

        Args:
            rpc_url (str): The HTTP or WebSocket URL of the blockchain node.
        """
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None
        self.connect()

    def connect(self) -> None:
        """Establishes a connection to the blockchain node."""
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.is_connected():
                raise ConnectionError("Failed to connect to the blockchain node.")
            logging.info(f"Successfully connected to blockchain node at {self.rpc_url}")
        except Exception as e:
            logging.error(f"Error connecting to blockchain node: {e}")
            self.web3 = None

    def is_connected(self) -> bool:
        """Checks if the connection to the node is active."""
        return self.web3 is not None and self.web3.is_connected()

    def get_latest_block(self) -> Optional[int]:
        """
        Fetches the latest block number from the blockchain.

        Returns:
            Optional[int]: The latest block number, or None if an error occurs.
        """
        if not self.is_connected():
            logging.warning("Not connected. Attempting to reconnect...")
            self.connect()
        if self.is_connected():
            try:
                return self.web3.eth.block_number
            except Exception as e:
                logging.error(f"Could not fetch latest block number: {e}")
        return None

    def get_contract(self, address: str, abi: List[Dict]) -> Optional[Contract]:
        """
        Creates a Web3.py Contract object.

        Args:
            address (str): The checksummed address of the smart contract.
            abi (List[Dict]): The ABI of the smart contract.

        Returns:
            Optional[Contract]: A contract object, or None if not connected.
        """
        if self.is_connected():
            checksum_address = Web3.to_checksum_address(address)
            return self.web3.eth.contract(address=checksum_address, abi=abi)
        logging.error("Cannot create contract object, not connected to the blockchain.")
        return None

class EventScanner:
    """Scans a range of blocks on the blockchain for specific smart contract events."""

    def __init__(self, contract: Contract):
        """
        Initializes the scanner with a contract object.

        Args:
            contract (Contract): The Web3.py contract object to scan events from.
        """
        if not isinstance(contract, Contract):
            raise TypeError("contract must be a valid Web3.py Contract instance.")
        self.contract = contract
        self.event_name = EVENT_NAME
        logging.info(f"EventScanner initialized for contract {self.contract.address} and event '{self.event_name}'.")

    def scan_blocks(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """
        Scans a given range of blocks for the configured event.

        Args:
            from_block (int): The starting block number (inclusive).
            to_block (int): The ending block number (inclusive).

        Returns:
            List[Dict[str, Any]]: A list of decoded event logs.
        """
        if from_block > to_block:
            logging.warning(f"from_block ({from_block}) cannot be greater than to_block ({to_block}). No scan performed.")
            return []

        logging.info(f"Scanning for '{self.event_name}' events from block {from_block} to {to_block}.")
        try:
            event_filter = getattr(self.contract.events, self.event_name).create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            events = event_filter.get_all_entries()
            if events:
                logging.info(f"Found {len(events)} '{self.event_name}' event(s) in block range.")
            return [dict(event) for event in events]
        except BlockNotFound:
            logging.warning(f"Block range from {from_block} to {to_block} not found. The RPC node may not have this data.")
        except Exception as e:
            logging.error(f"An unexpected error occurred during event scanning: {e}")
        return []

class CrossChainTransactionRelayer:
    """Handles the processing of events and simulates relaying them to a destination chain."""

    def __init__(self, api_endpoint: str):
        """
        Initializes the relayer with the destination API endpoint.

        Args:
            api_endpoint (str): The URL to which the processed event data will be POSTed.
        """
        self.api_endpoint = api_endpoint
        self.session = requests.Session()
        logging.info(f"Transaction Relayer initialized. Destination API: {self.api_endpoint}")

    def process_and_relay(self, event_log: Dict[str, Any]) -> bool:
        """
        Processes a single event log and simulates relaying it.

        Args:
            event_log (Dict[str, Any]): A single, decoded event log from the scanner.

        Returns:
            bool: True if the relay simulation was successful, False otherwise.
        """
        try:
            # 1. Format the event data into a payload for the destination chain
            payload = self._format_payload(event_log)
            logging.info(f"Prepared payload for transaction {event_log['transactionHash'].hex()}.")

            # 2. Simulate sending the transaction to the destination chain
            # In a real system, this would involve signing a transaction and submitting it
            # to the destination chain's RPC node.
            success, response_data = self._simulate_destination_chain_tx(payload)

            if success:
                logging.info(f"Successfully relayed transaction. Destination response ID: {response_data.get('id')}")
                return True
            else:
                logging.error(f"Failed to relay transaction. Reason: {response_data}")
                return False
        except Exception as e:
            logging.error(f"An error occurred during event processing and relaying: {e}")
            return False

    def _format_payload(self, event_log: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transforms a raw event log into a structured payload for the destination.
        """
        args = event_log['args']
        return {
            'sourceTransactionHash': event_log['transactionHash'].hex(),
            'sourceBlockNumber': event_log['blockNumber'],
            'bridgeNonce': args['nonce'],
            'sourceSender': args['sender'],
            'destinationRecipient': args['recipient'],
            'destinationChainId': args['destinationChainId'],
            'tokenAddress': args['token'],
            'amount': str(args['amount']) # Convert amount to string to avoid JSON precision issues
        }

    def _simulate_destination_chain_tx(self, payload: Dict[str, Any]) -> (bool, Dict):
        """
        Simulates the relaying action by sending a POST request to a mock API.
        """
        try:
            response = self.session.post(self.api_endpoint, json=payload, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            return True, response.json()
        except requests.exceptions.RequestException as e:
            return False, {'error': str(e)}

class BridgeOrchestrator:
    """The main component that orchestrates the entire event listening and relaying process."""

    def __init__(self, start_block: Optional[int] = None):
        """
        Initializes all components of the bridge listener.

        Args:
            start_block (Optional[int]): The block number to start scanning from. 
                                         If None, it starts from the latest block.
        """
        self.connector = BlockchainConnector(SOURCE_CHAIN_RPC_URL)
        if not self.connector.is_connected():
            raise RuntimeError("Could not establish initial blockchain connection. Exiting.")

        contract_instance = self.connector.get_contract(BRIDGE_CONTRACT_ADDRESS, BRIDGE_CONTRACT_ABI)
        if not contract_instance:
            raise RuntimeError("Could not create contract instance. Exiting.")

        self.scanner = EventScanner(contract_instance)
        self.relayer = CrossChainTransactionRelayer(DESTINATION_API_ENDPOINT)
        
        # State management for the last processed block
        self.last_scanned_block = start_block or (self.connector.get_latest_block() - CONFIRMATION_BLOCKS)
        if self.last_scanned_block < 0:
             self.last_scanned_block = 0
        
        logging.info(f"Orchestrator initialized. Starting scan from block {self.last_scanned_block}.")

    def run(self):
        """Starts the main execution loop of the orchestrator."""
        logging.info("Starting bridge orchestrator main loop... (Press Ctrl+C to stop)")
        while True:
            try:
                self._run_scan_cycle()
                logging.info(f"Cycle finished. Waiting {SCAN_INTERVAL_SECONDS} seconds for the next one.")
                time.sleep(SCAN_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logging.info("Shutdown signal received. Exiting gracefully.")
                break
            except Exception as e:
                logging.critical(f"A critical error occurred in the main loop: {e}")
                time.sleep(60) # Wait longer after a critical failure

    def _run_scan_cycle(self):
        """Executes a single cycle of fetching blocks, scanning for events, and relaying them."""
        latest_block = self.connector.get_latest_block()
        if latest_block is None:
            logging.error("Could not determine the latest block. Skipping this cycle.")
            return

        # The target block is the latest block minus a confirmation delay
        target_block = latest_block - CONFIRMATION_BLOCKS
        if self.last_scanned_block >= target_block:
            logging.info(f"No new blocks to scan. Current head: {latest_block}, last scanned: {self.last_scanned_block}")
            return

        # Process blocks in manageable chunks
        current_block = self.last_scanned_block + 1
        while current_block <= target_block:
            end_block = min(current_block + MAX_BLOCK_RANGE - 1, target_block)
            
            events = self.scanner.scan_blocks(current_block, end_block)
            
            if events:
                for event in events:
                    self.relayer.process_and_relay(event)
            
            # Update state for the next iteration
            self.last_scanned_block = end_block
            current_block = end_block + 1

if __name__ == "__main__":
    try:
        orchestrator = BridgeOrchestrator()
        orchestrator.run()
    except RuntimeError as e:
        logging.critical(str(e))
        sys.exit(1)
